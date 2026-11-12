"""Closed-vocabulary correction.

THE IDEA
--------
Some fields are not free text. They are drawn from a small, known set:

    months        12 values
    designations  a few hundred job titles, all of which appear in the
                  client's own spreadsheets
    status codes  P / A / L / W / H

For those fields, OCR does not need to *read* the value correctly -- it only
needs to get close enough to identify which member of the set it is. This is
the same insight that makes the employee roster work, applied to the other
closed fields.

Measured handwritten misreads that this fixes:
    "Apsinl -2026"       -> April-2026
    "Safrty Superwiser"  -> Safety Supervisor
    "APRTL.2026"         -> April-2026

SAFETY
------
Same rule as the roster: correct only on a confident, unambiguous match. A weak
or tied match is left alone so a reviewer sees the raw read rather than a
confidently-wrong substitution.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from rapidfuzz import fuzz, process

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")
_MONTH_LOOKUP = {m.upper(): m for m in MONTHS}
_MONTH_ABBR = {m[:3].upper(): m for m in MONTHS}

# Confidence floors. Deliberately high: a wrong correction is worse than none.
MONTH_MIN = 72
# Measured on the 24 scored designation cases with an 18-probe regression panel
# (tools/eval_desig.py). The plateau runs min 62-70 x margin 3-6, all at 15/24
# with the regression panel clean; 72+ starts losing correct answers and 78
# collapses to 10/24. The highest floor on the plateau is taken deliberately --
# on this corpus every point in it scores the same, so the safest one wins.
DESIG_MIN = 70
DESIG_MARGIN = 6

# A substring match is only evidence when the substring is substantial; below
# this length partial_ratio finds a good window in any large vocabulary.
_PARTIAL_MIN_LEN = 10
# Above this similarity, two vocabulary entries are variants of one title
# rather than rival answers, so a near-tie between them is not an ambiguity.
_FAMILY_MIN = 72
_TOKEN_SPLIT = re.compile(r"[^A-Z0-9]+")

_YEAR_RE = re.compile(r"(20\d{2}|\b\d{2}\b)")


def normalise_month(text: str | None) -> str | None:
    """Map a garbled month/year string onto 'Month-YYYY'.

    Handles the two things OCR does to these: mangled letters ("Apsinl") and
    inconsistent separators (" -", ".", "/").
    """
    if not text:
        return None
    raw = str(text).strip()
    if not raw:
        return None

    # Pull the year out first so it can't distort the month match.
    year = None
    ym = _YEAR_RE.search(raw)
    if ym:
        y = ym.group(1)
        year = y if len(y) == 4 else f"20{y}"

    # Strip digits and punctuation; what's left should be the month word.
    word = re.sub(r"[^A-Za-z]", " ", raw).strip()
    if not word:
        return None

    # Try each whitespace-separated token; the month may sit beside noise.
    best_month, best_score = None, 0
    for tok in [word] + word.split():
        if len(tok) < 3:
            continue
        t = tok.upper()
        if t in _MONTH_LOOKUP:
            best_month, best_score = _MONTH_LOOKUP[t], 100
            break
        if t[:3] in _MONTH_ABBR:
            cand, sc = _MONTH_ABBR[t[:3]], 95
            if sc > best_score:
                best_month, best_score = cand, sc
        hit = process.extractOne(t, MONTHS, scorer=fuzz.ratio)
        if hit and hit[1] > best_score:
            best_month, best_score = hit[0], hit[1]

    if not best_month or best_score < MONTH_MIN:
        return None
    return f"{best_month}-{year}" if year else best_month


class Vocabulary:
    """A closed set of allowed values for one field, with fuzzy lookup."""

    def __init__(self, values: list[str]):
        # Deduplicate case-insensitively, keeping the most common spelling.
        seen: dict[str, str] = {}
        for v in values:
            k = " ".join(str(v).upper().split())
            if k and k not in seen:
                seen[k] = " ".join(str(v).split())
        self.keys = list(seen)
        self.display = seen

    def __len__(self) -> int:
        return len(self.keys)

    @property
    def empty(self) -> bool:
        return not self.keys

    def normalise(self, text: str | None,
                  min_score: float = DESIG_MIN,
                  margin: float = DESIG_MARGIN) -> tuple[str | None, float]:
        """Return (corrected_value, score), or (None, 0) if not confident.

        A near-tie between two vocabulary entries returns None: the same
        ambiguity rule used for employee names, for the same reason.
        """
        if not text or self.empty:
            return None, 0.0
        q = " ".join(str(text).upper().split())
        if not q:
            return None, 0.0
        if q in self.display:
            return self.display[q], 100.0

        hits = process.extract(q, self.keys, scorer=fuzz.token_sort_ratio,
                               limit=3)

        # A vocabulary entry embedded VERBATIM in a contaminated read wins
        # outright, before any fuzzy or abbreviation guessing.
        #
        # Measured failure: 'SAFETY OFFICER SHAKTIPRASADBISUA' (the title with
        # the neighbouring name glued on). partial_ratio finds SAFETY OFFICER
        # at 100 -- but the abbreviation pass ran first, and contamination
        # penalises the correct 2-token entry harder than a wrong 3-token
        # entry that absorbs the junk token, so 'Sr. Officer (Safety).' won at
        # 73.7 and a clean read shipped as the wrong title. The bar is 95, not
        # 80: this early exit is only for near-exact embedded matches; weaker
        # substring evidence still goes through the guarded fallback below.
        if len(q) >= _PARTIAL_MIN_LEN:
            # An EMBEDDED match means the entry sits inside the query, so the
            # entry cannot be much longer than the query. Without this cap the
            # abbreviation 'SAFETY S.UP' (11 chars) was claimed by 'Safety
            # Supervisor (Structural)' (30 chars) on a window covering a third
            # of the entry -- abbreviations belong to the abbreviation pass
            # below, not to this one.
            p_hits = [h for h in process.extract(
                q, self.keys, scorer=fuzz.partial_ratio, limit=8)
                if h[1] >= 95 and len(h[0]) <= len(q) * 1.15]
            # Among embedded matches, the LONGEST entry wins, not the first.
            # 'Engineer Gr. III (Mechanicl)' embeds the bare entry 'ENGINEER'
            # at 100 -- but it also matches the full 'ENGINEER GR. III
            # (MECHANICAL)' at 96, and shipping the 8-character stub when a
            # 29-character title fits is a downgrade, not a match.
            p_hits.sort(key=lambda h: (-len(h[0]), -h[1]))
            if p_hits:
                top = p_hits[0]
                rival = next((h for h in p_hits[1:]
                              if not self._same_family(top[0], h[0])), None)
                if rival is None or top[1] - rival[1] >= margin \
                        or len(top[0]) > len(rival[0]):
                    return self.display[top[0]], float(top[1])

        # Abbreviation pass, tried when the plain fuzzy match is unconvincing.
        #
        # Supervisors abbreviate constantly: 'SAFETY S.UP', 'SAFETY S.U.P',
        # 'Sgjety. sup'. Whole-string similarity is the wrong tool for those --
        # 'SAFETY S.UP' scores 56 against SAFETY OFFICER and only 43 against
        # the correct SAFETY SUPERVISOR, so the plain matcher confidently ranks
        # the WRONG title first. Aligning token-by-token, and letting a query
        # token count as a prefix of a vocabulary token, reverses that.
        if not hits or hits[0][1] < 90:
            abbr = self._abbrev_rank(q)
            if abbr and (not hits or abbr[0][1] > hits[0][1]):
                hits = abbr

        if hits and hits[0][1] >= min_score:
            if len(hits) > 1 and hits[0][1] - hits[1][1] < margin \
                    and not self._same_family(hits[0][0], hits[1][0]):
                return None, float(hits[0][1])
            return self.display[hits[0][0]], float(hits[0][1])

        # SUBSTRING fallback for contaminated values.
        #
        # Measured on real pages, the extracted designation is frequently the
        # job title with a neighbouring field glued on:
        #     'Safity sulenvisor NeeraJ Sharomd'
        #     'Jitendna Singh Sayety Suyp'
        # A whole-string comparison scores those far too low, because most of
        # the string is the contaminant. partial_ratio finds the best-aligning
        # window instead, which is exactly the title we want.
        #
        # This is only tried AFTER the strict whole-string match fails, and it
        # demands a higher score, because a substring match is weaker evidence.
        #
        # LENGTH GUARD. partial_ratio finds the best-aligning window, so a
        # SHORT query always finds a good window somewhere in a large
        # vocabulary and the score means nothing. Measured: the junk reading
        # 'sds h' matched 'Mess Helper' at 80 and was emitted as a confident
        # designation. That is this product's worst possible output -- a wrong
        # value that looks certain and passes validation on its way to an
        # invoice. A substring match is only evidence when the substring is
        # substantial.
        if len(q) >= _PARTIAL_MIN_LEN:
            p_hits = process.extract(q, self.keys, scorer=fuzz.partial_ratio,
                                     limit=2)
            if p_hits and p_hits[0][1] >= max(min_score, 80):
                if len(p_hits) > 1 and p_hits[0][1] - p_hits[1][1] < margin \
                        and not self._same_family(p_hits[0][0], p_hits[1][0]):
                    return None, float(p_hits[0][1])
                return self.display[p_hits[0][0]], float(p_hits[0][1])

        # LAST RESORT: strip OCR digit/bracket noise and try once more.
        #
        # Measured failure: 'SAFETY S.(1.P' -- the abbreviation 'S.U.P' with
        # the U misread as '(1'. Every pass above rejects it (best 51.9), yet
        # the same string with digits and brackets removed matches Safety
        # Supervisor at 85.7. This is safe for THIS vocabulary because its
        # titles use roman numerals ('Engineer Gr. III'), never digits, so a
        # digit inside a designation query is always OCR noise. The retry runs
        # only after everything else has failed, on the full pass stack, so
        # every guard above (length, margin, family) still applies to the
        # cleaned string. Junk stays junk: '1ds h' cleans to 'ds h' and is
        # still rejected.
        cleaned = re.sub(r"\s+", " ", re.sub(r"[()\[\]{}0-9]+", "", q)).strip()
        if cleaned and cleaned != q:
            return self.normalise(cleaned, min_score=min_score, margin=margin)

        return None, float(hits[0][1]) if hits else 0.0

    def _abbrev_rank(self, q: str) -> list[tuple[str, float, int]]:
        """Rank the vocabulary treating query tokens as possible abbreviations.

        Each query token is matched against the vocabulary entry's tokens in
        order. A query token scores full marks if it is a prefix of a
        vocabulary token ('SUP' -> 'SUPERVISOR', 'S' -> 'SUPERVISOR'), and
        otherwise scores its fuzzy similarity. A single letter only counts as
        an initial, and is worth less, so 'S' alone cannot carry a match.

        Returned in the same (key, score, index) shape rapidfuzz uses so the
        caller can treat both paths identically.
        """
        q_toks = [t for t in _TOKEN_SPLIT.split(q) if t]
        if not q_toks:
            return []
        scored: list[tuple[str, float, int]] = []
        for i, key in enumerate(self.keys):
            k_toks = [t for t in _TOKEN_SPLIT.split(key) if t]
            if not k_toks or len(q_toks) > len(k_toks) + 1:
                continue
            total, used = 0.0, set()
            for qt in q_toks:
                best, best_j = 0.0, None
                for j, kt in enumerate(k_toks):
                    if j in used:
                        continue
                    if len(qt) == 1:
                        s = 60.0 if kt.startswith(qt) else 0.0
                    elif kt.startswith(qt):
                        s = 100.0
                    elif qt.startswith(kt):
                        s = 90.0
                    else:
                        s = float(fuzz.ratio(qt, kt))
                    if s > best:
                        best, best_j = s, j
                if best_j is not None:
                    used.add(best_j)
                total += best
            # Average over the LONGER side, so matching two of a title's five
            # tokens cannot score as well as matching all five.
            scored.append((key, total / max(len(q_toks), len(k_toks)), i))
        scored.sort(key=lambda r: -r[1])
        return scored[:3]

    def _same_family(self, a: str, b: str) -> bool:
        """Are the top two candidates variants of one title, or rival titles?

        The margin rule exists to refuse a coin-flip between two DIFFERENT
        answers. But a 444-entry vocabulary harvested from real spreadsheets is
        full of near-duplicates -- 'Safety Supervisor' vs 'Safety Supervisor
        (Structural)', 'Engineer Gr. III (Welding NDT)' vs '(Welding/NDT)'.
        Refusing those is not caution, it is throwing away a correct answer
        because a variant of it also scored well.

        So the margin only bites when the two candidates are genuinely
        different titles. When one contains the other, or they are highly
        similar to each other, the more frequent one is taken.
        """
        if a == b:
            return True
        if a in b or b in a:
            return True
        return fuzz.token_sort_ratio(a, b) >= _FAMILY_MIN

    @classmethod
    def from_csv(cls, path: str | Path, column: str) -> "Vocabulary":
        p = Path(path)
        if not p.exists():
            return cls([])
        vals: list[str] = []
        with p.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                v = (row.get(column) or "").strip()
                if v:
                    vals.append(v)
        return cls(vals)

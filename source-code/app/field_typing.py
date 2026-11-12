"""Content-based field typing.

THE BREAKTHROUGH
----------------
Six attempts to assign header values by GEOMETRY all failed, and reading the
actual scans explains why. On `IOCLMS APR 2026 p005` the handwriting is large
and spans rows, so the values sit almost exactly between their own label and
the next one:

    MONTH & YEAR    label cy=231    APRIL-2026         cy=257   (+26)
    EMPLOYEE NAME   label cy=262    RAJEEV IYENGAR      cy=292   (+30)
    DESIGNATION     label cy=292    SAFETY SUPERVISOR  cy=324   (+32)

`APRIL-2026` is 5 px from the WRONG label and 26 px from its own. No distance
rule, ordering rule, or 2-D cost can separate these -- the geometry is
genuinely ambiguous.

But the VALUES are not ambiguous at all:

    "APRIL-2026"         is obviously a month
    "RAJEEV IYENGAR"      is obviously a person's name
    "SAFETY SUPERVISOR"  is obviously a job title
    "50700"              is obviously a code

So we type each candidate by what it CONTAINS, and use position only to break
ties. Content is robust to exactly the vertical drift that defeats geometry.

HOW THE SCORES WORK
-------------------
Each typer returns 0..1 for "how much does this look like my field". We then
solve a small assignment problem: every candidate goes to the field that wants
it most, and each field takes at most one candidate. A value that looks like
nothing in particular scores low everywhere and is simply left unassigned,
which is the safe outcome.

TERMS
-----
typing       deciding what KIND of thing a string is, from its content
prior        a starting belief before evidence (here, the geometric guess)
assignment   matching candidates to fields, one each
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz, process

MONTHS = ("JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
          "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER")

# Words that appear in job titles on these forms. Harvested by reading the
# scans; extend freely -- a longer list only makes typing sharper.
JOB_WORDS = (
    "SUPERVISOR", "SUPERVISER", "ENGINEER", "TECHNICIAN", "OPERATOR",
    "KEEPER", "STORE", "SAFETY", "FOREMAN", "HELPER", "FITTER", "WELDER",
    "ELECTRICIAN", "INSPECTOR", "OFFICER", "MANAGER", "ASSISTANT", "CLERK",
    "DRAFTSMAN", "SURVEYOR", "RIGGER", "PAINTER", "MASON", "CARPENTER",
    "PLANNER", "COORDINATOR", "INCHARGE", "ATTENDANT", "DRIVER", "GUARD",
)

_YEAR = re.compile(r"\b(19|20)\d{2}\b")
_DIGITS = re.compile(r"\d")
_ALPHA_WORD = re.compile(r"[A-Za-z]{2,}")


def _norm(s: str) -> str:
    return " ".join(str(s or "").upper().split())


def score_month(text: str) -> float:
    """Looks like a month/period."""
    t = _norm(text)
    if not t:
        return 0.0
    best = 0.0
    for tok in re.split(r"[^A-Z]+", t):
        if len(tok) < 3:
            continue
        hit = process.extractOne(tok, MONTHS, scorer=fuzz.ratio)
        if hit:
            best = max(best, hit[1] / 100.0)
    if best < 0.7:
        return 0.0
    # A year alongside the month name makes it near-certain.
    return min(1.0, best + (0.15 if _YEAR.search(t) else 0.0))


# Printed phrases from the form itself. These must never be typed as a job
# title, and fuzzy job-word matching alone does not exclude them: "ATTENDANCE
# SHEET" -- the form's own heading -- scores 0.84 as a designation, because
# ATTENDANCE is one edit-cluster away from ATTENDANT. On a page where the real
# title was missed by OCR, the heading was promoted into the designation field
# and reported as a confident value.
FORM_PHRASES = (
    "ATTENDANCE SHEET", "ATTENDANCE", "EMPLOYEE SIGNATURE", "CLIENT AUTHORIZED",
    "AUTHORIZED BY", "NORMAL WORKING HOURS", "OVER TIME HOURS", "TOTAL HOURS",
    "TIME IN", "TIME OUT", "REMARKS", "SUPERVISOR NAME", "EMPLOYEE NAME",
    "SERVICE PERSON NAME", "SERVICE CATEGORY", "CHECKED BY", "APPROVER",
    "CLIENT'S APPROVAL", "SIGNATURE", "DESIGNATION", "EMPLOYEE CODE",
    "MONTH & YEAR", "AARVI ENCON LTD",
)


def is_form_phrase(text: str, threshold: int = 82) -> bool:
    """Is this the form's own printed wording rather than a filled-in value?"""
    t = _norm(text)
    if not t:
        return False
    hit = process.extractOne(t, FORM_PHRASES, scorer=fuzz.token_sort_ratio)
    return bool(hit and hit[1] >= threshold)


def score_designation(text: str) -> float:
    """Looks like a job title."""
    t = _norm(text)
    if not t or _DIGITS.search(t) and len(_DIGITS.findall(t)) > 2:
        return 0.0
    if is_form_phrase(t):
        return 0.0
    best = 0.0
    for tok in re.split(r"[^A-Z]+", t):
        if len(tok) < 4:
            continue
        hit = process.extractOne(tok, JOB_WORDS, scorer=fuzz.ratio)
        if hit:
            best = max(best, hit[1] / 100.0)
    return best if best >= 0.75 else 0.0


def score_code(text: str) -> float:
    """Looks like an employee code: mostly digits, short, no spaces."""
    t = _norm(text).strip()
    if not t or len(t) > 20:
        return 0.0
    compact = t.replace(" ", "")
    digits = len(_DIGITS.findall(compact))
    if digits == 0:
        return 0.0
    # A code is dominated by digits and has at most one word.
    digit_frac = digits / max(len(compact), 1)
    words = len([w for w in t.split() if w])
    if words > 2:
        return 0.0
    # Alphanumeric codes are the norm here, not the exception: SAFE900,
    # IOCLMS900, TEIL900, APPL900. Scoring purely on digit fraction rejected
    # them (SAFE900 -> 0.53, below threshold) and lost the code entirely.
    # A short single token that ENDS in digits is a code regardless of how
    # many letters precede it.
    score = digit_frac
    if 3 <= len(compact) <= 12:
        score += 0.2
    if words == 1 and re.search(r"\d$", compact) and len(compact) <= 12:
        score = max(score, 0.75)
    return min(1.0, score)


_YEARISH = re.compile(r"^(19|20)\d{2}$")
_TIMEISH = re.compile(r"\d\s*[:.]\s*\d{2}|\b[AP]\.?M\.?\b", re.I)


def _looks_temporal(tok: str) -> bool:
    """A year or a clock reading, i.e. not an employee code."""
    return bool(_YEARISH.match(tok.strip()) or _TIMEISH.search(tok))


def salvage_code(text: str) -> str | None:
    """Pull the employee code out of a value it got glued to.

    score_code() returns 0.0 for anything over two words, which is right as a
    *classifier* and wrong as an *extractor*. On handwritten pages the code box
    routinely merges with its neighbours:

        'Sayety Suyp. 54789'              code is 54789
        'Safety Superwisor 150698 PRO,ECT: Deptt'
        'Saltry Suppaui sar1 57078 NORMAL OVER TIME ATTENDANCR SHEET ...'

    Measured on the frozen corpus: 13 of 24 extracted codes were contaminated
    like this, and every one was then discarded as "not a code" -- the value
    was present and readable in all 13. No harness scored employee_code, so
    this had been invisible.

    So: score each token separately and take the best one that looks like a
    code on its own. Refuses when no single token is convincing, rather than
    guessing at the longest number on the line.
    """
    t = str(text or "").strip()
    if not t:
        return None
    # "Already clean" must mean ONE token. score_code accepts up to two words,
    # which lets a clock reading through: '9:00 AM' scores exactly 0.70 and was
    # returned verbatim as an employee code.
    if len(t.split()) == 1 and score_code(t) >= 0.7 and not _looks_temporal(t):
        return t
    best, best_score = None, 0.0
    for tok in re.split(r"[^A-Za-z0-9]+", t):
        if not tok or len(tok) < 3 or len(tok) > 12:
            continue
        if not _DIGITS.search(tok):
            continue
        s = score_code(tok)
        # A bare 4-digit run is as likely to be a year or an hour count as a
        # code, so require either some letters or a length codes actually have.
        if tok.isdigit() and not (4 <= len(tok) <= 8):
            continue
        # A bare year is the single most common non-code number on these
        # pages -- the period line sits directly above the code box.
        if _looks_temporal(tok):
            continue
        if s > best_score:
            best, best_score = tok, s
    return best if best_score >= 0.7 else None


def score_name(text: str, roster=None) -> float:
    """Looks like a person's name.

    The roster makes this decisive when available: a string that matches a
    known employee IS a name, whatever else it resembles.
    """
    t = _norm(text)
    if not t:
        return 0.0
    words = [w for w in re.split(r"[^A-Z]+", t) if len(w) >= 2]
    if not words or len(words) > 5:
        return 0.0
    # Names are alphabetic; digits argue against.
    if _DIGITS.search(t):
        return 0.0
    # A month or a job title is not a name, even though both are alphabetic.
    if score_month(t) > 0.7 or score_designation(t) > 0.8:
        return 0.0

    base = 0.45 + 0.15 * min(len(words), 3)
    if roster is not None and not roster.empty:
        m = roster.match(name=t)
        if m.status in ("exact_code", "strong_name"):
            return 1.0
        if m.status == "ambiguous":
            return 0.9
    return min(base, 0.85)


TYPERS = {
    "month_year": lambda t, r: score_month(t),
    "designation": lambda t, r: score_designation(t),
    "employee_code": lambda t, r: score_code(t),
    "employee_name": lambda t, r: score_name(t, r),
}

# Below this, a candidate is not confidently anything and is left alone.
MIN_SCORE = 0.62


_TRAILING_CODE = re.compile(r"^(?P<head>.*?[A-Za-z].*?)\s+(?P<code>[A-Za-z]?\d[\dA-Za-z\-/]{2,})\s*$")


def split_merged(text: str) -> list[str]:
    """Split a value that merged two fields into one OCR box.

    Handwritten forms routinely produce "SAFETY SUPERVISOR 50700" -- the
    designation and the code read as a single run. Left merged, the combined
    string scores below threshold for BOTH fields and is dropped entirely,
    which is how p005 lost its designation and its code at once.

    We only split where the tail is unambiguously a code (contains digits) and
    the head still contains letters, so ordinary values are untouched.
    """
    t = str(text or "").strip()
    if not t:
        return []
    # NEVER split a month/year. Measured regression: "APRIL 2026" was split
    # into "APRIL" + "2026", and "2026" then typed as an employee code --
    # losing both the month and the real code on that page.
    if score_month(t) >= 0.7:
        return [t]
    m = _TRAILING_CODE.match(t)
    if m:
        head, code = m.group("head").strip(), m.group("code").strip()
        # A bare 4-digit year is not a code.
        if _YEAR.fullmatch(code):
            return [t]
        if len(head) >= 3 and any(c.isdigit() for c in code):
            return [head, code]
    return [t]


def type_assign(candidates: dict[str, str], roster=None,
                fields: tuple[str, ...] = tuple(TYPERS)) -> dict[str, str]:
    """Re-assign already-extracted header values to the field they LOOK like.

    `candidates` maps the geometric guess (field -> text). We re-score every
    text against every field and solve for the best one-to-one assignment,
    greedily from the highest score down.

    Returns the corrected mapping. Values that score below MIN_SCORE for every
    field are dropped rather than forced somewhere wrong.
    """
    texts: list[str] = []
    for v in candidates.values():
        if not v or not str(v).strip():
            continue
        # A merged "DESIGNATION CODE" run is split so each half can be typed.
        for part in split_merged(v):
            if part and part not in texts:
                texts.append(part)

    pairs: list[tuple[float, str, str]] = []
    for f in fields:
        typer = TYPERS.get(f)
        if not typer:
            continue
        for t in texts:
            s = typer(t, roster)
            if s >= MIN_SCORE:
                pairs.append((s, f, t))
    pairs.sort(key=lambda p: -p[0])

    out: dict[str, str] = {}
    used_text: set[str] = set()
    for _s, f, t in pairs:
        if f in out or t in used_text:
            continue
        out[f] = t
        used_text.add(t)
    return out

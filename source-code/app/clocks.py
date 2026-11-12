"""Clock-time reading: grammar repair and sheet consensus for in/out times.

Measured starting point (D-070), 35 corpus pages / 766 rows of exact truth
taken from the sheets' own PDF text layer: **83.4%** of in/out values correct
through the real upload path. The failures were not evenly spread:

    unparseable   164   the OCR returned something that is not a clock at all
    missing        87   no value was produced for the cell
    wrong value    19   a clock, but the wrong one

So the dominant defect is *damaged*, not *wrong*. "9:00" comes back as "00:60",
"7:30" as "7!30 puy", "18:00" as "100:80". Nineteen genuinely wrong readings out
of 1,626 is the floor imposed by the recogniser; the other 251 are a parsing
problem, and parsing is something we control.

Two mechanisms, in order:

1.  **Grammar.** A clock is not free text. It is one or two digits, a
    separator, two digits, optionally a meridiem, and the hour and minute have
    hard bounds. That grammar lets us fold the characters OCR reliably
    confuses (S/5, O/0, l|)!/1, B/8) *only in positions where a digit is the
    only legal character*, which is why this does not corrupt anything else.

2.  **The sheet's own redundancy.** Nearly every timesheet records the same
    shift on every working day -- 8:30 to 19:30, thirty-one times. When one
    row reads '8:3O' and twenty-six read '8:30', the sheet itself says which
    is right. This is the same move that produced the largest gains elsewhere
    in this pipeline: read the structure, not the ink. It is applied only when
    the page actually is uniform, so punch-machine sheets with a genuinely
    different time every day (Reliance, TATA) are left alone.

What this module will not do is guess. A cell that cannot be resolved returns
None with a named reason, and the row is flagged. A fabricated time that looks
plausible is worse than a blank, because a blank gets checked.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

# Fold only in positions where the grammar allows nothing but a digit.
# Everything here is a confusion RapidOCR actually produced on these pages.
DIGIT_FOLD = {
    "O": "0", "o": "0", "Q": "0", "D": "0", "U": "0",
    "l": "1", "I": "1", "i": "1", "|": "1", "]": "1", "[": "1",
    ")": "1", "(": "1", "!": "1", "/": "1", "\\": "1", "L": "1", "j": "1",
    "Z": "2", "z": "2",
    "A": "4", "a": "4",
    "S": "5", "s": "5",
    "G": "6", "b": "6", "C": "6",
    "T": "7", "?": "7",
    "B": "8", "g": "9", "q": "9",
}
# Any of these between the hour and the minute is a misread colon.
SEP_CHARS = ":.;,'`·•*\"-_= "
# Glyphs a colon is actually mistaken for on these scans. A colon is two small
# dots in a vertical line, so it degrades into thin upright marks and specks --
# never into a round digit, which is why 0, 6, 8 and 9 are absent here.
COLON_LOOKALIKES = set(":;.,'`!|Il1i/\\)(·*\"-_= ")

_MERIDIEM_RE = re.compile(r'([ap])\s*[\./]?\s*m', re.I)
_TOKEN_RE = re.compile(r'[0-9A-Za-z|\]\[)(!/\\?.:;,\'`·*"_=-]+')


def _fold_digits(s: str) -> str:
    return "".join(DIGIT_FOLD.get(c, c) for c in s)


def _meridiem(raw: str) -> str | None:
    """'AM'/'PM' from however it was written, or None.

    Handwritten meridiems come back as 'A.m', 'Pvv', 'p.M', 'Am)' and worse.
    Only the first letter and a following m are load-bearing, so that is all
    this looks for.
    """
    m = _MERIDIEM_RE.search(raw)
    if m:
        return "AM" if m.group(1).lower() == "a" else "PM"
    return None


def _split_bare_digits(d: str) -> tuple[int, int] | None:
    """'0930' / '930' -> (9, 30). Chooses the split that is a legal clock."""
    if len(d) == 4:
        cands = [(int(d[:2]), int(d[2:]))]
    elif len(d) == 3:
        # '930' is 9:30, not 93:0. Try the two-digit minute first; fall back to
        # a two-digit hour only when that is the only legal reading ('130' is
        # 1:30, but '230' could be 2:30 -- the one-digit hour always wins
        # because no sheet in this corpus writes a one-digit minute).
        cands = [(int(d[0]), int(d[1:])), (int(d[:2]), int(d[2:]) * 10)]
    else:
        return None
    for h, mi in cands:
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return h, mi
    return None


def parse_clock(raw: Any) -> tuple[int, int] | None:
    """(hour, minute) in 24-hour form from a clean value, or None.

    Strict: this is the "was it already readable" test, so it must not repair
    anything. repair() is what repairs.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    m = re.fullmatch(r'\s*(\d{1,2})\s*:\s*(\d{2})\s*(?:[ap]\s*\.?\s*m\.?)?\s*', s, re.I)
    if not m:
        m = re.fullmatch(r'\s*(\d{1,2})\s*()(?:[ap]\s*\.?\s*m\.?)\s*', s, re.I)
        if not m:
            return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    return _apply_meridiem(h, mi, _meridiem(s))


def _apply_meridiem(h: int, mi: int, mer: str | None) -> tuple[int, int]:
    if mer == "PM" and h < 12:
        h += 12
    elif mer == "AM" and h == 12:
        h = 0
    return h % 24, mi


def repair(raw: Any) -> tuple[tuple[int, int] | None, str | None]:
    """Best reading of a damaged time cell.

    Returns ((hour, minute), reason) where reason is None if the cell was
    already clean, a short tag if it had to be repaired, and the value is None
    if the cell cannot be read as a clock at all.
    """
    if raw is None or not str(raw).strip():
        return None, "empty"
    s = str(raw).strip()

    clean = parse_clock(s)
    if clean is not None:
        return clean, None

    mer = _meridiem(s)
    # Drop the meridiem before folding: its own letters are not digits and
    # must not be folded into any ('A' -> '4' would turn '8:30 AM' into junk).
    body = _MERIDIEM_RE.sub(" ", s)

    # A cell often carries a neighbouring column's text ("17:01 2. SW7370").
    # Score each token and keep the best clock-shaped one rather than the
    # first, so a project code before the time does not win.
    best: tuple[int, tuple[int, int], str] | None = None
    for tok in _TOKEN_RE.findall(body):
        got = _repair_token(tok)
        if got is None:
            continue
        score = sum(c.isdigit() for c in tok) * 10 - len(tok)
        if best is None or score > best[0]:
            best = (score, got, tok)
    if best is None:
        return None, "not_a_time"

    h, mi = best[1]
    reason = "repaired" if best[2] == body.strip() else "trimmed"
    return _apply_meridiem(h, mi, mer), reason


def _repair_token(tok: str) -> tuple[int, int] | None:
    """One token -> (hour, minute), folding confusable characters."""
    t = tok.strip(SEP_CHARS)
    if not t or len(t) > 6:
        return None

    # Shape 1: something that looks like H<sep>MM.
    m = re.fullmatch(rf'(.{{1,2}})([{re.escape(SEP_CHARS)}])(.{{2}})', t)
    if m:
        hh, mm = _fold_digits(m.group(1)), _fold_digits(m.group(3))
        if hh.isdigit() and mm.isdigit():
            h, mi = int(hh), int(mm)
            if 0 <= h <= 23 and 0 <= mi <= 59:
                return h, mi

    # Shape 2: no separator survived at all -- fold, then split on the grammar.
    d = _fold_digits(t)
    if d.isdigit():
        got = _split_bare_digits(d)
        if got:
            return got

        # Shape 3: the colon itself was read as a digit, so the value carries
        # one character too many -- '7!30' is 7:30, '20133' is 20:33. Drop one
        # interior character and see whether what remains is a legal clock.
        #
        # Only a character that could plausibly HAVE BEEN the colon is
        # droppable, judged on the original glyph rather than the folded
        # digit. Without that test '20133' loses its leading zero and becomes
        # 21:33, which is a legal clock and completely wrong. With it, index 1
        # ('0') is not a candidate and index 2 ('1') is, giving 20:33.
        if 4 <= len(d) <= 5:
            for cut in range(1, len(d) - 2):
                if t[cut] not in COLON_LOOKALIKES:
                    continue
                got = _split_bare_digits(d[:cut] + d[cut + 1:])
                if got:
                    return got
    return None


def fmt(hm: tuple[int, int] | None) -> str | None:
    """24-hour HH:MM, the one form everything downstream reads."""
    return None if hm is None else f"{hm[0]:02d}:{hm[1]:02d}"


# ---------------------------------------------------------------------------
# Sheet consensus
# ---------------------------------------------------------------------------

UNIFORM_SHARE = 0.60     # a column is "one shift" when this share agrees
MIN_UNIFORM_ROWS = 4     # below this there is no consensus worth having


def _mode(values: list[tuple[int, int]]) -> tuple[tuple[int, int], float] | None:
    if not values:
        return None
    (val, n), = Counter(values).most_common(1)
    return val, n / len(values)


def _one_edit_apart(a: str, b: str) -> bool:
    """True when the two digit strings differ by at most one character.

    Deliberately narrow. Consensus may only confirm what the ink nearly says;
    it must never overwrite a value the page genuinely wrote differently, or a
    half-day on an otherwise uniform sheet would silently become a full day.
    """
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    short, long = (a, b) if len(a) < len(b) else (b, a)
    for i in range(len(long)):
        if long[:i] + long[i + 1:] == short:
            return True
    return False


def apply_to_days(days: list[dict], consensus: bool = True) -> dict:
    """Repair in/out times in place. Returns a small summary for the log.

    Every change is recorded on the row (`_time_fix`) so the reviewer is told
    what was altered and why, and so a bad repair is visible rather than
    buried. Nothing here invents a value for an empty cell.
    """
    stats = Counter()
    raw_by_side: dict[str, list[tuple[int, int]]] = {"in_time": [], "out_time": []}

    for d in days:
        for key in ("in_time", "out_time"):
            raw = d.get(key)
            if raw is None or not str(raw).strip():
                continue
            hm, reason = repair(raw)
            if hm is None:
                # Blank the field rather than pass 'S1:G|' downstream. An
                # export that prints OCR debris as if it were a time is worse
                # than one that prints nothing, because nothing gets checked.
                # What was actually read is kept in `_time_fix.from`, so the
                # reviewer still sees it when correcting the row.
                d.setdefault("_time_fix", {})[key] = {"from": str(raw), "to": None,
                                                      "why": reason or "not_a_time"}
                d[key] = None
                stats["unreadable"] += 1
                continue
            new = fmt(hm)
            if new != str(raw).strip():
                d.setdefault("_time_fix", {})[key] = {"from": str(raw), "to": new,
                                                      "why": reason or "normalised"}
                stats[reason or "normalised"] += 1
            d[key] = new
            raw_by_side[key].append(hm)

    if not consensus:
        return dict(stats)

    for key in ("in_time", "out_time"):
        vals = raw_by_side[key]
        if len(vals) < MIN_UNIFORM_ROWS:
            continue
        got = _mode(vals)
        if got is None:
            continue
        modal, share = got
        if share < UNIFORM_SHARE:
            # A sheet with a genuinely different time every day. Its rows carry
            # no mutual evidence, so consensus has nothing to say about them.
            continue
        modal_digits = f"{modal[0]:02d}{modal[1]:02d}"
        for d in days:
            fix = (d.get("_time_fix") or {}).get(key)
            if not fix or fix.get("to") is not None:
                continue            # only cells we failed to read outright
            digits = re.sub(r'\D', '', str(fix.get("from") or ""))
            if digits and _one_edit_apart(digits, modal_digits):
                d[key] = fmt(modal)
                fix.update({"to": fmt(modal), "why": "matched_the_rest_of_the_sheet"})
                stats["consensus"] += 1
                stats["unreadable"] -= 1
    return dict(stats)

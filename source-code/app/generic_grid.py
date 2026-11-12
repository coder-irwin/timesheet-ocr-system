"""Find the day grid on ANY timesheet, without knowing the client.

WHY
---
Extraction currently depends on `form_profiles`: three hand-written anchor
sets (aarvi, samsung, kbr). Any layout not in that list yields nothing at all.
Measured on the HO dataset, 207 of 247 pages produced no employee name, and
the failures cluster into eleven client folders -- so the hardcoded approach
does not merely lag the data, it cannot reach it. Adding an anchor set per
client does not generalise either: the next client arrives with the twelfth
layout.

THE INVARIANT
-------------
Whatever else differs, a monthly timesheet must enumerate its days. Somewhere
on the page there is a run of the integers 1..28-31 in order. That run is
either

    a COLUMN  -- days down the page, one row per day   (AARVI / IOCL)
    a ROW     -- days across the page, one column each (SHELL / BPCL)

So instead of asking "which client is this?", ask "where are the day numbers,
and which way do they run?". That question has the same answer on a layout
nobody has ever seen before, which is the property we actually need.

This module finds the axis and the per-day cell positions. It deliberately
does NOT interpret statuses or identities -- callers do that, because those
differ per family while the grid geometry does not.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

NUMERIC_CELL_IS_PRESENT = False  # D-086: measured, no gain (+1 cell). OFF.
# A day cell holding only a number: "10.0" hours, "1" present, "8.5".
_PLAIN_NUMBER = re.compile(r"\d{1,2}(?:\.\d{1,2})?")

MIN_RUN = 10          # a fortnightly sheet still has 15
NAME_NEAREST_BLOCK = True   # D-028: block name = nearest person-like text, not longest
NEAR_TOL = 0.6        # cluster tolerance, in units of median box height


@dataclass
class DayAxis:
    """Where the days are and which way they run."""
    orientation: str                 # "row" (days across) | "column" (down)
    days: dict[int, tuple[float, float]]   # day -> (lo, hi) along the axis
    band: tuple[float, float]        # extent of the header itself, other axis
    score: float

    def __len__(self) -> int:
        return len(self.days)


def _as_day(text: str) -> int | None:
    """A 1-2 digit day number, in ASCII only.

    str.isdigit() is True for Unicode forms int() cannot parse -- OCR on
    handwriting really does return '(2)8' as the circled digit U+2461 -- so
    the check has to be on the ASCII characters, not on isdigit().
    """
    # DAY-MONTH labels: "1-Jul", "12 Jul", "3/Aug", "07-APR-26". A sideways
    # three-employee grid (Avaada01) printed every day this way and the reader
    # returned None for all 31, so the page yielded no axis and no days.
    _dm = re.match(r"^\s*(\d{1,2})\s*[-/ ]\s*[A-Za-z]{3,9}\b", str(text or ""))
    if _dm:
        v = int(_dm.group(1))
        return v if 1 <= v <= 31 else None
    s = str(text or "").strip()
    if 1 <= len(s) <= 2 and all("0" <= c <= "9" for c in s):
        n = int(s)
        return n if 1 <= n <= 31 else None

    # A handwritten DATE cell, with its separators mangled by OCR:
    #     '01426' = 01/4/26     '0314126' = 03/4/26 (the '/' read as '1')
    #     '1614126' = 16/4/26   '2014126' = 20/4/26
    # The day is the leading one or two digits. Junk like '901150' and
    # '921h190' yields 90/92 and is rejected by the 1..31 bound; a constant
    # hours column ('17.00' on every row) survives here but cannot form an
    # ASCENDING run, so the run search discards it. That is why this can
    # afford to be permissive.
    if 3 <= len(s) <= 12:
        digits = sum(c.isascii() and c.isdigit() for c in s)
        if digits >= len(s) - 3 and s[:1].isdigit():
            head = s[:2] if (len(s) > 1 and s[1].isascii() and s[1].isdigit()) \
                else s[:1]
            n = int(head)
            return n if 1 <= n <= 31 else None
    return None


def _median(vals: list[float]) -> float:
    if not vals:
        return 1.0
    v = sorted(vals)
    return v[len(v) // 2]


def _cluster_by(items: list, key, tol: float) -> list[tuple[int, list]]:
    """Group items whose key values are within `tol` of their neighbour.

    D-087. Replaces `int(value // tol)` bucketing, which splits a group that
    straddles a bucket edge however tight the group actually is. Sorting and
    breaking only on a real gap has no such arbitrary boundary.
    """
    if not items:
        return []
    ordered = sorted(items, key=key)
    groups: list[list] = [[ordered[0]]]
    for it in ordered[1:]:
        if key(it) - key(groups[-1][-1]) <= max(tol, 1.0):
            groups[-1].append(it)
        else:
            groups.append([it])
    return list(enumerate(groups))


def _longest_ascending(seq: list[tuple[int, Any]]) -> list[tuple[int, Any]]:
    """Longest run of strictly increasing day numbers, in positional order.

    OCR misreads some headers ('10'->'20'), so the run must tolerate strays
    rather than demand a perfect 1..31. Classic O(n^2) LIS -- n is at most a
    few dozen boxes.
    """
    if not seq:
        return []
    best_len = [1] * len(seq)
    prev = [-1] * len(seq)
    for i in range(len(seq)):
        for j in range(i):
            if seq[j][0] < seq[i][0] and best_len[j] + 1 > best_len[i]:
                best_len[i] = best_len[j] + 1
                prev[i] = j
    end = max(range(len(seq)), key=lambda i: best_len[i])
    out = []
    while end != -1:
        out.append(seq[end])
        end = prev[end]
    return list(reversed(out))


CROSS_MONTH_RUN = True          # D-087


def _longest_day_run(seq: list[tuple[int, Any]]) -> list[tuple[int, Any]]:
    """Longest run of day numbers, allowing ONE month boundary.

    D-087. A timesheet period is not always a calendar month. This corpus is
    full of periods like "21 March to 20 April" and "26.3.26 to 25.04.26", and
    their headers read 21 22 ... 31 01 02 ... 20 -- a sequence that ascends,
    RESETS once, and ascends again. _longest_ascending can only keep one side
    of that reset, so a 32-column header yielded a 12-day axis and two thirds
    of the sheet was never looked at.

    This runs the same longest-increasing-subsequence over every possible split
    point and keeps the best ascending-then-ascending pair, provided the second
    part starts lower than the first part ends -- which is what a month
    boundary looks like and what a column of random numbers does not.

    At most ONE reset is allowed. Two would not be a period; it would be noise.
    """
    if not seq:
        return []
    best = _longest_ascending(seq)
    if not CROSS_MONTH_RUN or len(seq) < 4:
        return best
    for cut in range(2, len(seq) - 1):
        head = _longest_ascending(seq[:cut])
        tail = _longest_ascending(seq[cut:])
        if not head or not tail:
            continue
        # The reset must go DOWN -- 31 then 01, never 11 then 15.
        if tail[0][0] >= head[-1][0]:
            continue
        if len(head) + len(tail) > len(best):
            best = head + tail
    return best


def _looks_like_person(text: str) -> bool:
    """Two or more alphabetic words -- the shape of a name, not a cell value.

    Deliberately requires TWO words: 'AVAILED', 'PRESENT' and 'Sunday' are
    single words that legitimately appear in day rows, whereas 'Rahul Sahu'
    and 'Field Operator' are not day-cell content.
    """
    s = str(text or "").strip()
    if len(s) < 6:
        return False
    words = [w for w in s.split() if len(w) >= 2 and
             sum(c.isalpha() for c in w) >= len(w) - 1]
    return len(words) >= 2


_LABEL_WORDS = (
    "contractor", "location", "work order", "for the month", "time sheet",
    "timesheet", "emp.code", "emp code", "sr.no", "sr no", "signature",
    "approved", "designation", "department", "client", "project", "total",
    "name:", "name :", "month", "year", "shift", "present", "holiday",
    "leave", "company", "ltd", "pvt", "limited",
)


def looks_like_label(text: str) -> bool:
    """Is this printed form furniture rather than a person's name?

    The transposed layouts carry header lines that are longer than any
    employee name -- 'CONTRACTOR NAME:- AARVI ENCON LTD.' -- so a
    longest-string heuristic picks the furniture every time. Two signals
    separate them: label text carries a colon, or one of the words that only
    ever appears on pre-printed furniture.
    """
    s = str(text or "").strip().lower()
    if not s:
        return True
    if ":" in s:
        return True
    if sum(c.isdigit() for c in s) >= max(3, len(s) * 0.3):
        return True
    return any(w in s for w in _LABEL_WORDS)


_TAIL_WORDS = {
    "ot", "details", "detail", "contract", "employee", "employe", "sign",
    "date", "total", "hours", "hrs", "approved", "hr", "hod", "signature",
    "remarks", "reason", "working", "brief", "activities", "activity",
    "department", "designation", "code", "no", "sr",
}


def trim_trailing_label(name: str | None) -> str | None:
    """Cut printed furniture off the end of a name.

    Where a section title sits immediately right of the name, OCR merges the
    two into one box -- 'Harish Gaiknad Contract Employee OT Details'. The
    name is the head of that string, so trailing furniture words are dropped
    while at least two words survive; anything shorter is left alone rather
    than risk truncating a real name.
    """
    if not name:
        return name
    words = str(name).split()
    while len(words) > 2 and words[-1].strip(".,:-").lower() in _TAIL_WORDS:
        words.pop()
    return " ".join(words) if words else None


def _rows_look_like_people(boxes: list, days: dict[int, tuple[float, float]],
                           right_of: float) -> bool:
    """Is this an employee list rather than a day grid?"""
    if not days:
        return False
    hits = 0
    for _d, (y0, y1) in days.items():
        cy = (y0 + y1) / 2
        h = max(1.0, y1 - y0)
        row = [b for b in boxes
               if b.x0 > right_of and abs(b.cy - cy) <= h * 0.8]
        if any(_looks_like_person(getattr(b, "text", "")) for b in row):
            hits += 1
    return hits >= len(days) * 0.5


def find_day_axis(boxes: list, page_w: int, page_h: int) -> DayAxis | None:
    """Locate the run of day numbers, whichever way it runs."""
    cands = [(b, d) for b in boxes if (d := _as_day(getattr(b, "text", ""))) ]
    if len(cands) < MIN_RUN:
        return None

    heights = [max(1.0, b.y1 - b.y0) for b, _ in cands]
    tol = _median(heights) * NEAR_TOL

    best: DayAxis | None = None

    # --- days ACROSS a row: cluster by y, order by x ----------------------
    # D-087. Group by PROXIMITY, not by bucket index.
    #
    # `int(cy // tol)` splits a single header row whenever it straddles a
    # bucket boundary, and a printed header always has a little vertical
    # jitter. Measured on a Brilliant Bio sheet: the 32-column header came
    # back as 23 boxes in one bucket and 9 in the next, so eight day columns
    # were invisible to the axis finder no matter how the run was computed.
    # Nothing was wrong with the page; the boundary happened to fall inside it.
    for _k, grp in _cluster_by(cands, lambda t: t[0].cy, tol):
        if len(grp) < MIN_RUN:
            continue
        grp.sort(key=lambda t: t[0].x0)
        run = _longest_day_run([(d, b) for b, d in grp])
        if len(run) < MIN_RUN:
            continue
        days = {d: (b.x0, b.x1) for d, b in run}
        ys = [b.cy for _d, b in run]
        cand = DayAxis("row", days,
                       (min(ys) - tol, max(ys) + tol), float(len(run)))
        if best is None or cand.score > best.score:
            best = cand

    # --- days DOWN a column: cluster by x, order by y ---------------------
    widths = [max(1.0, b.x1 - b.x0) for b, _ in cands]
    xtol = _median(widths) * 1.2
    for _k, grp in _cluster_by(cands, lambda t: (t[0].x0 + t[0].x1) / 2, xtol):
        if len(grp) < MIN_RUN:
            continue
        grp.sort(key=lambda t: t[0].cy)
        run = _longest_day_run([(d, b) for b, d in grp])
        if len(run) < MIN_RUN:
            continue
        days = {d: (b.y0, b.y1) for d, b in run}
        xs = [(b.x0 + b.x1) / 2 for _d, b in run]
        right = max(xs) + xtol
        # An ascending column of integers is NOT necessarily days -- a Sr.No
        # column in an employee LIST looks identical. Measured on BHAR07,
        # which the detector happily called a 28-day grid:
        #
        #     4 | Rahul Sahu     | 260316054 | Field Operator | AVAILED
        #     5 | Anu Yadav      | 260131027 | Field Operator | AVAILED
        #
        # The rows give it away. A day row carries short cells -- statuses,
        # clock times, hours. A employee-list row carries a PERSON'S NAME.
        # If most rows next to the run hold long alphabetic text, this is a
        # list of people and returning it as a month of attendance would
        # fabricate data outright.
        if _rows_look_like_people(boxes, days, right):
            continue
        cand = DayAxis("column", days,
                       (min(xs) - xtol, right), float(len(run)))
        if best is None or cand.score > best.score:
            best = cand

    return best


# Single-letter day markings, as they appear in the cell itself. 'S' is the
# SHELL family's weekly off (its S cells fall on 5/12/19/26 of April 2026 --
# every Sunday), which is why it maps to W rather than being treated as an
# unknown code.
_CELL_STATUS = {
    "P": "P", "A": "A", "L": "L", "H": "H", "C": "C",
    "W": "W", "S": "W", "O": "W",
}


def _cell_status(text: str) -> str | None:
    s = str(text or "").strip().upper().strip(".:-")
    if len(s) == 1:
        return _CELL_STATUS.get(s)
    # D-089. Two-letter payroll codes, collected from the day columns of the
    # layouts that were yielding nothing rather than guessed at:
    #
    #   Brilliant Bio   'PP' x377  'W' x74  'IL' x19  'AB' x17
    #
    # PP is present, AB absent, and EL / CL / SL are the standard Indian
    # earned / casual / sick leave codes. 'IL' is 'EL' with the E read as an I,
    # a confusion this recogniser makes constantly.
    #
    # Purely additive: every one of these returns None today, so adding them
    # can only create hits that did not exist. No existing mapping changes.
    if s in ("WO", "W/O", "OFF", "PH", "CO", "C/O", "PP", "AB",
             "EL", "IL", "CL", "SL", "PL"):
        return {"WO": "W", "W/O": "W", "OFF": "W",
                "PH": "H", "CO": "C", "C/O": "C",
                "PP": "P", "AB": "A",
                "EL": "L", "IL": "L", "CL": "L", "SL": "L", "PL": "L"}[s]
    return None


def read_row_oriented(boxes: list, axis: DayAxis) -> list[dict[str, Any]]:
    """Read a transposed sheet: days across the top, employees as row blocks.

    The SHELL/BPCL family stacks several sub-rows per employee -- SHIFT, IN,
    OUT, O.T -- and only the SHIFT row carries the day marking. Rather than
    hardcode that label (the next client will name it something else), each
    horizontal band is scored by how many of its cells land inside a day
    column AND read as a status letter. The band that wins IS the status row,
    whatever it is called.

    Returns one dict per employee block: {"employee_name", "days": [...]}.
    """
    if axis.orientation != "row" or not axis.days:
        return []
    first_x = min(lo for lo, _hi in axis.days.values())
    header_bottom = axis.band[1]

    below = [b for b in boxes if b.cy > header_bottom]
    if not below:
        return []

    heights = [max(1.0, b.y1 - b.y0) for b in below]
    tol = _median(heights) * 0.7

    bands: dict[int, list] = {}
    for b in below:
        bands.setdefault(int(b.cy // max(tol, 1.0)), []).append(b)

    def day_of(b) -> int | None:
        """The day column this mark sits under -- the NEAREST one (D-071).

        This used to pad each band by half its width and return the first
        band in dict order that contained the point. On a 31-day sheet the
        columns are ~50px apart and ~46px wide, so padding them by 23px on
        each side made neighbouring bands overlap by more than a whole
        column, and the lower day number always won because it was tested
        first. A mark sitting dead centre under day 25 was therefore claimed
        by day 24, found day 24 already filled, and was discarded by the
        `d not in hits` guard below -- the day vanished from the output
        entirely while the OCR had read it at confidence 1.00.

        That is exactly what happened to 25 May on ISG MAY 2026, for all
        three employees at once, and nothing about it was specific to that
        sheet or that day: any tight horizontal grid could lose any column.

        Nearest-centre has no such failure mode. Every mark belongs to one
        column -- the one it is actually under -- and the acceptance window
        stays generous enough that a mark written off-centre still lands.
        """
        cx = (b.x0 + b.x1) / 2
        best_d, best_dist = None, None
        for d, (lo, hi) in axis.days.items():
            dist = abs(cx - (lo + hi) / 2)
            if dist <= max(hi - lo, 1.0) and (best_dist is None or dist < best_dist):
                best_d, best_dist = d, dist
        return best_d

    scored = []
    for key, grp in bands.items():
        hits = {}
        numeric: dict[int, str] = {}
        for b in grp:
            d = day_of(b)
            if d is None:
                continue
            st = _cell_status(getattr(b, "text", ""))
            if st and d not in hits:
                hits[d] = st
            elif st is None and d not in numeric:
                # D-086. Not every sheet marks attendance with a letter. The
                # Thyssen grids write the HOURS worked in the day cell (10.0,
                # 12.5) beside the occasional 'L'; the Petrofac grids write a
                # bare '1' beside 'WO' and 'PH'. Both mean the person worked,
                # and both returned None, so no band reached MIN_RUN and the
                # whole page yielded nothing.
                #
                # A number in a day cell is only read as presence when the SAME
                # BAND also carries at least one recognised status token (see
                # below). That is what makes it safe: a Sr.No column, an IVR
                # number or a row of totals carries no status letters, so it
                # cannot be promoted into a month of attendance. The sheet
                # declares its own vocabulary and we read it, rather than
                # hardcoding a client.
                if NUMERIC_CELL_IS_PRESENT:
                    v = str(getattr(b, "text", "")).strip()
                    if _PLAIN_NUMBER.fullmatch(v) and float(v) > 0:
                        numeric[d] = "P"
        if numeric and hits:
            for d, st in numeric.items():
                hits.setdefault(d, st)
        if len(hits) >= MIN_RUN:
            ys = [b.cy for b in grp]
            scored.append((len(hits), key, hits, min(ys), max(ys)))

    scored.sort(key=lambda t: t[1])          # top of page downwards
    out: list[dict[str, Any]] = []
    for _n, _key, hits, y0, y1 in scored:
        # The employee's name sits to the LEFT of the day columns, in or near
        # this band. Take the widest piece of text there -- names are the
        # longest thing in that region, codes and serial numbers are short.
        #
        # Two guards, both learned from the SHELL sheets. The band must stay
        # BELOW the day header or the search reaches up into the page title
        # block; and the longest string is the wrong pick when the furniture
        # is longer than the name, so anything label-shaped is discarded and
        # a person-shaped string wins over a merely long one.
        near = [b for b in boxes
                if b.x1 <= first_x
                and b.cy > header_bottom
                and (y0 - tol * 4) <= b.cy <= (y1 + tol * 4)]
        cands = [str(getattr(b, "text", "")).strip() for b in near]
        cands = [t for t in cands
                 if len(t) >= 4 and any(c.isalpha() for c in t)
                 and not looks_like_label(t)]
        name = None
        if cands:
            if NAME_NEAREST_BLOCK:
                # Nearest the block's own centre line wins. The +-4*tol window
                # spans neighbouring blocks on a dense multi-employee sheet,
                # and "longest" then handed the same name to every block
                # (Avaada01: three employees, all "BHASKAR BHANDARI"; D-015/D-028).
                yc = (y0 + y1) / 2
                scored = sorted(
                    ((abs(b.cy - yc), -len(str(getattr(b, "text", "")).strip()), b)
                     for b in near
                     if str(getattr(b, "text", "")).strip() in cands),
                    key=lambda t: (t[0], t[1]))
                people = [b for _d, _l, b in scored
                          if _looks_like_person(str(b.text))]
                pick = (people or [t[2] for t in scored])[0]
                # A single-word name ("Shankar") fails the two-word person
                # test, so a farther two-word neighbour used to win. If the
                # very nearest candidate sits within one row-height of the
                # block's centre and is a clean alphabetic word, it is this
                # block's own label; a person-like string a row away is the
                # neighbour's (D-034).
                nearest_d, _l, nearest_b = scored[0]
                nt = str(nearest_b.text).strip()
                if nearest_b is not pick and nearest_d <= tol * 1.0 \
                        and len(nt) >= 4 and nt.replace(" ", "").isalpha() \
                        and not looks_like_label(nt):
                    pick = nearest_b
                name = str(pick.text).strip()
            else:
                people = [t for t in cands if _looks_like_person(t)]
                name = max(people or cands, key=len)
        out.append({
            "employee_name": name,
            "days": [{"day": d, "status": s} for d, s in sorted(hits.items())],
        })
    return out


def read_column_oriented(boxes: list, axis: DayAxis) -> list[dict[str, Any]]:
    """Read the classic layout: days down the page, one row per day.

    This is the shape the profile extractor already handles for the three
    known clients. The point here is to read it for the OTHER clients --
    BHAR07, PETR03, LAXMI01 and the rest -- without an anchor set, by working
    purely from where the day numbers are.

    Only EXPLICIT status letters are taken. Where a form instead implies
    presence through clock times and hours (the AARVI family), that inference
    already lives in aarvi_form._infer_status and is far better tuned than
    anything repeated here; this returns nothing for those days rather than
    guessing, so the two never fight over the same cell.
    """
    if axis.orientation != "column" or not axis.days:
        return []
    date_col_right = axis.band[1]

    heights = [max(1.0, b.y1 - b.y0) for b in boxes] or [10.0]
    tol = _median(heights)

    days_out: list[dict[str, Any]] = []
    for d, (y0, y1) in sorted(axis.days.items()):
        cy = (y0 + y1) / 2
        row = [b for b in boxes
               if b.x0 > date_col_right and abs(b.cy - cy) <= tol * 0.8]
        st = None
        for b in sorted(row, key=lambda b: b.x0):
            s = _cell_status(getattr(b, "text", ""))
            if s:
                st = s
                break
        if st:
            days_out.append({"day": d, "status": st})

    if not days_out:
        return []

    # The employee's name is the longest alphabetic text ABOVE the grid.
    top = min(lo for lo, _hi in axis.days.values())
    header = [b for b in boxes if b.cy < top
              and any(c.isalpha() for c in str(getattr(b, "text", "")))]
    name = None
    if header:
        cand = max(header, key=lambda b: len(str(b.text)))
        txt = str(cand.text).strip()
        if len(txt) >= 4:
            name = txt
    return [{"employee_name": name, "days": days_out}]


def describe(axis: DayAxis | None) -> str:
    if axis is None:
        return "no day grid found"
    ds = sorted(axis.days)
    return (f"{axis.orientation}-oriented grid, {len(ds)} days "
            f"({ds[0]}..{ds[-1]})")

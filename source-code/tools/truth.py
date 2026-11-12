"""Robust ground-truth extraction from the client's typed Excel files.

WHY THIS EXISTS
---------------
`eval_100.parse_truth` recognised only one very specific Excel shape, and
silently returned nothing for anything else. Measured across all three
datasets, it parsed 35 of 702 Excel files. The rest were not junk -- most were
perfectly good attendance grids rejected for cosmetic reasons:

  * `Employee_Name` (underscore) did not equal `employee name`, so the whole
    file was dropped. That single character accounted for 73 Delhi files.
  * The header sat below row 15, outside the search window.
  * Fortnightly sheets have 15 day-columns, and the parser demanded >= 20 --
    even though the pipeline itself ships a `t15_fortnight` template.

Ground truth is the scarcest resource in this project: without it, no change
can be shown to help. Recovering these files is worth more than any single
extraction improvement, because it is what makes every later improvement
measurable.

DESIGN
------
Structure first, labels second -- the same principle that drives the extractor
itself. A day grid is found by looking for a run of columns headed 1..31, not
by trusting header wording. The name column is then located relative to that
grid, falling back to "the most name-shaped column to its left" when the
header is missing or oddly worded.
"""
from __future__ import annotations

import re
from pathlib import Path

# --- status vocabulary -----------------------------------------------------
# The client writes weekly-off as WO / W/O; the pipeline emits W.
STATUS_ALIASES = {
    # Bare comp-off forms. The table knew 'C/O' and not the letter, so every
    # correctly read comp-off row scored as an error (decision log D-023).
    "C": "C", "CO": "C", "C/O": "C", "C-O": "C", "COFF": "C", "C OFF": "C",
    "COMP OFF": "C", "COMPOFF": "C", "COMP-OFF": "C", "CF": "C",

    "P": "P", "PRESENT": "P", "PR": "P",
    "A": "A", "AB": "A", "ABSENT": "A", "ABS": "A",
    "L": "L", "CL": "L", "SL": "L", "PL": "L", "EL": "L", "LEAVE": "L",
    "WO": "W", "W/O": "W", "W": "W", "WEEKLY OFF": "W", "WOFF": "W",
    "OFF": "W", "WEEK OFF": "W",
    "H": "H", "PH": "H", "HO": "H", "HOLIDAY": "H", "FH": "H",
    "CO": "C", "C/O": "C",
}

MIN_DAY_COLS = 10          # 15-day fortnightly sheets must qualify
HEADER_SEARCH_ROWS = 60    # headers are not always near the top
MAX_ROWS, MAX_COLS = 600, 80

_NAME_EXACT = {
    "employee name", "name", "emp name", "employee", "emp",
    "name of employee", "employee names", "staff name", "worker name",
    "name of the employee", "candidate name", "person name",
}
# Columns that contain the word "name" but are never the employee.
_NAME_REJECT = ("father", "company", "site", "project", "client", "contractor",
                "bank", "guardian", "husband", "firm", "vendor")

_CODE_HDRS = {"e code", "ecode", "emp code", "employee code", "emp id",
              "employee id", "code", "empid", "emp no", "employee no",
              "token", "token no", "ticket no", "sap id", "emp_id"}
_DESIG_HDRS = {"designation", "desig", "job title", "trade", "category",
               "skill", "post", "position"}


def norm_hdr(s) -> str:
    """Collapse punctuation so `Employee_Name` == `employee name`."""
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


def norm_status(v) -> str | None:

    s = str(v or "").strip().upper().replace(".", "")
    if not s:
        return None
    return STATUS_ALIASES.get(s)


def _day_number(cell) -> int | None:
    """The day of month a column header denotes, in any shape seen in the wild.

    Clients head their day columns very differently, and the original
    integers-only rule silently discarded whole files:

        7  7.0  07          plain
        '7 Mon'             day plus weekday
        '2026-05-01 ...'    a real Excel datetime  (Kolkata LTMM)
        '21May Thu'         day + month + weekday  (Kolkata BBPPL, whose
                            payroll cycle runs the 21st to the 20th)
        '21/05/2026'        dd/mm/yyyy

    Returning None for the last three is why Kolkata appeared to contain no
    attendance data at all.
    """
    s = str(cell or "").strip()
    if not s:
        return None

    # A real date: ISO (Excel datetimes stringify this way) or dd/mm/yyyy.
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})\b", s)
    if m:
        n = int(m.group(3))
        return n if 1 <= n <= 31 else None
    m = re.match(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b", s)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= 31 else None

    # '7.0' from a float-typed cell.
    m = re.match(r"^(\d{1,2})\.0+$", s)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= 31 else None

    # A leading 1-2 digit number NOT followed by another digit or a decimal
    # point. The lookahead is what stops a bare year ('2026') matching as 20.
    m = re.match(r"^(\d{1,2})(?![\d.])", s)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= 31 else None
    return None


def read_sheets(path: Path):
    """Yield each worksheet as a grid of strings. .xls and .xlsx alike."""
    try:
        if path.suffix.lower() == ".xls":
            import xlrd
            bk = xlrd.open_workbook(str(path))
            for sh in bk.sheets():
                grid = []
                for r in range(min(sh.nrows, MAX_ROWS)):
                    row = []
                    for c in range(min(sh.ncols, MAX_COLS)):
                        v = sh.cell_value(r, c)
                        if isinstance(v, float) and v == int(v):
                            v = int(v)
                        row.append(str(v).strip())
                    grid.append(row)
                yield grid
        else:
            import openpyxl
            wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
            try:
                for ws in wb.worksheets:
                    yield [["" if v is None else str(v).strip() for v in row]
                           for row in ws.iter_rows(max_row=MAX_ROWS,
                                                   max_col=MAX_COLS,
                                                   values_only=True)]
            finally:
                wb.close()
    except Exception:                                          # noqa: BLE001
        return


def find_day_grids(grid: list[list[str]]) -> list[tuple[int, dict[int, int]]]:
    """Every (header_row, {day: column}) block in a sheet.

    Some workbooks stack several tables vertically, so all of them are
    returned rather than only the first.
    """
    found = []
    for hi, hdr in enumerate(grid[:HEADER_SEARCH_ROWS]):
        day_cols: dict[int, int] = {}
        for ci, cell in enumerate(hdr):
            n = _day_number(cell)
            # Keep the FIRST column claiming a given day: repeated 1..31 runs
            # (e.g. a second month to the right) must not overwrite it.
            if n is not None and n not in day_cols:
                day_cols[n] = ci
        if len(day_cols) < MIN_DAY_COLS:
            continue
        # Must be a genuine run of consecutive days, not scattered numerics
        # that happen to fall in 1..31 (amounts, serial numbers, rates).
        days = sorted(day_cols)
        if days[0] > 2:
            continue
        consecutive = sum(1 for a, b in zip(days, days[1:]) if b == a + 1)
        if consecutive < len(days) - 3:
            continue
        found.append((hi, day_cols))
    return found


def _looks_like_name(s: str) -> bool:
    s = str(s or "").strip()
    if len(s) < 3 or len(s) > 60:
        return False
    letters = sum(ch.isalpha() or ch.isspace() or ch in ".-'" for ch in s)
    return letters / len(s) > 0.85 and any(ch.isalpha() for ch in s)


def _find_col(grid, hi, first_day_col, wanted: set[str]) -> int | None:
    for ci, cell in enumerate(grid[hi][:first_day_col]):
        if norm_hdr(cell) in wanted:
            return ci
    return None


def find_name_col(grid, hi, first_day_col) -> int | None:
    """Header wording first; column shape as the fallback."""
    hdr = grid[hi][:first_day_col]

    for ci, cell in enumerate(hdr):
        if norm_hdr(cell) in _NAME_EXACT:
            return ci
    for ci, cell in enumerate(hdr):
        h = norm_hdr(cell)
        if "name" in h and not any(b in h for b in _NAME_REJECT):
            return ci

    # No usable header: score the columns to the left of the grid by how many
    # of their values actually look like people's names.
    best, best_score = None, 0.0
    body = grid[hi + 1:hi + 40]
    for ci in range(first_day_col):
        vals = [r[ci] for r in body if ci < len(r) and r[ci].strip()]
        if len(vals) < 3:
            continue
        score = sum(_looks_like_name(v) for v in vals) / len(vals)
        # Prefer the rightmost strong candidate: names sit next to the grid,
        # with codes and serial numbers further left.
        if score > 0.6 and score >= best_score:
            best, best_score = ci, score
    return best


def parse_truth(path: Path) -> list[dict]:
    """Employee rows with their day-status series, from any sheet shape."""
    out: list[dict] = []
    seen: set[tuple] = set()

    for grid in read_sheets(path):
        blocks = find_day_grids(grid)
        # Each block owns only the rows up to the NEXT header. Long sheets
        # repeat their header at page breaks, and parsing every row below
        # every header re-read the same employees under a later header's
        # column mapping -- which both inflated the row count ~7x and, far
        # worse, produced day numbers mapped to the wrong columns. Corrupt
        # ground truth is more dangerous than missing ground truth.
        starts = [hi for hi, _ in blocks]
        for bi, (hi, day_cols) in enumerate(blocks):
            end = starts[bi + 1] if bi + 1 < len(starts) else len(grid)
            first_day_col = min(day_cols.values())
            name_c = find_name_col(grid, hi, first_day_col)
            if name_c is None:
                continue
            code_c = _find_col(grid, hi, first_day_col, _CODE_HDRS)
            desig_c = _find_col(grid, hi, first_day_col, _DESIG_HDRS)

            # A row needs about half its days filled to be a real employee.
            min_days = max(6, int(0.45 * len(day_cols)))

            for r in grid[hi + 1:end]:
                if name_c >= len(r):
                    continue
                nm = r[name_c].strip()
                if len(nm) < 4 or not re.match(r"^[A-Za-z]", nm):
                    continue
                if norm_hdr(nm) in _NAME_EXACT:       # a repeated header row
                    continue
                days = {}
                for d, ci in day_cols.items():
                    if ci < len(r):
                        st = norm_status(r[ci])
                        if st:
                            days[d] = st
                if len(days) < min_days:
                    continue
                key = (nm.lower(), tuple(sorted(days.items())))
                if key in seen:
                    continue
                seen.add(key)
                out.append({
                    "employee_name": nm,
                    "employee_code": (r[code_c].strip()
                                      if code_c is not None and code_c < len(r) else ""),
                    "designation": (r[desig_c].strip()
                                    if desig_c is not None and desig_c < len(r) else ""),
                    "days": days,
                    "source": path.name,
                })
    return out

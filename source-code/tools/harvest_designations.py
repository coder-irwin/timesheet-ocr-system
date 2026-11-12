"""Build the designation vocabulary from the CLIENT'S spreadsheets.

Correcting an earlier mistake
-----------------------------
tools/build_designations.py states, as its whole premise:

    "the client has no designation column in any of their 289 spreadsheets,
     so there was no list to use"

That is false. Every one of those 289 files has a designation column; the
ground-truth parser simply looks at a fixed column index that only matches the
IOCL layout, so the values were never seen. Scanning all sheets for a header
cell reading "Designation" or "Service Category" finds **250 distinct
designations**.

The consequence was serious and silent. Rather than use the client's real list,
the vocabulary was harvested from our own OCR output on a handful of pages,
producing 25 generic titles ("Civil Engineer", "Store Keeper") -- almost none of
which are what this client actually writes:

    Engineer Gr. III (Civil)          460 employees
    Engineer Gr. III (Mechanical)     356
    Engineer Gr. IV (Welding NDT)     248
    Asst. Gr. C (HR)                  216
    Operator Gr. B (IT)               207

So the closed-vocabulary correction -- the technique that took employee names to
97% -- has been matching against the wrong closed set. A vocabulary that does
not contain the right answer cannot produce it, however good the matcher is.

This harvests the real list. Frequencies are kept, because a matcher should
prefer a title held by 460 people over one held by 2 when the reading is
ambiguous.

    python tools/harvest_designations.py
"""
from __future__ import annotations

import csv
import re
import sys
from collections import Counter
from pathlib import Path

BASE = Path(__file__).parent.parent
ROOT = BASE / "Timesheet - Delhi 2026-2027"
OUT = BASE / "data" / "designations.csv"

HEADERS = {"designation", "designations", "service category",
           "service catagory", "job title", "trade"}

# Values that appear under a designation header but are not job titles.
_NOT_A_TITLE = re.compile(
    r"^(nan|none|nil|n/?a|total|s\.?no\.?|sr\.?\s*no\.?|grand total|\d+([.,]\d+)?)$",
    re.I)


def _grids(path: Path):
    """Yield each sheet as a list of rows, for both .xls and .xlsx."""
    if path.suffix.lower() == ".xls":
        import xlrd
        wb = xlrd.open_workbook(str(path))
        for sh in wb.sheets():
            yield [[sh.cell_value(r, c) for c in range(sh.ncols)]
                   for r in range(sh.nrows)]
    else:
        import openpyxl
        wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
        for sh in wb.worksheets:
            yield [[c.value for c in row] for row in sh.iter_rows()]
        wb.close()


def clean(value: str) -> str | None:
    """Normalise spacing/punctuation without changing the client's wording.

    Their spreadsheets contain the same title spelled several ways --
    'Engineer Gr. III (Welding NDT)' / 'Engineer Gr. III (Welding/ NDT)', and
    'Controller Gr. D (EDMS /ERP/MIS )'. Collapsing whitespace and tidying the
    brackets merges those without inventing a new wording.
    """
    v = str(value or "").strip()
    if not v or len(v) < 3 or len(v) > 60:
        return None
    if _NOT_A_TITLE.match(v):
        return None
    v = re.sub(r"\s+", " ", v)
    v = re.sub(r"\s*/\s*", "/", v)
    v = re.sub(r"\(\s*", "(", v)
    v = re.sub(r"\s*\)", ")", v)
    if not re.search(r"[A-Za-z]{3}", v):
        return None
    return v


def harvest() -> Counter:
    counts: Counter = Counter()
    scanned = failed = 0
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".xls", ".xlsx"):
            continue
        if path.name.startswith(("~$", ".")):
            continue
        try:
            for grid in _grids(path):
                for r, row in enumerate(grid):
                    for c, cell in enumerate(row):
                        if str(cell or "").strip().lower() not in HEADERS:
                            continue
                        # Read down the column until it runs dry.
                        blanks = 0
                        for rr in range(r + 1, len(grid)):
                            if c >= len(grid[rr]):
                                break
                            val = clean(grid[rr][c])
                            if val:
                                counts[val] += 1
                                blanks = 0
                            else:
                                blanks += 1
                                if blanks > 8:
                                    break
            scanned += 1
        except Exception:                                       # noqa: BLE001
            failed += 1
    print(f"scanned {scanned} spreadsheets ({failed} unreadable)")
    return counts


def collapse(counts: Counter, threshold: int = 92) -> list[tuple[str, int]]:
    """Merge near-identical spellings, keeping the most frequent as canonical.

    'Engineer Gr. III (Welding NDT)' and 'Engineer Gr. III (Welding/ NDT)' are
    one title typed two ways. Merging them means the matcher has one target
    instead of two competing near-identical ones, which is what makes a margin
    test meaningful.
    """
    from rapidfuzz import fuzz

    ordered = counts.most_common()
    canon: list[list] = []
    for name, n in ordered:
        for entry in canon:
            if fuzz.ratio(name.upper(), entry[0].upper()) >= threshold:
                entry[1] += n
                entry[2].append(name)
                break
        else:
            canon.append([name, n, [name]])
    return [(c[0], c[1]) for c in canon]


def main() -> None:
    counts = harvest()
    if not counts:
        raise SystemExit("no designations found -- check the corpus path")
    merged = collapse(counts)
    merged.sort(key=lambda kv: (-kv[1], kv[0]))

    OUT.write_text("", encoding="utf-8")
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["designation", "count"])
        for name, n in merged:
            w.writerow([name, n])

    print(f"{len(counts)} raw -> {len(merged)} canonical designations")
    print(f"{sum(counts.values()):,} labelled employees")
    print(f"wrote {OUT}\n")
    for name, n in merged[:20]:
        print(f"  {n:>5}  {name}")


if __name__ == "__main__":
    main()

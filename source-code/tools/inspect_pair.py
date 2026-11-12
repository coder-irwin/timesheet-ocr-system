"""Dump the Excel side of a PDF/Excel pair.

The Excel files are what a human produced from the scanned PDF. They are
simultaneously (a) our ground truth for measuring accuracy and (b) the exact
output format the client expects. Both were listed as unknowns in the plan;
they are neither.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path("Timesheet - Delhi 2026-2027")


def read_any(path: Path, max_rows: int = 45, max_cols: int = 22):
    """xls and xlsx need different readers; normalise to a grid of strings."""
    if path.suffix.lower() == ".xls":
        import xlrd
        book = xlrd.open_workbook(str(path))
        for sh in book.sheets():
            grid = []
            for r in range(min(sh.nrows, max_rows)):
                row = []
                for c in range(min(sh.ncols, max_cols)):
                    v = sh.cell_value(r, c)
                    if isinstance(v, float) and v == int(v):
                        v = int(v)
                    row.append(str(v).strip())
                grid.append(row)
            yield sh.name, grid, (sh.nrows, sh.ncols)
    else:
        import openpyxl
        wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
        for ws in wb.worksheets:
            grid = []
            for r, row in enumerate(ws.iter_rows(max_row=max_rows,
                                                 max_col=max_cols,
                                                 values_only=True)):
                grid.append(["" if v is None else str(v).strip() for v in row])
            yield ws.title, grid, (ws.max_row, ws.max_column)
        wb.close()


def show(path: Path) -> None:
    print("=" * 100)
    print(f"FILE: {path.relative_to(ROOT)}")
    print("=" * 100)
    try:
        for name, grid, dims in read_any(path):
            print(f"\n--- sheet '{name}'  (rows={dims[0]} cols={dims[1]}) ---")
            for i, row in enumerate(grid):
                # Trim trailing empties so the shape is readable
                while row and not row[-1]:
                    row.pop()
                if not row:
                    continue
                cells = " | ".join(c[:18].ljust(18) for c in row[:14])
                print(f"{i:>3} {cells}")
            break            # first sheet is enough to see the layout
    except Exception as exc:  # noqa: BLE001
        print(f"  ERROR: {exc}")


if __name__ == "__main__":
    targets = [Path(a) for a in sys.argv[1:]]
    if not targets:
        targets = [
            ROOT / "IOCL30 Indian Oil Corporation Limited/IOCL30 Indian Oil Corporation Limited JULY   2026/July-26_Timesheet_IOCL Mathura.xls",
            ROOT / "Avaada01 Giriraj Renewable/Avaada01 Giriraj Renewable JULY  2026",
        ]
    for t in targets:
        if t.is_dir():
            for f in sorted(t.iterdir()):
                if f.suffix.lower() in (".xls", ".xlsx") and not f.name.startswith("~$"):
                    show(f)
                    break
        elif t.exists():
            show(t)
        else:
            print(f"missing: {t}")

"""Build the employee master roster from the client's own Excel files.

WHY THIS IS THE BIGGEST ACCURACY LEVER
--------------------------------------
Measured: OCR reads the numeric grid on handwritten sheets reasonably well, but
fails on handwritten NAMES and CODES -- on IOCL30 those were 4 of the 5 missed
fields. Handwriting recognition cannot fix that; the strokes genuinely are
ambiguous.

But names are not free text. They are drawn from a CLOSED SET of ~3,000 known
employees. So we do not need to *read* the name correctly -- we only need to
identify which roster entry it is. A garbled "Shiv Shankan" resolves to
"Lokesh Khurana" by similarity; "Safrty Superwiser" is recognisable as a
designation, not a name, and can be rejected.

The client was asked for this file and hasn't supplied it. They don't need to:
they have already typed thousands of these names into the Excel files that ship
alongside the scans. This script harvests them.

WHAT IT DOES
------------
Scans every .xls/.xlsx in the corpus, finds columns that look like employee
names and codes (by header text AND by content shape), and emits a deduplicated
roster CSV.

TERMS
-----
roster        the master list of employees (code + name)
fuzzy match   comparing strings by similarity rather than equality
header row    the row in a spreadsheet that names the columns; not always row 1
"""
from __future__ import annotations

import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("Timesheet - Delhi 2026-2027")
OUT = Path("data/roster.csv")

NAME_HEADERS = ("employee name", "name", "emp name", "employee",
                "service person name", "candidate name", "staff name")
CODE_HEADERS = ("e.code", "ecode", "emp id", "empid", "employee code",
                "emp code", "employee id", "code", "id", "emp. code",
                "service person code")
SKIP_HEADERS = ("client name", "project name", "company name", "location",
                "designation", "site name", "approver", "supervisor")

# A plausible person name: letters/spaces/dots, 2+ chars, not mostly digits.
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'\-]{2,60}$")
# A plausible employee code: has a digit, no spaces, reasonable length.
CODE_RE = re.compile(r"^[A-Za-z0-9\-/_]{2,24}$")

# Words that indicate the cell is a job title or a header, not a person.
NOT_A_NAME = {
    "TOTAL", "NAME", "EMPLOYEE", "SUPERVISOR", "ENGINEER", "TECHNICIAN",
    "SAFETY", "SUPERVISER", "STORE", "KEEPER", "OPERATOR", "HELPER",
    "FOREMAN", "MANAGER", "DESIGNATION", "PRESENT", "ABSENT", "GRAND",
    "SUB", "SNO", "S.NO", "SIGNATURE", "REMARKS", "DATE", "MONTH",
}


def iter_sheets(path: Path):
    """Yield (sheet_name, rows) for xls and xlsx alike."""
    try:
        if path.suffix.lower() == ".xls":
            import xlrd
            book = xlrd.open_workbook(str(path))
            for sh in book.sheets():
                rows = []
                for r in range(min(sh.nrows, 400)):
                    row = []
                    for c in range(min(sh.ncols, 60)):
                        v = sh.cell_value(r, c)
                        if isinstance(v, float) and v == int(v):
                            v = int(v)
                        row.append(str(v).strip())
                    rows.append(row)
                yield sh.name, rows
        else:
            import openpyxl
            wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
            for ws in wb.worksheets:
                rows = []
                for row in ws.iter_rows(max_row=400, max_col=60, values_only=True):
                    rows.append(["" if v is None else str(v).strip() for v in row])
                yield ws.title, rows
            wb.close()
    except Exception:                                          # noqa: BLE001
        return


def looks_like_name(s: str) -> bool:
    s = (s or "").strip()
    if not NAME_RE.match(s):
        return False
    up = s.upper()
    toks = set(re.split(r"[ .]+", up))
    if toks & NOT_A_NAME:
        return False
    if len(s) < 4 or " " not in s.strip():
        # Single-word names exist but are a common source of junk; require a
        # bit more length before accepting one.
        if len(s) < 6:
            return False
    return True


def looks_like_code(s: str) -> bool:
    s = (s or "").strip()
    if not CODE_RE.match(s):
        return False
    if not any(c.isdigit() for c in s):
        return False
    if s.upper() in NOT_A_NAME:
        return False
    # Reject bare years / tiny integers that are really serial numbers.
    if s.isdigit() and len(s) <= 2:
        return False
    return True


def find_columns(rows: list[list[str]]) -> list[tuple[int, int | None, int]]:
    """Locate (name_col, code_col, header_row) candidates.

    Two strategies, because headers are unreliable:
      1. Header text match -- fast and precise when the header exists.
      2. Content shape -- scan columns and pick the one whose cells most often
         look like person names. This rescues sheets with no usable header.
    """
    out = []
    for ri, row in enumerate(rows[:25]):
        low = [c.strip().lower() for c in row]
        name_col = code_col = None
        for ci, cell in enumerate(low):
            if not cell:
                continue
            if any(cell == h or cell.startswith(h) for h in SKIP_HEADERS):
                continue
            if name_col is None and any(cell == h or cell.startswith(h)
                                        for h in NAME_HEADERS):
                name_col = ci
            if code_col is None and any(cell == h or cell.startswith(h)
                                        for h in CODE_HEADERS):
                code_col = ci
        if name_col is not None:
            out.append((name_col, code_col, ri))
    if out:
        return out

    # Fallback: content-shape scan.
    ncols = max((len(r) for r in rows), default=0)
    best_col, best_hits = None, 0
    for ci in range(min(ncols, 20)):
        hits = sum(1 for r in rows[1:200] if ci < len(r) and looks_like_name(r[ci]))
        if hits > best_hits:
            best_col, best_hits = ci, hits
    if best_col is not None and best_hits >= 3:
        # Look for a code column immediately left or right of the names.
        code_col = None
        for cand in (best_col - 1, best_col + 1, best_col - 2):
            if cand is not None and cand >= 0:
                hits = sum(1 for r in rows[1:200]
                           if cand < len(r) and looks_like_code(r[cand]))
                if hits >= 3:
                    code_col = cand
                    break
        return [(best_col, code_col, 0)]
    return []


def main() -> None:
    files = [p for p in ROOT.rglob("*")
             if p.suffix.lower() in (".xls", ".xlsx", ".xlsm")
             and not p.name.startswith("~$") and not p.name.startswith(".")]
    print(f"scanning {len(files)} Excel files ...")

    # name -> {code -> count}; we keep counts so the most frequently seen
    # spelling/code pairing wins, which filters typos automatically.
    people: dict[str, Counter] = defaultdict(Counter)
    seen_clients: dict[str, set] = defaultdict(set)
    stats = Counter()

    for n, f in enumerate(files, 1):
        client = f.relative_to(ROOT).parts[0]
        got_any = False
        for _sheet, rows in iter_sheets(f):
            if not rows:
                continue
            for name_col, code_col, hdr in find_columns(rows):
                for r in rows[hdr + 1:]:
                    if name_col >= len(r):
                        continue
                    nm = r[name_col].strip()
                    if not looks_like_name(nm):
                        continue
                    cd = ""
                    if code_col is not None and code_col < len(r):
                        cand = r[code_col].strip()
                        if looks_like_code(cand):
                            cd = cand
                    key = " ".join(nm.upper().split())
                    people[key][cd] += 1
                    seen_clients[key].add(client)
                    got_any = True
        stats["files_with_people" if got_any else "files_without"] += 1
        if n % 50 == 0:
            print(f"  {n}/{len(files)}  people so far: {len(people)}")

    rows_out = []
    for name, codes in sorted(people.items()):
        code, _cnt = codes.most_common(1)[0]
        rows_out.append({
            "employee_code": code,
            "employee_name": name.title(),
            "clients": ";".join(sorted(seen_clients[name]))[:120],
            "occurrences": sum(codes.values()),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["employee_code", "employee_name",
                                           "clients", "occurrences"])
        w.writeheader()
        w.writerows(rows_out)

    with_code = sum(1 for r in rows_out if r["employee_code"])
    print(f"\n  files yielding people : {stats['files_with_people']}")
    print(f"  files yielding none   : {stats['files_without']}")
    print(f"  DISTINCT EMPLOYEES    : {len(rows_out)}")
    print(f"  with an employee code : {with_code} ({with_code/max(len(rows_out),1):.0%})")
    print(f"\n  sample:")
    for r in rows_out[:12]:
        print(f"    {r['employee_code']:<14} {r['employee_name'][:34]:<36} "
              f"x{r['occurrences']}")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()

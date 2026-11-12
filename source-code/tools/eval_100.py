"""Large-scale accuracy evaluation against the client's own typed Excel.

WHY THIS REPLACES EVERYTHING BEFORE IT
--------------------------------------
Every accuracy number so far came from FIVE hand-labelled pages. That is enough
to pick an OCR engine, and demonstrably NOT enough to tune an extractor: it hid
a bug that was destroying data on most pages, and it sent six "improvements"
in the wrong direction.

The client's corpus contains its own answer key. Alongside the scanned PDFs sit
the spreadsheets a human typed from them:

    S.No | Month | E.Code | Employee Name | Designation | DOJ | Location | 1 | 2 | 3 ... 31
    1    | 46082 | IOCLMS900 | Vikram Prasad Sethi | Safety Supervisor | ... | P | P | P | WO ...

That gives ~33 checkable values per employee (identity, designation, and a
status for every day of the month) instead of the 6-8 a hand-labelled header
provides.

WHAT IS COMPARED
----------------
    employee_name    fuzzy (OCR mangles letters; the roster resolves them)
    designation      fuzzy
    day status       exact, per day: P / A / L / WO / H

Day status is the valuable one. It is what the client's own output format
actually contains, there are ~30 of them per page, and it is derived from the
in/out and hours columns -- so it exercises the day-grid extraction end to end
rather than just the header.

MATCHING
--------
A PDF page is one employee-month; an Excel sheet is a whole site. We match a
page to its row by employee name (fuzzy, with a margin rule) or code. Pages
that cannot be matched are reported, never silently dropped -- an unmatched
page is itself a finding about name extraction.
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import xlrd                                                    # noqa: E402
from rapidfuzz import fuzz, process                            # noqa: E402

from app import pipeline, preprocess                           # noqa: E402
from app.roster import Roster                                  # noqa: E402

BASE = Path(".")
ROOT = BASE / "Timesheet - Delhi 2026-2027"
TMP = BASE / "data" / "_eval100"
TMP.mkdir(parents=True, exist_ok=True)
OUT = BASE / "data" / "eval_100.json"
ROSTER = Roster.from_csv(BASE / "data" / "roster.csv")

NAME_HDRS = ("employee name", "name", "emp name")
CODE_HDRS = ("e.code", "ecode", "emp code", "employee code", "emp id",
             "employee id", "code")
DESIG_HDRS = ("designation", "desig", "job title", "trade")

# The client writes weekly-off as WO / W/O; we emit W. Treat as equivalent.
STATUS_ALIASES = {
    # Bare comp-off forms. The table knew 'C/O' and not the letter, so a
    # correctly read comp-off row scored -- and exported -- as unknown
    # (decision log D-023).
    "C": "C", "CO": "C", "C/O": "C", "C-O": "C", "COFF": "C", "C OFF": "C",
    "COMP OFF": "C", "COMPOFF": "C", "COMP-OFF": "C",

    "P": "P", "PRESENT": "P",
    "A": "A", "AB": "A", "ABSENT": "A",
    "L": "L", "CL": "L", "SL": "L", "PL": "L", "LEAVE": "L",
    "WO": "W", "W/O": "W", "W": "W", "WEEKLY OFF": "W",
    "H": "H", "PH": "H", "HO": "H", "HOLIDAY": "H",
    "CO": "C", "C/O": "C",
}


def norm_status(v) -> str | None:
    s = str(v or "").strip().upper().replace(".", "")
    if not s:
        return None
    return STATUS_ALIASES.get(s)


def read_sheets(path: Path):
    """Yield grids of strings for .xls and .xlsx alike."""
    try:
        if path.suffix.lower() == ".xls":
            bk = xlrd.open_workbook(str(path))
            for sh in bk.sheets():
                grid = []
                for r in range(min(sh.nrows, 400)):
                    row = []
                    for c in range(min(sh.ncols, 60)):
                        v = sh.cell_value(r, c)
                        if isinstance(v, float) and v == int(v):
                            v = int(v)
                        row.append(str(v).strip())
                    grid.append(row)
                yield grid
        else:
            import openpyxl
            wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
            for ws in wb.worksheets:
                yield [["" if v is None else str(v).strip() for v in row]
                       for row in ws.iter_rows(max_row=400, max_col=60,
                                               values_only=True)]
            wb.close()
    except Exception:                                          # noqa: BLE001
        return


def parse_truth(path: Path) -> list[dict]:
    """Employee rows with their day-status series."""
    out: list[dict] = []
    for grid in read_sheets(path):
        for hi, hdr in enumerate(grid[:15]):
            low = [c.strip().lower() for c in hdr]
            name_c = code_c = desig_c = None
            day_cols: dict[int, int] = {}
            for ci, cell in enumerate(low):
                if not cell:
                    continue
                if name_c is None and any(cell == h for h in NAME_HDRS):
                    name_c = ci
                if code_c is None and any(cell == h for h in CODE_HDRS):
                    code_c = ci
                if desig_c is None and any(cell == h for h in DESIG_HDRS):
                    desig_c = ci
                # Day columns are headed 1..31 (as text or number).
                m = re.fullmatch(r"(\d{1,2})(\.0)?", cell)
                if m and 1 <= int(m.group(1)) <= 31:
                    day_cols[int(m.group(1))] = ci
            if name_c is None or len(day_cols) < 20:
                continue
            for r in grid[hi + 1:]:
                if name_c >= len(r):
                    continue
                nm = r[name_c].strip()
                if len(nm) < 4 or not re.match(r"^[A-Za-z]", nm):
                    continue
                days = {}
                for d, ci in day_cols.items():
                    if ci < len(r):
                        st = norm_status(r[ci])
                        if st:
                            days[d] = st
                if len(days) < 15:
                    continue
                out.append({
                    "employee_name": nm,
                    "employee_code": (r[code_c].strip()
                                      if code_c is not None and code_c < len(r) else ""),
                    "designation": (r[desig_c].strip()
                                    if desig_c is not None and desig_c < len(r) else ""),
                    "days": days,
                })
            if out:
                return out
    return out


def match_row(rec: dict, truth: list[dict]) -> dict | None:
    code = re.sub(r"[^A-Z0-9]", "", (rec.get("employee_code") or "").upper())
    name = " ".join((rec.get("employee_name") or "").upper().split())
    if code:
        for t in truth:
            tc = re.sub(r"[^A-Z0-9]", "", (t["employee_code"] or "").upper())
            if tc and tc == code:
                return t
    if not name:
        return None
    names = [t["employee_name"].upper() for t in truth]
    hits = process.extract(name, names, scorer=fuzz.token_sort_ratio, limit=2)
    if not hits or hits[0][1] < 80:
        return None
    if len(hits) > 1 and hits[0][1] - hits[1][1] < 5:
        return None
    return truth[hits[0][2]]


def main() -> None:
    target = int(sys.argv[1]) if len(sys.argv) > 1 else 100

    # Folders with both a PDF and an Excel that actually parses to day-grids.
    pairs: dict[Path, dict] = defaultdict(lambda: {"pdf": [], "xl": []})
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.name.startswith(("~$", ".")):
            continue
        if p.suffix.lower() == ".pdf":
            pairs[p.parent]["pdf"].append(p)
        elif p.suffix.lower() in (".xls", ".xlsx"):
            pairs[p.parent]["xl"].append(p)
    usable = []
    for d, v in sorted(pairs.items()):
        if not (v["pdf"] and v["xl"]):
            continue
        truth: list[dict] = []
        for xl in v["xl"]:
            truth.extend(parse_truth(xl))
        if truth:
            usable.append((d, v["pdf"], truth))
    print(f"folders with usable day-grid ground truth: {len(usable)}")
    print(f"employees in those sheets: {sum(len(t) for _, _, t in usable)}\n")

    import pypdfium2 as pdfium

    st = Counter()
    field_hit, field_tot = Counter(), Counter()
    rows_out = []
    n = 0
    t0 = time.time()

    for d, pdfs, truth in usable:
        if n >= target:
            break
        for pdf in pdfs:
            if n >= target:
                break
            try:
                doc = pdfium.PdfDocument(str(pdf))
                npages = len(doc)
            except Exception:                                  # noqa: BLE001
                st["pdf_error"] += 1
                continue
            for pi in range(npages):
                if n >= target:
                    break
                try:
                    img = doc[pi].render(scale=2).to_pil()
                    dest = TMP / f"{n:04d}.png"
                    img.save(dest)
                    preprocess.normalise_page(dest, dest)
                    out = pipeline.process_page(
                        dest, preprocess.file_sha256(dest), roster=ROSTER)
                except Exception as exc:                       # noqa: BLE001
                    st["page_error"] += 1
                    n += 1
                    continue
                n += 1
                rec = out["record"]
                row = match_row(rec, truth)
                if row is None:
                    st["unmatched"] += 1
                    rows_out.append({"pdf": str(pdf.relative_to(ROOT)),
                                     "page": pi + 1, "matched": False,
                                     "extracted_name": rec.get("employee_name")})
                    continue
                st["matched"] += 1

                # --- identity ---
                got_name = " ".join((rec.get("employee_name") or "").upper().split())
                want_name = row["employee_name"].upper()
                ok_name = bool(got_name) and \
                    fuzz.token_sort_ratio(got_name, want_name) >= 82
                field_tot["employee_name"] += 1
                field_hit["employee_name"] += ok_name

                if row["designation"]:
                    got_d = (rec.get("designation") or "").upper()
                    ok_d = bool(got_d) and \
                        fuzz.token_sort_ratio(got_d, row["designation"].upper()) >= 78
                    field_tot["designation"] += 1
                    field_hit["designation"] += ok_d

                # --- day status (the big one) ---
                got_days = {d_["day"]: (d_.get("status") or "")
                            for d_ in (rec.get("days") or []) if d_.get("day")}
                d_hit = d_tot = 0
                for day, want in row["days"].items():
                    field_tot["day_status"] += 1
                    d_tot += 1
                    if norm_status(got_days.get(day)) == want:
                        field_hit["day_status"] += 1
                        d_hit += 1
                st["day_cmp"] += d_tot
                st["day_ok"] += d_hit

                rows_out.append({
                    "pdf": str(pdf.relative_to(ROOT)), "page": pi + 1,
                    "matched": True, "name_ok": bool(ok_name),
                    "extracted_name": rec.get("employee_name"),
                    "truth_name": row["employee_name"],
                    "days_ok": d_hit, "days_cmp": d_tot,
                    "status": out["status"],
                })
                if n % 10 == 0:
                    print(f"  {n} pages  matched={st['matched']} "
                          f"day-acc={st['day_ok']}/{st['day_cmp']} "
                          f"({time.time()-t0:.0f}s)")
            doc.close()

    print("\n" + "=" * 88)
    print(f"ACCURACY vs THE CLIENT'S OWN TYPED EXCEL  ({n} pages)")
    print("=" * 88)
    print(f"  pages processed        : {n}")
    print(f"  matched to an Excel row: {st['matched']} ({st['matched']/max(n,1):.0%})")
    print(f"  unmatched              : {st['unmatched']}")
    print(f"  page errors            : {st['page_error']}")
    print("\n  FIELD ACCURACY (on matched pages)")
    for k in ("employee_name", "designation", "day_status"):
        if field_tot[k]:
            print(f"    {k:<16} {field_hit[k]:>5}/{field_tot[k]:<5} = "
                  f"{field_hit[k]/field_tot[k]:>5.1%}")
    tot_h = sum(field_hit[k] for k in field_tot)
    tot_t = sum(field_tot.values())
    print(f"\n  OVERALL                {tot_h}/{tot_t} = {tot_h/max(tot_t,1):.1%}")
    print(f"\n  elapsed {time.time()-t0:.0f}s ({(time.time()-t0)/max(n,1):.1f}s/page)")

    OUT.write_text(json.dumps({"stats": dict(st),
                               "field_hit": dict(field_hit),
                               "field_tot": dict(field_tot),
                               "rows": rows_out}, indent=2, default=str),
                   encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

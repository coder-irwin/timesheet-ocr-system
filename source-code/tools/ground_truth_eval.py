"""Accuracy against the client's OWN typed Excel files.

THE POINT
---------
63 folders in the corpus contain both the scanned PDF *and* the Excel a human
typed from it. That Excel is ground truth produced by the client's current
process -- exactly the thing our output has to match or beat.

This is the only measurement that answers "is this deliverable?", because it is
scored against real, human-produced output at scale rather than against five
pages someone eyeballed.

HOW MATCHING WORKS
------------------
A PDF page is one employee-month. An Excel file is usually a whole site: one
row per employee, days as columns. So we cannot compare file-to-file -- we must
find the row that corresponds to the page.

    1. run the pipeline on the PDF page  -> extracted name/code + totals
    2. parse every row of the Excel      -> candidate ground-truth records
    3. match on employee code (exact) or name (fuzzy, with a margin rule)
    4. compare the numeric fields that both sides carry

Pages that cannot be matched to a row are reported separately rather than
silently dropped -- an unmatched page is itself a finding (either our name
extraction failed, or the Excel covers a different month).

WHAT IS COMPARED
----------------
Only fields present on BOTH sides. The client's Excel layouts vary: some carry
per-day status codes (P/A/WO), some carry totals. We compare whatever overlaps,
and report coverage so the reader knows how much of the page was actually
checked.
"""
from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from rapidfuzz import fuzz, process                            # noqa: E402

from app import pipeline, preprocess                           # noqa: E402
from app.roster import Roster                                  # noqa: E402

ROOT = Path("Timesheet - Delhi 2026-2027")
BASE = Path(".")
OUT = BASE / "data" / "ground_truth_eval.json"
TMP = BASE / "data" / "_gt_tmp"
TMP.mkdir(parents=True, exist_ok=True)
ROSTER = Roster.from_csv(BASE / "data" / "roster.csv")

NAME_HDRS = ("employee name", "name", "emp name", "service person name")
CODE_HDRS = ("e.code", "ecode", "emp id", "employee code", "emp code",
             "employee id", "code", "emp. code")
# Total columns worth comparing, mapped to our field names.
TOTAL_HDRS = {
    "present": "total_present_days", "total present": "total_present_days",
    "p": "total_present_days", "total p": "total_present_days",
    "man hours": "total_man_hours", "total man hours": "total_man_hours",
    "manhours": "total_man_hours",
    "ot": "total_ot_hours", "ot hours": "total_ot_hours",
    "total ot": "total_ot_hours", "overtime": "total_ot_hours",
    "w/o": "total_weekly_off", "wo": "total_weekly_off",
    "weekly off": "total_weekly_off",
    "leave": "total_leave_days", "leaves": "total_leave_days",
}

NAME_RE = re.compile(r"^[A-Za-z][A-Za-z .'\-]{2,60}$")


def read_sheets(path: Path):
    try:
        if path.suffix.lower() == ".xls":
            import xlrd
            book = xlrd.open_workbook(str(path))
            for sh in book.sheets():
                rows = []
                for r in range(min(sh.nrows, 500)):
                    row = []
                    for c in range(min(sh.ncols, 70)):
                        v = sh.cell_value(r, c)
                        if isinstance(v, float) and v == int(v):
                            v = int(v)
                        row.append(str(v).strip())
                    rows.append(row)
                yield rows
        else:
            import openpyxl
            wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
            for ws in wb.worksheets:
                yield [["" if v is None else str(v).strip() for v in row]
                       for row in ws.iter_rows(max_row=500, max_col=70,
                                               values_only=True)]
            wb.close()
    except Exception:                                          # noqa: BLE001
        return


def parse_excel_records(path: Path) -> list[dict]:
    """Every employee row we can find, with whatever totals accompany it."""
    out: list[dict] = []
    for rows in read_sheets(path):
        if not rows:
            continue
        for hdr_i, hdr in enumerate(rows[:20]):
            low = [c.strip().lower() for c in hdr]
            name_c = code_c = None
            totals: dict[int, str] = {}
            for ci, cell in enumerate(low):
                if not cell:
                    continue
                if name_c is None and any(cell == h or cell.startswith(h)
                                          for h in NAME_HDRS):
                    name_c = ci
                if code_c is None and any(cell == h or cell.startswith(h)
                                          for h in CODE_HDRS):
                    code_c = ci
                for k, fieldname in TOTAL_HDRS.items():
                    if cell == k:
                        totals[ci] = fieldname
            if name_c is None:
                continue
            for r in rows[hdr_i + 1:]:
                if name_c >= len(r):
                    continue
                nm = r[name_c].strip()
                if not NAME_RE.match(nm) or len(nm) < 4:
                    continue
                rec = {"employee_name": nm,
                       "employee_code": (r[code_c].strip()
                                         if code_c is not None and code_c < len(r)
                                         else "")}
                for ci, fieldname in totals.items():
                    if ci < len(r) and r[ci].strip():
                        rec[fieldname] = r[ci].strip()
                out.append(rec)
            break          # one header row per sheet is enough
    return out


def _norm_num(v) -> str | None:
    if v is None or str(v).strip() == "":
        return None
    try:
        return f"{float(str(v).replace(':', '.')):g}"
    except ValueError:
        return None


def match_row(extracted: dict, candidates: list[dict]) -> dict | None:
    """Find the Excel row for this page. Code first, then fuzzy name."""
    code = (extracted.get("employee_code") or "").strip().upper()
    name = (extracted.get("employee_name") or "").strip().upper()
    if code:
        for c in candidates:
            if (c.get("employee_code") or "").strip().upper() == code:
                return c
    if not name:
        return None
    names = [c["employee_name"].upper() for c in candidates]
    if not names:
        return None
    hits = process.extract(name, names, scorer=fuzz.token_sort_ratio, limit=2)
    if not hits or hits[0][1] < 82:
        return None
    # Margin rule: a near-tie is not a match.
    if len(hits) > 1 and hits[0][1] - hits[1][1] < 6:
        return None
    return candidates[hits[0][2]]


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 40

    # Folders holding both a PDF and an Excel
    by_dir: dict[Path, dict] = defaultdict(lambda: {"pdf": [], "xl": []})
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.name.startswith("~$") or p.name.startswith("."):
            continue
        if p.suffix.lower() == ".pdf":
            by_dir[p.parent]["pdf"].append(p)
        elif p.suffix.lower() in (".xls", ".xlsx"):
            by_dir[p.parent]["xl"].append(p)
    paired = {d: v for d, v in by_dir.items() if v["pdf"] and v["xl"]}
    print(f"paired folders: {len(paired)}")

    import pypdfium2 as pdfium

    stats = Counter()
    field_hits: Counter = Counter()
    field_tot: Counter = Counter()
    rows_out = []
    t0 = time.time()
    n_pages = 0

    for d, v in sorted(paired.items()):
        if n_pages >= limit:
            break
        gt: list[dict] = []
        for xl in v["xl"]:
            gt.extend(parse_excel_records(xl))
        if not gt:
            stats["folders_no_gt"] += 1
            continue
        stats["folders_used"] += 1

        for pdf in v["pdf"]:
            if n_pages >= limit:
                break
            try:
                doc = pdfium.PdfDocument(str(pdf))
                img = doc[0].render(scale=2).to_pil()
                doc.close()
                dest = TMP / f"{n_pages:04d}.png"
                img.save(dest)
                preprocess.normalise_page(dest, dest)
                out = pipeline.process_page(dest, preprocess.file_sha256(dest),
                                            roster=ROSTER)
            except Exception as exc:                           # noqa: BLE001
                stats["page_error"] += 1
                continue
            n_pages += 1
            rec = out["record"]
            summ = rec.get("summary") or {}

            row = match_row(rec, gt)
            if row is None:
                stats["unmatched"] += 1
                rows_out.append({"pdf": str(pdf.relative_to(ROOT)),
                                 "matched": False,
                                 "extracted_name": rec.get("employee_name")})
                continue
            stats["matched"] += 1

            compared, correct, detail = 0, 0, []
            for fieldname in ("total_present_days", "total_man_hours",
                              "total_ot_hours", "total_weekly_off",
                              "total_leave_days"):
                want = _norm_num(row.get(fieldname))
                if want is None:
                    continue
                got = _norm_num(summ.get(fieldname))
                compared += 1
                field_tot[fieldname] += 1
                if got == want:
                    correct += 1
                    field_hits[fieldname] += 1
                else:
                    detail.append({"field": fieldname, "got": got, "want": want})
            stats["fields_compared"] += compared
            stats["fields_correct"] += correct
            if compared == 0:
                stats["matched_no_comparable_fields"] += 1

            rows_out.append({
                "pdf": str(pdf.relative_to(ROOT)), "matched": True,
                "extracted_name": rec.get("employee_name"),
                "gt_name": row.get("employee_name"),
                "compared": compared, "correct": correct, "wrong": detail,
                "status": out["status"],
            })
            if n_pages % 10 == 0:
                print(f"  {n_pages} pages ({time.time()-t0:.0f}s)  "
                      f"matched={stats['matched']} unmatched={stats['unmatched']}")

    print("\n" + "=" * 88)
    print("GROUND-TRUTH EVALUATION vs the client's own typed Excel")
    print("=" * 88)
    print(f"  pages processed          : {n_pages}")
    print(f"  matched to an Excel row  : {stats['matched']} "
          f"({stats['matched']/max(n_pages,1):.0%})")
    print(f"  unmatched                : {stats['unmatched']}")
    print(f"  matched but no comparable numeric field : "
          f"{stats['matched_no_comparable_fields']}")
    fc, ft = stats["fields_correct"], stats["fields_compared"]
    print(f"\n  NUMERIC FIELD ACCURACY   : {fc}/{ft} = "
          f"{fc/max(ft,1):.1%}")
    if field_tot:
        print("\n  per field:")
        for k in field_tot:
            print(f"    {k:<22} {field_hits[k]}/{field_tot[k]} = "
                  f"{field_hits[k]/field_tot[k]:.0%}")
    print(f"\n  elapsed {time.time()-t0:.0f}s")

    OUT.write_text(json.dumps({"stats": dict(stats), "rows": rows_out},
                              indent=2, default=str), encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

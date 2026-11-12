"""Score the pipeline on the horizontal, multi-employee sheets.

Test set: data/testsets/horizontal-multi-employee (see its README).

Truth comes from the PDFs' own text layer (tools/isgec_truth.py), so it is
independent of the OCR being tested. Pages go through the REAL upload path
(preprocess.prepare -> pipeline.process_page), the same as a user upload.

    python tools/eval_isgec.py            # score and print a per-employee grid

Reports employees found vs expected, day-status accuracy, wrong rows, missing
rows, and silent wrong rows (wrong while flagged "ok").
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rapidfuzz import fuzz

TRUTH = Path("data/testsets/horizontal-multi-employee/truth.json")
PDF_DIR = Path("data/testsets/horizontal-multi-employee/sheets")
def truth_norm(v) -> str:
    """Truth side: the sheets write "S" for Sunday, and an empty cell also
    means the person did not work. Both are a weekly off."""
    v = (v or "").strip().upper()
    return "W" if v in ("S", "") else v


def got_norm(v) -> str:
    """Produced side: never treat "no status read" as a weekly off -- that
    would credit a cell the reader never saw. Empty stays empty."""
    v = (v or "").strip().upper()
    return "W" if v == "S" else v


def records_for(pdf: str) -> list[dict]:
    """Every employee record the product produces for this file."""
    from app import pipeline, preprocess
    out = []
    for img, _meta in preprocess.prepare(str(PDF_DIR / pdf), out_dir=Path("data/testsets/horizontal-multi-employee/_run")):
        res = pipeline.process_page(img, hashlib.sha1(img.read_bytes()).hexdigest(),
                                    force=True, source_hint=str(PDF_DIR / pdf))
        out.append(res["record"])
        out.extend(m["record"] for m in res.get("more") or [])
    return out


def main() -> None:
    truth = json.loads(TRUTH.read_text())
    tot = dict(emp_exp=0, emp_got=0, days=0, right=0, wrong=0, missing=0, silent=0)
    for pdf, t in truth.items():
        n = t["days_in_month"]
        recs = records_for(pdf)
        print(f"\n{pdf}   month {t['month'][1]}/{t['month'][0]}, {n} days, "
              f"{len(t['employees'])} employees on the sheet, {len(recs)} record(s) produced")
        for emp in t["employees"]:
            tot["emp_exp"] += 1
            match = max(recs, key=lambda r: fuzz.ratio((r.get("employee_name") or "").upper().replace(" ", ""),
                                                       emp["name"].upper().replace(" ", "")), default=None)
            score = fuzz.ratio((match.get("employee_name") or "").upper().replace(" ", ""),
                               emp["name"].upper().replace(" ", "")) if match else 0
            if not match or score < 70:
                print(f"   {emp['name'][:20]:22} NOT PRODUCED — all {n} days lost")
                tot["missing"] += n; tot["days"] += n
                continue
            tot["emp_got"] += 1
            got = {int(d["day"]): d for d in (match.get("days") or []) if d.get("day")}
            line, right, wrong, miss, silent = [], 0, 0, 0, 0
            for day in range(1, n + 1):
                want = truth_norm(emp["days"].get(str(day)))
                d = got.get(day)
                if d is None:
                    line.append("–"); miss += 1
                    continue
                have = got_norm(d.get("status"))
                if have == want:
                    line.append(have or "·"); right += 1
                else:
                    line.append(f"{have or '?'}!"); wrong += 1
                    if d.get("_review") == "ok":
                        silent += 1
            tot.update(days=tot["days"] + n, right=tot["right"] + right,
                       wrong=tot["wrong"] + wrong, missing=tot["missing"] + miss,
                       silent=tot["silent"] + silent)
            print(f"   {emp['name'][:20]:22} {right}/{n} right, {wrong} wrong, {miss} missing"
                  f"{', ' + str(silent) + ' SILENT' if silent else ''}")
            print(f"     {' '.join(line)}")
    d = tot["days"] or 1
    print(f"\nTOTAL  employees produced {tot['emp_got']}/{tot['emp_exp']} · "
          f"days {tot['right']}/{d} = {100*tot['right']/d:.1f}% · "
          f"wrong {tot['wrong']} · missing {tot['missing']} · silent {tot['silent']}")


if __name__ == "__main__":
    main()

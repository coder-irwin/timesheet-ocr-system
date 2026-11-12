"""Re-export the ISGEC horizontal sheets to Excel with the current pipeline.

Written for the field report of 2026-10-06: the 25th was missing from three
exported workbooks (D-071). This regenerates them from the same PDFs so the
corrected files can be checked against the paper before anything is sent on.
"""
from __future__ import annotations
import hashlib, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from app import export_designs, pipeline, preprocess, validate   # noqa: E402
from app.roster import Roster                                     # noqa: E402

BASE = Path(__file__).parent.parent
SHEETS = BASE / "data" / "testsets" / "horizontal-multi-employee" / "sheets"
OUT = BASE / "data" / "exports_isgec"
TMP = BASE / "data" / "_eval_tmp" / "isgec_export"

roster = Roster.from_csv(BASE / "data" / "roster.csv")
TMP.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

for pdf in sorted(SHEETS.glob("*.pdf")):
    pages: list[dict] = []
    for img, meta in preprocess.prepare(pdf, TMP):
        res = pipeline.process_page(img, hashlib.sha1(Path(img).read_bytes()).hexdigest(),
                                    roster=roster, force=True)
        for r in [res] + list(res.get("more") or []):
            pages.append({
                "id": len(pages) + 1,
                "source_name": pdf.name,
                "image_path": str(img),
                "status": r.get("status", "needs_review"),
                "record": r["record"],
                "issues": r.get("issues") or [],
                "meta": meta,
                "created_at": time.time(),
                "updated_at": time.time(),
            })
    dest = export_designs.export(pages, pdf.stem, design="all", out_dir=OUT)
    days25 = [(p["record"].get("employee_name"),
               next((d.get("status") for d in (p["record"].get("days") or [])
                     if d.get("day") == 25), None))
              for p in pages]
    print(f"{pdf.name}: {len(pages)} employee record(s) -> {dest.name}")
    for name, st in days25:
        print(f"      day 25 = {st!r:5}  {name}")

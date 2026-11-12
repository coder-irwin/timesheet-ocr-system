"""Does the on-demand high-resolution rescue recover the pages it should?

SHELL04 is the SHELL layout printed on a PORTRAIT page, so the landscape rule
in split_pdf never fires and its 30 day-columns are destroyed at the standard
long edge. The rescue re-renders that single page large and re-reads it.

Reports, per sample: days and name with the rescue off vs on, and the wall
time each path costs -- because the rescue must buy accuracy without making a
500-document batch unaffordable.

    python tools/verify_hires_rescue.py [prefix ...]
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

from app import pipeline, preprocess                           # noqa: E402
from app.roster import Roster                                  # noqa: E402

OUT = BASE / "data" / "_hiresverify"


def main() -> None:
    prefixes = sys.argv[1:] or ["SHELL04", "SHELL02", "Thyssen02"]
    OUT.mkdir(parents=True, exist_ok=True)
    roster = Roster.from_csv(BASE / "data" / "roster.csv")

    ev = json.loads((BASE / "data" / "eval_corpus_v17_full.json").read_text())
    idx = json.loads((BASE / "data" / "truth_index.json").read_text())
    by_name = {}
    for _k, v in idx.items():
        for rel in v["pdfs"]:
            by_name[Path(rel).name] = BASE / rel

    for pref in prefixes:
        row = next((r for r in ev["rows"]
                    if not r.get("matched") and r["pdf"].startswith(pref)), None)
        if row is None:
            print(f"{pref}: no failing sample", flush=True)
            continue
        src = by_name.get(Path(row["pdf"]).name)
        if src is None or not src.exists():
            print(f"{pref}: sample not found", flush=True)
            continue

        t0 = time.time()
        pages = preprocess.prepare(src, out_dir=OUT)
        t_prep = time.time() - t0
        page = pages[0][0]
        print(f"\n=== {pref} :: {src.name[:44]} ===", flush=True)
        print(f"    prepare(): {t_prep:.1f}s for {len(pages)} page(s)",
              flush=True)

        for on in (False, True):
            pipeline.HIRES_RESCUE = on
            t0 = time.time()
            res = pipeline.process_page(
                page, preprocess.file_sha256(page) + ("H" if on else "N"),
                roster=roster, source_hint=str(src), force=True)
            dt = time.time() - t0
            rec = res["record"]
            print(f"    HIRES={str(on):<5} days={len(rec.get('days') or []):<3} "
                  f"name={str(rec.get('employee_name'))[:26]!r:<28} "
                  f"hires_used={bool(rec.get('_hires') or rec.get('_hires_boxes'))} "
                  f"{dt:6.1f}s", flush=True)


if __name__ == "__main__":
    main()

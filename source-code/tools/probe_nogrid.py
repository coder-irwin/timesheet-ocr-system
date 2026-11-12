"""Why does the generic detector find no day grid on these pages?

`find_day_axis` returns None for one of several quite different reasons, and
they need different fixes:

  * OCR found almost no text at all      -> a capture/rotation problem
  * day-like numbers exist but too few   -> cells unread, or a short run
  * a run exists but was REJECTED        -> the employee-list guard fired
  * the numbers are not bare integers    -> dates, or '1-May-26' style headers

This prints the evidence for each so the next fix is chosen from data.

    python tools/probe_nogrid.py [folder_prefix ...]
"""
from __future__ import annotations

import json
import sys
import warnings
from collections import Counter
from pathlib import Path

warnings.filterwarnings("ignore")
BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

from PIL import Image                                          # noqa: E402

from app import generic_grid as G                              # noqa: E402
from app import ocr_engine, preprocess                         # noqa: E402

OUT = BASE / "data" / "_nogrid"


def main() -> None:
    prefixes = sys.argv[1:] or ["Thyssen02", "SHELL04", "BBPP01", "ADANI02",
                                "AFCON08", "TRICHY01"]
    OUT.mkdir(parents=True, exist_ok=True)

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
            print(f"{pref:<12} no failing sample in the results")
            continue
        p = by_name.get(Path(row["pdf"]).name)
        if p is None or not p.exists():
            print(f"{pref:<12} sample path not found: {row['pdf']}")
            continue
        try:
            page = preprocess.prepare(p, out_dir=OUT)[0][0]
            boxes = ocr_engine.run_ocr(page)
            w, h = Image.open(page).size
        except Exception as exc:                               # noqa: BLE001
            print(f"{pref:<12} ERROR {exc}")
            continue

        prof = ocr_engine.confidence_profile(boxes)
        daylike = [(b, d) for b in boxes
                   if (d := G._as_day(getattr(b, "text", "")))]
        axis = G.find_day_axis(boxes, w, h)

        # Would a run exist if the employee-list guard were ignored?
        rows_by_x: Counter = Counter()
        for b, _d in daylike:
            rows_by_x[int(((b.x0 + b.x1) / 2) // 40)] += 1
        best_col = max(rows_by_x.values()) if rows_by_x else 0
        rows_by_y: Counter = Counter()
        for b, _d in daylike:
            rows_by_y[int(b.cy // 20)] += 1
        best_row = max(rows_by_y.values()) if rows_by_y else 0

        verdict = G.describe(axis)
        print(f"\n=== {pref} :: {p.name[:44]} p{row['page']} ===")
        print(f"    page {w}x{h}  boxes={len(boxes)}  meanconf={prof['mean']:.3f}")
        print(f"    day-like numbers found: {len(daylike)}")
        print(f"    biggest column cluster: {best_col}   "
              f"biggest row cluster: {best_row}   (need {G.MIN_RUN})")
        print(f"    verdict: {verdict}")
        if daylike:
            sample = sorted({d for _b, d in daylike})[:18]
            print(f"    day values seen: {sample}")
        texts = [str(getattr(b, 'text', ''))[:16] for b in boxes[:12]]
        print(f"    first texts: {texts}")


if __name__ == "__main__":
    main()

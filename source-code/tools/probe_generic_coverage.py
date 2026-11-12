"""How many of the failing client folders can the generic grid reader reach?

The profile-based extractor covers three layouts. `app/generic_grid` is meant
to cover the rest by structure rather than by client. This samples one failing
page from each client folder that produced no employee name and reports what
the structural detector finds -- which is the honest measure of how far the
generalisation actually goes, folder by folder.

    python tools/probe_generic_coverage.py [pages_per_folder]
"""
from __future__ import annotations

import json
import sys
import warnings
from collections import Counter, defaultdict
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from PIL import Image                                          # noqa: E402

from app import generic_grid, ocr_engine, preprocess           # noqa: E402

BASE = Path(__file__).parent.parent
OUT = BASE / "data" / "_genprobe"


def main() -> None:
    per = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    OUT.mkdir(parents=True, exist_ok=True)

    ev = json.loads((BASE / "data" / "eval_corpus_v17_full.json").read_text()) \
        if (BASE / "data" / "eval_corpus_v17_full.json").exists() \
        else json.loads((BASE / "data" / "eval_corpus.json").read_text())
    idx = json.loads((BASE / "data" / "truth_index.json").read_text())

    by_name = {}
    for _k, v in idx.items():
        for rel in v["pdfs"]:
            by_name[Path(rel).name] = BASE / rel

    bad = [r for r in ev["rows"]
           if not r.get("matched") and r.get("reason") == "no_name"]
    folders: dict[str, list] = defaultdict(list)
    for r in bad:
        folders[r["pdf"].split("/")[0]].append(r)

    print(f"{len(bad)} failing pages across {len(folders)} client folders\n")
    print(f"{'client folder':<44}{'orientation':>13}{'days':>6}  result")
    print("-" * 82)

    verdict = Counter()
    for folder, rows in sorted(folders.items(), key=lambda kv: -len(kv[1])):
        shown = 0
        for r in rows:
            if shown >= per:
                break
            p = by_name.get(Path(r["pdf"]).name)
            if p is None or not p.exists():
                continue
            try:
                d = preprocess.prepare(p, out_dir=OUT)[0][0]
                boxes = ocr_engine.run_ocr(d)
                w, h = Image.open(d).size
                ax = generic_grid.find_day_axis(boxes, w, h)
            except Exception as exc:                           # noqa: BLE001
                print(f"{folder[:42]:<44}{'ERROR':>13}{'':>6}  {exc}")
                verdict["error"] += 1
                shown += 1
                continue
            if ax is None:
                print(f"{folder[:42]:<44}{'-':>13}{0:>6}  no grid found")
                verdict["no_grid"] += 1
            else:
                blocks = (generic_grid.read_row_oriented(boxes, ax)
                          if ax.orientation == "row" else [])
                got = sum(len(b["days"]) for b in blocks)
                note = (f"{len(blocks)} employee block(s), {got} day cells"
                        if blocks else
                        ("column layout -- reader not yet written"
                         if ax.orientation == "column" else "grid but no rows"))
                print(f"{folder[:42]:<44}{ax.orientation:>13}"
                      f"{len(ax.days):>6}  {note}")
                verdict[f"{ax.orientation}_readable" if blocks
                        else f"{ax.orientation}_detected"] += 1
            shown += 1

    print()
    print("verdict:", dict(verdict))
    print(f"pages affected per folder: "
          f"{ {k: len(v) for k, v in sorted(folders.items(), key=lambda kv: -len(kv[1]))} }")


if __name__ == "__main__":
    main()

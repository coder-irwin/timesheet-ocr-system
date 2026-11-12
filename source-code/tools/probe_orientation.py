"""How many failing pages are simply rotated?

`preprocess.normalise_page` deskews only within +-15 degrees, so a page scanned
sideways is never straightened. On a 90-degree page the header band contains
the wrong content entirely, every column x-position is meaningless, and
extraction yields nothing.

This measures, for pages that produced no employee name, which of the four
orientations OCR actually prefers. Score is mean confidence weighted by how
much text was found, so "more text read more confidently" wins.

    python tools/probe_orientation.py [n_pages] [dataset]
"""
from __future__ import annotations

import json
import sys
import warnings
from collections import Counter
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import pypdfium2 as pdfium                                     # noqa: E402

from app import ocr_engine, preprocess                         # noqa: E402

BASE = Path(__file__).parent.parent
TMP = BASE / "data" / "_orient"


def score_rotation(img, rot: int) -> float:
    im = img if rot == 0 else img.rotate(rot, expand=True)
    f = TMP / f"probe_{rot}.png"
    im.save(f)
    preprocess.normalise_page(f, f)
    boxes = ocr_engine.run_ocr(f)
    if not boxes:
        return 0.0
    prof = ocr_engine.confidence_profile(boxes)
    return float(prof["mean"]) * (len(boxes) ** 0.3)


def main() -> None:
    n_want = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    dataset = sys.argv[2] if len(sys.argv) > 2 else "HO"
    TMP.mkdir(parents=True, exist_ok=True)

    ev = json.loads((BASE / "data" / "eval_corpus.json").read_text())
    idx = json.loads((BASE / "data" / "truth_index.json").read_text())
    by_name = {}
    for _k, v in idx.items():
        if v["dataset"] != dataset:
            continue
        for rel in v["pdfs"]:
            by_name[Path(rel).name] = BASE / rel

    bad = [r for r in ev["rows"]
           if r["dataset"] == dataset and r.get("reason") == "no_name"]
    print(f"{len(bad)} pages in {dataset} produced no name; sampling {n_want}\n",
          flush=True)

    best = Counter()
    done = 0
    for r in bad:
        if done >= n_want:
            break
        p = by_name.get(Path(r["pdf"]).name)
        if p is None or not p.exists():
            continue
        try:
            doc = pdfium.PdfDocument(str(p))
            img = doc[r["page"] - 1].render(scale=2).to_pil()
        except Exception:                                      # noqa: BLE001
            continue
        sc = {rot: score_rotation(img, rot) for rot in (0, 90, 180, 270)}
        b = max(sc, key=sc.get)
        best[b] += 1
        done += 1
        gain = (sc[b] / sc[0] - 1) * 100 if sc[0] else float("inf")
        print(f"{Path(r['pdf']).name[:36]:<38} p{r['page']:<3} best={b:<4} "
              f"0:{sc[0]:.2f} 90:{sc[90]:.2f} 180:{sc[180]:.2f} "
              f"270:{sc[270]:.2f}  gain={gain:+.0f}%", flush=True)

    print(f"\nsampled {done} failing pages")
    print("best orientation:", dict(best))
    upright = best.get(0, 0)
    print(f"already upright: {upright}/{done} = {upright/max(done,1):.0%}")
    print(f"ROTATED:         {done-upright}/{done} = "
          f"{(done-upright)/max(done,1):.0%}")


if __name__ == "__main__":
    main()

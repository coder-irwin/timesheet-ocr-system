"""Experiment: can OCR confidence route pages better than ink statistics?

BACKGROUND
----------
v1 and v2 of the router tried to classify a whole page as printed or
handwritten from pixel statistics. Both failed, and the failures pointed at a
flaw in the question itself: in this corpus almost every page is a PRINTED FORM
with either TYPED or HANDWRITTEN values in it. "Is this page handwritten" is not
a well-posed question about the page; it is a question about the filled cells.

IDEA UNDER TEST
---------------
Instead of guessing from pixels, run a fast OCR engine and look at what it
reports. OCR engines emit a per-detection confidence score (roughly, how sure
the recogniser is that it read the characters correctly). On typed text that
score is high; on handwriting the engine either scores low or fails to detect
the text at all.

That gives a router with three useful properties:
  * self-calibrating  -- no magic pixel thresholds to tune per client
  * task-aligned      -- it measures the thing we actually care about (can we
                         read this?) rather than a proxy for it
  * graceful          -- low-confidence regions can be escalated individually
                         to the expensive model instead of the whole page

WHAT WE MEASURE
---------------
For each labelled sample: wall-clock seconds (this must run on a CPU-only
laptop), number of text boxes found, and the distribution of confidence scores.

TERMS
-----
OCR       Optical Character Recognition -- turning pixels of text into strings.
ONNX      An open model format; ONNX Runtime executes it on plain CPU, which is
          why this works without a GPU or the heavy PaddlePaddle framework.
confidence A number in 0..1 the recogniser assigns to each text box.
"""
from __future__ import annotations

import statistics
import time
from pathlib import Path

import numpy as np
from rapidocr import RapidOCR

SAMPLES = Path("samples")

LABELLED = {
    "IOCL30_Indian_Oil_Corpor_p1.png": "handwritten values",
    "ADANI02__ADANI_INFRA__IN_p1.png": "typed values",
    "SAMS01_Samsung_Engineeri_p1.png": "typed values",
    "KBR02_Kellog_Brown___Roo_p1.png": "typed values",
    "SAFEARTH01___Safearth_Re_p1.png": "typed values (warped scan)",
    "GRSE01_Garden_Reach_Ship_p1.png": "unknown",
    "NUBE02_Nuberg_Engineerin_p1.png": "unknown",
    "FPEP01_Fourth_Partner_En_p1.png": "unknown",
}


def main() -> None:
    engine = RapidOCR()
    print(f"{'sample':<42} {'label':<26} {'sec':>6} {'boxes':>6} "
          f"{'mean':>6} {'med':>6} {'p25':>6} {'<0.8':>6}")
    print("-" * 108)

    for name, label in LABELLED.items():
        p = SAMPLES / name
        if not p.exists():
            continue
        t0 = time.time()
        res = engine(str(p))
        dt = time.time() - t0

        scores: list[float] = []
        if res is not None and getattr(res, "scores", None) is not None:
            scores = [float(s) for s in res.scores]

        if scores:
            mean = statistics.mean(scores)
            med = statistics.median(scores)
            p25 = float(np.percentile(scores, 25))
            low = sum(1 for s in scores if s < 0.8) / len(scores)
            print(f"{name[:40]:<42} {label:<26} {dt:>6.1f} {len(scores):>6} "
                  f"{mean:>6.3f} {med:>6.3f} {p25:>6.3f} {low:>5.0%}")
        else:
            print(f"{name[:40]:<42} {label:<26} {dt:>6.1f} {0:>6}   (no text found)")


if __name__ == "__main__":
    main()

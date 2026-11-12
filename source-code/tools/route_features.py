"""Page-route classifier, v2 — with a labelled validation set.

WHY THIS EXISTS
---------------
Routing a page to the right pipeline is the highest-leverage decision in the
whole system, because the three routes differ by ~1000x in cost and by a lot in
accuracy:

    digital      text layer already in the PDF -> parse it, 100% accurate, ~0ms
    printed      scan of a typed form          -> OCR, fast, high accuracy
    handwritten  scan of a hand-filled form    -> VLM, 2-5 min/page on CPU

Sending a printed page down the handwritten route wastes minutes per page.
Sending a handwritten page down the printed route silently produces garbage.

WHAT BROKE IN v1
----------------
v1 measured the coefficient of variation of stroke width across ALL ink pixels.
"Stroke width" = how thick the pen/print strokes are; printed glyphs are near
uniform, handwriting varies. The idea is sound, but the SAMS01 timesheets are
fully typed AND contain a column of small scanned signature images. Those few
signature pixels have wildly varying stroke width, which dragged the whole-page
statistic over the threshold and mislabelled 145 typed files as handwritten.

THE FIX
-------
Two changes, both aimed at making the statistic robust to a small contaminating
minority of pixels:

1.  Trim the distribution: use the 10th-90th percentile band of stroke widths
    instead of the full range. A signature column is a small fraction of page
    ink, so trimming removes it while leaving the body text untouched.

2.  Require agreement from a second, independent feature: text-line height
    consistency. Printed rows sit on a strict grid with near-identical glyph
    heights; handwriting wanders. Two weak features that fail in different ways
    are much harder to fool than one strong feature.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium

ROOT = Path("Timesheet - Delhi 2026-2027")

# Hand-labelled by visual inspection. Small, but every one of these was
# actually looked at -- which beats a large set of assumed labels.
LABELS: dict[str, str] = {
    "IOCL30 Indian Oil Corporation Limited/IOCL30 Indian Oil Corporation Limited APR 2026/IOCLMS APR 2026.pdf": "handwritten",
    "ADANI02  ADANI INFRA (INDIA) LIMITED/ADANI02  ADANI INFRA (INDIA) LIMITED APR 2026/ ADN901 APR 2026.pdf": "printed",
    "SAMS01 Samsung Engineering India Pvt Ltd /SAMS01 Samsung Engineering India Pvt Ltd APR 2026/SMEN APR 2026(1).pdf": "printed",
    "KBR02 Kellog Brown & Root Eng. & Const Pvt Ltd/KBR02 Kellog Brown & Root Eng. & Const Pvt Ltd JULY  2026/1.July2026.pdf": "digital",
    "SAFEARTH01 - Safearth Renewables Private Limited/SAFEARTH01 - Safearth Renewables Private Limited JULY  2026 /Bhanu prakash.pdf": "printed",
}


def stroke_width_cv(binimg: np.ndarray) -> float:
    """Trimmed coefficient of variation of stroke width.

    distanceTransform gives, for each ink pixel, the distance to the nearest
    background pixel -- i.e. roughly half the local stroke thickness. Taking
    the spread of that value across the page tells us how uniform the "pen" is.
    We trim to the 10th-90th percentile so a minority of odd strokes (scanned
    signatures, stamps, logos) cannot dominate the statistic.
    """
    dist = cv2.distanceTransform(binimg, cv2.DIST_L2, 3)
    vals = dist[dist > 0.8]
    if vals.size < 300:
        return 0.0
    lo, hi = np.percentile(vals, [10, 90])
    core = vals[(vals >= lo) & (vals <= hi)]
    if core.size < 100:
        return 0.0
    m = float(core.mean())
    return float(core.std() / m) if m else 0.0


def line_height_cv(binimg: np.ndarray) -> float:
    """Spread of text-line heights.

    We dilate horizontally so characters merge into text lines, find those
    blobs, and measure how consistent their heights are. Typed documents use
    one or two font sizes so heights cluster tightly; handwritten rows vary
    much more. Independent of stroke width, so it fails differently.
    """
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 1))
    merged = cv2.dilate(binimg, k, iterations=1)
    n, _, stats, _ = cv2.connectedComponentsWithStats(merged, connectivity=8)
    heights = [stats[i, cv2.CC_STAT_HEIGHT] for i in range(1, n)
               if 6 <= stats[i, cv2.CC_STAT_HEIGHT] <= 120
               and stats[i, cv2.CC_STAT_WIDTH] >= 40]
    if len(heights) < 8:
        return 0.0
    arr = np.array(heights, dtype=float)
    lo, hi = np.percentile(arr, [10, 90])
    core = arr[(arr >= lo) & (arr <= hi)]
    if core.size < 5:
        return 0.0
    m = float(core.mean())
    return float(core.std() / m) if m else 0.0


def features(pdf: Path, probe_pages: int = 2) -> dict:
    doc = pdfium.PdfDocument(str(pdf))
    try:
        n = len(doc)
        text_chars, sw, lh = 0, [], []
        for i in range(min(n, probe_pages)):
            page = doc[i]
            try:
                text_chars += len(page.get_textpage().get_text_range().strip())
            except Exception:                                  # noqa: BLE001
                pass
            g = np.array(page.render(scale=1.4).to_pil().convert("L"))
            _, b = cv2.threshold(g, 0, 255,
                                 cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            sw.append(stroke_width_cv(b))
            lh.append(line_height_cv(b))
        return {
            "pages": n,
            "avg_text": text_chars / max(min(n, probe_pages), 1),
            "sw_cv": float(np.mean(sw)) if sw else 0.0,
            "lh_cv": float(np.mean(lh)) if lh else 0.0,
        }
    finally:
        doc.close()


# Thresholds set from the labelled set below; see docs/03-page-routing.md.
SW_THRESHOLD = 0.42
LH_THRESHOLD = 0.28
TEXT_THRESHOLD = 400


def route(f: dict) -> str:
    if f["avg_text"] > TEXT_THRESHOLD:
        return "digital"
    # Require BOTH features to indicate handwriting. Demanding agreement makes
    # a false "handwritten" (the expensive mistake) much less likely.
    votes = (f["sw_cv"] > SW_THRESHOLD) + (f["lh_cv"] > LH_THRESHOLD)
    return "handwritten" if votes >= 2 else "printed"


def main() -> None:
    print(f"{'file':<46} {'label':<12} {'pred':<12} {'text':>6} {'sw_cv':>6} {'lh_cv':>6}  ok")
    print("-" * 100)
    ok = 0
    for rel, label in LABELS.items():
        p = ROOT / rel
        if not p.exists():
            print(f"{rel[:44]:<46} MISSING")
            continue
        f = features(p)
        pred = route(f)
        good = pred == label
        ok += good
        print(f"{Path(rel).parts[0][:44]:<46} {label:<12} {pred:<12} "
              f"{f['avg_text']:>6.0f} {f['sw_cv']:>6.3f} {f['lh_cv']:>6.3f}  "
              f"{'OK' if good else 'WRONG'}")
    print("-" * 100)
    print(f"accuracy on labelled set: {ok}/{len(LABELS)}")


if __name__ == "__main__":
    main()

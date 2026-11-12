"""Classify every PDF page in the corpus into the three processing routes.

This is the measurement that sizes the build, because the routes have wildly
different cost and accuracy:

  digital   -> extract the text layer directly. 100% accurate, ~0 cost, no model.
  printed   -> scanned image of a typed form. Clean OCR, high accuracy.
  handwrite -> scanned image of a hand-filled form. The genuinely hard case.

Anything routed away from the VLM is a page that costs no inference time on a
CPU-only laptop and cannot be misread. Knowing the split tells us how much of
the 3,000/month actually needs the expensive path.

Digital vs scanned is decided from the PDF text layer. Printed vs handwritten is
decided from ink-stroke statistics on the rendered image: printed glyphs have
near-uniform stroke width and sit on a strict baseline grid; handwriting varies.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else
            "Timesheet - Delhi 2026-2027")
OUT = Path("data/corpus_routes.json")


def ink_stats(img_gray: np.ndarray) -> dict:
    """Stroke-width statistics over the ink pixels.

    Printed text has a tight stroke-width distribution (one font, one weight).
    Handwriting spreads: pen pressure, speed and slant all vary. The ratio of
    the stroke-width std-dev to its mean is a cheap, robust separator that
    needs no model and runs in milliseconds on CPU.
    """
    # Binarise with Otsu on an inverted image so ink is white.
    _, binimg = cv2.threshold(img_gray, 0, 255,
                              cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ink_ratio = float(binimg.mean() / 255.0)
    if ink_ratio < 0.002:                    # essentially blank page
        return {"ink_ratio": ink_ratio, "sw_cv": 0.0, "n_ink": 0}

    # Distance transform gives half the local stroke width at each ink pixel;
    # the ridge (local maxima) approximates the stroke skeleton.
    dist = cv2.distanceTransform(binimg, cv2.DIST_L2, 3)
    vals = dist[dist > 0.8]                  # ignore anti-aliasing fringe
    if vals.size < 200:
        return {"ink_ratio": ink_ratio, "sw_cv": 0.0, "n_ink": int(vals.size)}
    mean, std = float(vals.mean()), float(vals.std())
    return {"ink_ratio": ink_ratio,
            "sw_cv": float(std / mean) if mean else 0.0,
            "n_ink": int(vals.size)}


def route_for(pdf: Path, probe_pages: int = 2) -> dict:
    try:
        doc = pdfium.PdfDocument(str(pdf))
    except Exception as exc:                                  # noqa: BLE001
        return {"route": "error", "error": str(exc)[:100], "pages": 0}
    try:
        n = len(doc)
        text_chars = 0
        stats: list[dict] = []
        for i in range(min(n, probe_pages)):
            page = doc[i]
            try:
                text_chars += len(page.get_textpage().get_text_range().strip())
            except Exception:                                 # noqa: BLE001
                pass
            try:
                img = page.render(scale=1.4).to_pil().convert("L")
                g = np.array(img)
                stats.append(ink_stats(g))
            except Exception:                                 # noqa: BLE001
                pass

        avg_text = text_chars / max(min(n, probe_pages), 1)
        if avg_text > 400:
            return {"route": "digital", "pages": n, "avg_text": round(avg_text)}

        sw_cv = float(np.mean([s["sw_cv"] for s in stats])) if stats else 0.0
        ink = float(np.mean([s["ink_ratio"] for s in stats])) if stats else 0.0
        # Threshold picked from the labelled samples we eyeballed: the typed
        # ADANI/KBR forms sit well below, the hand-filled IOCL sheet above.
        route = "handwritten" if sw_cv > 0.55 else "printed"
        return {"route": route, "pages": n, "avg_text": round(avg_text),
                "sw_cv": round(sw_cv, 3), "ink": round(ink, 4)}
    finally:
        doc.close()


def main() -> None:
    pdfs = [p for p in sorted(ROOT.rglob("*.pdf")) if not p.name.startswith(".")]
    print(f"classifying {len(pdfs)} PDFs ...\n")

    routes: Counter[str] = Counter()
    pages_by_route: Counter[str] = Counter()
    per_client: dict[str, Counter] = defaultdict(Counter)
    detail: dict[str, dict] = {}

    for i, p in enumerate(pdfs, 1):
        info = route_for(p)
        r = info["route"]
        routes[r] += 1
        pages_by_route[r] += info.get("pages", 0)
        client = p.relative_to(ROOT).parts[0]
        per_client[client][r] += 1
        detail[str(p.relative_to(ROOT))] = info
        if i % 100 == 0:
            print(f"  {i}/{len(pdfs)} ...")

    total_pages = sum(pages_by_route.values())
    print("\n=== ROUTE SPLIT (files) ===")
    for r, c in routes.most_common():
        print(f"  {r:<12} {c:>4} files  ({c/len(pdfs):.0%})")
    print("\n=== ROUTE SPLIT (pages) ===")
    for r, c in pages_by_route.most_common():
        print(f"  {r:<12} {c:>5} pages ({c/max(total_pages,1):.0%})")
    print(f"\n  TOTAL PAGES: {total_pages}")

    vlm_pages = pages_by_route.get("handwritten", 0)
    print(f"\n  pages needing the slow VLM path : {vlm_pages} "
          f"({vlm_pages/max(total_pages,1):.0%})")
    print(f"  pages needing NO model at all   : {pages_by_route.get('digital',0)}")

    print("\n=== BY CLIENT ===")
    for c, cnt in sorted(per_client.items()):
        print(f"  {c[:50]:<52} {dict(cnt)}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(
        {"routes_files": dict(routes), "routes_pages": dict(pages_by_route),
         "total_pages": total_pages,
         "per_client": {k: dict(v) for k, v in per_client.items()},
         "detail": detail}, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()

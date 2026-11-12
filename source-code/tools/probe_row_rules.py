"""Diagnostic: can the PRINTED horizontal rules define the day-row bands?

Why this matters
----------------
Day status is 94% of all field comparisons and sits at 56%. The dominant
failure category is `row_missing` (35% of comparisons) -- rows the clusterer
never produced, because two physical rows' ink merged into one cluster.

Every downstream repair for that has been an inference over ink:
  cluster_rows      -> merges rows when handwriting is tall
  cluster_by_pitch  -> assumes a uniform pitch across the whole grid
  split_merged_rows -> measured WORSE (60.2% -> 57.3%), disabled

All three guess row boundaries from where the *writing* is. The printed rules
are where the boundaries actually ARE. ocr_engine._lines already finds them --
they are simply not wired into extract_day_rows.

Two properties would follow if the rules are usable, and neither is available
from ink clustering:
  1. two rows whose ink merged still occupy two separate bands
  2. a BLANK row still occupies a band, so it holds its place in the day
     numbering instead of shifting every later day up by one

This script measures whether the rules are actually there, per page:
  rules_in_grid   how many horizontal rules fall in the day-grid band
  pitch_cv        coefficient of variation of the gaps between them
                  (low = regular grid, high = spurious lines mixed in)
It changes nothing. Measure first.
"""
from __future__ import annotations

import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app import aarvi_form, ocr_engine                          # noqa: E402

BASE = Path(__file__).parent.parent
PAGES = BASE / "data" / "pages"


def probe(path: Path) -> dict:
    an = ocr_engine.analyse(path)
    boxes = an["boxes"]
    rules = an["grid"]["rows"]
    page_h = max((b.y1 for b in boxes), default=1)
    page_w = max((b.x1 for b in boxes), default=1)

    cols = aarvi_form.learn_columns(boxes, page_w)
    date_anc = aarvi_form.find_anchor(boxes, aarvi_form.COLUMN_ANCHORS["date"])
    header_y = date_anc.y1 if date_anc else page_h * 0.25
    footer_y = aarvi_form.summary_band_start(boxes, page_h)
    rows = aarvi_form.extract_day_rows(boxes, cols, header_y)

    lo, hi = header_y, (footer_y if footer_y else page_h)
    inband = sorted(r for r in rules if lo < r < hi)
    gaps = [b - a for a, b in zip(inband, inband[1:])]
    # Ignore hairline duplicates: two detections of one thick rule.
    gaps = [g for g in gaps if g > 4]
    cv = (statistics.pstdev(gaps) / statistics.mean(gaps)) if len(gaps) > 2 else None

    return {
        "page": path.name[-22:],
        "ocr_rows": len(rows),
        "rules_total": len(rules),
        "rules_in_grid": len(inband),
        "median_gap": round(statistics.median(gaps), 1) if gaps else None,
        "pitch_cv": round(cv, 3) if cv is not None else None,
    }


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    pages = sorted(PAGES.glob("*.png"))[:n]
    print(f"{'page':<24}{'ocr_rows':>9}{'rules_grid':>12}"
          f"{'med_gap':>9}{'pitch_cv':>10}")
    for p in pages:
        try:
            r = probe(p)
        except Exception as exc:                                # noqa: BLE001
            print(f"{p.name[-22:]:<24} ERROR {str(exc)[:50]}")
            continue
        print(f"{r['page']:<24}{r['ocr_rows']:>9}{r['rules_in_grid']:>12}"
              f"{str(r['median_gap']):>9}{str(r['pitch_cv']):>10}")


if __name__ == "__main__":
    main()

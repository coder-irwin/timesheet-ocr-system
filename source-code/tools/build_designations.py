"""Harvest a designation vocabulary from the corpus itself.

WHY THIS IS POSSIBLE WITHOUT THE CLIENT
---------------------------------------
Designation is the worst field in the product (19.2%). The fix that took
employee_name to 96.4% was a closed vocabulary -- but the client has no
designation column in any of their 289 spreadsheets, so there was no list to
use.

There is one hiding in the corpus anyway. Two facts make it recoverable:

  1. A large share of pages are PRINTED, and printed designations OCR cleanly.
  2. The same handful of job titles recur across hundreds of pages.

So: read the designation field off many pages, keep the readings that are
frequent and confidently read, and treat those as the vocabulary. A garbled
one-off ("Safrty Superwiser") is rare; the true spelling ("Safety Supervisor")
is common. Frequency separates them without anyone typing a list.

SAFETY
------
A vocabulary built from OCR output can enshrine an OCR error. Guards:
  * require a minimum number of independent sightings
  * require the reading to look like a job title (known job words)
  * collapse near-duplicates, keeping the most frequent spelling as canonical
"""
from __future__ import annotations

import csv
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rapidfuzz import fuzz                                     # noqa: E402

from app import aarvi_form, ocr_engine, preprocess             # noqa: E402
from app.field_typing import JOB_WORDS                         # noqa: E402

BASE = Path(".")
ROOT = BASE / "Timesheet - Delhi 2026-2027"
TMP = BASE / "data" / "_desig"
TMP.mkdir(parents=True, exist_ok=True)
OUT = BASE / "data" / "designations.csv"

MIN_SIGHTINGS = 2          # must be seen independently this many times
MERGE_THRESHOLD = 86       # near-duplicate spellings collapse into one


def looks_like_job(text: str) -> bool:
    t = " ".join(str(text or "").upper().split())
    if not (4 <= len(t) <= 44):
        return False
    if any(c.isdigit() for c in t):
        return False
    for tok in re.split(r"[^A-Z]+", t):
        if len(tok) < 4:
            continue
        for w in JOB_WORDS:
            if fuzz.ratio(tok, w) >= 82:
                return True
    return False


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    import cv2
    import numpy as np
    import pypdfium2 as pdfium

    pdfs = [p for p in sorted(ROOT.rglob("*.pdf")) if not p.name.startswith(".")]
    # Round-robin across clients for a representative spread.
    by_client: dict[str, list[Path]] = {}
    for p in pdfs:
        by_client.setdefault(p.relative_to(ROOT).parts[0], []).append(p)
    ordered: list[Path] = []
    i = 0
    while True:
        added = False
        for lst in by_client.values():
            if i < len(lst):
                ordered.append(lst[i])
                added = True
        if not added:
            break
        i += 1

    seen: Counter = Counter()
    n = 0
    t0 = time.time()
    for pdf in ordered:
        if n >= limit:
            break
        try:
            doc = pdfium.PdfDocument(str(pdf))
        except Exception:                                      # noqa: BLE001
            continue
        try:
            dest = TMP / f"{n:04d}.png"
            doc[0].render(scale=2).to_pil().save(dest)
            preprocess.normalise_page(dest, dest)
            img = cv2.imdecode(np.fromfile(str(dest), dtype=np.uint8),
                               cv2.IMREAD_GRAYSCALE)
            h, w = img.shape
            boxes = ocr_engine.run_ocr(dest)
            prof = ocr_engine.confidence_profile(boxes)
            rec = aarvi_form.extract(boxes, w, h)
            d = (rec.get("designation") or "").strip()
            # Only trust readings from pages the OCR was confident about.
            if d and looks_like_job(d) and prof.get("p25", 0) >= 0.85:
                seen[" ".join(d.title().split())] += 1
        except Exception:                                      # noqa: BLE001
            pass
        finally:
            doc.close()
        n += 1
        if n % 25 == 0:
            print(f"  {n}/{limit} pages, {len(seen)} distinct "
                  f"({time.time()-t0:.0f}s)", flush=True)

    # Collapse near-duplicate spellings, keeping the most frequent as canonical.
    canon: dict[str, int] = {}
    for text, cnt in seen.most_common():
        hit = None
        for c in canon:
            if fuzz.token_sort_ratio(text.upper(), c.upper()) >= MERGE_THRESHOLD:
                hit = c
                break
        if hit:
            canon[hit] += cnt
        else:
            canon[text] = cnt

    rows = [(k, v) for k, v in sorted(canon.items(), key=lambda x: -x[1])
            if v >= MIN_SIGHTINGS]
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        wtr = csv.writer(fh)
        wtr.writerow(["designation", "count"])
        wtr.writerows(rows)

    print(f"\n  pages read           : {n}")
    print(f"  raw distinct readings: {len(seen)}")
    print(f"  after merge          : {len(canon)}")
    print(f"  kept (>= {MIN_SIGHTINGS} sightings): {len(rows)}")
    for k, v in rows[:20]:
        print(f"    {k:<36} x{v}")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()

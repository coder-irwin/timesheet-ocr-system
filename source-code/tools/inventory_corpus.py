"""Count every document and page across the three datasets.

No OCR, no rendering -- just opens each PDF for its page count, so it finishes
in minutes rather than hours. Used to size the handwritten-extraction job
before committing to it.
"""
from __future__ import annotations

import sys
import warnings
from collections import Counter
from pathlib import Path

warnings.filterwarnings("ignore")
BASE = Path(__file__).parent.parent

ROOTS = {
    "Delhi": BASE / "Timesheet - Delhi 2026-2027",
    "HO": BASE / "Timesheet - HO 2026-2027",
    "Kolkata": BASE / "Timesheet - KOLKATA 2026-2027",
}
IMG = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}


def main() -> None:
    import pypdfium2 as pdfium

    grand = Counter()
    print(f"{'dataset':<10}{'pdfs':>7}{'pdf pages':>11}{'digital':>9}"
          f"{'scanned':>9}{'images':>8}{'unreadable':>11}")
    for ds, root in ROOTS.items():
        if not root.exists():
            print(f"{ds:<10} MISSING")
            continue
        pdfs = [p for p in root.rglob("*")
                if p.is_file() and p.suffix.lower() == ".pdf"
                and not p.name.startswith(("~$", "."))]
        imgs = [p for p in root.rglob("*")
                if p.is_file() and p.suffix.lower() in IMG
                and not p.name.startswith(("~$", "."))]
        pages = digital = scanned = bad = 0
        for i, p in enumerate(pdfs):
            try:
                doc = pdfium.PdfDocument(str(p))
                n = len(doc)
                pages += n
                # A page with an extractable text layer is digital-native.
                # Cheap proxy: sample the first page only.
                try:
                    txt = doc[0].get_textpage().get_text_bounded() or ""
                except Exception:                              # noqa: BLE001
                    txt = ""
                if len(txt.strip()) >= 40:
                    digital += n
                else:
                    scanned += n
                doc.close()
            except Exception:                                  # noqa: BLE001
                bad += 1
            if (i + 1) % 400 == 0:
                print(f"    ...{ds} {i+1}/{len(pdfs)}", flush=True)
        print(f"{ds:<10}{len(pdfs):>7}{pages:>11}{digital:>9}{scanned:>9}"
              f"{len(imgs):>8}{bad:>11}", flush=True)
        grand["pdfs"] += len(pdfs); grand["pages"] += pages
        grand["digital"] += digital; grand["scanned"] += scanned
        grand["images"] += len(imgs); grand["bad"] += bad

    print(f"{'TOTAL':<10}{grand['pdfs']:>7}{grand['pages']:>11}"
          f"{grand['digital']:>9}{grand['scanned']:>9}{grand['images']:>8}"
          f"{grand['bad']:>11}")
    candidates = grand["scanned"] + grand["images"]
    print()
    print(f"candidate pages to OCR-classify (scanned PDF pages + images): "
          f"{candidates}")
    for rate in (5.0, 8.0):
        print(f"   at {rate:.0f}s/page, 1 worker : {candidates*rate/3600:6.1f} h"
              f"   |  4 workers: {candidates*rate/3600/4:5.1f} h")


if __name__ == "__main__":
    main()

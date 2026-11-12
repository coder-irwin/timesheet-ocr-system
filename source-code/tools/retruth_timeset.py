"""Recompute clock-time truth for the existing pages, without re-rendering.

Kept separate from build_timeset.py so the page selection stays frozen: if the
sample changed every time the truth rule was tightened, a score could move
because the pages moved, which is the one thing a test set must never do.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import pypdfium2 as pdfium

sys.path.insert(0, str(Path(__file__).parent))
from build_timeset import rows_from_text                       # noqa: E402

BASE = Path(__file__).parent.parent
TRUTH = BASE / "data" / "testsets" / "clock-times" / "truth.json"

truth = json.loads(TRUTH.read_text())
before = sum(len(t["rows"]) for t in truth.values())
dropped_pages = []
for key, t in truth.items():
    pdf = pdfium.PdfDocument(str(BASE / t["src"]))
    try:
        txt = pdf[t["page"] - 1].get_textpage().get_text_range()
    finally:
        pdf.close()
    rows = rows_from_text(txt)
    t["rows"] = {str(k): v for k, v in sorted(rows.items())}
    if len(rows) < 8:
        dropped_pages.append(key)
for key in dropped_pages:
    del truth[key]
TRUTH.write_text(json.dumps(truth, indent=1))
after = sum(len(t["rows"]) for t in truth.values())
print(f"rows {before} -> {after};  pages {len(truth)+len(dropped_pages)} -> {len(truth)}"
      f"{'  dropped ' + ','.join(dropped_pages) if dropped_pages else ''}")

"""Build ground truth for the horizontal multi-employee sheets from the PDF TEXT LAYER.

Test set: data/testsets/horizontal-multi-employee (see its README).

These four sheets are typed PDFs, so every cell's letter and its position are
in the file itself. Reading them from the text layer gives truth that is
completely independent of the OCR pipeline we are testing -- a different
source, not a second opinion from the same reader.

Method: take every character with its box; the row of bare day numbers gives
the column centres; each employee row is a horizontal band; each letter is
assigned to the column it sits in. A column with no letter is a blank cell,
which on these sheets means the person did not work that day.

Writes data/_isgec/truth.json:  {file: {"month": [y,m], "employees": [
    {"name": ..., "days": {"1": "P", ...}}]}}
"""
from __future__ import annotations

import calendar
import json
import re
import sys
from pathlib import Path

import pypdfium2 as pdfium

PDF_DIR = Path("data/testsets/horizontal-multi-employee/sheets")
FILES = ["ISG01,2,3 APR 2026.pdf", "ISGEC_July.pdf", "ISGEC JUNE.pdf", "ISG MAY 2026.pdf"]
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
STATUS = set("PALHOSTW")


def chars(page):
    tp = page.get_textpage()
    out = []
    for i in range(tp.count_chars()):
        ch = tp.get_text_range(i, 1)
        if not ch.strip():
            continue
        l, b, r, t = tp.get_charbox(i)
        out.append({"c": ch, "x": (l + r) / 2, "y": (b + t) / 2})
    return out


def build(path: str) -> dict:
    doc = pdfium.PdfDocument(str(PDF_DIR / path))
    cs = chars(doc[0])
    full = "".join(c["c"] for c in cs)
    m = re.search(r"MONTH:\s*([A-Za-z]+)\s*(\d{4})", full)
    year, mon = (int(m.group(2)), MONTHS[m.group(1).lower()]) if m else (None, None)
    ndays = calendar.monthrange(year, mon)[1] if year else 31

    # The day-number row: the band holding the longest run of bare numbers 1..N.
    bands: dict[int, list] = {}
    for c in cs:
        bands.setdefault(round(c["y"] / 4), []).append(c)
    def digits_in(b):
        words = group_words(b)
        return [w for w in words if w["t"].isdigit() and 1 <= int(w["t"]) <= 31]
    hdr_key = max(bands, key=lambda k: len(digits_in(bands[k])))
    cols = {int(w["t"]): w["x"] for w in digits_in(bands[hdr_key])}
    assert len(cols) >= ndays - 1, f"{path}: found {len(cols)} day columns, expected {ndays}"

    # Employee rows sit below the header; a row is a band containing a name
    # (letters at the far left) and status letters across the day columns.
    left = min(cols.values()) - 20
    rows = []
    for k, b in sorted(bands.items()):
        if b[0]["y"] >= bands[hdr_key][0]["y"]:          # above the header (PDF y grows upward)
            continue
        words = group_words(b)
        name_words = [w for w in group_words(b, gap=12.0) if w["x"] < left and not w["t"].isdigit()]
        name = " ".join(w["t"] for w in name_words)
        cells = [w for w in words if w["x"] >= left and w["t"].upper() in STATUS]
        if name and len(cells) >= 10:          # a real employee row, not the "Payment made at site Yes/No" line
            days = {}
            for w in cells:
                day = min(cols, key=lambda d: abs(cols[d] - w["x"]))
                if abs(cols[day] - w["x"]) < 12:
                    days[str(day)] = w["t"].upper()
            rows.append({"name": name.strip(), "days": days})
    return {"month": [year, mon], "days_in_month": ndays,
            "sundays": [d for d in range(1, ndays + 1) if calendar.weekday(year, mon, d) == 6],
            "employees": rows}


def group_words(band: list, gap: float = 6.0) -> list:
    """Characters on one line -> words, by horizontal gap."""
    band = sorted(band, key=lambda c: c["x"])
    words, cur = [], []
    for c in band:
        if cur and c["x"] - cur[-1]["x"] > gap:
            words.append({"t": "".join(x["c"] for x in cur), "x": sum(x["x"] for x in cur) / len(cur)})
            cur = []
        cur.append(c)
    if cur:
        words.append({"t": "".join(x["c"] for x in cur), "x": sum(x["x"] for x in cur) / len(cur)})
    return [w for w in words if w["t"].strip()]


if __name__ == "__main__":
    out = {}
    for f in FILES:
        out[f] = build(f)
        e = out[f]["employees"]
        print(f"{f[:26]:28} {out[f]['month']}  {len(e)} employees")
        for r in e:
            got = r["days"]
            blanks = [d for d in range(1, out[f]['days_in_month'] + 1) if str(d) not in got]
            print(f"    {r['name'][:20]:22} {len(got):2} letters, blank on {blanks}")
    Path("data/testsets/horizontal-multi-employee").mkdir(parents=True, exist_ok=True)
    Path("data/testsets/horizontal-multi-employee/truth.json").write_text(json.dumps(out, indent=1))
    print("-> data/testsets/horizontal-multi-employee/truth.json")

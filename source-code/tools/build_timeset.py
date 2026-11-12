"""Build the in/out clock-time test set from PDF text layers.

Truth here is *independent* of the OCR under test: it comes from the text the
sheet was printed with, not from reading the image. Pages are sampled across
datasets and client folders so no single client's layout dominates the score --
the corpus is 194 Siemens pages out of 735, and tuning on those would repeat
the "tuning on five pages" mistake at larger scale.
"""
from __future__ import annotations
import json, random, re
from collections import defaultdict
from pathlib import Path
import pypdfium2 as pdfium

BASE = Path(__file__).parent.parent
SRC = BASE / "data" / "timelayer_pages.jsonl"
OUTDIR = BASE / "data" / "testsets" / "clock-times"
RENDER_SCALE = 200 / 72

DATE = r'(\d{1,2})\s*[-/.]\s*(\d{1,2})\s*[-/.]\s*(\d{2,4})'
# Colon only. Sheets write clock times with a colon and *hours* with a dot
# ("01.05.2026 00:00 0.00 HOLIDAY"), so accepting a dot pulled the hours
# column in as a time and invented truth rows that were never clock values.
CLK = r'(\d{1,2}\s*:\s*\d{2})'
ROW = re.compile(rf'^\s*{DATE}\s+{CLK}\s+{CLK}(?![:\d])')
# A row carrying one of these is not a worked day; its "times" are column
# bleed, not something the OCR should be scored against.
NOT_WORKED = re.compile(r'\b(holiday|sunday|week\s*off|weekoff|w\s*/\s*o|\bwo\b|'
                        r'absent|leave|\bcl\b|\bpl\b|\bel\b|\bsl\b)\b', re.I)
PER_CLIENT = 4


def client_of(src: str) -> str:
    parts = src.split("/")
    return parts[1] if len(parts) > 1 else src


def rows_from_text(text: str) -> dict[int, dict]:
    """day -> {'in': 'HH:MM', 'out': 'HH:MM'} for every line that is a full row."""
    out: dict[int, dict] = {}
    for line in text.splitlines():
        m = ROW.match(line)
        if not m:
            continue
        day = int(m.group(1))
        if not 1 <= day <= 31 or day in out:
            continue
        if NOT_WORKED.search(line):
            continue
        norm = lambda s: re.sub(r'\s+', '', s).replace(".", ":")
        t_in, t_out = norm(m.group(4)), norm(m.group(5))
        # 00:00 -> 00:00 is the "nothing happened" filler these sheets print
        # on non-working days, not a shift anyone worked.
        if t_in == t_out == "00:00":
            continue
        out[day] = {"in": t_in, "out": t_out}
    return out


def main(n_per_client: int = PER_CLIENT, seed: int = 20261006) -> None:
    pages = [json.loads(l) for l in SRC.open()]
    by_client: dict[str, list] = defaultdict(list)
    for p in pages:
        rows = rows_from_text(p["text"])
        if len(rows) >= 8:
            p["truth_rows"] = rows
            by_client[client_of(p["src"])].append(p)

    rng = random.Random(seed)
    picked = []
    for client in sorted(by_client):
        pool = by_client[client]
        rng.shuffle(pool)
        picked.extend(pool[:n_per_client])
    picked.sort(key=lambda p: (p["dataset"], p["src"], p["page"]))

    (OUTDIR / "pages").mkdir(parents=True, exist_ok=True)
    truth = {}
    for i, p in enumerate(picked):
        key = f"t{i:03d}"
        img = OUTDIR / "pages" / f"{key}.png"
        pdf = pdfium.PdfDocument(str(BASE / p["src"]))
        try:
            pdf[p["page"] - 1].render(scale=RENDER_SCALE).to_pil().convert("L").save(img)
        finally:
            pdf.close()
        truth[key] = {"src": p["src"], "page": p["page"], "dataset": p["dataset"],
                      "client": client_of(p["src"]), "img": str(img.relative_to(BASE)),
                      "rows": {str(k): v for k, v in sorted(p["truth_rows"].items())}}
        if i % 20 == 0:
            print(f"  rendered {i+1}/{len(picked)}", flush=True)

    (OUTDIR / "truth.json").write_text(json.dumps(truth, indent=1))
    n_rows = sum(len(t["rows"]) for t in truth.values())
    clients = len({t["client"] for t in truth.values()})
    print(f"{len(truth)} pages / {n_rows} rows / {clients} clients -> {OUTDIR/'truth.json'}")


if __name__ == "__main__":
    main()

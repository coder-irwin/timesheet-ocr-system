"""A random 50-page sample from HO and Kolkata, for hand grading.

The 50-page sample this project quotes at 95.8% is drawn from a population
that is 70% Delhi, so every per-site figure for HO and Kolkata rests on a
handful of pages. This draws a fresh sample from the 6,476 HO and Kolkata
pages so the headline can be stated for all three sites rather than one.

Sampled in proportion to the pages each site actually has, and capped at four
pages per client folder: Technip-Dahej alone is 985 pages, and letting one
layout supply a fifth of the sample would repeat the mistake that produced
"82.1% from five hand-picked pages" when the real number was 50.7%.
"""
from __future__ import annotations
import collections, json, random
from pathlib import Path
import pypdfium2 as pdfium

BASE = Path(__file__).parent.parent
POOL = BASE / "data" / "_eval_tmp" / "ho_kol_pool.json"
OUT = BASE / "data" / "_hokol50"
N = 50
PER_FOLDER = 4
SEED = 20261013


def main() -> None:
    pool = [tuple(x) for x in json.loads(POOL.read_text())]
    rng = random.Random(SEED)
    rng.shuffle(pool)

    by_site = collections.Counter(d for d, _, _ in pool)
    total = sum(by_site.values())
    quota = {s: max(1, round(N * n / total)) for s, n in by_site.items()}

    picked: list[tuple] = []
    per_folder: collections.Counter = collections.Counter()
    taken: collections.Counter = collections.Counter()
    for ds, pdf, page in pool:
        folder = pdf.split("/")[1] if "/" in pdf else pdf
        if taken[ds] >= quota[ds] or per_folder[folder] >= PER_FOLDER:
            continue
        picked.append((ds, pdf, page))
        taken[ds] += 1
        per_folder[folder] += 1
        if len(picked) >= N:
            break

    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, (ds, pdf, page) in enumerate(picked):
        doc = pdfium.PdfDocument(str(BASE / pdf))
        try:
            img = doc[page - 1].render(scale=2).to_pil().convert("L")
        finally:
            doc.close()
        name = f"h{i:02d}_{ds[:1]}.png"
        img.save(OUT / name)
        manifest.append({"i": i, "img": str((OUT / name).relative_to(BASE)),
                         "dataset": ds, "src": pdf, "page": page,
                         "client": pdf.split("/")[1] if "/" in pdf else pdf})
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"sampled {len(picked)} pages -> {OUT}")
    print("  by site:", dict(taken), " (quota", dict(quota), ")")
    print("  distinct client folders:", len({m['client'] for m in manifest}))


if __name__ == "__main__":
    main()

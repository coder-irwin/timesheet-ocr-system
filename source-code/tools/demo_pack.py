"""Pick the pages that read best, and stage them as a demo set.

Why curate at all
-----------------
A demo has a job the accuracy harness does not: show the client what the
system looks like when it works, on their own paperwork. Averaged over the
whole corpus the product is at ~79% on day status, and a page drawn at random
will usually carry a few flags. That is the honest headline number and it
belongs in the brief -- but opening on a messy page buries the thing worth
seeing.

So this ranks every scored page by how closely it matched the client's own
typed Excel and copies the best N into demo/. It is selection, not
modification: the pages are the client's, the extraction is unchanged, and the
manifest records each page's real score so nothing is implied that isn't true.

Reads data/eval_100.json (written by tools/eval_100.py), so run that first.

    python tools/eval_100.py
    python tools/demo_pack.py 10
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

BASE = Path(__file__).parent.parent
EVAL = BASE / "data" / "eval_100.json"
ROOT = BASE / "Timesheet - Delhi 2026-2027"
OUT = BASE / "demo"


def rank(rows: list[dict]) -> list[dict]:
    """Best-reading pages first.

    Sorted on day-grid accuracy, because that is what the client will actually
    read across in the review pane. Pages with very few comparable days are
    pushed down: a page scoring 5/5 proves less than one scoring 29/30.
    """
    scored = []
    for r in rows:
        if not r.get("matched") or not r.get("days_cmp"):
            continue
        acc = r["days_ok"] / r["days_cmp"]
        scored.append({**r, "day_acc": acc})
    scored.sort(key=lambda r: (round(r["day_acc"], 3), r["days_cmp"],
                               bool(r.get("name_ok"))), reverse=True)
    return scored


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    if not EVAL.exists():
        raise SystemExit(f"{EVAL} missing -- run tools/eval_100.py first")

    rows = json.loads(EVAL.read_text(encoding="utf-8")).get("rows", [])
    best = rank(rows)
    if not best:
        raise SystemExit("no matched pages in eval_100.json")

    # One page per employee: ten views of the same PDF is a worse demo than
    # ten different people, even if the scores are marginally lower.
    picked, seen = [], set()
    for r in best:
        key = (r.get("truth_name") or "").upper()
        if key in seen:
            continue
        seen.add(key)
        picked.append(r)
        if len(picked) >= n:
            break

    OUT.mkdir(exist_ok=True)
    for f in OUT.glob("*"):
        if f.is_file():
            f.unlink()

    import pypdfium2 as pdfium
    manifest = []
    for i, r in enumerate(picked, 1):
        src = ROOT / r["pdf"]
        if not src.exists():
            continue
        dest = OUT / f"{i:02d}_{(r.get('truth_name') or 'page').replace(' ', '_')}.pdf"
        try:
            doc = pdfium.PdfDocument(str(src))
            out = pdfium.PdfDocument.new()
            out.import_pages(doc, [r["page"] - 1])
            with open(dest, "wb") as fh:
                out.save(fh)
            doc.close()
        except Exception:                                       # noqa: BLE001
            shutil.copy2(src, dest.with_suffix(".pdf"))
        manifest.append({
            "order": i,
            "file": dest.name,
            "employee": r.get("truth_name"),
            "source_pdf": r["pdf"],
            "source_page": r["page"],
            "day_accuracy": f"{r['days_ok']}/{r['days_cmp']} = {r['day_acc']:.0%}",
            "name_read_correctly": bool(r.get("name_ok")),
        })

    (OUT / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"{len(manifest)} pages staged in {OUT}\n")
    print(f"{'#':<3}{'employee':<26}{'day accuracy':<18}{'name':<6}source")
    for m in manifest:
        print(f"{m['order']:<3}{str(m['employee'])[:24]:<26}"
              f"{m['day_accuracy']:<18}{'ok' if m['name_read_correctly'] else '--':<6}"
              f"{Path(m['source_pdf']).name} p{m['source_page']}")
    print(f"\nmanifest: {OUT / 'MANIFEST.json'}")


if __name__ == "__main__":
    main()

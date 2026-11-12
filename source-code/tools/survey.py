"""Survey the client's real data before designing anything further.

Answers the questions that actually determine the architecture:
  1. Are the PDFs scanned images (OCR needed) or digital text (parse, no OCR)?
  2. How many PDF/Excel pairs exist -- i.e. how much ground truth do we have?
  3. What do the Excel files look like (the real output contract)?
  4. How many pages per PDF, and how many distinct layouts?
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pypdfium2 as pdfium

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else
            "Timesheet - Delhi 2026-2027")

IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
XL_EXT = {".xls", ".xlsx", ".xlsm"}


def probe_pdf(path: Path) -> dict:
    """Digital-text vs scanned-image is THE fork: digital text needs no OCR at
    all and is ~100% accurate by construction."""
    try:
        doc = pdfium.PdfDocument(str(path))
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:120]}
    try:
        n = len(doc)
        text_chars, image_count = 0, 0
        probe_pages = min(n, 3)
        for i in range(probe_pages):
            page = doc[i]
            try:
                tp = page.get_textpage()
                text_chars += len(tp.get_text_range().strip())
            except Exception:  # noqa: BLE001
                pass
            try:
                image_count += sum(1 for o in page.get_objects() if o.type == 3)
            except Exception:  # noqa: BLE001
                pass
        avg = text_chars / max(probe_pages, 1)
        if avg > 400:
            kind = "digital_text"
        elif avg > 40:
            kind = "mixed"
        else:
            kind = "scanned_image"
        return {"pages": n, "avg_text_chars": round(avg), "images": image_count,
                "kind": kind}
    finally:
        doc.close()


def main() -> None:
    pdfs, xls, imgs = [], [], []
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.name.startswith("~$") or p.name.startswith("."):
            continue
        s = p.suffix.lower()
        if s == ".pdf":
            pdfs.append(p)
        elif s in XL_EXT:
            xls.append(p)
        elif s in IMG_EXT:
            imgs.append(p)

    print(f"ROOT: {ROOT.name}")
    print(f"  PDFs   : {len(pdfs)}")
    print(f"  Excel  : {len(xls)}")
    print(f"  Images : {len(imgs)}")

    # ---- 1. PDF nature -------------------------------------------------
    print("\n=== PDF NATURE (sampling up to 60) ===")
    kinds: Counter[str] = Counter()
    pages_total = 0
    per_client_kind: dict[str, Counter] = defaultdict(Counter)
    sample = pdfs[:60]
    for p in sample:
        info = probe_pdf(p)
        if "error" in info:
            kinds["error"] += 1
            continue
        kinds[info["kind"]] += 1
        pages_total += info["pages"]
        client = p.relative_to(ROOT).parts[0]
        per_client_kind[client][info["kind"]] += 1
    for k, v in kinds.most_common():
        print(f"  {k:<16} {v:>4}  ({v / max(len(sample),1):.0%})")
    print(f"  avg pages/pdf   {pages_total / max(len(sample) - kinds['error'], 1):.1f}")

    print("\n  by client (sampled):")
    for c, cnt in sorted(per_client_kind.items())[:15]:
        print(f"    {c[:46]:<48} {dict(cnt)}")

    # ---- 2. Ground-truth pairs ----------------------------------------
    print("\n=== PDF + EXCEL PAIRS (ground truth available) ===")
    by_dir: dict[Path, dict[str, list[Path]]] = defaultdict(
        lambda: {"pdf": [], "xl": []})
    for p in pdfs:
        by_dir[p.parent]["pdf"].append(p)
    for p in xls:
        by_dir[p.parent]["xl"].append(p)
    paired = {d: v for d, v in by_dir.items() if v["pdf"] and v["xl"]}
    print(f"  folders with both : {len(paired)}")
    print(f"  PDFs in those     : {sum(len(v['pdf']) for v in paired.values())}")
    print(f"  Excels in those   : {sum(len(v['xl']) for v in paired.values())}")

    # ---- 3. Clients / layouts -----------------------------------------
    print("\n=== CLIENTS (each is potentially its own template) ===")
    clients = sorted({p.relative_to(ROOT).parts[0] for p in pdfs + xls})
    print(f"  distinct client folders: {len(clients)}")
    for c in clients:
        n_pdf = sum(1 for p in pdfs if p.relative_to(ROOT).parts[0] == c)
        n_xl = sum(1 for p in xls if p.relative_to(ROOT).parts[0] == c)
        print(f"    {c[:52]:<54} pdf={n_pdf:<4} xls={n_xl}")

    out = ROOT.parent / "data" / "survey.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "counts": {"pdf": len(pdfs), "excel": len(xls), "image": len(imgs)},
        "pdf_kinds_sampled": dict(kinds),
        "paired_folders": len(paired),
        "clients": clients,
        "paired": {str(d.relative_to(ROOT)): {
            "pdf": [p.name for p in v["pdf"]],
            "xl": [p.name for p in v["xl"]]} for d, v in paired.items()},
    }, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()

"""Render representative PDF pages to PNG so they can actually be looked at.

Everything about the extraction design depends on what these pages really are:
a handwritten in/out + OT grid (hard), or an attendance-status grid of single
characters (much easier and far more accurate). Guessing this wrong wastes the
whole build.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pypdfium2 as pdfium

ROOT = Path("Timesheet - Delhi 2026-2027")
OUT = Path("samples")
OUT.mkdir(parents=True, exist_ok=True)

# One PDF per client so we see the spread of layouts, not one client's quirk.
def pick_one_per_client(limit_clients: int = 12) -> list[Path]:
    by_client: dict[str, Path] = {}
    for p in sorted(ROOT.rglob("*.pdf")):
        if p.name.startswith("."):
            continue
        client = p.relative_to(ROOT).parts[0]
        by_client.setdefault(client, p)
    return list(by_client.values())[:limit_clients]


def render(pdf: Path, out_stem: str, max_pages: int = 1, scale: float = 2.0) -> list[Path]:
    written = []
    doc = pdfium.PdfDocument(str(pdf))
    try:
        for i in range(min(len(doc), max_pages)):
            img = doc[i].render(scale=scale).to_pil()
            # Downscale so the file is small enough to view quickly but still
            # legible for handwriting.
            w, h = img.size
            if max(w, h) > 1700:
                r = 1700 / max(w, h)
                img = img.resize((int(w * r), int(h * r)))
            dest = OUT / f"{out_stem}_p{i+1}.png"
            img.save(dest)
            written.append(dest)
    finally:
        doc.close()
    return written


if __name__ == "__main__":
    targets = [Path(a).resolve() for a in sys.argv[1:]] or pick_one_per_client()
    for pdf in targets:
        # Accept paths given relative to cwd as well as absolute ones.
        try:
            client = pdf.relative_to(ROOT).parts[0]
        except ValueError:
            client = pdf.parent.parent.name or pdf.stem
        stem = "".join(ch if ch.isalnum() else "_" for ch in client)[:24]
        try:
            for f in render(pdf, stem):
                print(f"{f.name:<40} <- {pdf.relative_to(ROOT)}")
        except Exception as exc:  # noqa: BLE001
            print(f"FAILED {pdf.name}: {exc}")

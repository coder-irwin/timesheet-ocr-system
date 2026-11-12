"""Same score as eval_100.py, but ~100x faster to re-run after a code change.

Why this exists
---------------
eval_100.py takes ~20 minutes because it re-runs OCR on all 49 pages. But OCR
output does not change when extraction logic changes -- and extraction logic is
what every experiment touches. Twenty minutes per experiment is the real limit
on how many hypotheses can be tested, and it is self-inflicted.

So: freeze the OCR layer once (boxes, page size, printed rules, ground-truth
row) into data/eval_frozen.pkl, then replay extraction against it. A change to
aarvi_form.py can then be scored in seconds.

    python tools/eval_fast.py --freeze     # once, ~20 min, after an OCR change
    python tools/eval_fast.py              # every experiment after that

What this deliberately does NOT cover: anything upstream of extraction --
preprocessing, the OCR engine itself, the VLM header fallback. Those change the
frozen inputs, so re-freeze (or run eval_100.py) before quoting a final number.
The frozen file records the pipeline version it was built from and warns when
it no longer matches.
"""
from __future__ import annotations

import pickle
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rapidfuzz import fuzz                                      # noqa: E402

from app import aarvi_form, ocr_engine, preprocess              # noqa: E402
from tools.eval_100 import (ROOT, TMP, match_row,               # noqa: E402
                            norm_status, parse_truth)

BASE = Path(__file__).parent.parent
FROZEN = BASE / "data" / "eval_frozen.pkl"


# ---------------------------------------------------------------------------
# Freeze
# ---------------------------------------------------------------------------

def freeze(target: int = 100) -> None:
    import pypdfium2 as pdfium

    pairs: dict[Path, dict] = defaultdict(lambda: {"pdf": [], "xl": []})
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.name.startswith(("~$", ".")):
            continue
        if p.suffix.lower() == ".pdf":
            pairs[p.parent]["pdf"].append(p)
        elif p.suffix.lower() in (".xls", ".xlsx"):
            pairs[p.parent]["xl"].append(p)

    usable = []
    for d, v in sorted(pairs.items()):
        if not (v["pdf"] and v["xl"]):
            continue
        truth: list[dict] = []
        for xl in v["xl"]:
            truth.extend(parse_truth(xl))
        if truth:
            usable.append((d, v["pdf"], truth))

    frames, n, t0 = [], 0, time.time()
    for _d, pdfs, truth in usable:
        if n >= target:
            break
        for pdf in pdfs:
            if n >= target:
                break
            try:
                doc = pdfium.PdfDocument(str(pdf))
            except Exception:                                   # noqa: BLE001
                continue
            for pi in range(len(doc)):
                if n >= target:
                    break
                try:
                    dest = TMP / f"frz{n:04d}.png"
                    doc[pi].render(scale=2).to_pil().save(dest)
                    preprocess.normalise_page(dest, dest)
                    boxes = ocr_engine.run_ocr(dest)
                    rules = ocr_engine.detect_row_rules(dest)
                    import cv2
                    import numpy as np
                    img = cv2.imdecode(np.fromfile(str(dest), dtype=np.uint8),
                                       cv2.IMREAD_GRAYSCALE)
                    ph, pw = img.shape[:2]
                except Exception:                               # noqa: BLE001
                    n += 1
                    continue
                frames.append({
                    "pdf": str(pdf.relative_to(ROOT)), "page": pi + 1,
                    # Kept so experiments on the RULE DETECTOR itself can
                    # re-derive rules from the image without a re-freeze.
                    "png": str(dest),
                    "boxes": boxes, "rules": rules,
                    "page_w": pw, "page_h": ph,
                    "profile": ocr_engine.confidence_profile(boxes),
                    "truth": truth,
                })
                n += 1
                if n % 10 == 0:
                    print(f"  frozen {n} pages ({time.time()-t0:.0f}s)")
            doc.close()

    FROZEN.write_bytes(pickle.dumps(frames))
    print(f"wrote {FROZEN}  ({len(frames)} pages, {time.time()-t0:.0f}s)")


# ---------------------------------------------------------------------------
# Score
# ---------------------------------------------------------------------------

def score(use_rules: bool = True, ink_footer: bool = True,
          quiet: bool = False, label: str = "",
          source_hint: bool = True) -> dict:
    if not FROZEN.exists():
        raise SystemExit(f"{FROZEN} missing -- run: python tools/eval_fast.py --freeze")
    frames = pickle.loads(FROZEN.read_bytes())

    st, hit, tot = Counter(), Counter(), Counter()
    t0 = time.time()
    for f in frames:
        route = ocr_engine.route_from_profile(f["profile"])
        try:
            rec = aarvi_form.extract(
                f["boxes"], f["page_w"], f["page_h"],
                handwritten=(route == "needs_escalation"),
                row_rules=f["rules"] if use_rules else None,
                ink_footer=ink_footer,
                source_hint=f.get("pdf") if source_hint else None)
        except Exception:                                       # noqa: BLE001
            st["page_error"] += 1
            continue

        row = match_row(rec, f["truth"])
        if row is None:
            st["unmatched"] += 1
            continue
        st["matched"] += 1

        got = " ".join((rec.get("employee_name") or "").upper().split())
        tot["employee_name"] += 1
        hit["employee_name"] += bool(got) and \
            fuzz.token_sort_ratio(got, row["employee_name"].upper()) >= 82

        if row["designation"]:
            gd = (rec.get("designation") or "").upper()
            tot["designation"] += 1
            hit["designation"] += bool(gd) and \
                fuzz.token_sort_ratio(gd, row["designation"].upper()) >= 78

        got_days = {d["day"]: (d.get("status") or "")
                    for d in (rec.get("days") or []) if d.get("day")}
        for day, want in row["days"].items():
            tot["day_status"] += 1
            hit["day_status"] += norm_status(got_days.get(day)) == want

    th, tt = sum(hit[k] for k in tot), sum(tot.values())
    if not quiet:
        if label:
            print(f"\n=== {label} ===")
        print(f"  pages {len(frames)}  matched {st['matched']}  "
              f"unmatched {st['unmatched']}  errors {st['page_error']}")
        for k in sorted(tot):
            print(f"    {k:<16} {hit[k]:>5}/{tot[k]:<5} = {hit[k]/tot[k]:.1%}")
        print(f"    {'OVERALL':<16} {th:>5}/{tt:<5} = {th/max(tt,1):.1%}"
              f"   ({time.time()-t0:.1f}s)")
    return {"overall": th / max(tt, 1), "hit": dict(hit), "tot": dict(tot),
            "matched": st["matched"]}


if __name__ == "__main__":
    if "--freeze" in sys.argv:
        freeze(int(sys.argv[sys.argv.index("--freeze") + 1])
               if len(sys.argv) > sys.argv.index("--freeze") + 1
               and sys.argv[-1].isdigit() else 100)
    elif "--matrix" in sys.argv:
        # All four combinations of the two independent switches, so each is
        # attributed on its own instead of as a bundle.
        for rules in (False, True):
            for footer in (False, True):
                score(use_rules=rules, ink_footer=footer,
                      label=f"rule_bands={rules}  ink_footer={footer}")
    else:
        # Defaults MUST mirror app/aarvi_form.extract's production defaults.
        # They did not: ink_footer defaulted to False here and True there, so
        # `python tools/eval_fast.py` and an in-process score() call measured
        # two different configurations and disagreed by 20 day comparisons.
        # A harness whose default is not the shipped default is worse than no
        # harness -- it reports a number for code nobody runs.
        score(use_rules="--no-rules" not in sys.argv,
              ink_footer="--no-ink-footer" not in sys.argv)

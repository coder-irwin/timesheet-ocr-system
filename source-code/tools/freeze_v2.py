"""Freeze a corpus-faithful fast set: the clients where the corpus loses.

eval_fast's frozen set is 41/49 IOCL30 -- it cannot see ADANI02 or GRSE01,
which carry 69% of corpus day errors (decision log D-007). This freezes a
second set, sampled by client, into data/frozen_v2.pkl. Same frame shape as
eval_fast so score() can consume it unchanged.
"""
import pickle, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import eval_fast as ef
from app import ocr_engine, preprocess
from tools.truth import parse_truth
import pypdfium2 as pdfium, cv2, numpy as np

WANT = {"ADANI02": 30, "GRSE01": 25, "IOCL30": 15, "Avaada01": 4}
OUT = ef.FROZEN.with_name("frozen_v2.pkl")
TMP = ef.TMP.with_name("frz2"); TMP.mkdir(parents=True, exist_ok=True)

frames, t0 = [], time.time()
got = {k: 0 for k in WANT}
for d in sorted(ef.ROOT.rglob("*")):
    if not d.is_dir(): continue
    fam = next((k for k in WANT if k in d.name), None)
    if not fam or got[fam] >= WANT[fam]: continue
    pdfs = sorted(d.glob("*.pdf")); xls = list(d.glob("*.xls*"))
    if not pdfs or not xls: continue
    truth = []
    for x in xls:
        try: truth.extend(parse_truth(x))
        except Exception: pass
    if not truth: continue
    for pdf in pdfs:
        if got[fam] >= WANT[fam]: break
        try: doc = pdfium.PdfDocument(str(pdf))
        except Exception: continue
        for pi in range(min(len(doc), 3)):
            if got[fam] >= WANT[fam]: break
            n = len(frames); dest = TMP / f"frz{n:04d}.png"
            try:
                doc[pi].render(scale=2).to_pil().save(dest)
                preprocess.normalise_page(dest, dest)
                boxes = ocr_engine.run_ocr(dest)
                rules = ocr_engine.detect_row_rules(dest)
                img = cv2.imdecode(np.fromfile(str(dest), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
                ph, pw = img.shape[:2]
            except Exception: continue
            frames.append({"pdf": str(pdf.relative_to(ef.ROOT)), "page": pi+1, "png": str(dest),
                           "boxes": boxes, "rules": rules, "page_w": pw, "page_h": ph,
                           "profile": ocr_engine.confidence_profile(boxes), "truth": truth})
            got[fam] += 1
            if len(frames) % 10 == 0: print(f"  frozen {len(frames)} {got} ({time.time()-t0:.0f}s)", flush=True)
        doc.close()
OUT.write_bytes(pickle.dumps(frames))
print(f"wrote {OUT} ({len(frames)} pages) {got} {time.time()-t0:.0f}s")

"""Stage-1 probe: does a pre-OCR technique change day accuracy on handwriting?

Takes the handwritten frames of a frozen set (their PNGs are stored), applies
one technique, re-runs OCR, re-extracts, re-scores. Reports strict day hits
per technique on the same pages. Measured, so the report can say what
Stage 1 was worth rather than assert it.
"""
import pickle, sys, time
from pathlib import Path
import cv2, numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent)); sys.path.insert(0, ".")
import eval_fast as ef
from app import aarvi_form as af, ocr_engine

def t_baseline(img): return img
def t_clahe(img):
    c = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)); return c.apply(img)
def t_adaptive(img):
    return cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 12)
def t_unsharp(img):
    blur = cv2.GaussianBlur(img, (0, 0), 2.0); return cv2.addWeighted(img, 1.6, blur, -0.6, 0)
def t_denoise(img):
    return cv2.fastNlMeansDenoising(img, None, h=7, templateWindowSize=7, searchWindowSize=21)
def t_morph_close(img):
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2)); return cv2.morphologyEx(img, cv2.MORPH_CLOSE, k)
TECH = {"baseline": t_baseline, "clahe": t_clahe, "adaptive": t_adaptive,
        "unsharp": t_unsharp, "denoise": t_denoise, "morph_close": t_morph_close}

def run(frames, name, tmp):
    fn = TECH[name]; hit = tot = 0; t0 = time.time()
    for i, f in enumerate(frames):
        src = Path(f["png"])
        if not src.exists(): continue
        img = cv2.imdecode(np.fromfile(str(src), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
        out = tmp / f"{name}_{i:03d}.png"
        cv2.imencode(".png", fn(img))[1].tofile(str(out))
        boxes = ocr_engine.run_ocr(out)
        prof = ocr_engine.confidence_profile(boxes)
        route = ocr_engine.route_from_profile(prof)
        try:
            rec = af.extract(boxes, f["page_w"], f["page_h"], handwritten=(route == "needs_escalation"),
                             row_rules=f["rules"], ink_footer=True, source_hint=f.get("pdf"))
        except Exception: continue
        row = ef.match_row(rec, f["truth"])
        if row is None: continue
        got = {d["day"]: ef.norm_status(d.get("status") or "") for d in (rec.get("days") or []) if d.get("day")}
        for day, want in row["days"].items():
            tot += 1; hit += (got.get(day) == want)
    return hit, tot, time.time() - t0

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "v2"
    fz = ef.FROZEN.with_name("frozen_v2.pkl") if which == "v2" else ef.FROZEN
    frames = pickle.loads(fz.read_bytes())
    # handwritten only: the route says needs_escalation
    hw = [f for f in frames if ocr_engine.route_from_profile(f["profile"]) == "needs_escalation"]
    print(f"{which}: {len(hw)} handwritten frames of {len(frames)}")
    tmp = Path("data/_preocr_probe"); tmp.mkdir(parents=True, exist_ok=True)
    names = sys.argv[2:] or list(TECH)
    for n in names:
        h, t, s = run(hw, n, tmp)
        print(f"  {n:<12} {h:>4}/{t:<4} = {100*h/max(t,1):5.1f}%   ({s:.0f}s)", flush=True)

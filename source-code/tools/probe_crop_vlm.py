"""Experiment: VLM on a CROPPED region instead of a whole page.

WHY REVISIT THE VLM
-------------------
The earlier benchmark ran VLMs as whole-page transcribers and they lost badly:
Qwen3-VL scored 30% on handwriting at 563 s/page -- ~100x slower than OCR and
less accurate. That result is real, but it measured the wrong job.

Whole-page transcription is the VLM's worst case: a huge image to encode, and
thousands of output tokens where any drift compounds. The header block is the
opposite: a small crop (~15% of the page), four fields, and a ~40-token answer.

Meanwhile the header is exactly where our rule-based extractor is weakest --
43% of pages cannot even be matched to a ground-truth row because the name came
out as 'APRIL-2026'.

So the question worth asking is not "VLM or OCR" but "can the VLM handle the
one small region OCR keeps getting wrong, cheaply enough to be worth it".

WHAT THIS MEASURES
------------------
For each test page: crop the header, ask the VLM for four fields as JSON, and
compare against ground truth I read off the scans by eye. Records accuracy AND
seconds, because a fix that costs 60 s/page is not shippable at 3,000/day.
"""
from __future__ import annotations

import base64
import io
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import cv2                                                     # noqa: E402
import httpx                                                   # noqa: E402
import numpy as np                                             # noqa: E402
from PIL import Image                                          # noqa: E402

BASE = Path(".")
PAGES = BASE / "data" / "pages"

# Ground truth read directly off the scans during this session.
TRUTH = {
    "1_IOCLMS APR 2026_p001.png": dict(
        month="April-2026", name="Lokesh Khurana",
        designation="Safety Supervisor", code="54788"),
    "1_IOCLMS APR 2026_p003.png": dict(
        month="APRIL 2026", name="Pradeep Chauhan",
        designation="Safety Supervisor", code="50782"),
    "1_IOCLMS APR 2026_p005.png": dict(
        month="APRIL-2026", name="RAJEEV IYENGAR",
        designation="SAFETY SUPERVISOR", code="50700"),
}

PROMPT = """This is the header of a handwritten timesheet form.

Read these four handwritten values and return ONLY JSON:
{"month":"...","name":"...","designation":"...","code":"..."}

- "month" is the MONTH & YEAR value
- "name" is the EMPLOYEE NAME value
- "designation" is the DESIGNATION value (a job title)
- "code" is the EMPLOYEE CODE value (digits)

Copy exactly what is handwritten. Use "" if you cannot read a field."""


def crop_header(path: Path, frac: float = 0.22) -> bytes:
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    h, w = img.shape[:2]
    crop = img[0:int(h * frac), 0:w]
    # Upscale: small text benefits, and the image is tiny either way.
    crop = cv2.resize(crop, (int(w * 1.5), int(h * frac * 1.5)),
                      interpolation=cv2.INTER_CUBIC)
    ok, buf = cv2.imencode(".png", crop)
    return buf.tobytes()


def ask(model: str, png: bytes, timeout: float = 300.0) -> tuple[dict, float]:
    b64 = base64.b64encode(png).decode()
    t0 = time.time()
    with httpx.Client(timeout=timeout) as c:
        r = c.post("http://127.0.0.1:11434/api/generate", json={
            "model": model, "prompt": PROMPT, "images": [b64],
            "stream": False, "think": False, "format": "json",
            "options": {"temperature": 0.0, "num_predict": 512},
        })
        r.raise_for_status()
        j = r.json()
    dt = time.time() - t0
    txt = j.get("response") or j.get("thinking") or ""
    try:
        return json.loads(txt), dt
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", txt, re.S)
        if m:
            try:
                return json.loads(m.group(0)), dt
            except json.JSONDecodeError:
                pass
    return {}, dt


def norm(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def score(got: dict, want: dict) -> tuple[int, list[str]]:
    from rapidfuzz import fuzz
    hits, detail = 0, []
    for k in ("month", "name", "designation", "code"):
        g, w = str(got.get(k) or ""), want[k]
        if k == "code":
            ok = norm(g) == norm(w)
        else:
            ok = bool(g) and fuzz.token_sort_ratio(g.upper(), w.upper()) >= 80
        hits += ok
        detail.append(f"{k}={'OK' if ok else 'X'}({g[:22]!r})")
    return hits, detail


def main() -> None:
    models = sys.argv[1:] or ["qwen3-vl:4b"]
    for model in models:
        print(f"\n=== {model} on CROPPED header ===")
        tot_h = tot_n = 0
        tot_t = 0.0
        for name, want in TRUTH.items():
            p = PAGES / name
            if not p.exists():
                continue
            png = crop_header(p)
            try:
                got, dt = ask(model, png)
            except Exception as exc:                           # noqa: BLE001
                print(f"  {name[-12:]}: ERROR {str(exc)[:60]}")
                continue
            h, detail = score(got, want)
            tot_h += h
            tot_n += 4
            tot_t += dt
            print(f"  {name[-12:]}  {h}/4  {dt:>5.1f}s  {' '.join(detail)}")
        if tot_n:
            print(f"  -> {tot_h}/{tot_n} = {tot_h/tot_n:.0%}  "
                  f"mean {tot_t/max(tot_n/4,1):.1f}s/page")


if __name__ == "__main__":
    main()

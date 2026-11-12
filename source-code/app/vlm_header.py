"""VLM fallback for the header block.

WHY A VLM IS BACK, AFTER BEING RULED OUT
----------------------------------------
An earlier benchmark ran VLMs as whole-page transcribers and they lost badly:
Qwen3-VL scored 30% on handwriting at 563 s/page -- ~100x slower than OCR and
less accurate. That measurement was correct, but it measured the wrong job.

Whole-page transcription is a VLM's worst case: a large image to encode and
thousands of output tokens, where drift compounds. A cropped header is the
opposite -- a small image, four fields, ~40 tokens of output.

Measured on the same pages, same model, cropped instead of whole-page:

    whole page   30% accuracy   563 s/page
    header crop  67% accuracy    24 s/page

That is 2.2x the accuracy at 4% of the cost, on the exact region where the
rule-based extractor is weakest (43% of pages could not even be matched to a
ground-truth row because the name came out as 'APRIL-2026').

WHY THE PAIRING WITH THE ROSTER MATTERS
---------------------------------------
The VLM's remaining errors are near-misses, not nonsense:

    'JACODISH SINGH'  for  RAJEEV IYENGAR
    'NURAI SPANOOQ'   for  Pradeep Chauhan

Those are exactly what the 96%-accurate roster match resolves. VLM for reading,
roster for resolving: each covers the other's weakness.

WHEN IT RUNS
------------
Only when the cheap path has already failed -- a missing name, or a name that
does not look like a name. At ~24 s it is far too expensive to run on every
page, but on the ~40% that need it the cost is affordable inside the
3,000-pages-per-day budget when spread across the worker pool.
"""
from __future__ import annotations

import base64
import json
import re
import time
from pathlib import Path
from typing import Any

from . import config

MODEL = "qwen3-vl:4b"
TIMEOUT_S = 240.0
CROP_FRACTION = 0.22          # top 22% of the page holds the header block
UPSCALE = 1.5                 # small text benefits; the crop is tiny anyway
MAX_CROP_W = 2400             # D-056: the width the 67% figure was measured at

PROMPT = """This is the header of a handwritten timesheet form.

Read these four handwritten values and return ONLY JSON:
{"month":"...","name":"...","designation":"...","code":"..."}

- "month" is the MONTH & YEAR value
- "name" is the EMPLOYEE NAME value
- "designation" is the DESIGNATION value (a job title)
- "code" is the EMPLOYEE CODE value (digits)

Copy exactly what is handwritten. Use "" if you cannot read a field."""


def available() -> bool:
    """True if a local Ollama with the model is reachable."""
    try:
        import httpx
        r = httpx.get("http://127.0.0.1:11434/api/tags", timeout=3.0)
        names = [m["name"] for m in r.json().get("models", [])]
        return MODEL in names
    except Exception:                                          # noqa: BLE001
        return False


def crop_header(image_path: str | Path) -> bytes | None:
    import cv2
    import numpy as np
    img = cv2.imdecode(np.fromfile(str(image_path), dtype=np.uint8),
                       cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    crop = img[0:int(h * CROP_FRACTION), 0:w]
    # D-056: the 67%-accuracy figure was measured on 1600 px pages upscaled
    # 1.5x (crop ~2400 px wide). A page that went through the hi-res rescue
    # is 2600 px tall; cropping THAT and upscaling again sent ~2.5x the
    # vision tokens and the call took 1m40s-2m07s instead of 43 s (full pass,
    # PIL03 block). Cap the crop at the measured width.
    tw = min(int(w * UPSCALE), MAX_CROP_W)
    th = int(h * CROP_FRACTION * tw / w)
    crop = cv2.resize(crop, (tw, th), interpolation=cv2.INTER_CUBIC)
    ok, buf = cv2.imencode(".png", crop)
    return buf.tobytes() if ok else None


def read_header(image_path: str | Path) -> dict[str, Any]:
    """Ask the VLM for the four header fields. Returns {} on any failure.

    Failing soft is deliberate: this is a fallback, and a page must never be
    lost because an optional model was slow, missing, or returned nonsense.
    """
    import httpx

    png = crop_header(image_path)
    if png is None:
        return {}
    b64 = base64.b64encode(png).decode()
    t0 = time.time()
    try:
        with httpx.Client(timeout=TIMEOUT_S) as c:
            r = c.post("http://127.0.0.1:11434/api/generate", json={
                "model": MODEL, "prompt": PROMPT, "images": [b64],
                "stream": False,
                # Qwen3-VL is a reasoning model: left alone it spends the whole
                # budget in its thinking channel and returns an empty answer.
                "think": False,
                "format": "json",
                "options": {"temperature": 0.0, "num_predict": 512},
            })
            r.raise_for_status()
            j = r.json()
    except Exception:                                          # noqa: BLE001
        return {}

    txt = j.get("response") or j.get("thinking") or ""
    data = None
    try:
        data = json.loads(txt)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", txt, re.S)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                data = None
    if not isinstance(data, dict):
        return {}

    out = {k: (str(v).strip() or None) for k, v in data.items()
           if k in ("month", "name", "designation", "code")}
    out["_vlm_seconds"] = round(time.time() - t0, 1)
    return out


_NAME_LIKE = re.compile(r"^[A-Za-z][A-Za-z .'\-]{3,}$")


def header_needs_help(record: dict) -> bool:
    """Should we spend ~24 s of VLM time on this page?

    Only when the cheap path has produced something that clearly is not an
    employee name: nothing at all, a month, or a string containing digits.
    """
    name = (record.get("employee_name") or "").strip()
    if not name:
        return True
    if not _NAME_LIKE.match(name):
        return True
    # A "name" that parses as a month is the classic header-shift failure.
    from .field_typing import score_month
    return score_month(name) > 0.7


# D-046: the VLM (qwen3-vl:4b) FABRICATES a header when the crop holds no
# name -- "S. RAVI / JUL 2023 / SE / 123456" on an On-Duty form, "Jin Hui /
# May 2023" on a rotated period grid, "Bhagat" on a Tecnimont hours grid
# (3 of 10 refused pages in the 50-page sample; "S. RAVI" recurs across the
# corpus eval). A VLM answer is accepted only when the page's own OCR text
# corroborates it: a fabricated name has no support anywhere on the page,
# a misread one ("JACODISH SINGH") still does.
VLM_CORROBORATE = True


def corroborated(field: str, value: str | None, page_texts: list[str]) -> bool:
    """True when `value` (a VLM answer) is supported by OCR text on the page."""
    if not VLM_CORROBORATE:
        return True
    if not value:
        return False
    from rapidfuzz import fuzz
    hay = " ".join(t for t in page_texts if t).upper()
    v = re.sub(r"[^A-Z0-9 ]", " ", str(value).upper())
    v = re.sub(r"\s+", " ", v).strip()
    if not v:
        return False
    if field == "code":
        digits = re.sub(r"\D", "", v)
        return bool(digits) and digits in re.sub(r"\D", "", hay)
    if field == "month":
        toks = [t for t in v.split() if len(t) >= 3]
        return any(fuzz.partial_ratio(t, hay) >= 90 for t in toks)
    # name / designation: the longest word must appear (near-verbatim)
    # somewhere on the page, and the whole string must be found loosely.
    toks = sorted((t for t in v.split() if len(t) >= 3), key=len, reverse=True)
    if not toks:
        return False
    return (fuzz.partial_ratio(toks[0], hay) >= 88
            and fuzz.partial_ratio(v, hay) >= 75)

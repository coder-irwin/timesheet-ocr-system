"""Experiment: VLM on the cropped DAY GRID.

The header-crop experiment showed a VLM is strong on a small region with a
short structured answer (67% vs 30% whole-page, 24 s vs 563 s). Day status is
now 94% of all field comparisons and sits at 56%, so the same trick is worth
testing there.

The risk is different, though. A header asks for 4 values; a day grid asks for
~30. Longer output means more room for drift, and a VLM that loses its place in
a table will renumber everything after it -- which is worse than missing rows,
because wrong-but-plausible statuses pass validation.

So this measures two things:
    1. accuracy of the returned statuses
    2. whether the model keeps the day numbering aligned at all
"""
from __future__ import annotations

import base64
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import cv2                                                     # noqa: E402
import httpx                                                   # noqa: E402
import numpy as np                                             # noqa: E402

BASE = Path(".")
PAGES = BASE / "data" / "pages"

# Ground truth for the day-status series, taken from the client's own Excel
# (IOCLMS APR 2026). P=present, WO=weekly off, A=absent, H=holiday.
TRUTH = {
    # Vikram Prasad Sethi -- p001 is Lokesh Khurana; use the Excel rows we
    # actually verified in eval_100 instead of guessing here.
}

PROMPT = """This is the attendance grid of a handwritten timesheet.

For EVERY row, decide the day's status from the columns:
- If TIME IN / TIME OUT / HOURS contain values -> "P"
- If the row says SUNDAY or WEEK OFF -> "W"
- If the row says ABSENT -> "A"
- If the row says HOLIDAY -> "H"
- If the row is empty -> ""

Return ONLY JSON mapping day number to status, for all days present:
{"1":"P","2":"P","3":"W",...}

Use the DATE column for the day number. Do not skip rows."""


def crop_grid(path: Path, top: float = 0.20, bot: float = 0.80) -> bytes | None:
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    h, w = img.shape[:2]
    crop = img[int(h * top):int(h * bot), 0:w]
    ok, buf = cv2.imencode(".png", crop)
    return buf.tobytes() if ok else None


def ask(model: str, png: bytes) -> tuple[dict, float]:
    b64 = base64.b64encode(png).decode()
    t0 = time.time()
    with httpx.Client(timeout=600.0) as c:
        r = c.post("http://127.0.0.1:11434/api/generate", json={
            "model": model, "prompt": PROMPT, "images": [b64],
            "stream": False, "think": False, "format": "json",
            "options": {"temperature": 0.0, "num_predict": 2048},
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


def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "qwen3-vl:4b"
    pages = sorted(PAGES.glob("1_IOCLMS*.png"))[:3]
    for p in pages:
        png = crop_grid(p)
        if png is None:
            continue
        try:
            got, dt = ask(model, png)
        except Exception as exc:                               # noqa: BLE001
            print(f"{p.name[-12:]}: ERROR {str(exc)[:70]}")
            continue
        days = {k: v for k, v in got.items() if str(k).isdigit()}
        print(f"{p.name[-12:]}  {dt:>6.1f}s  days_returned={len(days)}")
        if days:
            keys = sorted(int(k) for k in days)
            print(f"   range {keys[0]}..{keys[-1]}  "
                  f"sample: {[(k, days[str(k)]) for k in keys[:10]]}")


if __name__ == "__main__":
    main()

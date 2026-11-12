"""Comparative OCR benchmark.

Compares every engine we can run on the target class of hardware, on the SAME
pages, with the SAME scoring, so the numbers are directly comparable.

WHAT IS MEASURED
----------------
speed_s      wall-clock seconds for one page, CPU only
peak_mb      peak resident memory added during the call (matters on a 16 GB box)
boxes        how many text regions the engine found (recall proxy)
mean/p25     confidence statistics, where the engine reports them
field_recall fraction of the invoice-critical ground-truth values that appear
             ANYWHERE in the engine's output

WHY "field_recall" AND NOT CER
------------------------------
Character Error Rate is the standard OCR metric, but it answers the wrong
question here. A page can score 99% CER and still be a failure if the one
number it fluffed was "Total OT Hours"; conversely, mangling the employee's
designation costs nothing. The client's money is concentrated in about a dozen
numbers per page, so we score those.

field_recall is deliberately GENEROUS: it only asks whether the correct string
appears somewhere in the output, ignoring position and layout. It therefore
measures "could the value be read at all", which is an upper bound on what a
full extraction pipeline could achieve with that engine. An engine that scores
badly here cannot be rescued by better prompting downstream.

TERMS
-----
recall      of the things that were there, what fraction did we find?
p25         the 25th-percentile confidence -- describes the weakest quarter of
            readings, which is where errors concentrate. Means hide this.
RSS         Resident Set Size: real RAM a process is using.
"""
from __future__ import annotations

import gc
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Callable

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from ground_truth import GROUND_TRUTH, critical_fields  # noqa: E402

SAMPLES = Path("samples")
OUT = Path("data/benchmark_ocr.json")


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _norm(s: str) -> str:
    """Normalise for comparison: case, spacing and common OCR lookalikes.

    We are testing whether the engine *read the value*, not whether it matched
    our punctuation. Being strict about 'O' vs '0' would penalise engines for a
    difference no downstream consumer would care about, because the validation
    engine coerces these anyway.
    """
    s = str(s).upper()
    s = s.replace("O", "0").replace("I", "1").replace("L", "1")
    s = re.sub(r"[^A-Z0-9.]", "", s)
    return s


# Label words we expect to sit near each short numeric value on the page. Used
# to make the match positional instead of "appears anywhere".
FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "present_days": ("PRESENT", "TOTALPRESENT", "P"),
    "total_man_hours": ("MANH0URS", "T0TALMANH0URS", "MANH0UR"),
    "total_ot_hours": ("0TH0URS", "T0TAL0T", "0VERT1ME"),
    "weekly_off": ("WEEKLY0FF", "W0", "WEEKLY"),
    "public_holiday": ("H0L1DAY", "PUBL1CH0L1DAY", "PH"),
    "leaves": ("LEAVE", "T0TALLEAVES"),
    "comp_off": ("C0MPENSAT0RY", "C0", "C0MP"),
    "total_normal_hours": ("N0RMAL", "T0TAL"),
    "total_extra_hours": ("EXTRA",),
    "total_hours": ("T0TAL",),
    "calendar_days": ("CALENDAR",),
    "total_working": ("W0RK1NG",),
}

# Values at or below this length are too short to be evidence on their own:
# a 2-digit number will occur by chance on a page containing 200 numbers.
SHORT_VALUE_LEN = 3
PROXIMITY_CHARS = 60


def _found_near_label(hay: str, needle: str, labels: tuple[str, ...]) -> bool:
    """True if `needle` occurs within PROXIMITY_CHARS of any of `labels`.

    This is what makes the metric honest for short numbers. Without it, "25"
    scores a hit because some unrelated cell happens to contain 25.
    """
    if not labels:
        return needle in hay
    for lab in labels:
        start = 0
        while True:
            i = hay.find(lab, start)
            if i == -1:
                break
            window = hay[max(0, i - PROXIMITY_CHARS): i + len(lab) + PROXIMITY_CHARS]
            if needle in window:
                return True
            start = i + 1
    return False


def field_recall(text: str, truth: dict[str, str]) -> tuple[float, list[str]]:
    hay = _norm(text)
    missed = []
    hit = 0
    for k, v in truth.items():
        needle = _norm(v)
        if not needle:
            continue
        if len(needle) > 12:
            # Long values (names, client strings) count as found if most of
            # their tokens survive -- OCR routinely splits or drops a word.
            toks = [_norm(t) for t in str(v).split() if len(t) > 2]
            found = sum(1 for t in toks if t and t in hay)
            ok = bool(toks) and found / len(toks) >= 0.6
        elif len(needle) <= SHORT_VALUE_LEN:
            # Short numerics must be found NEAR their label, not anywhere.
            ok = _found_near_label(hay, needle, FIELD_LABELS.get(k, ()))
        else:
            ok = needle in hay
        if ok:
            hit += 1
        else:
            missed.append(k)
    total = len([v for v in truth.values() if _norm(v)])
    return (hit / total if total else 0.0), missed


def peak_rss_mb() -> float:
    try:
        import resource
        v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reports bytes; Linux reports kilobytes.
        return v / (1024 * 1024) if sys.platform == "darwin" else v / 1024
    except Exception:                                          # noqa: BLE001
        return 0.0


# ---------------------------------------------------------------------------
# Engines. Each returns (full_text, scores, n_boxes) or raises.
# ---------------------------------------------------------------------------

def engine_rapidocr():
    from rapidocr import RapidOCR
    eng = RapidOCR()

    def run(path: Path):
        r = eng(str(path))
        if r is None or getattr(r, "txts", None) is None:
            return "", [], 0
        txts = list(r.txts)
        scores = [float(s) for s in (r.scores if r.scores is not None else [])]
        return "\n".join(txts), scores, len(txts)
    return run


def engine_tesseract():
    import pytesseract
    from PIL import Image

    def run(path: Path):
        img = Image.open(path)
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        words, scores = [], []
        for t, c in zip(data["text"], data["conf"]):
            if t and t.strip():
                words.append(t)
                try:
                    ci = float(c)
                    if ci >= 0:
                        scores.append(ci / 100.0)
                except (TypeError, ValueError):
                    pass
        return " ".join(words), scores, len(words)
    return run


def engine_easyocr():
    import easyocr
    reader = easyocr.Reader(["en"], gpu=False, verbose=False)

    def run(path: Path):
        res = reader.readtext(str(path))
        txts = [r[1] for r in res]
        scores = [float(r[2]) for r in res]
        return "\n".join(txts), scores, len(txts)
    return run


def engine_ollama(model: str):
    import base64
    import httpx

    PROMPT = ("Transcribe ALL text visible in this timesheet image, including "
              "every header field, every table cell and every total. Preserve "
              "the reading order. Output plain text only.")

    def run(path: Path):
        b64 = base64.b64encode(Path(path).read_bytes()).decode("ascii")
        with httpx.Client(timeout=1800.0) as c:
            r = c.post("http://127.0.0.1:11434/api/generate", json={
                "model": model, "prompt": PROMPT, "images": [b64],
                "stream": False,
                # Qwen3-VL is a REASONING model. Left to itself it spends the
                # entire token budget in its `thinking` channel and returns an
                # EMPTY `response` with done_reason="length". Measured: 5,027
                # chars of thinking, 0 chars of answer -- which scored it 0%
                # across every page and would have been published as "the model
                # cannot read timesheets". It reads them fine; we were throwing
                # the answer away.
                #
                # Two defences, because `think` is not honoured by every model
                # or every Ollama build:
                #   1. ask the server to skip the thinking phase entirely
                #   2. give a much larger budget so an answer still lands if it
                #      thinks anyway
                "think": False,
                "options": {"temperature": 0.0, "num_predict": 16384},
            })
            r.raise_for_status()
            j = r.json()
            txt = j.get("response", "")
            # Last-resort salvage: if the answer is still empty but the model
            # reasoned, score the reasoning rather than record a false zero.
            if not txt.strip():
                txt = j.get("thinking", "") or ""
        return txt, [], len([l for l in txt.split("\n") if l.strip()])
    return run


def available() -> dict[str, Callable]:
    engines: dict[str, Callable] = {}
    for name, factory in (
        ("RapidOCR (PP-OCRv6/ONNX)", engine_rapidocr),
        ("Tesseract 5", engine_tesseract),
        ("EasyOCR", engine_easyocr),
    ):
        try:
            engines[name] = factory()
        except Exception as exc:                               # noqa: BLE001
            print(f"  [skip] {name}: {type(exc).__name__}: {str(exc)[:90]}")

    # Ollama VLMs, if the daemon is up
    try:
        import httpx
        tags = httpx.get("http://127.0.0.1:11434/api/tags", timeout=4.0).json()
        names = [m["name"] for m in tags.get("models", [])]
        for want in ("glm-ocr:latest", "qwen3-vl:4b", "qwen3-vl:8b"):
            if want in names:
                engines[f"VLM {want}"] = engine_ollama(want)
            else:
                print(f"  [skip] VLM {want}: not pulled")
    except Exception as exc:                                   # noqa: BLE001
        print(f"  [skip] ollama: {str(exc)[:90]}")
    return engines


# ---------------------------------------------------------------------------

def main() -> None:
    only = sys.argv[1:] or None
    print("Discovering engines...")
    engines = available()
    if only:
        engines = {k: v for k, v in engines.items()
                   if any(o.lower() in k.lower() for o in only)}
    print(f"Running: {', '.join(engines) or '(none)'}\n")

    pages = [p for p in sorted(SAMPLES.glob("*.png")) if p.name in GROUND_TRUTH]
    results: dict[str, list[dict]] = {}

    for ename, run in engines.items():
        print(f"=== {ename} ===")
        rows = []
        for page in pages:
            truth = critical_fields(page.name)
            kind = GROUND_TRUTH[page.name].get("_kind", "?")
            gc.collect()
            rss0 = peak_rss_mb()
            t0 = time.time()
            try:
                text, scores, boxes = run(page)
                err = None
            except Exception as exc:                           # noqa: BLE001
                text, scores, boxes, err = "", [], 0, f"{type(exc).__name__}: {exc}"
            dt = time.time() - t0
            rss = max(0.0, peak_rss_mb() - rss0)

            rec, missed = field_recall(text, truth) if text else (0.0, list(truth))
            row = {
                "page": page.name, "kind": kind, "sec": round(dt, 2),
                "boxes": boxes, "field_recall": round(rec, 3),
                "missed": missed, "rss_mb": round(rss, 1),
                "mean_conf": round(statistics.mean(scores), 3) if scores else None,
                "p25_conf": round(float(np.percentile(scores, 25)), 3) if scores else None,
                "chars": len(text), "error": err,
            }
            rows.append(row)
            flag = "ERR" if err else ""
            print(f"  {page.name[:34]:<36} {kind:<16} {dt:>6.1f}s "
                  f"recall={rec:>5.0%} boxes={boxes:<5} {flag}")
            if missed and not err:
                print(f"      missed: {', '.join(missed[:6])}")
        results[ename] = rows
        ok = [r for r in rows if not r["error"]]
        if ok:
            print(f"  -> mean {statistics.mean(r['sec'] for r in ok):.1f}s/page, "
                  f"mean field_recall {statistics.mean(r['field_recall'] for r in ok):.0%}\n")

    # ---- summary table -------------------------------------------------
    print("\n" + "=" * 104)
    print("SUMMARY  (field_recall = % of invoice-critical values found)")
    print("=" * 104)
    print(f"{'engine':<28} {'handwritten':>22} {'printed':>22} {'mean s/page':>14}")
    print("-" * 104)
    for ename, rows in results.items():
        ok = [r for r in rows if not r["error"]]
        hw = [r for r in ok if r["kind"] == "handwritten"]
        pr = [r for r in ok if r["kind"].startswith("printed")]
        f = lambda g: f"{statistics.mean(r['field_recall'] for r in g):.0%}" if g else "-"
        s = f"{statistics.mean(r['sec'] for r in ok):.1f}" if ok else "-"
        print(f"{ename:<28} {f(hw):>22} {f(pr):>22} {s:>14}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()

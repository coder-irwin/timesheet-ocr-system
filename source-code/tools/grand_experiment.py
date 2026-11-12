"""Large-scale, parallel, resumable engine comparison over the real corpus.

PURPOSE
-------
Produce a defensible side-by-side comparison of every OCR engine on the CLIENT'S
OWN 2,527 pages, measuring speed, coverage and self-consistency -- so the
findings can be shown to the client as evidence rather than opinion.

SCALING REALITY (measured, not assumed)
---------------------------------------
Running every engine over every page is not possible in one night:

    engine          s/page   x2527 pages
    Tesseract 5        1.6      1.1 h
    RapidOCR           5.7      4.0 h
    EasyOCR           11.0      7.7 h
    glm-ocr 1.1B      66.3     46.5 h     <- infeasible
    Qwen3-VL 4B      563.0    395.3 h     <- wildly infeasible

So the design is tiered, and the tiering is stated in the output so nobody
mistakes a sampled number for a full-corpus one:

    Tier A (full/large sample) : Tesseract, RapidOCR, EasyOCR   -- run in parallel
    Tier B (small sample)      : glm-ocr, Qwen3-VL              -- run serially

PARALLELISM
-----------
The classical engines are CPU-bound and release the GIL inside their native
libraries, but they are not thread-safe in general, so we use PROCESSES.
Workers = cpu_count - 2, leaving headroom so the machine stays usable.

The VLMs are NOT parallelised: Ollama serialises requests to one model anyway,
and running two models concurrently on a 16 GB box will swap.

RESUMABILITY
------------
Every result is appended to a JSONL file as it completes. Re-running skips work
already done. An overnight run that dies at 3 a.m. loses nothing.

WHAT IS MEASURED PER PAGE
-------------------------
  seconds        wall-clock for that engine on that page
  n_boxes        text regions found (recall proxy)
  mean/p25 conf  confidence statistics where the engine provides them
  chars          total characters returned
  anchors_found  how many of the known form labels were locatable
  fields_found   how many invoice-critical fields the pipeline extracted
  checksum_ok    whether the page's own arithmetic balanced

The last three are the ones that matter: raw OCR output is not the product.
"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path("Timesheet - Delhi 2026-2027")
BASE = Path(".")
WORK = BASE / "data" / "experiment"
WORK.mkdir(parents=True, exist_ok=True)
RESULTS = WORK / "results.jsonl"
PAGES_DIR = WORK / "pages"
PAGES_DIR.mkdir(parents=True, exist_ok=True)

TIER_A = ["rapidocr", "tesseract", "easyocr"]
TIER_B = ["glm-ocr:latest", "qwen3-vl:4b"]


# ---------------------------------------------------------------------------
# Page preparation (done once, shared by every engine so the comparison is fair)
# ---------------------------------------------------------------------------

def prepare_pages(limit: int | None, per_pdf_pages: int = 1) -> list[dict]:
    """Rasterise + normalise pages once. Every engine then sees identical input."""
    import pypdfium2 as pdfium
    sys.path.insert(0, str(BASE))
    from app import preprocess

    manifest_path = WORK / "manifest.json"
    if manifest_path.exists():
        man = json.loads(manifest_path.read_text())
        if limit is None or len(man) >= limit:
            return man[:limit] if limit else man

    pdfs = [p for p in sorted(ROOT.rglob("*.pdf")) if not p.name.startswith(".")]
    # Round-robin across clients so a sample is representative, not one client.
    by_client: dict[str, list[Path]] = {}
    for p in pdfs:
        by_client.setdefault(p.relative_to(ROOT).parts[0], []).append(p)
    ordered: list[Path] = []
    i = 0
    while True:
        added = False
        for lst in by_client.values():
            if i < len(lst):
                ordered.append(lst[i]); added = True
        if not added:
            break
        i += 1

    man: list[dict] = []
    for pdf in ordered:
        if limit and len(man) >= limit:
            break
        try:
            doc = pdfium.PdfDocument(str(pdf))
            n = min(len(doc), per_pdf_pages)
            for pi in range(n):
                if limit and len(man) >= limit:
                    break
                pid = f"{len(man):05d}"
                dest = PAGES_DIR / f"{pid}.png"
                if not dest.exists():
                    doc[pi].render(scale=2).to_pil().save(dest)
                    preprocess.normalise_page(dest, dest)
                man.append({
                    "page_id": pid,
                    "png": str(dest),
                    "pdf": str(pdf.relative_to(ROOT)),
                    "client": pdf.relative_to(ROOT).parts[0],
                    "pdf_page": pi + 1,
                })
            doc.close()
        except Exception as exc:                               # noqa: BLE001
            print(f"  prep failed {pdf.name}: {str(exc)[:70]}")
    manifest_path.write_text(json.dumps(man, indent=1))
    return man


# ---------------------------------------------------------------------------
# Engines (constructed inside each worker process)
# ---------------------------------------------------------------------------

_CACHE: dict = {}


def get_engine(name: str):
    if name in _CACHE:
        return _CACHE[name]
    if name == "rapidocr":
        from rapidocr import RapidOCR
        eng = RapidOCR()

        def run(path):
            r = eng(str(path))
            if r is None or r.txts is None:
                return "", [], 0
            return ("\n".join(r.txts),
                    [float(s) for s in (r.scores if r.scores is not None else [])],
                    len(r.txts))
    elif name == "tesseract":
        import pytesseract
        from PIL import Image

        def run(path):
            d = pytesseract.image_to_data(Image.open(path),
                                          output_type=pytesseract.Output.DICT)
            w, sc = [], []
            for t, c in zip(d["text"], d["conf"]):
                if t and t.strip():
                    w.append(t)
                    try:
                        ci = float(c)
                        if ci >= 0:
                            sc.append(ci / 100.0)
                    except (TypeError, ValueError):
                        pass
            return " ".join(w), sc, len(w)
    elif name == "easyocr":
        import easyocr
        rd = easyocr.Reader(["en"], gpu=False, verbose=False)

        def run(path):
            res = rd.readtext(str(path))
            return ("\n".join(r[1] for r in res),
                    [float(r[2]) for r in res], len(res))
    else:                                    # an Ollama VLM
        import base64
        import httpx
        PROMPT = ("Transcribe ALL text visible in this timesheet image, "
                  "including every header field, table cell and total. "
                  "Output plain text only.")

        def run(path):
            b64 = base64.b64encode(Path(path).read_bytes()).decode()
            with httpx.Client(timeout=1800.0) as c:
                r = c.post("http://127.0.0.1:11434/api/generate", json={
                    "model": name, "prompt": PROMPT, "images": [b64],
                    "stream": False, "think": False,
                    "options": {"temperature": 0.0, "num_predict": 16384}})
                r.raise_for_status()
                j = r.json()
            txt = j.get("response", "") or j.get("thinking", "") or ""
            return txt, [], len([l for l in txt.split("\n") if l.strip()])
    _CACHE[name] = run
    return run


def score_page(engine: str, item: dict) -> dict:
    """Run one engine on one page and compute every metric."""
    import numpy as np
    sys.path.insert(0, str(BASE))

    png = item["png"]
    t0 = time.time()
    try:
        text, scores, boxes = get_engine(engine)(png)
        err = None
    except Exception as exc:                                   # noqa: BLE001
        text, scores, boxes, err = "", [], 0, f"{type(exc).__name__}: {exc}"
    dt = time.time() - t0

    rec_fields = 0
    anchors = 0
    checksum_ok = None
    days = 0
    # The pipeline's structured extraction only works from positioned boxes, so
    # it is measured for RapidOCR (which we build the product on). For the other
    # engines we compare raw-text coverage, which is all they can offer here.
    if engine == "rapidocr" and not err:
        try:
            import cv2
            from app import aarvi_form, ocr_engine
            from app.validate import validate
            from app.templates_spec import get as get_template
            from app import pipeline as pl

            img = cv2.imread(png, cv2.IMREAD_GRAYSCALE)
            h, w = (img.shape if img is not None else (0, 0))
            boxes_o = ocr_engine.run_ocr(png)
            rec = aarvi_form.extract(boxes_o, w, h)
            anchors = len(rec.get("_anchors_found") or [])
            summ = rec.get("summary") or {}
            days = len(rec.get("days") or [])
            rec_fields = sum(1 for k in ("employee_name", "employee_code",
                                         "designation", "client", "project",
                                         "period_label") if rec.get(k))
            rec_fields += sum(1 for v in summ.values() if v)
            norm = pl._to_validator_shape(rec)
            iss = validate(norm, get_template(None), roster=None)
            codes = {i["code"] for i in iss}
            checksum_ok = ("summary_normal_missing" not in codes
                           and "normal_hours_sum_mismatch" not in codes)
        except Exception:                                      # noqa: BLE001
            pass

    return {
        "engine": engine,
        "page_id": item["page_id"],
        "client": item["client"],
        "pdf": item["pdf"],
        "seconds": round(dt, 2),
        "boxes": boxes,
        "chars": len(text),
        "mean_conf": round(float(np.mean(scores)), 4) if scores else None,
        "p25_conf": round(float(np.percentile(scores, 25)), 4) if scores else None,
        "frac_low": round(float(sum(1 for s in scores if s < 0.8) / len(scores)), 4)
                    if scores else None,
        "anchors_found": anchors,
        "fields_found": rec_fields,
        "day_rows": days,
        "checksum_ok": checksum_ok,
        "error": err,
    }


def _worker(args):
    engine, item = args
    try:
        return score_page(engine, item)
    except Exception:                                          # noqa: BLE001
        return {"engine": engine, "page_id": item["page_id"],
                "error": traceback.format_exc(limit=2)[:300], "seconds": 0}


def load_done() -> set[tuple[str, str]]:
    done = set()
    if RESULTS.exists():
        with RESULTS.open() as fh:
            for line in fh:
                try:
                    r = json.loads(line)
                    done.add((r["engine"], r["page_id"]))
                except (json.JSONDecodeError, KeyError):
                    continue
    return done


def main() -> None:
    n_pages = int(os.getenv("EXP_PAGES", "300"))
    n_vlm = int(os.getenv("EXP_VLM_PAGES", "25"))
    workers = max(1, (os.cpu_count() or 4) - 2)

    print(f"Preparing up to {n_pages} pages (one per PDF, round-robin by client)...")
    man = prepare_pages(n_pages)
    print(f"  {len(man)} pages ready, {len({m['client'] for m in man})} clients\n")

    done = load_done()
    print(f"Already done: {len(done)} (engine,page) pairs — will skip\n")

    jobs = [(e, m) for e in TIER_A for m in man if (e, m["page_id"]) not in done]
    print(f"TIER A  {TIER_A}  ->  {len(jobs)} jobs on {workers} processes")

    t0 = time.time()
    with RESULTS.open("a") as out:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_worker, j): j for j in jobs}
            for i, f in enumerate(as_completed(futs), 1):
                r = f.result()
                out.write(json.dumps(r) + "\n")
                out.flush()
                if i % 25 == 0:
                    el = time.time() - t0
                    print(f"  {i}/{len(jobs)}  {el:.0f}s  "
                          f"eta {el/i*(len(jobs)-i)/60:.0f}m")

    print(f"\nTIER A done in {(time.time()-t0)/60:.1f} min")

    # ---- Tier B: VLMs, small sample, serial -----------------------------
    vlm_pages = man[:n_vlm]
    vjobs = [(e, m) for e in TIER_B for m in vlm_pages
             if (e, m["page_id"]) not in done]
    print(f"\nTIER B  {TIER_B}  ->  {len(vjobs)} jobs (serial, sampled)")
    t1 = time.time()
    with RESULTS.open("a") as out:
        for i, (e, m) in enumerate(vjobs, 1):
            r = _worker((e, m))
            out.write(json.dumps(r) + "\n")
            out.flush()
            el = time.time() - t1
            print(f"  {i}/{len(vjobs)} {e} {r.get('seconds')}s  "
                  f"eta {el/i*(len(vjobs)-i)/60:.0f}m")

    print(f"\nALL DONE. total {(time.time()-t0)/60:.1f} min -> {RESULTS}")


if __name__ == "__main__":
    main()

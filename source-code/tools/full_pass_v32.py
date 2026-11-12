"""Run EVERY page of all three datasets through the product pipeline
(pipeline.process_page: rescue ladder, generic grid, reconcile, validate,
row confidence) and record per page: status, row flags, days, name.

Checkpointed (data/full_pass_v32.jsonl); a restart skips completed pages.
Not an accuracy measure -- there is no truth for ~8,900 of these pages.
It answers: did every page run, and how many rows were ok / review /
must_fix. Workers = 3 (memory)."""
import json, os, sys, time, hashlib
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
ROOT = Path(".")
OUT = Path("data/full_pass_v32.jsonl"); TMP = Path("data/_full_pass_tmp"); TMP.mkdir(exist_ok=True)

def enumerate_pages():
    import pypdfium2 as pdfium
    jobs = []
    for ds in ("Delhi", "HO", "Kolkata"):
        base = next((p for p in ROOT.iterdir() if p.is_dir() and p.name.lower().startswith(f"timesheet - {ds.lower()}")), None)
        if not base: continue
        for pdf in sorted(base.rglob("*.pdf")):
            try: n = len(pdfium.PdfDocument(str(pdf)))
            except Exception: continue
            for i in range(n): jobs.append((ds, str(pdf), i))
    return jobs

def one(job):
    ds, pdf, i = job
    from app import pipeline
    import pypdfium2 as pdfium
    from collections import Counter
    try:
        pg = pdfium.PdfDocument(pdf)[i]; w, h = pg.get_size()
        img = TMP / f"w{os.getpid()}_{hashlib.md5(f'{pdf}{i}'.encode()).hexdigest()[:10]}.png"
        pg.render(scale=1600 / max(w, h)).to_pil().save(img)
        res = pipeline.process_page(img, hashlib.sha1(img.read_bytes()).hexdigest(), force=True, source_hint=pdf)
        rec = res["record"]; days = rec.get("days") or []
        fl = Counter(d.get("_review") for d in days)
        out = {"dataset": ds, "pdf": pdf, "page": i + 1, "status": res["status"],
               "name": rec.get("employee_name"), "n_days": len(days),
               "ok": fl.get("ok", 0), "review": fl.get("review", 0), "must_fix": fl.get("must_fix", 0),
               "n_issues": len(res.get("issues") or []), "grid": rec.get("_generic_grid"), "rotated": rec.get("_rotated")}
        try: img.unlink()
        except Exception: pass
        return out
    except Exception as e:
        return {"dataset": ds, "pdf": pdf, "page": i + 1, "status": "worker_error", "error": str(e)[:120]}

if __name__ == "__main__":
    done = set()
    if OUT.exists():
        for l in OUT.read_text().splitlines():
            try: d = json.loads(l); done.add((d["dataset"], d["pdf"], d["page"]))
            except Exception: pass
    jobs = [j for j in enumerate_pages() if (j[0], j[1], j[2] + 1) not in done]
    print(f"{len(done)} done, {len(jobs)} to do", flush=True)
    t0 = time.time(); n = 0
    with OUT.open("a") as f, ProcessPoolExecutor(max_workers=int(os.getenv("TS_WORKERS", "3"))) as ex:
        for r in as_completed({ex.submit(one, j): j for j in jobs}):
            f.write(json.dumps(r.result(), default=str) + "\n"); f.flush(); n += 1
            if n % 50 == 0: print(f"  {n}/{len(jobs)}  {(time.time()-t0)/n:.1f}s/page", flush=True)
    print(f"done {n} in {(time.time()-t0)/3600:.1f}h", flush=True)

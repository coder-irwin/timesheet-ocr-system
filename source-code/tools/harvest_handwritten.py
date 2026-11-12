"""Find every handwritten page in all three datasets, extract it, keep the OCR.

WHAT THIS PRODUCES
------------------
    handwritten_corpus/
        pages/<dataset>__<n>__<stem>_pNNN.png   the normalised handwritten page
        records.jsonl                            one line per page examined
        summary.json                             counts, written at the end

Every page examined gets a line in records.jsonl, INCLUDING the typed ones --
a page that was looked at and rejected is evidence too, and without it there
is no way to audit whether the classifier missed handwriting.

HOW "HANDWRITTEN" IS DECIDED
----------------------------
Not by a new heuristic. The pipeline already routes pages on OCR confidence,
with thresholds documented in docs/03-page-routing.md as sitting in the
measured gap between typed pages (p25 >= 0.993) and handwritten ones
(p25 = 0.777):

    typed        p25 >= 0.90  AND  frac_low <= 0.15
    handwritten  anything else

A typed FORM filled in by hand counts as handwritten -- that is the IOCL case
and the whole point of the product, so the ink decides, not the blank form.

RESUMABLE
---------
Every page is appended to records.jsonl the moment it is done, and a restart
skips whatever is already there. Long runs on this machine get killed; losing
hours of OCR to that is not acceptable.

    python tools/harvest_handwritten.py --validate     # check the classifier
    python tools/harvest_handwritten.py --limit 40     # smoke test
    python tools/harvest_handwritten.py --workers 3    # the real run
"""
from __future__ import annotations

import json
import os
import sys
import time
import warnings
from collections import Counter
from pathlib import Path

# Set BEFORE numpy/onnxruntime are imported, or they are ignored.
for _v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
           "ORT_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

warnings.filterwarnings("ignore")
BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

ROOTS = {
    "Delhi": BASE / "Timesheet - Delhi 2026-2027",
    "HO": BASE / "Timesheet - HO 2026-2027",
    "Kolkata": BASE / "Timesheet - KOLKATA 2026-2027",
}
IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}

OUT = BASE / "handwritten_corpus"
PAGES = OUT / "pages"
RECORDS = OUT / "records.jsonl"
WORK = BASE / "data" / "_harvest"


def enumerate_pages() -> list[tuple[str, str, int]]:
    """(dataset, source_path, page_index). Images are page 0."""
    import pypdfium2 as pdfium

    out: list[tuple[str, str, int]] = []
    for ds, root in ROOTS.items():
        if not root.exists():
            continue
        for p in sorted(root.rglob("*")):
            if not p.is_file() or p.name.startswith(("~$", ".")):
                continue
            ext = p.suffix.lower()
            if ext in IMG_EXT:
                out.append((ds, str(p), 0))
            elif ext == ".pdf":
                try:
                    doc = pdfium.PdfDocument(str(p))
                    n = len(doc)
                    doc.close()
                except Exception:                              # noqa: BLE001
                    continue
                out.extend((ds, str(p), i) for i in range(n))
    return out


def _render(ds: str, src: Path, page_idx: int, dest: Path) -> bool:
    """Normalised page image at dest. False if it could not be produced."""
    from app import preprocess
    try:
        if src.suffix.lower() in IMG_EXT:
            import shutil
            shutil.copyfile(src, dest)
        else:
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(str(src))
            try:
                page = doc[page_idx]
                scale = 2.0
                try:
                    w_pt, h_pt = page.get_size()
                    from app import config
                    if w_pt > h_pt * config.LANDSCAPE_ASPECT_MIN:
                        scale = max(2.0, min(
                            config.LANDSCAPE_LONG_EDGE / max(w_pt, h_pt), 4.0))
                except Exception:                              # noqa: BLE001
                    pass
                page.render(scale=scale).to_pil().save(dest)
            finally:
                doc.close()
        preprocess.normalise_page(dest, dest)
        return True
    except Exception:                                          # noqa: BLE001
        return False


def _page_size_of(png: Path) -> tuple[int, int]:
    from PIL import Image
    try:
        with Image.open(png) as im:
            return im.size
    except Exception:                                          # noqa: BLE001
        return (0, 0)


def _ink_features(boxes: list, page_png: Path) -> dict:
    """Measure handwriting where it lives: the data region, not the header.

    A printed form's labels are crisp and sit in the top band and the left
    column. The handwriting is in the body. Averaging over the whole page lets
    the printed furniture hide the ink, which is exactly how a filled IOCL
    sheet came out looking typed.
    """
    from PIL import Image
    try:
        w, h = Image.open(page_png).size
    except Exception:                                          # noqa: BLE001
        w = h = 0
    if not boxes or not h:
        return {"handwritten": False, "n_body": 0, "body_low_frac": 0.0,
                "body_p25": 0.0, "n_low_body": 0}

    # Body = below the header band. The header is where the printed labels and
    # the client's name live on every layout seen so far.
    body = [b for b in boxes if b.cy > h * 0.30]
    if len(body) < 8:
        body = list(boxes)
    confs = sorted(b.conf for b in body)
    n = len(confs)
    p25 = confs[max(0, int(n * 0.25) - 1)] if n else 0.0
    n_low = sum(1 for c in confs if c < 0.80)
    low_frac = n_low / max(n, 1)

    # Threshold set from the measured separation, not guessed. On pages whose
    # answer is known:
    #
    #     Sharad  HANDWRITTEN   n_low_body 23   low_frac 0.125
    #     Vivek   HANDWRITTEN   n_low_body 42   low_frac 0.244
    #     SHELL   TYPED         n_low_body  0   low_frac 0.000
    #
    # A cleanly typed page produces essentially NO weak readings in its body;
    # ink produces dozens. The gap is between 0 and 23, so a cut at 6 sits far
    # from both sides and still tolerates a typed sheet carrying a signature
    # or a stamped note.
    #
    # Deliberately biased toward calling a page handwritten. A typed page
    # wrongly kept costs disk; a handwritten page wrongly dropped is exactly
    # the failure this job exists to avoid.
    # The rule above was an OR, and that was wrong. It was calibrated against
    # a SHELL typed page carrying ZERO weak body readings, so "6 low boxes"
    # looked like a safe cut. An AARVI sheet has an EMPLOYEE SIGNATURE column
    # with one signature per day -- twenty-odd guaranteed weak boxes on a
    # page that is otherwise entirely machine-printed. Measured on a typed
    # ADN905 sheet: n_low 24, low_frac 0.124, but p25 0.976.
    #
    # Under an OR, the signature count convicted the page and the strongest
    # evidence that it was TYPED -- a crisp p25 -- was never consulted. That
    # mislabelled 1,972 pages, 31% of the handwritten set.
    #
    # So p25 decides, and ink volume only breaks the tie in the middle band.
    if n < 8:
        handwritten = bool(n_low >= 6)          # too little evidence to judge
    elif p25 >= 0.95:
        handwritten = False                     # crisp body: typed, signatures or not
    elif p25 < 0.90:
        handwritten = True
    else:
        handwritten = (low_frac >= 0.10) or (n_low >= max(10, 0.10 * n))
    return {"handwritten": bool(handwritten), "n_body": n,
            "body_low_frac": round(low_frac, 4), "body_p25": round(p25, 4),
            "n_low_body": n_low}


def process_one(job: tuple[str, str, int, int]) -> dict:
    """Classify one page; extract and keep it if it is handwritten."""
    ds, src_s, page_idx, n = job
    src = Path(src_s)
    from app import ocr_engine, pipeline, preprocess
    from app.roster import Roster

    global _ROSTER
    try:
        _ROSTER
    except NameError:
        _ROSTER = Roster.from_csv(BASE / "data" / "roster.csv")

    rel = str(src.relative_to(BASE))
    rec: dict = {"dataset": ds, "source": rel, "page": page_idx + 1}

    WORK.mkdir(parents=True, exist_ok=True)
    tmp = WORK / f"w{os.getpid()}_{n}.png"
    if not _render(ds, src, page_idx, tmp):
        rec["verdict"] = "render_error"
        return rec

    try:
        boxes = ocr_engine.run_ocr(tmp)
        prof = ocr_engine.confidence_profile(boxes)
        route = ocr_engine.route_from_profile(prof)
    except Exception as exc:                                   # noqa: BLE001
        rec["verdict"] = "ocr_error"
        rec["error"] = str(exc)[:200]
        return rec

    rec["profile"] = {k: (round(v, 4) if isinstance(v, float) else v)
                      for k, v in prof.items()}
    rec["route"] = route
    if route == "unreadable":
        rec["verdict"] = "unreadable"
        return rec

    # --- classify, but NEVER discard --------------------------------------
    #
    # The page-level confidence route cannot separate these two reliably.
    # Measured on pages whose answer is known:
    #
    #     01_Sharad_Saxena  HANDWRITTEN   p25 0.9236  frac_low 0.1059
    #     SHELL APR 2026    TYPED         p25 0.9357  frac_low 0.1139
    #
    # Nearly identical -- because the IOCL sheet is a printed FORM filled in
    # by hand, so crisp printed labels dominate the aggregate and drown out
    # the ink. The documented typed/handwritten gap does not survive contact
    # with the wider corpus.
    #
    # So the ink is measured where it actually lives: the DATA region below
    # the header, ignoring the printed furniture above it. And every page is
    # kept regardless, with its features recorded -- a filter that silently
    # drops handwriting is worse than no filter, and the label can be revised
    # later without re-running twelve hours of OCR.
    ink = _ink_features(boxes, tmp)
    rec["ink"] = ink
    rec["verdict"] = ("handwritten" if ink["handwritten"] else "typed")
    sub = PAGES / rec["verdict"]
    sub.mkdir(parents=True, exist_ok=True)
    kept = sub / f"{ds}__{n:05d}__{src.stem[:48]}_p{page_idx+1:03d}.png"
    try:
        import shutil
        shutil.copyfile(tmp, kept)
        rec["page_file"] = str(kept.relative_to(OUT))
    except Exception:                                          # noqa: BLE001
        pass

    try:
        # Extract from the boxes we ALREADY have.
        #
        # This called pipeline.process_page, which re-runs OCR internally --
        # so every handwritten page was read twice. Handwritten is ~80% of
        # the corpus, i.e. 1.8 OCR passes per page instead of 1.0, and OCR is
        # essentially the whole cost of this job.
        #
        # aarvi_form.extract takes the boxes directly, so the second pass
        # disappears. The rescue ladder stays off: bounded at 45s per failing
        # page it is fine for one upload and ruinous across 9,000.
        pipeline.ORIENTATION_RETRY = False
        pipeline.HIRES_RESCUE = False
        from app import aarvi_form
        from app.validate import status_for, validate
        from app.templates_spec import get as get_template

        pw, ph = _page_size_of(kept if kept.exists() else tmp)
        # Printed row rules are pure morphology -- milliseconds, no OCR -- and
        # dropping them cost a day per page in testing (30 vs 31). Cheap to
        # keep, so keep them.
        try:
            rules = ocr_engine.detect_row_rules(kept if kept.exists() else tmp)
        except Exception:                                      # noqa: BLE001
            rules = []
        r = aarvi_form.extract(
            boxes, pw, ph,
            handwritten=True, row_rules=rules, source_hint=str(src))
        r = pipeline.apply_roster(r, _ROSTER)
        try:
            issues = validate(pipeline._to_validator_shape(r),
                              get_template(None), roster=_ROSTER,
                              disagreements=None)
        except Exception:                                      # noqa: BLE001
            issues = []
        out = {"record": r, "status": status_for(issues), "issues": issues}
        rec["ocr"] = {
            "employee_name": r.get("employee_name"),
            "employee_code": r.get("employee_code"),
            "designation": r.get("designation"),
            "client": r.get("client"),
            "project": r.get("project"),
            "period_label": r.get("period_label"),
            "summary": r.get("summary"),
            "days": [{"day": d.get("day"), "status": d.get("status"),
                      "in_time": d.get("in_time"), "out_time": d.get("out_time"),
                      "normal_hours": d.get("normal_hours"),
                      "ot_hours": d.get("ot_hours"),
                      "total_hours": d.get("total_hours")}
                     for d in (r.get("days") or [])],
            "n_days": len(r.get("days") or []),
            "status": out.get("status"),
            "n_issues": len(out.get("issues") or []),
            "rotated": r.get("_rotated"),
            "hires": bool(r.get("_hires") or r.get("_hires_boxes")),
            "generic_grid": r.get("_generic_grid"),
        }
    except Exception as exc:                                   # noqa: BLE001
        rec["ocr_error"] = str(exc)[:200]
    finally:
        try:
            tmp.unlink()
        except Exception:                                      # noqa: BLE001
            pass
    return rec


def validate() -> None:
    """Check the classifier against pages we already know the answer for."""
    known = [
        ("HANDWRITTEN", BASE / "demo" / "01_Sharad_Saxena.pdf", 0),
        ("HANDWRITTEN", BASE / "demo" / "10_Vivek_Kumar.pdf", 0),
        ("TYPED", BASE / ("Timesheet - HO 2026-2027/SHELL02 SHELL ENERGY "
                          "INDIAPVTLTD(Hazira)/SHELL02 SHELL ENERGY INDIA PVT "
                          "LTD(Hazira) APR 2026/SHELL APR 2026(1).pdf"), 0),
    ]
    ok = 0
    for expect, path, idx in known:
        if not path.exists():
            print(f"  SKIP (missing) {path.name}")
            continue
        r = process_one(("validate", str(path), idx, 0))
        got = r.get("verdict", "?")
        good = (expect == "HANDWRITTEN" and got == "handwritten") or \
               (expect == "TYPED" and got == "typed")
        ok += good
        p = r.get("profile", {})
        print(f"  {'OK  ' if good else 'WRONG'} {path.name[:38]:<40} "
              f"expected={expect:<12} got={got:<12} "
              f"p25={p.get('p25')} frac_low={p.get('frac_low')}")
    print(f"\n  classifier: {ok}/{len(known)} known pages correct")


def main() -> None:
    args = sys.argv[1:]
    if "--validate" in args:
        validate()
        return
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    workers = int(args[args.index("--workers") + 1]) if "--workers" in args else 3

    OUT.mkdir(parents=True, exist_ok=True)
    PAGES.mkdir(parents=True, exist_ok=True)

    done: set[tuple] = set()
    if RECORDS.exists():
        for line in RECORDS.read_text().splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
                # A crashed worker is not a result. Recording it as "done"
                # would make a restart skip the page for ever, silently
                # dropping it from the corpus.
                if d.get("verdict") == "worker_error":
                    continue
                done.add((d["dataset"], d["source"], d["page"]))
            except Exception:                                  # noqa: BLE001
                pass
        print(f"resuming: {len(done)} pages already examined", flush=True)

    print("enumerating pages ...", flush=True)
    all_pages = enumerate_pages()
    jobs = [(ds, s, i, n) for n, (ds, s, i) in enumerate(all_pages)
            if (ds, str(Path(s).relative_to(BASE)), i + 1) not in done]
    if limit:
        jobs = jobs[:limit]
    print(f"{len(all_pages)} pages total, {len(jobs)} to do, {workers} workers",
          flush=True)

    t0 = time.time()
    counts: Counter = Counter()
    fh = RECORDS.open("a")
    n_done = 0

    if workers <= 1:
        for j in jobs:
            r = process_one(j)
            fh.write(json.dumps(r) + "\n"); fh.flush()
            counts[r.get("verdict", "?")] += 1
            n_done += 1
            if n_done % 25 == 0:
                el = time.time() - t0
                print(f"  {n_done}/{len(jobs)}  {dict(counts)}  "
                      f"{el/n_done:.1f}s/page  eta "
                      f"{(len(jobs)-n_done)*el/n_done/3600:.1f}h", flush=True)
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        # NOTE: max_tasks_per_child was tried here and removed. Worker memory
        # was measured at 0.2-0.4 GB and never grew, so recycling fixed nothing
        # -- and the pool deadlocked with every worker gone and the parent idle
        # at 0% CPU. Pool size is the real lever: 5 workers died on the
        # oversized-scan cluster, 4 survive it.
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(process_one, j): j for j in jobs}
            for fut in as_completed(futs):
                try:
                    r = fut.result()
                except Exception as exc:                       # noqa: BLE001
                    j = futs[fut]
                    r = {"dataset": j[0], "source": str(Path(j[1]).relative_to(BASE)),
                         "page": j[2] + 1, "verdict": "worker_error",
                         "error": str(exc)[:200]}
                fh.write(json.dumps(r) + "\n"); fh.flush()
                counts[r.get("verdict", "?")] += 1
                n_done += 1
                if n_done % 25 == 0:
                    el = time.time() - t0
                    print(f"  {n_done}/{len(jobs)}  {dict(counts)}  "
                          f"{el/n_done:.2f}s/page  eta "
                          f"{(len(jobs)-n_done)*el/n_done/3600:.1f}h", flush=True)
    fh.close()

    print(f"\ndone in {(time.time()-t0)/3600:.2f}h: {dict(counts)}")
    (OUT / "summary.json").write_text(json.dumps({
        "examined": n_done, "counts": dict(counts),
        "pages_total": len(all_pages),
    }, indent=1))


if __name__ == "__main__":
    main()

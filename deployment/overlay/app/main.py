"""FastAPI application: upload -> extract -> validate -> review -> export.

Single process, no queue broker, no DB server. Extraction runs on a background
worker thread with a queue of one worker: on a CPU-only laptop the model is the
bottleneck and running two pages concurrently makes both slower while doubling
peak RAM -- which is the thing most likely to kill a 16GB machine mid-demo.
"""
from __future__ import annotations

import json
import queue
import shutil
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import (config, db, eventlog, export_designs, export_excel,
               pipeline, preprocess)
from .roster import Roster
from .templates_spec import TEMPLATES, get as get_template
from .validate import status_for, validate

app = FastAPI(title=config.APP_TITLE)

WEB_DIR = config.BASE_DIR / "web"
ROSTER_PATH = config.DATA_DIR / "roster.csv"

_roster = Roster.from_csv(ROSTER_PATH)
_work: "queue.Queue[tuple[int, bool]]" = queue.Queue()
_progress: dict[str, Any] = {"active": False, "page_id": None, "done": 0, "total": 0}


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

def _process_page(page_id: int, force: bool = False) -> None:
    page = db.get_page(page_id)
    if not page:
        return
    db.set_page_status(page_id, "processing")
    started = time.time()
    eventlog.emit(f"Reading {page['source_name']}", "step", page_id)
    try:
        out = pipeline.process_page(
            Path(page["image_path"]), page["page_hash"], roster=_roster,
            force=force)
        _log_outcome(page_id, out)
        db.set_page_result(
            page_id,
            template_key=out["analysis"].get("route", ""),
            status=out["status"],
            record=out["record"],
            issues=out["issues"],
            disagreements=out["analysis"],
            from_cache=out["from_cache"],
            extract_ms=out["ms"])
        db.audit(page_id, "system", "extracted",
                 detail=f"route={out['analysis'].get('route')} "
                        f"cached={out['from_cache']} issues={len(out['issues'])}")
        _add_shared_page_employees(page, out)
    except Exception as exc:                                    # noqa: BLE001
        db.set_page_result(
            page_id, template_key="", status="error", record={},
            issues=[{"code": "extraction_failed", "severity": "block",
                     "message": f"Extraction failed: {exc}", "field": None,
                     "day": None, "expected": None, "found": None}],
            disagreements={}, from_cache=False,
            extract_ms=int((time.time() - started) * 1000))
        db.audit(page_id, "system", "error", detail=traceback.format_exc(limit=3))
        eventlog.emit(f"Could not read this page — {exc}", "bad", page_id)


def _add_shared_page_employees(page: dict, out: dict) -> None:
    """One sheet can list several people (D-066).

    The reader returns the others alongside the first; each becomes a page of
    its own, pointing at the same scan, so every person can be checked,
    corrected, locked and exported exactly like anyone else. Without this they
    were silently dropped: on the four ISGEC sheets, 8 of 12 people and 246
    day rows never reached the reviewer.
    """
    extras = out.get("more") or []
    if not extras:
        return
    made = 0
    for i, ex in enumerate(extras, start=2):
        rec = ex.get("record") or {}
        if not (rec.get("days") and rec.get("employee_name")):
            continue
        try:
            meta = dict(page.get("meta") or {})
            meta.update(shared_page_of=page["id"], shared_page_index=i)
            pid = db.add_page(page["batch_id"],
                              f"{page['source_name']} — {rec['employee_name']}",
                              page["image_path"],
                              f"{page['page_hash']}:e{i}", meta)
            db.set_page_result(
                pid, template_key="shared_page", status=ex["status"],
                record=rec, issues=ex["issues"],
                disagreements={"route": "shared_page",
                               "shared_page_of": page["id"]},
                from_cache=False, extract_ms=0)
            db.audit(pid, "system", "extracted",
                     detail=f"second employee from {page['source_name']}")
            made += 1
        except Exception:                                       # noqa: BLE001
            continue
    if made:
        eventlog.emit(
            f"This sheet lists {made + 1} people — added {made} more "
            f"to check", "good", page["id"])


def _log_outcome(page_id: int, out: dict) -> None:
    """Narrate one page in the words the client uses, not the code's."""
    rec, an = out.get("record") or {}, out.get("analysis") or {}
    name = rec.get("employee_name") or "name not found"
    days = rec.get("days") or []
    read = sum(1 for d in days
               if any(str(d.get(k) or "").strip()
                      for k in ("in_time", "out_time", "normal_hours")))

    if out.get("from_cache"):
        eventlog.emit(f"{name} — seen before, reused instantly",
                      "good", page_id)
    else:
        eventlog.emit(
            f"{name} — {len(days)} day rows, {read} with times "
            f"({out.get('ms', 0) / 1000:.1f}s)", "info", page_id,
            detail=f"{an.get('n_boxes', 0)} text areas, "
                   f"{an.get('row_rules', 0)} printed lines found")

    if rec.get("_reconciled"):
        eventlog.emit(
            f"Filled {rec['_reconciled']} unreadable row(s) from the totals "
            f"written on the sheet", "good", page_id)
    if rec.get("_vlm_header"):
        eventlog.emit("Name box was unclear — took a closer look",
                      "step", page_id)

    issues = out.get("issues") or []
    blocks = [i for i in issues if i.get("severity") == "block"]
    if blocks:
        eventlog.emit(f"Flagged — {blocks[0]['message']}", "bad", page_id,
                      detail=(f"and {len(blocks) - 1} more"
                              if len(blocks) > 1 else None))
    elif issues:
        eventlog.emit(f"Minor warnings ({len(issues)}) — worth a glance",
                      "warn", page_id)
    else:
        eventlog.emit("Every check passed — no review needed", "good", page_id)


def _worker() -> None:
    while True:
        # Queue items are (page_id, force). `force` skips the extraction cache,
        # which a re-extract request MUST do -- otherwise it re-serves the very
        # result the user asked to discard.
        page_id, force = _work.get()
        try:
            _progress.update(active=True, page_id=page_id)
            _process_page(page_id, force=force)
            _progress["done"] += 1
        finally:
            _progress["active"] = _work.qsize() > 0
            _work.task_done()


# Worker pool sizing for the 3,000 pages/day requirement.
#
# Measured single-page cost is ~3-6 s (OCR dominates; it releases the GIL
# inside ONNX Runtime, so threads genuinely run in parallel here).
#   1 worker  : 3000 x 5 s          = ~4.2 h   -- meets the target, barely
#   4 workers : 3000 x 5 s / 4      = ~1.0 h   -- comfortable
#
# The ceiling is RAM, not CPU. Each worker holds an OCR session plus a decoded
# page (~250-400 MB peak). On the 16 GB target laptop, with Windows taking
# 3-4 GB, four workers is the safe maximum; we leave 2 cores free so the
# machine stays usable while a batch runs.
def _pool_size() -> int:
    import os
    env = os.getenv("TS_WORKERS")
    if env and env.isdigit() and int(env) > 0:
        return int(env)
    cores = os.cpu_count() or 4
    return max(1, min(4, cores - 2))


WORKERS = _pool_size()
for _i in range(WORKERS):
    threading.Thread(target=_worker, daemon=True,
                     name=f"extract-worker-{_i}").start()


@app.on_event("startup")
def _startup() -> None:
    db.init()


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((WEB_DIR / "index.html").read_text(encoding="utf-8"))


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/api/cost")
def cloud_cost() -> dict:
    """Hidden: what this project costs on Google Cloud (exact when the billing export is on)."""
    from . import cloudcost
    return cloudcost.snapshot()


@app.get("/cost", response_class=HTMLResponse)
def cost_page() -> str:
    return (config.BASE_DIR / "web" / "cost.html").read_text(encoding="utf-8")


def _who(request: Request | None) -> str:
    """The signed-in person. The login gate (Caddy) sets X-Remote-User after
    basic-auth; on a laptop there is no gate, so it is 'local'."""
    if request is None:
        return "reviewer"
    return (request.headers.get("x-remote-user") or "local").strip()[:60]


@app.get("/api/me")
def me(request: Request) -> dict:
    return {"user": _who(request)}


@app.get("/api/health")
def health() -> dict:
    ocr_ready, ocr_name = True, "RapidOCR PP-OCRv6"
    try:
        from .ocr_engine import _engine
        _engine()
    except Exception as exc:                                    # noqa: BLE001
        ocr_ready, ocr_name = False, str(exc)[:60]
    return {
        "ocr_ready": ocr_ready,
        "ocr_engine": ocr_name,
        "roster_loaded": not _roster.empty,
        "roster_size": len(_roster),
        "templates": list(TEMPLATES),
        "pipeline": pipeline.PIPELINE_VERSION,
        "workers": WORKERS,
        "queue_depth": _work.qsize(),
        "progress": _progress,
    }


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------

@app.post("/api/batches")
async def create_batch(request: Request, name: str = Form(...),
                       files: list[UploadFile] = File(...)) -> dict:
    if not files:
        raise HTTPException(400, "No files uploaded")
    batch_id = db.create_batch(name)
    db.audit(None, _who(request), "batch_created", detail=f"batch={name} files={len(files)}")

    added, skipped = [], []
    for f in files:
        raw = await f.read()
        if not raw:
            skipped.append({"name": f.filename, "reason": "empty file"})
            continue
        safe_name = Path(f.filename or "upload").name
        dest = config.UPLOAD_DIR / f"{batch_id}_{safe_name}"
        dest.write_bytes(raw)
        try:
            pages = preprocess.prepare(dest)
        except Exception as exc:                                # noqa: BLE001
            skipped.append({"name": safe_name, "reason": str(exc)})
            continue

        for img_path, meta in pages:
            # Hash the *normalised* page, not the upload: the same photo saved
            # twice by two different phones must resolve to one cache entry.
            page_hash = preprocess.file_sha256(img_path)
            pid = db.add_page(batch_id, safe_name, str(img_path), page_hash, meta)
            _work.put((pid, False))
            added.append(pid)

    _progress["total"] += len(added)
    eventlog.emit(f"Received {len(files)} file(s) — {len(added)} page(s) to read",
                  "step")
    for sk in skipped:
        eventlog.emit(f"Skipped {sk['name']} — {sk['reason']}", "warn")
    return {"batch_id": batch_id, "pages": len(added), "page_ids": added,
            "skipped": skipped}


@app.get("/api/batches")
def batches() -> list[dict]:
    return db.list_batches()


@app.get("/api/batches/{batch_id}/pages")
def batch_pages(batch_id: int, status: str | None = None) -> list[dict]:
    pages = db.list_pages(batch_id=batch_id, status=status)
    holders = db.locks_for([p["id"] for p in pages])
    # Trim the record out of list responses; the grid can be large and the
    # review queue only needs counts to render.
    out = []
    for p in pages:
        rec = p.get("record") or {}
        out.append({
            "id": p["id"], "source_name": p["source_name"], "checking_by": holders.get(p["id"]),
            "status": p["status"], "template_key": p["template_key"],
            "from_cache": bool(p["from_cache"]), "extract_ms": p["extract_ms"],
            "employee_name": rec.get("employee_name"),
            "employee_code": rec.get("employee_code"),
            "issue_count": len(p.get("issues") or []),
            "block_count": sum(1 for i in (p.get("issues") or [])
                               if i.get("severity") == "block"),
            "field_count": _field_count(rec),
        })
    return out


def _field_count(rec: dict) -> int:
    """How many non-empty values were actually lifted off this page.

    The demo needs a number that means something concrete to the client
    ("we read 1,340 values off 46 sheets"), so this counts real extracted
    values -- header fields, summary fields, and every populated day cell --
    not row counts or a percentage.
    """
    n = sum(1 for k in ("employee_name", "employee_code", "designation",
                        "period_label", "location", "company")
            if (rec.get(k) or "").strip())
    n += sum(1 for v in (rec.get("summary") or {}).values()
             if str(v or "").strip())
    for d in rec.get("days") or []:
        n += sum(1 for k, v in d.items()
                 if k != "day" and str(v or "").strip())
    return n


@app.get("/api/accuracy")
def accuracy() -> dict:
    """The last benchmark run, scored against the client's own typed Excel.

    Deliberately served from the eval harness output rather than computed
    live: a system cannot measure its own accuracy without ground truth, and
    showing a self-reported number in a demo would be misleading.
    """
    path = config.DATA_DIR / "eval_100.json"
    if not path.exists():
        return {"available": False}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:                                           # noqa: BLE001
        return {"available": False}
    hit, tot = data.get("field_hit") or {}, data.get("field_tot") or {}
    total_hit = sum(hit.get(k, 0) for k in tot)
    total_tot = sum(tot.values())
    st = data.get("stats") or {}
    return {
        "available": True,
        "overall": round(100 * total_hit / total_tot, 1) if total_tot else None,
        "comparisons": total_tot,
        "pages": st.get("pages") or st.get("matched"),
        "matched": st.get("matched"),
        "fields": {k: {"pct": round(100 * hit.get(k, 0) / v, 1), "n": v}
                   for k, v in sorted(tot.items()) if v},
        "measured_at": time.strftime(
            "%d %b %Y", time.localtime(path.stat().st_mtime)),
    }


@app.get("/api/log")
def activity_log(after: int = 0) -> dict:
    """Live activity feed for the UI. `after` is the last seq the client saw."""
    return {"events": eventlog.since(after), "latest": eventlog.latest_seq()}


@app.get("/api/export-designs")
def export_designs_list() -> list[dict]:
    """The five presentations the client can choose between."""
    return [{"key": k, "label": lab} for k, (lab, _) in
            export_designs.DESIGNS.items()] + [
        {"key": "all", "label": "All five (one workbook, for comparison)"}]


@app.get("/api/batches/{batch_id}/export")
def export(batch_id: int, request: Request, design: str = "all") -> FileResponse:
    pages = db.list_pages(batch_id=batch_id)
    if not pages:
        raise HTTPException(404, "No pages in this batch")
    batches_ = {b["id"]: b for b in db.list_batches()}
    name = batches_.get(batch_id, {}).get("name", f"batch{batch_id}")
    if design not in export_designs.DESIGNS and design != "all":
        raise HTTPException(400, f"Unknown design '{design}'")
    path = export_designs.export(pages, name, design)
    db.audit(None, _who(request), "exported",
             detail=f"batch={batch_id} pages={len(pages)} file={path.name}")
    eventlog.emit(f"Excel created — {len(pages)} page(s), {path.name}", "good")
    return FileResponse(path, filename=path.name,
                        media_type="application/vnd.openxmlformats-officedocument."
                                   "spreadsheetml.sheet")


# ---------------------------------------------------------------------------
# Pages / review
# ---------------------------------------------------------------------------

@app.get("/api/pages/{page_id}")
def page_detail(page_id: int, request: Request, claim: int = 1) -> dict:
    p = db.get_page(page_id)
    if not p:
        raise HTTPException(404, "Page not found")
    # Opening a page claims it for the person (unless ?claim=0, e.g. the
    # records screen just reading). Someone else's live lock is reported,
    # never overridden -- they get a read-only view.
    me = _who(request)
    p["lock"] = db.acquire_lock(page_id, me) if claim else (db.lock_status(page_id) or {"ok": True})
    p["lock"]["me"] = me
    rec = p.get("record") or {}
    spec = get_template(p.get("template_key"))
    p["day_fields"] = spec.day_fields()
    p["summary_fields"] = spec.summary_fields()
    p["period_days"] = spec.period_days
    p["roster_suggestions"] = _roster.suggest(rec.get("employee_name") or "") \
        if not _roster.empty else []
    p["audit"] = db.audit_trail(page_id)
    return p


@app.post("/api/pages/{page_id}/lock")
def lock_heartbeat(page_id: int, request: Request) -> dict:
    """Renew (or first claim) the lock while the page is on someone's screen."""
    r = db.acquire_lock(page_id, _who(request)); r["me"] = _who(request); return r


@app.delete("/api/pages/{page_id}/lock")
def lock_release(page_id: int, request: Request) -> dict:
    db.release_lock(page_id, _who(request)); return {"ok": True}


@app.get("/api/pages/{page_id}/image")
def page_image(page_id: int) -> FileResponse:
    p = db.get_page(page_id)
    if not p:
        raise HTTPException(404, "Page not found")
    path = Path(p["image_path"])
    if not path.exists():
        raise HTTPException(404, "Image file missing")
    return FileResponse(path, media_type="image/png")


@app.put("/api/pages/{page_id}")
async def save_page(page_id: int, payload: dict, request: Request) -> dict:
    """Save reviewer corrections, re-validate, and record every changed field.

    Re-validation on save is the point: a correction that fixes one number but
    breaks the row-sum must be caught immediately, not at invoice time.
    """
    p = db.get_page(page_id)
    if not p:
        raise HTTPException(404, "Page not found")

    actor = _who(request)
    held = db.lock_status(page_id)
    if held and held["actor"] != actor:
        raise HTTPException(409, f"This page is being checked by {held['actor']} right now. "
                                 f"Your changes were not saved.")
    new_record = payload.get("record") or {}
    old_record = p.get("record") or {}

    from .extract import _flatten
    old_flat, new_flat = _flatten(old_record), _flatten(new_record)
    changed = 0
    for key in sorted(set(old_flat) | set(new_flat)):
        ov, nv = old_flat.get(key), new_flat.get(key)
        if str(ov or "") != str(nv or ""):
            db.audit(page_id, actor, "field_corrected", field=key, old=ov, new=nv)
            changed += 1

    spec = get_template(p.get("template_key"))
    # Validate the SAME shape the pipeline validates.
    #
    # This passed the raw record straight to validate(), while extraction
    # passes pipeline._to_validator_shape(record). The two differ -- the
    # validator reads period_start/period_end, which the raw record does not
    # have (it carries period_label) -- so every save re-validated against a
    # shape the checks could not read and invented issues.
    #
    # Measured: a page sitting at review_optional with NO blocking issues was
    # saved with ZERO changes and came back needs_review with one block. A
    # reviewer confirming a good page made it look worse, which is the exact
    # opposite of what the review screen is for.
    issues = validate(pipeline._to_validator_shape(new_record), spec,
                      roster=_roster,
                      disagreements=p.get("disagreements") or {})
    # Re-score every row after a correction, so the reviewer's own edit
    # clears the flag it addressed (app/rowconf.py).
    from . import rowconf as _rowconf
    _rowconf.annotate(new_record, issues)
    status = "corrected" if changed and not any(
        i["severity"] == "block" for i in issues) else status_for(issues)
    db.update_record(page_id, new_record, issues, status)
    db.release_lock(page_id, actor)
    db.audit(page_id, actor, "saved",
             detail=f"changed={changed} remaining_issues={len(issues)}")
    left = sum(1 for i in issues if i["severity"] == "block")
    eventlog.emit(
        f"You corrected {changed} field(s) — " +
        ("all checks pass now" if not left else f"{left} issue(s) still open"),
        "good" if not left else "warn", page_id)
    return {"ok": True, "status": status, "issues": issues, "changed": changed}


@app.post("/api/pages/{page_id}/reextract")
def reextract(page_id: int, request: Request) -> dict:
    """Force a fresh extraction, bypassing the cache. Used when a page was
    misclassified into the wrong template."""
    p = db.get_page(page_id)
    if not p:
        raise HTTPException(404, "Page not found")
    db.audit(page_id, _who(request), "reextract_requested")
    _work.put((page_id, True))
    return {"ok": True, "queued": True}


# ---------------------------------------------------------------------------
# Roster / audit
# ---------------------------------------------------------------------------

@app.post("/api/roster")
async def upload_roster(request: Request, file: UploadFile = File(...)) -> dict:
    global _roster
    raw = await file.read()
    ROSTER_PATH.write_bytes(raw)
    _roster = Roster.from_csv(ROSTER_PATH)
    db.audit(None, _who(request), "roster_uploaded",
             detail=f"rows={len(_roster)} file={file.filename}")
    return {"ok": True, "rows": len(_roster),
            "columns": list(_roster.rows[0]) if _roster.rows else []}


@app.get("/api/audit")
def audit_log(limit: int = 300) -> list[dict]:
    return db.audit_all(limit=limit)

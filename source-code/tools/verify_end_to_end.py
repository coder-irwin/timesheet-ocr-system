"""End-to-end verification of the whole system, in one run.

Checks the real chain a document travels -- import, preprocess, OCR, extract,
reconcile, validate, roster, export -- plus the accuracy harnesses and the
regression panel, and prints a PASS/FAIL table.

Nothing here is mocked. Every step runs the shipped code on real files.

    python tools/verify_end_to_end.py
"""
from __future__ import annotations

import sys
import time
import traceback
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str):
    def deco(fn):
        def run():
            t0 = time.time()
            try:
                detail = fn()
                RESULTS.append((name, True, f"{detail}  ({time.time()-t0:.1f}s)"))
            except Exception as exc:                           # noqa: BLE001
                RESULTS.append((name, False,
                                f"{type(exc).__name__}: {exc}"))
                traceback.print_exc()
        return run
    return deco


@check("1. all app modules import")
def _imports():
    import importlib
    mods = ["config", "preprocess", "ocr_engine", "aarvi_form", "generic_grid",
            "reconcile", "validate", "roster", "vocab", "field_typing",
            "pipeline", "export_excel", "export_designs", "db", "main"]
    for m in mods:
        importlib.import_module(f"app.{m}")
    from app import pipeline
    return f"{len(mods)} modules, PIPELINE_VERSION={pipeline.PIPELINE_VERSION}"


@check("2. roster loads")
def _roster():
    from app.roster import Roster
    r = Roster.from_csv(BASE / "data" / "roster.csv")
    assert not r.empty, "roster is empty"
    n = len(getattr(r, "rows", []) or [])
    return f"{n} employees"


@check("3. handwritten page: preprocess -> OCR -> extract -> validate")
def _handwritten():
    from app import pipeline, preprocess
    from app.roster import Roster
    src = next(iter((BASE / "Timesheet - Delhi 2026-2027").rglob(
        "IOCLMS APR 2026.pdf")))
    out = BASE / "data" / "_verify"
    out.mkdir(parents=True, exist_ok=True)
    page = preprocess.prepare(src, out_dir=out)[0][0]
    res = pipeline.process_page(page, preprocess.file_sha256(page),
                                roster=Roster.from_csv(BASE / "data" / "roster.csv"),
                                source_hint=str(src), force=True)
    rec = res["record"]
    days = rec.get("days") or []
    assert days, "no days extracted from a handwritten page"
    assert res["status"] in ("clean", "review_optional", "needs_review")
    return (f"name={rec.get('employee_name')!r} days={len(days)} "
            f"status={res['status']} issues={len(res['issues'])}")


@check("4. typed transposed page via generic grid")
def _transposed():
    from app import pipeline, preprocess
    from app.roster import Roster
    src = BASE / ("Timesheet - HO 2026-2027/SHELL02 SHELL ENERGY INDIAPVTLTD"
                  "(Hazira)/SHELL02 SHELL ENERGY INDIA PVT LTD(Hazira) APR "
                  "2026/SHELL APR 2026(1).pdf")
    if not src.exists():
        return "SKIPPED (sample not present)"
    out = BASE / "data" / "_verify"
    page = preprocess.prepare(src, out_dir=out)[0][0]
    res = pipeline.process_page(page, preprocess.file_sha256(page),
                                roster=Roster.from_csv(BASE / "data" / "roster.csv"),
                                source_hint=str(src), force=True)
    rec = res["record"]
    days = rec.get("days") or []
    assert days, "generic grid produced no days on the transposed sheet"
    return (f"name={rec.get('employee_name')!r} days={len(days)} "
            f"via={rec.get('_generic_grid')}")


@check("5. no page may fall through (corrupt input)")
def _fallthrough():
    from app import pipeline
    bad = BASE / "data" / "_verify" / "not_an_image.png"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"this is not a png")
    res = pipeline.process_page(bad, "deadbeef" * 8, force=True)
    assert res["status"] == "needs_review", res["status"]
    assert res["issues"], "a failed page produced no issue to review"
    return f"status={res['status']} issue={res['issues'][0]['code']}"


@check("6. Excel export produces a real workbook")
def _export():
    import openpyxl

    from app import export_designs, preprocess, pipeline
    from app.roster import Roster
    src = next(iter((BASE / "demo").glob("*.pdf")))
    out = BASE / "data" / "_verify"
    page = preprocess.prepare(src, out_dir=out)[0][0]
    res = pipeline.process_page(page, preprocess.file_sha256(page),
                                roster=Roster.from_csv(BASE / "data" / "roster.csv"),
                                source_hint=str(src), force=True)
    # Same shape the API passes: db page rows carrying the extracted record.
    page_row = {"id": 1, "source_name": src.name, "status": res["status"],
                "record": res["record"], "issues": res["issues"]}
    dest = export_designs.export([page_row], "verify", "all", out_dir=out)
    wb = openpyxl.load_workbook(dest)
    rows = sum(ws.max_row for ws in wb.worksheets)
    assert rows > 10, "workbook is essentially empty"
    return f"{dest.name}: {len(wb.sheetnames)} sheets, {rows} rows total"


@check("7. fast accuracy harness")
def _fast():
    from eval_fast import score
    r = score(quiet=True)
    dh, dt = r["hit"]["day_status"], r["tot"]["day_status"]
    assert dt > 500, "harness scored suspiciously few comparisons"
    return (f"matched={r['matched']} day={dh}/{dt} = {dh/dt:.1%} "
            f"overall={r['overall']:.1%}")


@check("8. designation regression panel")
def _regression():
    import subprocess
    p = subprocess.run([sys.executable, str(BASE / "tools" / "eval_desig.py")],
                       capture_output=True, text=True, cwd=str(BASE))
    tail = [ln for ln in p.stdout.splitlines() if "REGRESSION" in ln]
    assert tail, "regression panel produced no verdict"
    assert "PASS" in tail[-1], tail[-1]
    return tail[-1].strip()


@check("9. generic grid refuses an employee list")
def _guard():
    from app import generic_grid as G
    assert G._looks_like_person("Rahul Sahu") is True
    assert G._looks_like_person("AVAILED") is False
    assert G._as_day("②8") is None          # unicode digit that int() rejects
    assert G._as_day("0314126") == 3        # mangled handwritten date
    return "person/day heuristics behave"


@check("10. ground-truth index is loadable and non-trivial")
def _truth():
    import json
    idx = json.loads((BASE / "data" / "truth_index.json").read_text())
    rows = sum(len(v["truth"]) for v in idx.values())
    pdfs = sum(len(v["pdfs"]) for v in idx.values())
    assert rows > 1000
    return f"{len(idx)} folders, {rows} truth rows, {pdfs} PDFs"


def main() -> None:
    for fn in (_imports, _roster, _handwritten, _transposed, _fallthrough,
               _export, _fast, _regression, _guard, _truth):
        fn()
    print("\n" + "=" * 78)
    print("END-TO-END VERIFICATION")
    print("=" * 78)
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name:<52}")
        print(f"        {detail}")
    bad = [r for r in RESULTS if not r[1]]
    print("=" * 78)
    print(f"{len(RESULTS)-len(bad)}/{len(RESULTS)} passed")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

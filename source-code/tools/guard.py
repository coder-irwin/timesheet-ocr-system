"""The floor. Run this before shipping anything that touches accuracy.

    ./.venv/bin/python tools/guard.py            # ~25 min, the full floor
    ./.venv/bin/python tools/guard.py --quick    # ~2 min, structural checks only

Why this exists. Every regression this project has shipped followed the same
shape: a change improved the number someone was looking at, and quietly moved a
number nobody was looking at. Twice in one week.

  * D-073 turned off the angle classifier. Clock times went 83.6% -> 93.8% and
    day status looked flat -- but rows wrong AND unflagged went 10 -> 15, which
    nobody would have seen without checking for it.
  * D-075 stopped blocking pages whose checksums could not be computed. Half
    the false alarms went away, the 50-page sample did not move at all, and two
    corpus pages began passing as CLEAN while 15 of their 30 days were wrong.

Neither was caught by the metric the change was aimed at. Both were caught by
asking the same boring questions afterwards. So the questions are written down
here and run as one command, and the thresholds are the measured floor rather
than aspirations: the guard fails if the system gets WORSE, not if it fails to
get better.

ESCAPED is the one that must never move. A wrong day on a page the system
passed as clean is a wrong number reaching an invoice with nobody asked to look
at it. Everything else in this file is an accuracy figure; that one is the
product's promise.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
PY = str(BASE / ".venv" / "bin" / "python")

# Measured floor, pipeline v41-clean-means-verified, 7 Oct 2026. Raise these
# ONLY after a run proves the new value, and record the run in the decision log.
FLOOR = {
    "sample_strict_pct": 95.5,      # 50 pages hand-graded against the paper
    "sample_silent_max": 2,         # rows wrong AND unflagged
    "sample_missing_max": 0,
    "isgec_days_pct": 100.0,        # horizontal multi-employee sheets
    "isgec_silent_max": 0,
    "guard_day_pct": 93.0,          # frozen-OCR extraction harness
    "name_min": 30,                 # of 31
}


def run(cmd: list[str]) -> str:
    p = subprocess.run(cmd, cwd=BASE, capture_output=True, text=True)
    return p.stdout + p.stderr


def check(label: str, got, floor, ok: bool, fails: list[str]) -> None:
    mark = "PASS" if ok else "**FAIL**"
    print(f"  {mark:9} {label:44} {got}   (floor {floor})")
    if not ok:
        fails.append(f"{label}: {got}, floor {floor}")


def structural(fails: list[str]) -> None:
    """Things that must be true of the code itself, checked in seconds."""
    print("\nSTRUCTURAL")
    sys.path.insert(0, str(BASE))
    from app import clocks, generic_grid, ocr_engine, pipeline, rowconf, validate  # noqa: E402

    # Flags whose default IS the measured decision. A silent flip of any of
    # these is a regression that no accuracy run would attribute correctly.
    for name, obj, want, why in [
        ("ocr_engine.OCR_USE_CLS", ocr_engine.OCR_USE_CLS, False, "D-073"),
        ("pipeline.CLOCK_REPAIR", pipeline.CLOCK_REPAIR, False, "D-072 measured worse"),
        ("pipeline.UNIT_SUFFIX_HOURS", pipeline.UNIT_SUFFIX_HOURS, True, "D-076"),
        ("pipeline.SPLIT_CELL_IS_UNREADABLE", pipeline.SPLIT_CELL_IS_UNREADABLE, True, "D-076"),
        ("validate.UNCOMPUTABLE_IS_NOT_FAILED", validate.UNCOMPUTABLE_IS_NOT_FAILED, True, "D-075"),
        ("rowconf.CROWDED_CELL_REVIEW", rowconf.CROWDED_CELL_REVIEW, True, "D-074"),
        ("generic_grid.NUMERIC_CELL_IS_PRESENT",
         generic_grid.NUMERIC_CELL_IS_PRESENT, False, "D-086 measured no gain"),
    ]:
        check(f"{name} is {want}  [{why}]", obj, want, obj is want, fails)

    # Unit behaviour that three separate defects have turned on.
    cases = [("10Hrs", 10.0), ("3 6", None), ("85", 8.5), ("42", 0.42),
             ("1000", 10.0), ("10:00", 10.0), ("8.5", 8.5), ("8", 8.0)]
    bad = [(r, validate._num(pipeline.normalise_hours(r)), w)
           for r, w in cases if validate._num(pipeline.normalise_hours(r)) != w]
    check("hours parsing (10Hrs, 3 6, 85, 42, 1000, 10:00)",
          "all ok" if not bad else bad, "all ok", not bad, fails)

    cl = [("8:30 AM", (8, 30)), ("7:30 Pm", (19, 30)), ("00:60", None), ("9 AM", (9, 0))]
    bad = [(r, clocks.repair(r)[0], w) for r, w in cl if clocks.repair(r)[0] != w]
    check("clock grammar (8:30 AM, 7:30 Pm, 00:60, 9 AM)",
          "all ok" if not bad else bad, "all ok", not bad, fails)

    # D-092. Every harness in this project calls process_page(force=True), so
    # NONE of them exercises the cache branch -- and that branch rejoins the
    # common code with a different set of locals defined. Twice now something
    # added to the common path has referenced a name that only exists on the
    # fresh path, and both times it reached production because the floor above
    # was green. A real page, read twice.
    try:
        import hashlib
        from app import preprocess
        from app.roster import Roster
        pages = preprocess.prepare(
            BASE / "data/testsets/horizontal-multi-employee/sheets/ISG MAY 2026.pdf",
            BASE / "data/_eval_tmp/guard_cache")
        img = Path(pages[0][0])
        h = hashlib.sha1(img.read_bytes()).hexdigest()
        roster = Roster.from_csv(BASE / "data" / "roster.csv")
        fresh = pipeline.process_page(img, h, roster=roster, force=True)
        cached = pipeline.process_page(img, h, roster=roster, force=False)

        def shape(r):
            recs = [r["record"]] + [m["record"] for m in (r.get("more") or [])]
            return (len(recs), r.get("status"),
                    sum(1 for rc in recs for d in (rc.get("days") or [])
                        if (d.get("status") or "").strip()))
        got, want = shape(cached), shape(fresh)
        check("cache path returns the same page as a fresh read",
              f"{got}", f"{want}",
              got == want and cached.get("from_cache") is True, fails)
    except Exception as exc:                                     # noqa: BLE001
        check("cache path runs at all", f"{type(exc).__name__}: {exc}",
              "no exception", False, fails)


def accuracy(fails: list[str]) -> None:
    print("\nACCURACY  (this takes about 25 minutes)")

    out = run([PY, "tools/eval_fast.py"])
    m = re.search(r"day_status\s+(\d+)/(\d+)", out)
    pct = 100.0 * int(m.group(1)) / int(m.group(2)) if m else 0.0
    check("fast harness, day status", f"{pct:.1f}%", f">={FLOOR['guard_day_pct']}%",
          pct >= FLOOR["guard_day_pct"], fails)
    m = re.search(r"employee_name\s+(\d+)/", out)
    n = int(m.group(1)) if m else 0
    check("fast harness, employee name", f"{n}/31", f">={FLOOR['name_min']}",
          n >= FLOOR["name_min"], fails)

    out = run([PY, "tools/eval_isgec.py"])
    m = re.search(r"days (\d+)/(\d+) = ([\d.]+)%.*?silent (\d+)", out, re.S)
    if m:
        pct, silent = float(m.group(3)), int(m.group(4))
        check("horizontal sheets, days", f"{pct:.1f}%", f">={FLOOR['isgec_days_pct']}%",
              pct >= FLOOR["isgec_days_pct"], fails)
        check("horizontal sheets, silent errors", silent, f"<={FLOOR['isgec_silent_max']}",
              silent <= FLOOR["isgec_silent_max"], fails)
    else:
        check("horizontal sheets", "could not parse output", "a number", False, fails)

    out = run([PY, "tools/eval_sample50.py", "--run", "--normalise"])
    m = re.search(r"this run\s+strict (\d+)/(\d+) = ([\d.]+)%.*?silent (\d+)\s+missing (\d+)", out)
    if m:
        pct, silent, missing = float(m.group(3)), int(m.group(4)), int(m.group(5))
        check("50-page sample, day status", f"{pct:.1f}%", f">={FLOOR['sample_strict_pct']}%",
              pct >= FLOOR["sample_strict_pct"], fails)
        check("50-page sample, ROWS WRONG AND UNFLAGGED", silent,
              f"<={FLOOR['sample_silent_max']}", silent <= FLOOR["sample_silent_max"], fails)
        check("50-page sample, days missing", missing, f"<={FLOOR['sample_missing_max']}",
              missing <= FLOOR["sample_missing_max"], fails)
    else:
        check("50-page sample", "could not parse output", "a number", False, fails)


def main() -> int:
    quick = "--quick" in sys.argv
    sys.path.insert(0, str(BASE))
    from app.pipeline import PIPELINE_VERSION
    print(f"GUARD · pipeline {PIPELINE_VERSION}" + ("  (--quick: structural only)" if quick else ""))

    fails: list[str] = []
    structural(fails)
    if not quick:
        accuracy(fails)

    print()
    if fails:
        print(f"GUARD FAILED — {len(fails)} check(s) below the floor:")
        for f in fails:
            print(f"   - {f}")
        print("\nDo not ship. Either fix it, or change the floor in tools/guard.py")
        print("and write down in docs/revamp/00-DECISION-LOG.md why the floor moved.")
        return 1
    print("GUARD PASSED — safe to ship.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

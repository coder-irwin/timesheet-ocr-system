"""Does more resolution read HANDWRITING better?

PAGE_LONG_EDGE=1600 is described in config.py as "the tested compromise", but
that test predates the current extractor and was never repeated. Resolution
turned out to be decisive for dense landscape grids (a day header went from
4/30 to 30/30 correct), so the same question has to be asked of the
handwritten portrait pages that are the product's core.

This is an OCR/preprocess change, so the frozen inputs MUST be rebuilt at each
setting -- scoring the old freeze would measure nothing. That makes this slow
and is why it exists as its own script.

The frozen file is backed up first and rebuilt at the chosen value afterwards,
because a sweep otherwise leaves it holding whatever the LAST setting was --
a trap this project has hit before.

    python tools/sweep_resolution.py 1600 2000 2400
"""
from __future__ import annotations

import shutil
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from app import config                                         # noqa: E402
import eval_fast                                               # noqa: E402

BASE = Path(__file__).parent.parent
FROZEN = BASE / "data" / "eval_frozen.pkl"
BACKUP = BASE / "data" / "eval_frozen.before_sweep.pkl"


def main() -> None:
    edges = [int(a) for a in sys.argv[1:]] or [1600, 2000, 2400]

    if FROZEN.exists() and not BACKUP.exists():
        shutil.copy2(FROZEN, BACKUP)
        print(f"backed up frozen inputs -> {BACKUP.name}\n", flush=True)

    results = []
    for edge in edges:
        config.PAGE_LONG_EDGE = edge
        t0 = time.time()
        print(f"--- long edge {edge}: re-running OCR over the corpus ...",
              flush=True)
        eval_fast.freeze(100)
        r = eval_fast.score(quiet=True)
        dh = r["hit"].get("day_status", 0)
        dt = r["tot"].get("day_status", 1)
        nh = r["hit"].get("employee_name", 0)
        nt = r["tot"].get("employee_name", 1)
        results.append((edge, r["matched"], dh, dt, nh, nt, r["overall"]))
        print(f"    edge={edge}  matched={r['matched']}  "
              f"day={dh}/{dt} = {dh/max(dt,1):.2%}  "
              f"name={nh}/{nt}  overall={r['overall']:.4f}  "
              f"({time.time()-t0:.0f}s)", flush=True)

    print("\n" + "=" * 72)
    print(f"{'edge':>6}{'matched':>9}{'day':>14}{'day%':>9}{'name':>9}"
          f"{'overall':>10}")
    for edge, m, dh, dt, nh, nt, ov in results:
        print(f"{edge:>6}{m:>9}{f'{dh}/{dt}':>14}{dh/max(dt,1):>8.2%}"
              f"{f'{nh}/{nt}':>9}{ov:>10.4f}")

    best = max(results, key=lambda r: r[2] / max(r[3], 1))
    print(f"\nbest day accuracy at long edge {best[0]}")
    print("NOTE: day totals differ between rows when a page becomes matchable,"
          " so compare the day% AND the counts, not the percentage alone.")

    # Leave the frozen inputs at the winning setting, never at whatever ran
    # last -- otherwise every later measurement silently uses the wrong OCR.
    config.PAGE_LONG_EDGE = best[0]
    print(f"\nrebuilding frozen inputs at {best[0]} ...", flush=True)
    eval_fast.freeze(100)
    print("done")


if __name__ == "__main__":
    main()

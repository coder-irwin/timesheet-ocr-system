"""Parse every client Excel once and cache the result.

Parsing 702 Excel files takes minutes. Doing it at the start of every
evaluation run makes experimentation impossibly slow, so it happens once here
and every harness loads the JSON index instead.

The index is keyed by folder, because a PDF is matched against the ground
truth that lives alongside it.

    python tools/build_truth_index.py            # build/refresh
    python tools/build_truth_index.py --stats    # summarise what we have
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from collections import defaultdict
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import truth as truthmod                                       # noqa: E402

BASE = Path(__file__).parent.parent
ROOTS = {
    "Delhi": BASE / "Timesheet - Delhi 2026-2027",
    "HO": BASE / "Timesheet - HO 2026-2027",
    "Kolkata": BASE / "Timesheet - KOLKATA 2026-2027",
}
INDEX = BASE / "data" / "truth_index.json"


def build() -> dict:
    idx: dict[str, dict] = {}
    t0 = time.time()
    for ds, root in ROOTS.items():
        if not root.exists():
            print(f"  {ds}: MISSING at {root}")
            continue
        pairs: dict[Path, dict] = defaultdict(lambda: {"pdf": [], "xl": []})
        for p in root.rglob("*"):
            if not p.is_file() or p.name.startswith(("~$", ".")):
                continue
            s = p.suffix.lower()
            if s == ".pdf":
                pairs[p.parent]["pdf"].append(p)
            elif s in (".xls", ".xlsx"):
                pairs[p.parent]["xl"].append(p)

        folders, rows, pdfs = 0, 0, 0
        for i, (d, v) in enumerate(sorted(pairs.items())):
            if not (v["pdf"] and v["xl"]):
                continue
            t: list[dict] = []
            for xl in v["xl"]:
                try:
                    t.extend(truthmod.parse_truth(xl))
                except Exception:                              # noqa: BLE001
                    pass
            if not t:
                continue
            folders += 1
            rows += len(t)
            pdfs += len(v["pdf"])
            idx[str(d.relative_to(BASE))] = {
                "dataset": ds,
                "pdfs": sorted(str(x.relative_to(BASE)) for x in v["pdf"]),
                "truth": t,
            }
            if folders % 10 == 0:
                print(f"    {ds}: {folders} folders, {rows} truth rows",
                      flush=True)
        print(f"  {ds}: {folders} folders with truth, {rows} truth rows, "
              f"{pdfs} PDFs to evaluate", flush=True)
    print(f"  built in {time.time()-t0:.0f}s")
    return idx


def stats() -> None:
    idx = json.loads(INDEX.read_text())
    per = defaultdict(lambda: [0, 0, 0])
    for _k, v in idx.items():
        p = per[v["dataset"]]
        p[0] += 1
        p[1] += len(v["truth"])
        p[2] += len(v["pdfs"])
    print(f"{'dataset':<10}{'folders':>9}{'truth rows':>12}{'pdfs':>8}")
    for ds, (f, t, p) in sorted(per.items()):
        print(f"{ds:<10}{f:>9}{t:>12}{p:>8}")
    tot = [sum(x) for x in zip(*per.values())]
    print(f"{'TOTAL':<10}{tot[0]:>9}{tot[1]:>12}{tot[2]:>8}")


if __name__ == "__main__":
    if "--stats" in sys.argv:
        stats()
    else:
        idx = build()
        INDEX.write_text(json.dumps(idx))
        print(f"wrote {INDEX} ({INDEX.stat().st_size/1e6:.1f} MB)")

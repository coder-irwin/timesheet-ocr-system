"""Compare ground-truth recovery: legacy parser vs tools/truth.py.

Reports coverage gain AND guards against regression -- every employee row the
legacy parser found must still be found, or the new parser is not safe to
adopt no matter how much extra data it unlocks.
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import eval_100 as old                                         # noqa: E402
import truth as new                                            # noqa: E402

BASE = Path(__file__).parent.parent
ROOTS = [BASE / "Timesheet - Delhi 2026-2027",
         BASE / "Timesheet - HO 2026-2027",
         BASE / "Timesheet - KOLKATA 2026-2027"]


def key_of(rows):
    return {(r["employee_name"].lower().strip(),
             tuple(sorted(r["days"].items()))) for r in rows}


def main() -> None:
    tot = {"fo": 0, "fn": 0, "eo": 0, "en": 0}
    lost = []
    for R in ROOTS:
        if not R.exists():
            continue
        xls = [p for p in R.rglob("*")
               if p.is_file() and p.suffix.lower() in (".xls", ".xlsx")
               and not p.name.startswith(("~$", "."))]
        fo = fn = eo = en = 0
        for i, p in enumerate(xls):
            try:
                o = old.parse_truth(p)
            except Exception:                                  # noqa: BLE001
                o = []
            try:
                n = new.parse_truth(p)
            except Exception:                                  # noqa: BLE001
                n = []
            if o:
                fo += 1
                eo += len(o)
            if n:
                fn += 1
                en += len(n)
            if o:
                missing = key_of(o) - key_of(n)
                if missing:
                    lost.append((str(p.relative_to(BASE)), len(missing), len(o)))
            if (i + 1) % 50 == 0:
                print(f"    ...{R.name[:22]} {i+1}/{len(xls)}", flush=True)
        print(f"{R.name:<34} files {fo:>3} -> {fn:<4}  employees {eo:>4} -> {en}",
              flush=True)
        tot["fo"] += fo; tot["fn"] += fn; tot["eo"] += eo; tot["en"] += en

    print()
    print(f"TOTAL   files {tot['fo']} -> {tot['fn']}"
          f"   employees {tot['eo']} -> {tot['en']}")
    if tot["eo"]:
        print(f"        coverage x{tot['en']/max(tot['eo'],1):.1f} on employees")
    print()
    print(f"REGRESSION CHECK: {len(lost)} file(s) lost previously-found rows")
    for f, m, t in lost[:15]:
        print(f"   LOST {m}/{t}  {f[-80:]}")
    if not lost:
        print("   none -- new parser is a strict superset on these files")


if __name__ == "__main__":
    main()

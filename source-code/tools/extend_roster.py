"""Extend the roster with identities from the attendance-grid Excels.

WHY A SECOND HARVEST
--------------------
tools/build_roster.py reads Excels whose layout is *list-like* (a header row
with NAME / CODE columns and one employee per row). But a large share of the
corpus is *attendance grids*: employee rows with day-number columns, the very
sheets eval_100 scores against. Their name/code columns sit next to 31 day
columns, and several never made it through the list-style detector -- which is
exactly why employees who demonstrably exist in the client's own spreadsheets
(Yogesh Raman / 51078, Rajeev Iyengar / 50700) were missing from the roster and
their pages could not be identity-matched.

eval_100.parse_truth() already parses that grid layout reliably (it is the
basis of every accuracy number in this project). This script reuses it
verbatim over EVERY Excel in the corpus and merges what it finds into
data/roster.csv. Merge only -- nothing already in the roster is removed, and
an existing code's name is never overwritten.

    python tools/extend_roster.py
"""
from __future__ import annotations

import csv
import shutil
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

# The grid parser moved to tools/truth.py, which recognises far more sheet
# shapes than eval_100's original (285 files vs 126, including Kolkata's
# datetime and '21May Thu' day headers). All three datasets are scanned, not
# just Delhi -- the whole point of this pass is to learn from the new data.
from truth import parse_truth                                   # noqa: E402

_BASE = Path(__file__).parent.parent
ROOTS = [_BASE / "Timesheet - Delhi 2026-2027",
         _BASE / "Timesheet - HO 2026-2027",
         _BASE / "Timesheet - KOLKATA 2026-2027"]

OUT = Path(__file__).parent.parent / "data" / "roster.csv"


def norm(s: str) -> str:
    return " ".join(str(s or "").upper().split())


def main() -> None:
    existing: list[dict] = []
    by_code: dict[str, dict] = {}
    by_name: set[str] = set()
    with OUT.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            existing.append(row)
            if row.get("employee_code"):
                by_code[norm(row["employee_code"])] = row
            by_name.add(norm(row.get("employee_name")))

    files = [p for R in ROOTS if R.exists() for p in R.rglob("*")
             if p.suffix.lower() in (".xls", ".xlsx")
             and not p.name.startswith(("~$", "."))]
    print(f"scanning {len(files)} Excel files with the grid parser ...")

    found: dict[tuple[str, str], dict] = {}
    clients: dict[tuple[str, str], set] = defaultdict(set)
    for f in files:
        client = next((f.relative_to(R).parts[0] for R in ROOTS
                        if R.exists() and R in f.parents), f.parent.name)
        for t in parse_truth(f):
            key = (norm(t["employee_code"]), norm(t["employee_name"]))
            if not key[1]:
                continue
            found.setdefault(key, t)
            clients[key].add(client)

    added = 0
    for (code_n, name_n), t in sorted(found.items()):
        if code_n and code_n in by_code:
            continue                       # code already known
        if not code_n and name_n in by_name:
            continue                       # codeless duplicate of a known name
        if code_n and name_n in by_name and not code_n:
            continue
        existing.append({
            "employee_code": t["employee_code"].strip(),
            "employee_name": t["employee_name"].strip(),
            "clients": ";".join(sorted(clients[(code_n, name_n)])),
            "occurrences": "1",
        })
        if code_n:
            by_code[code_n] = existing[-1]
        by_name.add(name_n)
        added += 1

    backup = OUT.with_suffix(".csv.bak")
    shutil.copy2(OUT, backup)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["employee_code", "employee_name",
                                           "clients", "occurrences"])
        w.writeheader()
        for row in existing:
            w.writerow({k: row.get(k, "") for k in w.fieldnames})

    print(f"grid parser found {len(found)} identities; "
          f"added {added} new to roster ({len(existing)} total)")
    print(f"previous roster backed up to {backup.name}")


if __name__ == "__main__":
    main()

"""How often does the client's own ground truth contradict itself?

Accuracy can only be measured against a single agreed answer. While matching
SHELL02 it turned out that one employee had THREE different April records in
the client's own spreadsheets, disagreeing with each other on four to five
days. Our extraction matched one of them exactly, and still scored zero,
because the harness refuses to pick between conflicting truths.

That is not a pipeline defect and no amount of engineering removes it: where
the source data disagrees with itself there is no single correct answer to be
right about. This quantifies how much of the corpus is in that state, per
folder, so the ceiling on measurable accuracy is known rather than guessed.

    python tools/truth_conflicts.py
"""
from __future__ import annotations

import json
import sys
import warnings
from collections import Counter, defaultdict
from pathlib import Path

warnings.filterwarnings("ignore")
BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "tools"))

INDEX = BASE / "data" / "truth_index.json"


def main() -> None:
    idx = json.loads(INDEX.read_text())
    tot_names = 0
    dup_names = 0
    conflicting = 0
    per_folder: dict[str, tuple[int, int]] = {}
    examples = []

    for folder, v in sorted(idx.items()):
        by_name: dict[str, list] = defaultdict(list)
        for t in v["truth"]:
            by_name[" ".join(t["employee_name"].upper().split())].append(t)
        f_names = f_conf = 0
        for name, rows in by_name.items():
            tot_names += 1
            f_names += 1
            if len(rows) < 2:
                continue
            dup_names += 1
            bad = False
            for i in range(len(rows)):
                for j in range(i + 1, len(rows)):
                    a, b = rows[i]["days"], rows[j]["days"]
                    common = set(a) & set(b)
                    if any(a[k] != b[k] for k in common):
                        bad = True
                        break
                if bad:
                    break
            if bad:
                conflicting += 1
                f_conf += 1
                if len(examples) < 6:
                    examples.append((folder.split("/")[-1][:40], name,
                                     len(rows)))
        per_folder[folder] = (f_names, f_conf)

    print(f"employee-name records examined : {tot_names}")
    print(f"names appearing more than once : {dup_names}")
    print(f"names whose records CONTRADICT : {conflicting}"
          f"  ({conflicting/max(tot_names,1):.1%} of all names)")
    print()
    worst = sorted(per_folder.items(), key=lambda kv: -kv[1][1])[:12]
    print(f"{'folder':<56}{'names':>7}{'conflicting':>13}")
    for f, (n, c) in worst:
        if not c:
            continue
        print(f"{f.split('/')[-1][:54]:<56}{n:>7}{c:>13}")
    print()
    print("examples:")
    for folder, name, k in examples:
        print(f"   {folder:<42} {name[:26]:<28} {k} conflicting records")
    print()
    print("These pages cannot be scored against a single answer, so they cap")
    print("what any measured accuracy figure can reach -- for this pipeline or")
    print("any other. Resolving them is a data-cleanup task on the client side.")


if __name__ == "__main__":
    main()

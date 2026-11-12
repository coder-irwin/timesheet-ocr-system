"""Diagnose WHERE day-status accuracy is lost.

Day status is 787 of 837 comparisons in the 49-page evaluation, so it dominates
the headline accuracy number. Before changing anything we need to know which of
these is happening:

    (a) the day row was never extracted          -> grid recovery problem
    (b) the row exists but status is empty       -> status inference problem
    (c) the status is present but wrong          -> which confusions, exactly?

Those need completely different fixes, and guessing between them is how the
last several attempts went wrong.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import xlrd                                                    # noqa: E402,F401
from rapidfuzz import fuzz, process                            # noqa: E402

from app import pipeline, preprocess                           # noqa: E402
from app.roster import Roster                                  # noqa: E402
from eval_100 import (ROOT, match_row, norm_status,            # noqa: E402
                      parse_truth)

BASE = Path(".")
TMP = BASE / "data" / "_diagdays"
TMP.mkdir(parents=True, exist_ok=True)
ROSTER = Roster.from_csv(BASE / "data" / "roster.csv")


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    import pypdfium2 as pdfium

    # Reuse the same folder discovery as the evaluation.
    from collections import defaultdict
    pairs: dict[Path, dict] = defaultdict(lambda: {"pdf": [], "xl": []})
    for p in ROOT.rglob("*"):
        if not p.is_file() or p.name.startswith(("~$", ".")):
            continue
        if p.suffix.lower() == ".pdf":
            pairs[p.parent]["pdf"].append(p)
        elif p.suffix.lower() in (".xls", ".xlsx"):
            pairs[p.parent]["xl"].append(p)

    usable = []
    for d, v in sorted(pairs.items()):
        if not (v["pdf"] and v["xl"]):
            continue
        truth = []
        for xl in v["xl"]:
            truth.extend(parse_truth(xl))
        if truth:
            usable.append((d, v["pdf"], truth))

    cause = Counter()
    confusion = Counter()
    examples = []
    n = 0

    for _d, pdfs, truth in usable:
        if n >= limit:
            break
        for pdf in pdfs:
            if n >= limit:
                break
            try:
                doc = pdfium.PdfDocument(str(pdf))
            except Exception:                                  # noqa: BLE001
                continue
            for pi in range(len(doc)):
                if n >= limit:
                    break
                try:
                    dest = TMP / f"{n:04d}.png"
                    doc[pi].render(scale=2).to_pil().save(dest)
                    preprocess.normalise_page(dest, dest)
                    out = pipeline.process_page(
                        dest, preprocess.file_sha256(dest), roster=ROSTER)
                except Exception:                              # noqa: BLE001
                    n += 1
                    continue
                n += 1
                rec = out["record"]
                row = match_row(rec, truth)
                if row is None:
                    continue

                got = {d_["day"]: d_ for d_ in (rec.get("days") or [])
                       if d_.get("day")}
                miss_rows = []
                for day, want in row["days"].items():
                    g = got.get(day)
                    if g is None:
                        cause["row_missing"] += 1
                        miss_rows.append(day)
                        continue
                    st = norm_status(g.get("status"))
                    if st is None:
                        cause["status_empty"] += 1
                    elif st == want:
                        cause["correct"] += 1
                    else:
                        cause["status_wrong"] += 1
                        confusion[f"{want}->{st}"] += 1

                if len(examples) < 3 and miss_rows:
                    examples.append({
                        "pdf": pdf.name, "page": pi + 1,
                        "rows_extracted": sorted(got),
                        "rows_expected": sorted(row["days"]),
                        "missing": miss_rows[:12],
                    })
            doc.close()

    tot = sum(cause.values()) or 1
    print("=" * 74)
    print(f"WHERE DAY-STATUS ACCURACY IS LOST   ({tot} day comparisons)")
    print("=" * 74)
    for k in ("correct", "row_missing", "status_empty", "status_wrong"):
        print(f"  {k:<16} {cause[k]:>5}  {cause[k]/tot:>6.1%}")
    print("\n  most common status confusions (truth -> ours):")
    for k, v in confusion.most_common(10):
        print(f"    {k:<12} {v}")
    print("\n  example pages with missing rows:")
    for e in examples:
        print(f"    {e['pdf']} p{e['page']}: extracted "
              f"{len(e['rows_extracted'])} rows, expected "
              f"{len(e['rows_expected'])}; missing e.g. {e['missing'][:8]}")
        print(f"      got days: {e['rows_extracted'][:15]}")


if __name__ == "__main__":
    main()

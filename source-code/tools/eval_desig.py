"""Score the DESIGNATION field end-to-end, in about a second.

Why this is separate from eval_fast
-----------------------------------
eval_fast calls aarvi_form.extract() directly, but the designation vocabulary
normalisation lives in pipeline.py, *after* extraction. So eval_fast reports
5/24 for designation while the real pipeline gets 15/31 -- the fast harness
cannot see the very step a vocabulary change modifies. Iterating on the
matcher therefore meant a 14-minute run per idea, which is how the field ended
up untouched for so long.

This replays the frozen OCR through extraction AND the vocabulary step, so a
matcher change is measurable immediately.

It also prints a REGRESSION panel. Designation has a trap the other fields do
not: the vocabulary now holds 444 entries harvested from the client's own
spreadsheets, and many are near-neighbours ('Safety Supervisor',
'Safety Officer', 'Safety Supervisor (Structural)', 'Site Supervisor'). A
matcher loosened until all 24 cases pass can easily be one that maps every
vaguely-safety-ish string to the most common entry. The panel checks that
distinct titles still resolve to themselves, and that junk still resolves to
nothing.

    python tools/eval_desig.py
"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rapidfuzz import fuzz                                      # noqa: E402

from app import aarvi_form, config, ocr_engine                  # noqa: E402
from app.vocab import Vocabulary                                # noqa: E402
from tools.eval_100 import match_row                            # noqa: E402
from tools.eval_fast import FROZEN                              # noqa: E402

# Distinct titles that must keep resolving to themselves. Drawn from the real
# harvested vocabulary and chosen to be mutually confusable -- these are the
# pairs a loosened matcher collapses first.
REGRESSION = [
    ("Safety Officer", "Safety Officer"),
    ("Site Supervisor", "Site Supervisor"),
    ("Technician", "Technician"),
    ("Cook", "Cook"),
    ("Engineer Gr. III (Civil)", "Engineer Gr. III (Civil)"),
    ("Engineer Gr. III (Mechanical)", "Engineer Gr. III (Mechanical)"),
    ("Asst. Gr. C (HR)", "Asst. Gr. C (HR)"),
    ("Operator Gr. B (IT)", "Operator Gr. B (IT)"),
    ("Scaffolding Inspector", "Scaffolding Inspector"),
    # OCR-plausible variants of a DIFFERENT title must not become the common one
    ("Safty Officer", "Safety Officer"),
    ("Sr. Store Keper", "Sr. Store Keeper"),
    ("Engineer Gr. III (Mechanicl)", "Engineer Gr. III (Mechanical)"),
    # Junk must stay junk. A confident wrong answer is this product's worst
    # output: it passes validation and reaches the invoice.
    ("1ds h", None),
    ("sds h", None),
    ("", None),
    ("9:00 AM", None),
    ("54788", None),
    ("April - 2026", None),
]


def vocab() -> Vocabulary:
    return Vocabulary.from_csv(config.DATA_DIR / "designations.csv",
                               "designation")


def score(verbose: bool = True,
          min_score: float | None = None,
          margin: float | None = None) -> dict:
    """min_score/margin are passed EXPLICITLY, never via module globals.

    Python binds default argument values at def time, so a sweep that sets
    app.vocab.DESIG_MIN and re-runs measures nothing at all -- it silently
    reports the same number for every setting. Threading them through is the
    only way a sweep of these two is real.
    """
    kw = {}
    if min_score is not None:
        kw["min_score"] = min_score
    if margin is not None:
        kw["margin"] = margin
    frames = pickle.loads(FROZEN.read_bytes())
    v = vocab()
    hit = tot = 0
    rows = []
    for f in frames:
        route = ocr_engine.route_from_profile(f["profile"])
        rec = aarvi_form.extract(f["boxes"], f["page_w"], f["page_h"],
                                 handwritten=(route == "needs_escalation"),
                                 row_rules=f["rules"])
        row = match_row(rec, f["truth"])
        if row is None or not row["designation"]:
            continue
        raw = (rec.get("designation") or "").strip()
        fixed, sc = v.normalise(raw, **kw) if raw else (None, 0.0)
        got = fixed or raw
        want = row["designation"].strip()
        ok = bool(got) and fuzz.token_sort_ratio(got.upper(), want.upper()) >= 78
        tot += 1
        hit += ok
        rows.append((ok, raw, fixed, round(sc, 1), want))

    # --- regression: does the matcher still tell titles apart? ---
    reg_ok = reg_tot = 0
    reg_rows = []
    for probe, expect in REGRESSION:
        fixed, sc = v.normalise(probe, **kw)
        good = (fixed == expect) if expect else (fixed is None)
        reg_tot += 1
        reg_ok += good
        reg_rows.append((good, probe, fixed, expect, round(sc, 1)))

    if verbose:
        print(f"DESIGNATION  {hit}/{tot} = {hit / max(tot, 1):.1%}   "
              f"(vocabulary: {len(v)} entries)\n")
        for ok, raw, fixed, sc, want in sorted(rows, key=lambda r: r[0]):
            mark = "OK  " if ok else "MISS"
            print(f"  {mark} {raw[:26]!r:<28} -> {str(fixed)[:24]:<26} "
                  f"({sc:>5}) want {want}")
        print(f"\nREGRESSION  {reg_ok}/{reg_tot} "
              f"{'PASS' if reg_ok == reg_tot else '*** FAILURES ***'}")
        for good, probe, fixed, expect, sc in reg_rows:
            if not good:
                print(f"  FAIL {probe[:24]!r:<26} -> {str(fixed)[:26]:<28} "
                      f"expected {expect} ({sc})")

    return {"hit": hit, "tot": tot, "acc": hit / max(tot, 1),
            "reg_ok": reg_ok, "reg_tot": reg_tot, "rows": rows}


if __name__ == "__main__":
    score()

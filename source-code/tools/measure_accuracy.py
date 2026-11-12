"""End-to-end PIPELINE accuracy — the number that actually matters.

This is deliberately different from tools/benchmark_ocr.py.

  benchmark_ocr.py  asks "could the OCR engine READ this value anywhere on the
                    page?"  -- a generous upper bound, used to choose an engine.

  this file         asks "did the FULL PIPELINE put the right value in the right
                    field?" -- which is what the client actually receives.

The second number is always lower, and it is the only one that should ever be
quoted to a client.

TWO MEASUREMENTS
----------------
1. EXACT FIELD ACCURACY on hand-labelled pages. Small sample, absolute truth.

2. SELF-CONSISTENCY over a large unlabelled sample. Every well-formed timesheet
   must satisfy its own arithmetic (rows sum to the stated total; present +
   leave + week-off + holiday = period length). We can therefore measure, at
   scale and with no labelling effort, how often the pipeline produces an
   internally coherent record. This is not the same as being correct -- a page
   can balance and still be wrong -- but a page that does NOT balance is either
   a extraction failure or a genuine defect, and either way it gets flagged.
   That is the "error detection" property, measured rather than asserted.
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from app import pipeline, preprocess                          # noqa: E402
from app.roster import Roster                                 # noqa: E402
from ground_truth import GROUND_TRUTH, critical_fields        # noqa: E402

ROSTER = Roster.from_csv(Path("data/roster.csv"))

ROOT = Path("Timesheet - Delhi 2026-2027")
SAMPLES = Path("samples")
OUT = Path("data/accuracy.json")

# Maps our hand-labelled ground-truth keys onto where the pipeline puts them.
FIELD_MAP = {
    "employee_name": ("record", "employee_name"),
    "employee_code": ("record", "employee_code"),
    "designation": ("record", "designation"),
    "client": ("record", "client"),
    "project": ("record", "project"),
    "location": ("record", "location"),
    "month_year": ("record", "period_label"),
    "present_days": ("summary", "total_present_days"),
    "total_man_hours": ("summary", "total_man_hours"),
    "total_ot_hours": ("summary", "total_ot_hours"),
    "weekly_off": ("summary", "total_weekly_off"),
    "public_holiday": ("summary", "total_public_holiday"),
    "leaves": ("summary", "total_leave_days"),
    "comp_off": ("summary", "total_comp_off"),
    # Samsung / KBR totals-row fields
    "total_normal_hours": ("summary", "total_man_hours"),
    "total_extra_hours": ("summary", "total_ot_hours"),
    "total_hours": ("summary", "total_hours"),
    "period": ("record", "period_label"),
    "week_end_date": ("record", "period_label"),
}


def _norm(v) -> str:
    if v is None:
        return ""
    s = str(v).strip().upper()
    # Numeric values compare by value, not by spelling: "04" == "4" == "4.0".
    try:
        f = float(s.replace(":", "."))
        return f"{f:g}"
    except ValueError:
        pass
    return " ".join(s.split())


def _name_match(got: str, want: str) -> bool:
    """Names count as correct if most tokens survive -- OCR routinely mangles
    one letter, and the roster match would resolve that in production."""
    g, w = _norm(got), _norm(want)
    if not w:
        return False
    if g == w:
        return True
    wt = [t for t in w.split() if len(t) > 2]
    if not wt:
        return False
    hit = sum(1 for t in wt if t in g)
    return hit / len(wt) >= 0.6


def measure_exact() -> dict:
    """Field-level accuracy on the hand-labelled pages."""
    rows = []
    per_field = Counter()
    per_field_total = Counter()

    for page_name, truth_all in GROUND_TRUTH.items():
        p = SAMPLES / page_name
        if not p.exists():
            continue
        truth = critical_fields(page_name)
        kind = truth_all.get("_kind", "?")
        h = preprocess.file_sha256(p)
        out = pipeline.process_page(p, h, roster=ROSTER)
        rec, summ = out["record"], (out["record"].get("summary") or {})

        correct, wrong, missing = 0, [], []
        for k, want in truth.items():
            if k not in FIELD_MAP:
                continue
            where, key = FIELD_MAP[k]
            got = rec.get(key) if where == "record" else summ.get(key)
            per_field_total[k] += 1

            if k in ("employee_name",):
                ok = _name_match(got or "", want)
            else:
                ok = _norm(got) == _norm(want) and _norm(got) != ""
            if ok:
                correct += 1
                per_field[k] += 1
            elif got in (None, ""):
                missing.append(k)
            else:
                wrong.append((k, got, want))

        total = sum(1 for k in truth if k in FIELD_MAP)
        rows.append({
            "page": page_name, "kind": kind,
            "correct": correct, "total": total,
            "accuracy": round(correct / total, 3) if total else 0.0,
            "wrong": [{"field": f, "got": str(g), "want": str(w)} for f, g, w in wrong],
            "missing": missing,
            "issues": len(out["issues"]),
            "blocking": sum(1 for i in out["issues"] if i["severity"] == "block"),
            "status": out["status"],
        })

    return {"rows": rows,
            "per_field": {k: [per_field[k], per_field_total[k]]
                          for k in per_field_total}}


def measure_consistency(limit: int = 60) -> dict:
    """Self-consistency over a larger unlabelled sample."""
    import pypdfium2 as pdfium

    pdfs = [p for p in sorted(ROOT.rglob("*.pdf")) if not p.name.startswith(".")]
    # Spread across clients rather than taking the first N (which would all be
    # one client and tell us nothing about generality).
    by_client: dict[str, list[Path]] = {}
    for p in pdfs:
        by_client.setdefault(p.relative_to(ROOT).parts[0], []).append(p)
    picked: list[Path] = []
    i = 0
    while len(picked) < limit:
        added = False
        for c, lst in by_client.items():
            if i < len(lst):
                picked.append(lst[i]); added = True
                if len(picked) >= limit:
                    break
        if not added:
            break
        i += 1

    tmp = Path("data/_acc_tmp")
    tmp.mkdir(parents=True, exist_ok=True)

    stats = Counter()
    detail = []
    t0 = time.time()
    for n, pdf in enumerate(picked, 1):
        try:
            doc = pdfium.PdfDocument(str(pdf))
            img = doc[0].render(scale=2).to_pil()
            doc.close()
            dest = tmp / f"{n:04d}.png"
            img.save(dest)
            preprocess.normalise_page(dest, dest)
            h = preprocess.file_sha256(dest)
            out = pipeline.process_page(dest, h, roster=ROSTER)
        except Exception as exc:                               # noqa: BLE001
            stats["error"] += 1
            detail.append({"pdf": str(pdf.relative_to(ROOT)), "error": str(exc)[:90]})
            continue

        rec = out["record"]
        summ = rec.get("summary") or {}
        days = rec.get("days") or []
        codes = {i["code"] for i in out["issues"]}

        stats["pages"] += 1
        stats["days_found"] += 1 if len(days) >= 10 else 0
        stats["name_found"] += 1 if rec.get("employee_name") else 0
        stats["code_found"] += 1 if rec.get("employee_code") else 0
        stats["summary_found"] += 1 if any(v for v in summ.values()) else 0
        # The two checksums we care about
        stats["sum_checkable"] += 0 if "summary_normal_missing" in codes else 1
        stats["sum_balanced"] += 1 if ("summary_normal_missing" not in codes
                                       and "normal_hours_sum_mismatch" not in codes) else 0
        stats["daycount_balanced"] += 0 if "present_days_mismatch" in codes else 1
        stats[out["status"]] += 1

        detail.append({
            "pdf": str(pdf.relative_to(ROOT)),
            "status": out["status"],
            "days": len(days),
            "name": rec.get("employee_name"),
            "issues": len(out["issues"]),
            "codes": sorted(codes)[:6],
        })
        if n % 10 == 0:
            print(f"  {n}/{len(picked)}  ({time.time()-t0:.0f}s)")

    return {"stats": dict(stats), "detail": detail,
            "seconds": round(time.time() - t0, 1), "n": len(picked)}


def main() -> None:
    print("=" * 92)
    print("1. EXACT FIELD ACCURACY  (hand-labelled pages, absolute truth)")
    print("=" * 92)
    ex = measure_exact()
    tot_c = sum(r["correct"] for r in ex["rows"])
    tot_t = sum(r["total"] for r in ex["rows"])
    for r in ex["rows"]:
        print(f"  {r['page'][:34]:<36} {r['kind']:<16} "
              f"{r['correct']}/{r['total']} = {r['accuracy']:>5.0%}   "
              f"status={r['status']}")
        for w in r["wrong"]:
            print(f"       WRONG  {w['field']}: got {w['got'][:30]!r} want {w['want'][:30]!r}")
        if r["missing"]:
            print(f"       MISSING {', '.join(r['missing'])}")
    print(f"\n  OVERALL FIELD ACCURACY: {tot_c}/{tot_t} = {tot_c/max(tot_t,1):.1%}")

    hw = [r for r in ex["rows"] if r["kind"] == "handwritten"]
    pr = [r for r in ex["rows"] if r["kind"].startswith("printed")]
    if hw:
        c = sum(r['correct'] for r in hw); t = sum(r['total'] for r in hw)
        print(f"    handwritten: {c}/{t} = {c/max(t,1):.0%}")
    if pr:
        c = sum(r['correct'] for r in pr); t = sum(r['total'] for r in pr)
        print(f"    printed    : {c}/{t} = {c/max(t,1):.0%}")

    print("\n  per field:")
    for k, (got, tot) in sorted(ex["per_field"].items(),
                                key=lambda x: x[1][0]/max(x[1][1],1)):
        print(f"    {k:<22} {got}/{tot} = {got/max(tot,1):>4.0%}")

    print("\n" + "=" * 92)
    print("2. SELF-CONSISTENCY  (large unlabelled sample across all clients)")
    print("=" * 92)
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 60
    co = measure_consistency(n)
    s = co["stats"]
    pages = max(s.get("pages", 0), 1)
    print(f"\n  pages processed: {s.get('pages',0)}  errors: {s.get('error',0)}  "
          f"({co['seconds']}s, {co['seconds']/max(co['n'],1):.1f}s/page)")
    for label, key in (("employee name found", "name_found"),
                       ("employee code found", "code_found"),
                       ("summary block found", "summary_found"),
                       ("day grid recovered (>=10 rows)", "days_found"),
                       ("row-sum checksum applicable", "sum_checkable"),
                       ("row-sum BALANCED", "sum_balanced"),
                       ("day-count BALANCED", "daycount_balanced")):
        v = s.get(key, 0)
        print(f"    {label:<34} {v:>4}/{pages} = {v/pages:>4.0%}")
    print("\n  status distribution:")
    for k in ("clean", "review_optional", "needs_review", "error"):
        if s.get(k):
            print(f"    {k:<20} {s[k]:>4} = {s[k]/pages:>4.0%}")

    OUT.write_text(json.dumps({"exact": ex, "consistency": co}, indent=2,
                              default=str), encoding="utf-8")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()

"""Summarise the v33 corpus eval (data/eval_corpus.json) and the 9,271-page
product pass (data/full_pass_v32.jsonl) into docs/revamp/02-V33-CORPUS-RESULTS.md
and data/v33_final_summary.json. Idempotent. `--dry` prints only.
Only quotes what is measured; the eval is against the client's Excel (conventions
included), the sample number is against the paper."""
import json, sys, collections, datetime
from pathlib import Path
DRY = "--dry" in sys.argv
E = Path("data/eval_corpus.json"); F = Path("data/full_pass_v32.jsonl")
out = {"generated": datetime.datetime.now().isoformat(timespec="minutes")}
lines = ["# v33 corpus results (measured, not projected)", "",
         f"Generated {out['generated']}. Pipeline v33-sample-fixes.", ""]
if E.exists():
    d = json.load(open(E)); rows = d["rows"]
    m = [r for r in rows if r.get("matched") and r.get("days_cmp")]
    def agg(sel):
        ok = sum(r["days_ok"] for r in sel); cmp = sum(r["days_cmp"] for r in sel)
        nm = sum(1 for r in sel if r.get("name_ok")); return ok, cmp, nm, len(sel)
    by = {ds: agg([r for r in m if r["dataset"] == ds]) for ds in ("Delhi", "HO", "Kolkata")}
    ok, cmp, nm, n = agg(m)
    imp = [r for r in m if r["days_ok"] < r["days_cmp"] or not r.get("name_ok")]
    fl = sum(1 for r in imp if r.get("flagged")); esc = len(imp) - fl
    pct = lambda a, b: round(100 * a / max(b, 1), 1)
    out["eval"] = {"matched_pages": n, "day_cmp": cmp, "day_ok": ok, "day_pct": pct(ok, cmp),
                   "name_pct": pct(nm, n), "by": {k: {"pages": v[3], "day_ok": v[0], "day_cmp": v[1], "day_pct": pct(v[0], v[1])} for k, v in by.items()},
                   "imperfect": len(imp), "flagged": fl, "escaped": esc, "version": Path("data/eval_corpus.version").read_text().strip() if Path("data/eval_corpus.version").exists() else "?"}
    lines += ["## Accuracy against the client's Excel (pages that have truth)", "",
              f"Checkpoint version: {out['eval']['version']}", "",
              "| dataset | matched pages | day rows right | day % |", "|---|---|---|---|"]
    for k, v in by.items():
        lines.append(f"| {k} | {v[3]} | {v[0]}/{v[1]} | {pct(v[0], v[1]) if v[1] else 'no truth'} |")
    lines += [f"| **combined** | **{n}** | **{ok}/{cmp}** | **{pct(ok, cmp)}** |", "",
              f"Name right on {pct(nm, n)}% of matched pages. Imperfect pages {len(imp)}: flagged {fl}, escaped unflagged **{esc}**.", "",
              "This number is bounded by the client's own conventions (LEAVE coded A vs L, worked Sunday W vs P, comp-off C) and by 9.2% self-contradicting truth rows; it is NOT the per-row accuracy against the paper, which is 95.6% on the 50-page hand-graded sample (D-045..D-051).", ""]
if F.exists():
    fp = [json.loads(l) for l in open(F) if l.strip()]
    st = collections.Counter(r.get("status") for r in fp)
    byds = collections.defaultdict(lambda: collections.Counter())
    tot = collections.Counter()
    for r in fp:
        for k in ("ok", "review", "must_fix", "n_days"): tot[k] += r.get(k, 0) or 0; byds[r["dataset"]][k] += r.get(k, 0) or 0
        byds[r["dataset"]]["pages"] += 1; byds[r["dataset"]][r.get("status") or "?"] += 1
    out["full_pass"] = {"pages": len(fp), "status": dict(st), "rows": dict(tot),
                        "by": {k: dict(v) for k, v in byds.items()}}
    lines += ["## Full product pass, every page of every PDF (no truth; what the reviewer will see)", "",
              f"Pages run: **{len(fp)}** of 9,271. Page status: " + ", ".join(f"{k} {v}" for k, v in st.most_common()), "",
              f"Day rows emitted: {tot['n_days']:,} = ok {tot['ok']:,} ({100*tot['ok']/max(tot['n_days'],1):.1f}%) / review {tot['review']:,} / must_fix {tot['must_fix']:,}", "",
              "| dataset | pages | ok rows | review | must_fix | pages needs_review | worker_error |", "|---|---|---|---|---|---|---|"]
    for k, v in byds.items():
        lines.append(f"| {k} | {v['pages']} | {v['ok']} | {v['review']} | {v['must_fix']} | {v.get('needs_review',0)} | {v.get('worker_error',0)} |")
    lines.append("")
txt = "\n".join(lines)
if DRY:
    print(txt); print(json.dumps(out, indent=1)[:600])
else:
    Path("docs/revamp/02-V33-CORPUS-RESULTS.md").write_text(txt)
    Path("data/v33_final_summary.json").write_text(json.dumps(out, indent=1))
    L = Path("docs/revamp/00-DECISION-LOG.md"); s = L.read_text()
    tag = "## D-052 · v33 corpus eval FINAL" if "eval" in out and "full_pass" not in out else "## D-053 · v33 full 9,271-page pass FINAL"
    if tag not in s and ("eval" in out or "full_pass" in out):
        body = txt.split("\n", 3)[3]
        L.write_text(s + f"\n\n{tag} · {out['generated']}\n" + body)
    print("written; keys:", list(out))

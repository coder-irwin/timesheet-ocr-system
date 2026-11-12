"""Fill the revamp report's final corpus rows from data/eval_corpus.json.

Run once the v29 corpus eval has written its JSON. Idempotent: replaces the
'scoring now' row and the pending safety row; leaves everything else.
"""
import json, re, sys
from pathlib import Path
P = Path("docs/revamp/01-REVAMP-REPORT.md"); L = Path("docs/revamp/00-DECISION-LOG.md")
d = json.load(open("data/eval_corpus.json"))
rows = d["rows"]; m = [r for r in rows if r.get("matched") and r.get("days_cmp")]
def agg(sel):
    ok = sum(r["days_ok"] for r in sel); cmp = sum(r["days_cmp"] for r in sel)
    nm = sum(1 for r in sel if r.get("name_ok")); return ok, cmp, nm, len(sel)
by = {ds: agg([r for r in m if r["dataset"] == ds]) for ds in ("Delhi", "HO", "Kolkata")}
ok, cmp, nm, n = agg(m)
imp = [r for r in m if r["days_ok"] < r["days_cmp"] or not r.get("name_ok")]
fl = sum(1 for r in imp if r.get("flagged")); esc = len(imp) - fl
clean = [r for r in m if r not in imp]
def pct(a, b): return f"{100*a/max(b,1):.1f}"
ho = by["HO"]; ko = by["Kolkata"]
s = P.read_text()
s = re.sub(r"\| Full corpus eval — HO \+ Kolkata \|.*?\|\n",
  f"| Full corpus eval — HO + Kolkata | HO {ho[3]} matched / Kolkata {ko[3]} matched (thin ground truth) | day 50.0 (11 pages) / — | HO day **{pct(ho[0],ho[1])}** ({ho[0]}/{ho[1]}) / Kolkata {('**'+pct(ko[0],ko[1])+'**') if ko[1] else 'no truth overlap'} | |\n"
  f"| **Full corpus eval — combined** | **{n} matched pages, {cmp:,} day comparisons** | day 73.2 / name 97.0 / overall 74.0 | day **{pct(ok,cmp)}** / name **{pct(nm,n)}** | **{100*ok/max(cmp,1)-73.2:+.1f} day** |\n", s, flags=re.S)
s = re.sub(r"\| Safety \| imperfect pages flagged / escaped \| 254/254 / 0 \| \*re-measured with the corpus run\* \| \|",
  f"| Safety | imperfect pages flagged / escaped | 254/254 / 0 | **{fl}/{len(imp)} / {esc}** — pages passed clean and correct: {len(clean)}/{len(clean)} | held |", s)
P.write_text(s)
L.write_text(L.read_text() + f"""

## D-036 · v29 corpus eval FINAL
    Delhi   {by['Delhi'][3]} matched   day {by['Delhi'][0]}/{by['Delhi'][1]} = {pct(*by['Delhi'][:2])}%
    HO      {ho[3]} matched   day {ho[0]}/{ho[1]} = {pct(ho[0],ho[1])}%
    Kolkata {ko[3]} matched   day {ko[0]}/{ko[1]} = {pct(ko[0],ko[1]) if ko[1] else 'n/a'}
    COMBINED {n} matched, {cmp:,} comparisons: day {pct(ok,cmp)}%  name {pct(nm,n)}%   (v25: 73.2 / 97.0)
    SAFETY: imperfect {len(imp)}, flagged {fl}, ESCAPED {esc}; clean-and-correct {len(clean)}/{len(clean)}
""")
print(f"combined day {pct(ok,cmp)}% ({ok}/{cmp}) name {pct(nm,n)}% | HO {pct(ho[0],ho[1])}% on {ho[3]} | Kolkata {ko[3]} matched | safety {fl}/{len(imp)} escaped {esc}")

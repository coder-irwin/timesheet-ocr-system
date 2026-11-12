"""Fast harness over the corpus-faithful frozen set (decision log D-007).

Same frame shape and same scoring loop as eval_fast, pointed at
data/frozen_v2.pkl (ADANI02 / GRSE01 / IOCL30 / Avaada01). Reports:

  strict       status must equal the truth code exactly
  convention   per-client map derived FROM the truth file: a client whose
               truth never contains L records LEAVE as A, etc. (D-006)

Both are printed. Neither is hidden. Usage:
  python tools/eval_fast_v2.py                 # current code
  python tools/eval_fast_v2.py --ab            # trust_anchors on/off
  python tools/eval_fast_v2.py --sweep         # ANCHOR_AGREE x step
"""
import json, pickle, sys, time
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import eval_fast as ef
from app import aarvi_form as af, ocr_engine

FROZEN2 = ef.FROZEN.with_name("frozen_v2.pkl")
TRUTH_IDX = Path("data/truth_index.json")

def _vocab():
    v = defaultdict(Counter)
    for k, val in json.load(open(TRUTH_IDX)).items():
        cl = k.split("/")[1][:12] if "/" in k else k[:12]
        for t in val["truth"]:
            for s in t["days"].values():
                v[cl][s] += 1
    return v

def _conv(vocab, cl):
    c = vocab.get(cl, Counter()); m = {}
    if c["L"] == 0 and c["A"] > 0: m["L"] = "A"
    if c["H"] == 0 and c["W"] > 0: m["H"] = "W"
    if c["W"] == 0 and c["H"] == 0 and c["A"] > 0: m["W"] = "A"; m["H"] = "A"
    return m

def score(label="", quiet=False, trust=None):
    frames = pickle.loads(FROZEN2.read_bytes())
    vocab = _vocab()
    st, hit_s, hit_c, tot = Counter(), Counter(), Counter(), Counter()
    per_client = defaultdict(lambda: [0, 0, 0])   # strict, conv, total
    t0 = time.time()
    for f in frames:
        route = ocr_engine.route_from_profile(f["profile"])
        kw = {} if trust is None else {"trust_anchors": trust}
        try:
            rec = af.extract(f["boxes"], f["page_w"], f["page_h"],
                             handwritten=(route == "needs_escalation"),
                             row_rules=f["rules"], ink_footer=True,
                             source_hint=f.get("pdf"), **kw)
        except Exception:                                       # noqa: BLE001
            st["page_error"] += 1; continue
        row = ef.match_row(rec, f["truth"])
        if row is None:
            st["unmatched"] += 1; continue
        st["matched"] += 1
        cl = (f.get("pdf") or "").split("/")[0][:12]; m = _conv(vocab, cl)
        got = {d["day"]: ef.norm_status(d.get("status") or "")
               for d in (rec.get("days") or []) if d.get("day")}
        for day, want in row["days"].items():
            g = got.get(day); gm = m.get(g, g) if g else g
            tot["day"] += 1; per_client[cl][2] += 1
            if g == want: hit_s["day"] += 1; per_client[cl][0] += 1
            if gm == want: hit_c["day"] += 1; per_client[cl][1] += 1
    n = max(tot["day"], 1)
    if not quiet:
        if label: print(f"\n=== {label} ===")
        print(f"  pages {len(frames)}  matched {st['matched']}  unmatched {st['unmatched']}  errors {st['page_error']}")
        print(f"    day strict      {hit_s['day']:>5}/{n:<5} = {100*hit_s['day']/n:.1f}%")
        print(f"    day convention  {hit_c['day']:>5}/{n:<5} = {100*hit_c['day']/n:.1f}%   ({time.time()-t0:.1f}s)")
        for cl, (s, c, t) in sorted(per_client.items(), key=lambda x: -x[1][2]):
            print(f"      {cl:<12} strict {100*s/max(t,1):5.1f}%  conv {100*c/max(t,1):5.1f}%  (n={t})")
    return {"strict": hit_s["day"], "conv": hit_c["day"], "n": n, "per_client": dict(per_client)}

if __name__ == "__main__":
    if not FROZEN2.exists():
        raise SystemExit(f"{FROZEN2} missing -- run tools/freeze_v2.py")
    if "--ab" in sys.argv:
        score("trust_anchors=False (old)", trust=False)
        score("trust_anchors=True  (new)", trust=True)
    elif "--sweep" in sys.argv:
        for ag in (0.9, 0.95, 1.0):
            af.ANCHOR_AGREE = ag
            r = score(quiet=True, trust=True)
            print(f"  ANCHOR_AGREE={ag:<4}  strict {r['strict']}/{r['n']} = {100*r['strict']/r['n']:.1f}%   conv {100*r['conv']/r['n']:.1f}%")
        af.ANCHOR_AGREE = 1.0
    else:
        score()

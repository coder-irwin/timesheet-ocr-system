"""Run the 50-page HO/Kolkata sample through the REAL upload path."""
from __future__ import annotations
import hashlib, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from app import pipeline, preprocess                             # noqa: E402
from app.roster import Roster                                    # noqa: E402

BASE = Path(__file__).parent.parent
OUT = BASE / "data" / "_hokol50"
M = json.loads((OUT / "manifest.json").read_text())
roster = Roster.from_csv(BASE / "data" / "roster.csv")
res = {}
t0 = time.time()
for m in M:
    img = BASE / m["img"]
    dst = OUT / f"n_{Path(m['img']).name}"
    preprocess.normalise_page(img, dst)
    try:
        out = pipeline.process_page(dst, hashlib.sha1(dst.read_bytes()).hexdigest(),
                                    roster=roster, source_hint=m["src"], force=True)
    except Exception as e:                                       # noqa: BLE001
        res[str(m["i"])] = {"error": str(e)[:120]}
        continue
    recs = [out["record"]] + [x["record"] for x in (out.get("more") or [])]
    res[str(m["i"])] = {
        "status": out.get("status"),
        "employees": [{
            "name": r.get("employee_name"),
            "period": r.get("period_label"),
            "days": {str(d.get("day")): (d.get("status") or "")
                     for d in (r.get("days") or []) if d.get("day")},
        } for r in recs],
    }
    print(f"  {m['i']:2} {m['dataset']:8} {m['client'][:30]:32} "
          f"{len(recs)} emp  {out.get('status')}  ({time.time()-t0:.0f}s)", flush=True)
(OUT / "run.json").write_text(json.dumps(res, indent=1))
print(f"\nwrote {OUT/'run.json'}  ({time.time()-t0:.0f}s)")

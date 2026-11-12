"""Which validation rule blocks pages that were read perfectly?

The corpus run found 150 pages whose every day matched the client's own
records, and which the system still refused to pass as clean. A reviewer who
is sent perfect pages learns to click through them, which is how a real
problem gets clicked through too. This counts the cause before anything is
changed.
"""
from __future__ import annotations
import collections, json, random, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import pypdfium2 as pdfium                                       # noqa: E402
from app import pipeline, preprocess                             # noqa: E402
from app.roster import Roster                                    # noqa: E402

BASE = Path(__file__).parent.parent
ROOTS = {"Delhi": BASE / "Timesheet - Delhi 2026-2027",
         "HO": BASE / "Timesheet - HO 2026-2027",
         "Kolkata": BASE / "Timesheet - KOLKATA 2026-2027"}
REFS = BASE / "data" / "_eval_tmp" / "perfect_but_flagged.json"
TMP = BASE / "data" / "_eval_tmp" / "fa"
N_PER_FOLDER = int(sys.argv[1]) if len(sys.argv) > 1 else 10

refs = json.loads(REFS.read_text())
by_folder = collections.defaultdict(list)
for r in refs:
    by_folder[r["pdf"].split("/")[0]].append(r)

rng = random.Random(7)
picked = []
for folder, rs in sorted(by_folder.items()):
    rng.shuffle(rs)
    picked.extend(rs[:N_PER_FOLDER])
print(f"probing {len(picked)} of {len(refs)} perfect-but-flagged pages "
      f"across {len(by_folder)} folders", flush=True)

roster = Roster.from_csv(BASE / "data" / "roster.csv")
TMP.mkdir(parents=True, exist_ok=True)
codes = collections.Counter()
blocking = collections.Counter()
examples: dict[str, str] = {}
# Why the rule fired matters more than that it fired. These count the two
# shapes seen by hand: the same number landing in two summary boxes, and a
# stated total standing against day rows that carry no hours at all.
shapes = collections.Counter()
statuses = collections.Counter()

for i, r in enumerate(picked, 1):
    pdf = ROOTS[r["dataset"]] / r["pdf"]
    try:
        doc = pdfium.PdfDocument(str(pdf))
        img = doc[r["page"] - 1].render(scale=2).to_pil()
        dest = TMP / f"{i:03d}.png"
        img.save(dest)
        preprocess.normalise_page(dest, dest)
        out = pipeline.process_page(dest, preprocess.file_sha256(dest),
                                    roster=roster, source_hint=str(pdf), force=True)
    except Exception as e:                                       # noqa: BLE001
        codes["PROBE_ERROR"] += 1
        continue
    statuses[out.get("status")] += 1
    rec = out["record"]
    summ = rec.get("summary") or {}
    days = rec.get("days") or []

    def num(v):
        import re as _re
        m = _re.search(r"\d+(?:\.\d+)?", str(v or ""))
        return float(m.group()) if m else None

    mh, ot = num(summ.get("total_man_hours")), num(summ.get("total_ot_hours"))
    if mh is not None and ot is not None and mh == ot:
        shapes["man_hours and ot_hours read as the SAME number"] += 1
    rows_nh = sum(num(d.get("normal_hours")) or 0 for d in days)
    rows_ot = sum(num(d.get("ot_hours")) or 0 for d in days)
    if mh is not None and rows_nh == 0:
        shapes["a total is stated but no day row carries normal hours"] += 1
    if ot is not None and ot > 0 and rows_ot == 0:
        shapes["OT total stated but no day row carries OT"] += 1
    if mh is None:
        shapes["no total hours read from the sheet at all"] += 1

    for iss in out.get("issues") or []:
        code = iss.get("code") or "?"
        sev = (iss.get("severity") or "").lower()
        codes[f"{sev:5} {code}"] += 1
        if sev == "block":
            blocking[code] += 1
            examples.setdefault(code, str(iss.get("message") or "")[:150])
    if i % 10 == 0:
        print(f"  {i}/{len(picked)}", flush=True)

print("\n=== every issue raised on pages that were read PERFECTLY ===")
for k, v in codes.most_common():
    print(f"   {v:4}  {k}")
print("\n=== page status of these PERFECTLY-READ pages ===")
for k, v in statuses.most_common():
    print(f"   {v:4}  {k}")
print("\n=== the SHAPE of the data behind those issues ===")
for k, v in shapes.most_common():
    print(f"   {v:4}  {k}")
print("\n=== BLOCKING issues -- these are what force 'needs review' ===")
for k, v in blocking.most_common():
    print(f"   {v:4}  {k}")
    print(f"         e.g. {examples.get(k, '')}")

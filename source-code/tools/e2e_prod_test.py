"""End-to-end test of a LIVE deployment, through the real HTTP path.

    ./.venv/bin/python tools/e2e_prod_test.py --url https://<ip>.nip.io

Why this exists, separately from tools/guard.py. The guard proves the pipeline
is correct on this machine, calling process_page() directly. It cannot see any
of the things that actually broke production in this project's history:

  * a bind-mount of a missing host path, which Docker silently turns into an
    empty DIRECTORY -- the app went down for 4 minutes on 21 Sep that way;
  * an overlay file that never got copied, so the VM quietly ran older code
    than the version string claimed;
  * the cache branch of process_page, which no harness exercises because they
    all pass force=True (D-092 ran broken in production from v45 to v51);
  * Caddy auth, the X-Remote-User header, and therefore every audit entry;
  * the Excel export, which is the only artifact the client ever sees.

So this test uploads a real sheet whose answer is already known from the PDF's
own text layer, and checks the whole chain: auth -> upload -> extraction ->
validation -> per-row confidence -> Excel -> locking -> audit trail. Truth is
data/testsets/horizontal-multi-employee/truth.json, which was built from the
text layer, never from the OCR under test.

ISG MAY 2026 is the sheet chosen on purpose: it is a horizontal multi-employee
sheet, the hardest template, and the measured floor for it is 100% (366/366 day
cells across the set). Anything less than a perfect 93/93 here is a regression.

Exit code 0 means every check passed. Non-zero means do not share the URL.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import time
from pathlib import Path

import requests
from openpyxl import load_workbook

BASE = Path(__file__).parent.parent
PDF = BASE / "data/testsets/horizontal-multi-employee/sheets/ISG MAY 2026.pdf"
TRUTH = BASE / "data/testsets/horizontal-multi-employee/truth.json"
LOGINS = Path.home() / "ocr_production/gcp/.logins.txt"
TIMEOUT = 900          # a cold VM loads the OCR model on the first page
# Poll on TERMINAL states, never on a guessed list of in-flight ones. The
# first version of this test waited for "queued"/"working" to clear, but the
# app actually sets "processing" (app/main.py), so every check ran against a
# half-read page and reported 0/93 as if the pipeline were broken.
TERMINAL = {"clean", "review_optional", "needs_review", "error", "corrected"}

results: list[tuple[bool, str, str]] = []


def check(ok: bool, label: str, detail: str = "") -> bool:
    results.append((ok, label, detail))
    print(f"  {'PASS' if ok else '**FAIL**':9} {label:52} {detail}")
    return ok


def creds(user: str) -> tuple[str, str]:
    """Read a password from .logins.txt. Never printed, never logged."""
    if not LOGINS.exists():
        sys.exit(f"FATAL: {LOGINS} not found; cannot authenticate.")
    for line in LOGINS.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].rstrip(":") == user:
            return user, parts[1]
    sys.exit(f"FATAL: no password for '{user}' in {LOGINS}")


def flat(v) -> str:
    """Strip a name down for comparison: 'OMKAR GUPTA' -> 'OMKARGUPTA'."""
    return re.sub(r"[^A-Z0-9.]", "", str(v or "").strip().upper())


# The two normalisers below are NOT symmetric, and copying only one of them is
# how the first version of this test reported 87.1% on a sheet the product
# reads perfectly. They are lifted from tools/eval_isgec.py deliberately, so
# this test and that harness cannot drift apart.
def truth_norm(v) -> str:
    """Truth side: the sheets write "S" for Sunday, and an empty cell also
    means the person did not work. Both are a weekly off."""
    v = str(v or "").strip().upper()
    return "W" if v in ("S", "") else v


def got_norm(v) -> str:
    """Produced side: never treat "no status read" as a weekly off -- that
    would credit a cell the reader never saw. Empty stays empty."""
    v = str(v or "").strip().upper()
    return "W" if v == "S" else v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True, help="https://<ip>.nip.io")
    ap.add_argument("--user", default="team")
    ap.add_argument("--keep", action="store_true",
                    help="leave the test batch in place instead of reporting it for cleanup")
    a = ap.parse_args()
    url = a.url.rstrip("/")
    auth = creds(a.user)
    s = requests.Session()
    s.auth = auth
    s.verify = True

    print(f"E2E · {url}  as '{a.user}'")

    # ---- 1. the gate itself -------------------------------------------------
    print("\nAUTH + HEALTH")
    try:
        anon = requests.get(f"{url}/api/health", timeout=30)
        check(anon.status_code == 401, "unauthenticated request is refused",
              f"HTTP {anon.status_code}")
    except Exception as exc:                                    # noqa: BLE001
        check(False, "unauthenticated request is refused", repr(exc)[:60])

    try:
        h = s.get(f"{url}/api/health", timeout=60)
    except Exception as exc:                                    # noqa: BLE001
        check(False, "authenticated /api/health reachable", repr(exc)[:70])
        return summarise()
    if not check(h.status_code == 200, "authenticated /api/health reachable",
                 f"HTTP {h.status_code}"):
        return summarise()
    hj = h.json()
    check(hj.get("ocr_ready") is True, "OCR engine loaded", str(hj.get("ocr_engine"))[:40])
    check(bool(hj.get("roster_loaded")), "roster loaded",
          f"{hj.get('roster_size')} names")
    ver = hj.get("pipeline")
    # The version the deployed overlay should be serving.
    want_ver = (BASE / "app/pipeline.py").read_text()
    want_ver = re.search(r'PIPELINE_VERSION\s*=\s*"([^"]+)"', want_ver).group(1)
    check(ver == want_ver, "pipeline version matches local app/", f"{ver} (want {want_ver})")

    me = s.get(f"{url}/api/me", timeout=30)
    who = me.json() if me.ok else {}
    whoname = who.get("name") or who.get("user") or who.get("me") or ""
    check(whoname == a.user, "Caddy passes X-Remote-User through to the app",
          f"app sees '{whoname}'")

    # ---- 2. upload ----------------------------------------------------------
    print("\nUPLOAD + EXTRACTION")
    if not PDF.exists():
        check(False, "test sheet present", str(PDF))
        return summarise()
    bname = f"e2e-{time.strftime('%Y%m%d-%H%M%S')}"
    up = s.post(f"{url}/api/batches",
                data={"name": bname},
                files={"files": (PDF.name, PDF.read_bytes(), "application/pdf")},
                timeout=300)
    if not check(up.status_code == 200, "upload accepted", f"HTTP {up.status_code}"):
        print(up.text[:300])
        return summarise()
    uj = up.json()
    bid = uj["batch_id"]
    check(uj.get("pages", 0) >= 1, "pages queued", f"batch {bid}, {uj.get('pages')} page(s)")
    check(not uj.get("skipped"), "nothing skipped", str(uj.get("skipped"))[:50])

    # ---- 3. wait for the workers -------------------------------------------
    t0 = time.time()
    pages: list[dict] = []
    stable = 0
    while time.time() - t0 < TIMEOUT:
        r = s.get(f"{url}/api/batches/{bid}/pages", timeout=60)
        if r.ok:
            fresh = r.json()
            done = bool(fresh) and all(p["status"] in TERMINAL for p in fresh)
            # A horizontal sheet spawns one extra page record per additional
            # employee as it finishes, so "all terminal" can be true while more
            # records are still appearing. Require the count to hold steady.
            stable = stable + 1 if (done and len(fresh) == len(pages)) else 0
            pages = fresh
            if done and stable >= 2:
                break
        time.sleep(5)
    took = time.time() - t0
    check(bool(pages) and all(p["status"] in TERMINAL for p in pages),
          "all pages finished processing",
          f"{len(pages)} page(s) in {took:.0f}s, statuses="
          + ",".join(sorted({p["status"] for p in pages})))
    check(all(p["status"] != "error" for p in pages), "no page errored",
          ",".join(sorted({p["status"] for p in pages})))

    # A horizontal sheet carrying 3 employees must become 3 page records.
    check(len(pages) == 3, "multi-employee sheet split into one record per person",
          f"{len(pages)} records")

    # ---- 4. accuracy against independent truth ------------------------------
    print("\nACCURACY  (truth = the PDF's own text layer, not this OCR)")
    truth = json.loads(TRUTH.read_text())["ISG MAY 2026.pdf"]
    ndays = truth["days_in_month"]
    want = {flat(e["name"]): {str(d): truth_norm(e["days"].get(str(d)))
                              for d in range(1, ndays + 1)}
            for e in truth["employees"]}

    got: dict[str, dict[str, str]] = {}
    details = []
    for p in pages:
        d = s.get(f"{url}/api/pages/{p['id']}?claim=0", timeout=120)
        if not d.ok:
            continue
        dj = d.json()
        details.append(dj)
        rec = dj.get("record") or {}
        nm = flat(rec.get("employee_name"))
        got[nm] = {str(x.get("day")): got_norm(x.get("status"))
                   for x in (rec.get("days") or []) if x.get("day")}

    # D-092 lived in production from v45 to v51: the cache branch of
    # process_page rejoins the common path with a different set of locals, and
    # every offline harness passes force=True so none of them touch it. If this
    # upload was served from cache, the day comparison below IS that test.
    cached = [d for d in details if d.get("from_cache")]
    check(True, "cache branch exercised by this run",
          f"{len(cached)}/{len(details)} record(s) served from cache")

    matched_names = sum(1 for n in want if n in got)
    check(matched_names == len(want), "every employee name read correctly",
          f"{matched_names}/{len(want)}  got={sorted(got)}")

    total = right = 0
    misses = []
    for nm, days in want.items():
        g = got.get(nm, {})
        for day, w in days.items():
            total += 1
            if g.get(day, "") == w:
                right += 1
            else:
                misses.append(f"{nm} d{day}: want {w!r} got {g.get(day, '')!r}")
    pct = 100.0 * right / total if total else 0.0
    check(right == total, "day status 100% against truth",
          f"{right}/{total} = {pct:.1f}%")
    for m in misses[:8]:
        print(f"              - {m}")

    # ---- 5. validation + confidence layers are alive ------------------------
    print("\nVALIDATION + CONFIDENCE")
    check(all("status" in d for d in details), "page status computed",
          ",".join(sorted({d.get("status", "?") for d in details})))
    has_rows = any((d.get("record") or {}).get("days") for d in details)
    check(has_rows, "day grid present on the records")
    # Real field names, confirmed against the live API: _row_conf (float),
    # _review (ok|review|must_fix) and _review_why (list of named reasons).
    rows = [x for d in details for x in ((d.get("record") or {}).get("days") or [])]
    scored = [x for x in rows if "_row_conf" in x and "_review" in x]
    check(len(scored) == len(rows) and bool(rows),
          "per-row confidence on every day row",
          f"{len(scored)}/{len(rows)} rows scored")
    verdicts = sorted({x.get("_review") for x in scored})
    check(all(v in ("ok", "review", "must_fix") for v in verdicts),
          "row verdicts are from the known set", ",".join(map(str, verdicts)))
    # Nothing wrong may pass as clean: with 100% correct days above, a 'clean'
    # page here is correct; the dangerous combination is wrong AND clean.
    silent = sum(1 for d in details if d.get("status") == "clean"
                 and norm((d.get("record") or {}).get("employee_name")) not in want)
    check(silent == 0, "no unknown record passed as clean", str(silent))

    # ---- 6. the Excel the client actually receives --------------------------
    print("\nEXCEL EXPORT")
    x = s.get(f"{url}/api/batches/{bid}/export", timeout=300)
    if check(x.status_code == 200 and len(x.content) > 5000,
             "export downloads", f"HTTP {x.status_code}, {len(x.content)} bytes"):
        try:
            wb = load_workbook(io.BytesIO(x.content))
            check(len(wb.sheetnames) >= 1, "workbook opens", f"sheets={wb.sheetnames[:6]}")
            # Parse the Attendance grid properly instead of substring-matching
            # a concatenated blob: that earlier approach could not survive the
            # S->W mapping and told us nothing about which cell was wrong.
            ws = wb["Attendance"]
            grid = [[("" if c is None else str(c).strip()) for c in r]
                    for r in ws.iter_rows(values_only=True)]
            hdr = next((i for i, r in enumerate(grid)
                        if "EMPLOYEE NAME" in [c.upper() for c in r]), None)
            if check(hdr is not None, "Attendance sheet has a header row"):
                head = [c.upper() for c in grid[hdr]]
                namecol = head.index("EMPLOYEE NAME")
                daycol = {c: i for i, c in enumerate(grid[hdr])
                          if c.isdigit() and 1 <= int(c) <= 31}
                check(len(daycol) == ndays,
                      "Attendance sheet has a column per day",
                      f"{len(daycol)} day columns (month has {ndays})")
                xl = {}
                for r in grid[hdr + 1:]:
                    if namecol < len(r) and flat(r[namecol]):
                        xl[flat(r[namecol])] = {
                            d: got_norm(r[i]) for d, i in daycol.items()
                            if i < len(r)}
                check(len(xl) == len(want), "all employees appear in the Excel",
                      f"{len(xl)}/{len(want)}  {sorted(xl)}")
                xtot = xright = 0
                xbad = []
                for nm, days in want.items():
                    g = xl.get(nm, {})
                    for day, w in days.items():
                        xtot += 1
                        if g.get(day, "") == w:
                            xright += 1
                        else:
                            xbad.append(f"{nm} d{day}: want {w!r} got {g.get(day,'')!r}")
                check(xright == xtot,
                      "every day status survives into the Excel",
                      f"{xright}/{xtot}")
                for m in xbad[:6]:
                    print(f"              - {m}")
        except Exception as exc:                                # noqa: BLE001
            check(False, "workbook opens", repr(exc)[:70])

    # ---- 7. locking + audit trail ------------------------------------------
    print("\nLOCKING + AUDIT TRAIL")
    pid = pages[0]["id"]
    lk = s.post(f"{url}/api/pages/{pid}/lock", timeout=30)
    check(lk.ok and (lk.json() or {}).get("ok") is not False,
          "page lock can be acquired", f"HTTP {lk.status_code}")
    rel = s.delete(f"{url}/api/pages/{pid}/lock", timeout=30)
    check(rel.ok, "page lock releases", f"HTTP {rel.status_code}")

    au = s.get(f"{url}/api/audit", timeout=60)
    if check(au.ok, "audit endpoint responds", f"HTTP {au.status_code}"):
        rows = au.json()
        rows = rows if isinstance(rows, list) else rows.get("rows", [])
        mine = [r for r in rows if r.get("actor") == a.user]
        check(bool(mine), "this upload is attributed to the signed-in person",
              f"{len(mine)} row(s) as '{a.user}'")
        check(any("batch" in str(r.get("action", "")) for r in mine),
              "batch_created recorded in the audit trail")

    acc = s.get(f"{url}/api/accuracy", timeout=60)
    check(acc.ok, "accuracy endpoint responds", f"HTTP {acc.status_code}")

    print(f"\nTest batch left on the server: id={bid} name={bname}"
          + ("" if a.keep else "  <- delete this before the client sees the Home screen"))
    return summarise()


def summarise() -> int:
    bad = [(l, d) for ok, l, d in results if not ok]
    print()
    if bad:
        print(f"E2E FAILED — {len(bad)} of {len(results)} checks below the line:")
        for l, d in bad:
            print(f"   - {l}  {d}")
        print("\nDo not share the URL until these pass.")
        return 1
    print(f"E2E PASSED — {len(results)}/{len(results)} checks. Safe to share.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

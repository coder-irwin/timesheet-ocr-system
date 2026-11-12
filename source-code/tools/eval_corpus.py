"""Full-corpus evaluation across Delhi, HO and Kolkata.

`eval_100.py` measures 49 pages in one dataset. This measures every PDF page
that has recoverable ground truth in any of the three, using tools/truth.py --
which parses 126 Excel files instead of 35.

WHY MATCHING IS DELIBERATELY STRICT
-----------------------------------
A workbook often holds the same employee on several sheets (different months
or sites), so one name can map to several different day-series. Picking any
one of them would manufacture errors -- or, worse, silently pick whichever
agrees with our own output, which is not measurement at all.

So when a name resolves to more than one CONFLICTING truth row, the page is
recorded as `ambiguous` and excluded from scoring. An honest denominator
matters more than a large one.

Usage:
    python tools/eval_corpus.py                  # everything (hours)
    python tools/eval_corpus.py --limit 60       # quick sample
    python tools/eval_corpus.py --dataset HO
"""
from __future__ import annotations

import json
import re
import sys
import time
import warnings
from collections import Counter, defaultdict
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from rapidfuzz import fuzz, process                            # noqa: E402

import truth as truthmod                                       # noqa: E402
from runstate import RunState                                  # noqa: E402
from app import pipeline, preprocess                           # noqa: E402
from app.roster import Roster                                  # noqa: E402

BASE = Path(__file__).parent.parent
ROOTS = {
    "Delhi": BASE / "Timesheet - Delhi 2026-2027",
    "HO": BASE / "Timesheet - HO 2026-2027",
    "Kolkata": BASE / "Timesheet - KOLKATA 2026-2027",
}
TMP = BASE / "data" / "_evalcorpus"
OUT = BASE / "data" / "eval_corpus.json"
# Per-page results appended as they are produced. A run over the whole corpus
# takes hours; losing all of it to an interrupted process is not acceptable,
# so every page is durable the moment it is scored and a restart resumes.
CKPT = BASE / "data" / "eval_corpus.jsonl"
ROSTER = Roster.from_csv(BASE / "data" / "roster.csv")


def _period_of(name: str | None):
    from app.reconcile import infer_period_from_source
    return infer_period_from_source(name)


def _disambiguate(rows: list[dict], pdf_period) -> list[dict]:
    """Narrow conflicting truth rows using the month each one came from.

    A workbook folder often holds the same employee for several months, so one
    name maps to several different day-series and the matcher (correctly)
    refuses to guess. But each truth row records the Excel file it came from,
    and that filename usually names its month -- as does the PDF's path. When
    exactly one candidate agrees with the PDF's month, that is the right row.

    This uses only metadata on BOTH sides. It never consults what the pipeline
    predicted, so it cannot flatter the result.
    """
    if not pdf_period or len(rows) < 2:
        return rows
    same = [r for r in rows if _period_of(r.get("source")) == pdf_period]
    return same or rows


def match_truth(rec: dict, truth: list[dict],
                pdf_period=None) -> tuple[dict | None, str]:
    """Return (row, reason). Refuses to guess between conflicting rows."""
    code = re.sub(r"[^A-Z0-9]", "", (rec.get("employee_code") or "").upper())
    if code:
        hits = [t for t in truth
                if re.sub(r"[^A-Z0-9]", "", (t["employee_code"] or "").upper()) == code]
        hits = _disambiguate(hits, pdf_period)
        uniq = {tuple(sorted(t["days"].items())) for t in hits}
        if len(uniq) == 1:
            return hits[0], "code"
        if len(uniq) > 1:
            return None, "ambiguous_code"

    name = " ".join((rec.get("employee_name") or "").upper().split())
    if not name:
        return None, "no_name"
    names = [t["employee_name"].upper() for t in truth]
    hits = process.extract(name, names, scorer=fuzz.token_sort_ratio, limit=5)
    if not hits or hits[0][1] < 80:
        return None, "below_threshold"
    top = hits[0][1]
    # Everything essentially as good as the best candidate.
    close = _disambiguate([truth[h[2]] for h in hits if top - h[1] < 5],
                          pdf_period)
    uniq = {tuple(sorted(t["days"].items())) for t in close}
    if len(uniq) > 1:
        return None, "ambiguous_name"
    return close[0], "name"


INDEX = BASE / "data" / "truth_index.json"


def collect(dsname: str) -> list[tuple[Path, list[Path], list[dict]]]:
    """Folders for one dataset, from the prebuilt index.

    Parsing the Excels inline cost minutes per run and made experimentation
    impractical; tools/build_truth_index.py does it once instead.
    """
    if not INDEX.exists():
        raise SystemExit("data/truth_index.json missing -- run: "
                         "python tools/build_truth_index.py")
    idx = json.loads(INDEX.read_text())
    out = []
    for folder, v in sorted(idx.items()):
        if v["dataset"] != dsname:
            continue
        # JSON has no integer keys: day 1 round-trips as "1". Left uncoerced,
        # every day lookup misses and the harness reports 0/736 correct --
        # which is how this was caught. Restore integer day numbers.
        tru = []
        for t in v["truth"]:
            t = dict(t)
            t["days"] = {int(k): val for k, val in t["days"].items()}
            tru.append(t)
        out.append((BASE / folder,
                    [BASE / p for p in v["pdfs"]],
                    tru))
    return out


def main() -> None:
    args = sys.argv[1:]
    limit = None
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    only = args[args.index("--dataset") + 1] if "--dataset" in args else None

    TMP.mkdir(parents=True, exist_ok=True)
    import pypdfium2 as pdfium

    if "--restart" in args and CKPT.exists():
        CKPT.unlink()

    # The checkpoint is only valid for the pipeline that wrote it. Without this
    # guard a resume silently blends pages scored under an older extractor with
    # new ones and reports the average as if it measured one thing -- which is
    # exactly what happened when v25 resumed 1,218 pages scored under v24.
    from app.pipeline import PIPELINE_VERSION
    stamp = CKPT.with_suffix(".version")
    if CKPT.exists():
        prev = stamp.read_text().strip() if stamp.exists() else "(unstamped)"
        if prev != PIPELINE_VERSION:
            print(f"checkpoint written by {prev}, now {PIPELINE_VERSION} "
                  f"-- discarding and rescoring from scratch", flush=True)
            CKPT.unlink()
    stamp.write_text(PIPELINE_VERSION)

    # Resume: anything already scored is replayed from the checkpoint rather
    # than recomputed.
    done: dict[tuple, dict] = {}
    if CKPT.exists():
        for line in CKPT.read_text().splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except Exception:                                  # noqa: BLE001
                continue
            done[(r["dataset"], r["pdf"], r["page"])] = r
        print(f"resuming: {len(done)} pages already scored", flush=True)
    ck = CKPT.open("a")

    # Total page count up front. Opening 457 PDFs costs about a minute and is
    # what makes the ETA a real number instead of a guess; a run this long is
    # unwatchable without one.
    total_pages = 0
    for _ds in ROOTS:
        if only and only.lower() != _ds.lower():
            continue
        for _d, _pdfs, _t in collect(_ds):
            for _p in _pdfs:
                try:
                    _doc = pdfium.PdfDocument(str(_p))
                    total_pages += len(_doc)
                    _doc.close()
                except Exception:                              # noqa: BLE001
                    pass
    if limit:
        # --limit is applied per dataset inside the loop, not across the run,
        # so the expected total is limit x however many datasets are in scope.
        n_ds = sum(1 for _ds in ROOTS
                   if not only or only.lower() == _ds.lower())
        total_pages = min(total_pages, limit * n_ds)
    print(f"{total_pages} pages to score", flush=True)
    RS = RunState(total_pages, "corpus accuracy", PIPELINE_VERSION, resumed=0)

    grand: dict[str, dict] = {}
    rows_out = []
    t0 = time.time()

    for dsname, root in ROOTS.items():
        if only and only.lower() != dsname.lower():
            continue
        if not root.exists():
            continue
        folders = collect(dsname)
        print(f"\n=== {dsname}: {len(folders)} folders with ground truth, "
              f"{sum(len(t) for _, _, t in folders)} truth rows ===", flush=True)

        st, hit, tot = Counter(), Counter(), Counter()
        n = 0
        for d, pdfs, tru in folders:
            for pdf in pdfs:
                if limit and n >= limit:
                    break
                try:
                    doc = pdfium.PdfDocument(str(pdf))
                    npages = len(doc)
                except Exception:                              # noqa: BLE001
                    st["pdf_error"] += 1
                    continue
                for pi in range(npages):
                    if limit and n >= limit:
                        break
                    n += 1
                    relpdf = str(pdf.relative_to(root))
                    key = (dsname, relpdf, pi + 1)

                    res = done.get(key)
                    _t_page = time.time()
                    _cached = res is not None
                    if res is None:
                        try:
                            img = doc[pi].render(scale=2).to_pil()
                            dest = TMP / f"{dsname}_{n:05d}.png"
                            img.save(dest)
                            preprocess.normalise_page(dest, dest)
                            out = pipeline.process_page(
                                dest, preprocess.file_sha256(dest), roster=ROSTER,
                                source_hint=str(pdf))
                        except Exception:                      # noqa: BLE001
                            res = {"dataset": dsname, "pdf": relpdf,
                                   "page": pi + 1, "matched": False,
                                   "reason": "page_error"}
                        else:
                            rec = out["record"]
                            row, why = match_truth(
                                rec, tru, _period_of(str(pdf)))
                            if row is None:
                                res = {"dataset": dsname, "pdf": relpdf,
                                       "page": pi + 1, "matched": False,
                                       "reason": why,
                                       "extracted_name": rec.get("employee_name")}
                            else:
                                got_days = {dd["day"]: (dd.get("status") or "")
                                            for dd in (rec.get("days") or [])
                                            if dd.get("day")}
                                # D-077. Score only the days this PAGE covers.
                                # A scanned sheet is often one week of a month
                                # the client's spreadsheet holds in full: a
                                # Garden Reach page carrying 24-31 July was
                                # compared against a truth row for 1-23 and
                                # scored 0 of 23, while being read perfectly.
                                # Sixteen pages were written off that way.
                                #
                                # The page's span is the first to the last day
                                # it actually recorded a status for. Within
                                # that span a missed day still counts against
                                # us -- this narrows WHAT is compared, never
                                # whether a real miss is forgiven.
                                filled = sorted(d for d, st in got_days.items()
                                                if str(st).strip())
                                if filled:
                                    lo, hi = filled[0], filled[-1]
                                    cmp_days = {d: w for d, w in row["days"].items()
                                                if lo <= d <= hi}
                                else:
                                    cmp_days = {}
                                if not cmp_days:
                                    res = {"dataset": dsname, "pdf": relpdf,
                                           "page": pi + 1, "matched": False,
                                           "reason": "no_date_overlap",
                                           "extracted_name": rec.get("employee_name")}
                                    ck.write(json.dumps(res) + "\n")
                                    ck.flush()
                                    RS.page(res, secs=(time.time() - _t_page),
                                            from_ckpt=False)
                                    rows_out.append(res)
                                    st[res["reason"]] += 1
                                    continue
                                d_ok = sum(
                                    truthmod.norm_status(got_days.get(day)) == want
                                    for day, want in cmp_days.items())
                                gname = " ".join(
                                    (rec.get("employee_name") or "").upper().split())
                                res = {
                                    "dataset": dsname, "pdf": relpdf,
                                    "page": pi + 1, "matched": True, "how": why,
                                    "extracted_name": rec.get("employee_name"),
                                    "truth_name": row["employee_name"],
                                    "days_ok": d_ok,
                                    "days_cmp": len(cmp_days),
                                    "days_on_page": len(filled),
                                    # The safety metric. A page the system
                                    # passes as clean while it actually holds a
                                    # wrong day is an ESCAPED error -- a wrong
                                    # value reaching an invoice with nobody
                                    # asked to look. That count, not raw
                                    # accuracy, is what must reach zero.
                                    "page_status": out.get("status"),
                                    "flagged": out.get("status") != "clean",
                                    "name_ok": bool(gname) and
                                    fuzz.token_sort_ratio(
                                        gname, row["employee_name"].upper()) >= 82}
                        ck.write(json.dumps(res) + "\n")
                        ck.flush()

                    RS.page(res, secs=(time.time() - _t_page) if not _cached else None,
                            from_ckpt=_cached)
                    rows_out.append(res)
                    if not res.get("matched"):
                        st[res.get("reason", "unmatched")] += 1
                        continue
                    st["matched"] += 1
                    tot["day_status"] += res["days_cmp"]
                    hit["day_status"] += res["days_ok"]
                    tot["employee_name"] += 1
                    hit["employee_name"] += bool(res.get("name_ok"))
                    if st["matched"] % 25 == 0:
                        print(f"    {dsname}: {n} pages, {st['matched']} matched, "
                              f"day {hit['day_status']}/{tot['day_status']}",
                              flush=True)
                if limit and n >= limit:
                    break
            if limit and n >= limit:
                break

        th = sum(hit[k] for k in tot)
        tt = sum(tot.values())
        grand[dsname] = {"pages": n, "stats": dict(st),
                         "hit": dict(hit), "tot": dict(tot)}
        print(f"  pages {n}  matched {st['matched']}  "
              f"unmatched {sum(v for k, v in st.items() if k != 'matched')}")
        for k in sorted(tot):
            print(f"    {k:<16} {hit[k]:>6}/{tot[k]:<6} = {hit[k]/max(tot[k],1):.1%}")
        print(f"    {'OVERALL':<16} {th:>6}/{tt:<6} = {th/max(tt,1):.1%}")

    # ---- combined ----
    ah, at = Counter(), Counter()
    for v in grand.values():
        ah.update(v["hit"]); at.update(v["tot"])
    th, tt = sum(ah[k] for k in at), sum(at.values())
    print("\n" + "=" * 70)
    print("COMBINED ACROSS ALL DATASETS")
    for k in sorted(at):
        print(f"    {k:<16} {ah[k]:>6}/{at[k]:<6} = {ah[k]/max(at[k],1):.1%}")
    print(f"    {'OVERALL':<16} {th:>6}/{tt:<6} = {th/max(tt,1):.1%}")
    print(f"    elapsed {time.time()-t0:.0f}s")

    # ---- the safety metric --------------------------------------------
    # Raw accuracy is not what protects an invoice run. What matters is
    # whether every page that is WRONG got flagged for a human. A page passed
    # as clean while holding a wrong day is an escaped error.
    scored = [r for r in rows_out if r.get("matched") and "flagged" in r]
    if scored:
        perfect = [r for r in scored if r["days_ok"] == r["days_cmp"]]
        imperfect = [r for r in scored if r["days_ok"] != r["days_cmp"]]
        escaped = [r for r in imperfect if not r["flagged"]]
        clean_passed = [r for r in scored if not r["flagged"]]
        print("\n" + "-" * 70)
        print("SAFETY: does every wrong page get flagged for review?")
        print(f"    pages scored                 {len(scored)}")
        print(f"    perfect                      {len(perfect)}")
        print(f"    imperfect                    {len(imperfect)}")
        print(f"    imperfect AND flagged        "
              f"{len(imperfect)-len(escaped)}/{len(imperfect)} = "
              f"{(len(imperfect)-len(escaped))/max(len(imperfect),1):.1%}"
              "   <- must be 100%")
        print(f"    ESCAPED (wrong, not flagged) {len(escaped)}"
              "   <- must be 0")
        if clean_passed:
            good = sum(1 for r in clean_passed
                       if r["days_ok"] == r["days_cmp"])
            print(f"    of pages passed clean, correct "
                  f"{good}/{len(clean_passed)} = "
                  f"{good/len(clean_passed):.1%}")
        for r in escaped[:10]:
            print(f"      escaped: {r['pdf'][-46:]} p{r['page']} "
                  f"{r['days_ok']}/{r['days_cmp']} status={r['page_status']}")

    OUT.write_text(json.dumps({"grand": grand, "rows": rows_out}, indent=1))
    RS.done()
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()

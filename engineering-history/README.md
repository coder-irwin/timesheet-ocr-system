# Timesheet Extraction &amp; Validation

Turns photographed/scanned handwritten timesheets into validated Excel, running
**entirely on one 16 GB Windows laptop** — no cloud, no API keys, no per-page cost.

```
Upload (PDF/images, batch)
   ↓
Preprocessing        deskew · flatten lighting · denoise · resize
   ↓
Page Routing         digital text | OCR-confident | needs escalation
   ↓
Extraction           printed-label anchors + learned column geometry
   ↓
Validation Engine    row-sum vs summary · day counts · OT bounds · roster match
   ↓
Review UI            ONLY flagged pages surface — image left, editable grid right
   ↓
Export               Excel (Timesheets / Daily / Exceptions)
   ↓
Audit log            who corrected what, when
```

---

## Run it

**Windows** — double-click `run.bat`. First run creates the environment and
installs dependencies (a few minutes); afterwards it starts in seconds and
opens `http://127.0.0.1:8077`.

**macOS / Linux** — `./run.sh`

Requires Python 3.11 or later (developed on 3.11–3.12; the current working
environment runs 3.14, and the Docker image pins 3.12). Nothing else — no GPU,
no database server, no Docker, no internet after install.

`requirements.txt` is the runtime set and is fully pinned. The documentation
tooling (`tools/build_tech_doc.py`, `tools/doc_diagrams.py`) additionally needs
`requirements-dev.txt`; it is deliberately separate so a deployment does not
carry a plotting library it never imports.

---

## The core idea

The extractor is unreliable and always will be — open handwriting OCR does not
reach the accuracy an invoice needs. **So the product is not the extractor. It
is the validation layer around it.**

Every timesheet is *self-validating*:

- day rows must sum to the stated monthly total
- present + leave + weekly-off + holidays must equal the period length
- OT must sit in a plausible band
- the employee must exist in the master roster

That converts an unreliable reader into a reliable **system**: we may not know
a field is right, but we always know when something is wrong.

**This is measured, not asserted.** On a real client page (`ADANI02 / ADN901
APR 2026`) the engine reported:

> *Counted 24 present days in the grid but the sheet states 26.*
> *Day 24: normal hours 42.0 is outside 0–12.*

Both are genuine defects in the client's own paperwork. Someone had already
noticed the first one and scrawled `25+3+2 = 30` at the bottom of the page by
hand. The system found it independently, in seconds, without being told.

### The metric that matters

Do not quote a single accuracy percentage. A 30-day sheet has ~120 fields; at
"95% accuracy" that is six wrong fields per page, and one wrong field freezes a
50-person invoice for months.

Commit instead to **error-detection rate** — and to this guarantee:

> **No page exits the system unvalidated.** Every branch of the pipeline ends in
> a record *and* a status. If any stage fails, the page is flagged with the
> reason attached. It is never dropped and never silently emitted as clean.

---

## Measured accuracy (pipeline v52, 15 Oct 2026)

Every figure below comes from a harness in `tools/`, and every one is
reproduced by `tools/guard.py` before anything ships. The full history,
including everything that was tried and rejected, is in
`docs/revamp/00-DECISION-LOG.md` (99 decisions).

**Against the paper** — a seeded 50-page random sample, every day row graded
by eye against the image, never used for tuning:

| What is being read | Result |
|---|---:|
| Day rows correct (1,157 rows) | **95.8%** (96.9% by the sheet's own convention) |
| Rows wrong AND carrying no flag | **2 of 1,157** |
| In / out clock times (own test set, 1,532 values) | **93.8%** |
| Shared multi-employee sheets (12 people, 366 days) | **100%** |
| Employee name | 30 of 31 on the guard harness; 98.6% corpus-wide |

**Against the client's own Excel** — the full corpus run, 1,218 pages,
8 Oct 2026: day rows **89.5%** (7,114 / 7,945), names 98.6%.

Read that number with its caveat. Six pages disagreed with the client's
records; all six were checked against the paper by hand and **five were the
spreadsheet being wrong, not the system** — four `L`-vs-`A` codings where the
sheet plainly says "Leave", and one where the sheet shows a worked shift
against a record marked weekly-off. The corpus figure therefore understates
the system by an amount this measurement cannot quantify.

It is also, structurally, a **Delhi number**: only 278 of 1,218 pages could be
scored at all (Kolkata 0 of 29, HO 7 of 247), because the same employee name
recurs across months and the matcher refuses to guess. Employee codes on the
sheets would fix this, and that is a client-side change, not a code change.

**Which number to quote.** Lead with **95.8% against the paper**. Present
89.5% as a cross-check against the client's own records, with the convention
caveat. Do not quote "95% on 9,000 pages": the 9,003-page production pass has
no truth to score against.

**Error detection** — what the product exists for. On the hand-graded sample,
2 rows in 1,157 were wrong without a flag. On the corpus run, 116 of 122
imperfect pages were flagged; the 6 that were not are the five
spreadsheet-error pages above plus one genuine escape, now closed (D-091).

---

## The floor, and how it is held

`tools/guard.py` is the gate. It runs the harnesses, hard-codes the measured
floor, and **fails** rather than printing a number:

```
./.venv/bin/python tools/guard.py            # ~25 min, the full floor
./.venv/bin/python tools/guard.py --quick    # ~2 min, structural only
```

It exists because every regression this project shipped had the same shape:
the number being watched improved while a number nobody was watching broke.
It has since caught three bad changes and one of its own author's incomplete
reverts (D-099) — a rejected experiment that read as reverted, because the
flag was off but two supporting edits were still in place.

It also pins the flags whose value **is** a measured decision, so a rejected
behaviour cannot drift back in unnoticed.

---

## What the real data looks like

Measured across the client's `Timesheet - Delhi 2026-2027` corpus:

| | |
|---|---|
| PDFs | 708 (≈2,527 pages) |
| Excel files | 289 |
| Client folders | 34 |
| Folders with **both** PDF and Excel | 63 → usable as ground truth |

Pages split three ways, and the routes differ by ~1,000× in cost:

| Route | Share | Cost/page | Accuracy |
|---|---:|---|---|
| Born-digital PDF | 8% | ~0 ms | 100% by construction |
| Printed form, typed values | 75% | ~6 s | very high |
| Printed form, handwritten values | 16% | slow path | the hard case |

**Only ~16% of pages need the expensive path.** That is what makes a CPU-only
laptop viable in production: roughly **8–23 machine-hours/month** instead of
100–250.

Three important facts the original plan got wrong, corrected by looking at the data:

1. It is **34 clients, not 12–15 templates** — but most share one base
   AARVI ENCON form, so it's far less work than 34 layouts.
2. **Most pages are typed, not handwritten.** Handwriting is the minority case.
3. **The output format was never unknown** — the client's own Excel files are
   sitting in the corpus next to the PDFs.

---

## Documentation

Written to be read start-to-finish as an explanation of *why*, not just *what*.
Every technical term is defined where it first appears.

| Doc | Contents |
|---|---|
| [`docs/03-page-routing.md`](docs/03-page-routing.md) | Two failed classifier designs; the OCR-confidence router that shipped |
| [`docs/04-ocr-engine-benchmark.md`](docs/04-ocr-engine-benchmark.md) | Engine head-to-head; why field-recall beats CER; why a VLM is not the default extractor |
| [`docs/05-analysis.md`](docs/05-analysis.md) | Corpus survey — what the client's data actually contains |
| [`docs/06-accuracy-improvements.md`](docs/06-accuracy-improvements.md) | The anchor/threshold fixes and their measurements |
| [`docs/07-scale-findings.md`](docs/07-scale-findings.md) | Throughput: worker pool sizing for 3,000 pages/day on 16 GB |
| [`docs/08-supervision-review.md`](docs/08-supervision-review.md) | Systematic audit that found the furniture-threshold bug |
| [`docs/09-real-accuracy.md`](docs/09-real-accuracy.md) | The 82.1% → 50.7% correction; scoring against the client's own Excel |
| [`docs/10-vlm-hybrid.md`](docs/10-vlm-hybrid.md) | VLM on header crops: the biggest single gain — and the fabricated-grid rejection |
| [`docs/11-row-bands.md`](docs/11-row-bands.md) | Row boundaries from printed rules; a mis-attributed win caught and corrected |
| [`docs/12-columns-and-calendar.md`](docs/12-columns-and-calendar.md) | Column recovery, the calendar-fitted ladder, self-reconciling pages |
| [`docs/13-designation.md`](docs/13-designation.md) | The vocabulary built from the wrong source; six matcher defects |
| [`docs/14-day-grid-push.md`](docs/14-day-grid-push.md) | 78.8% → 87.3%: the summary-pad amputation, upside-down Sundays, stated-total reconciliation |
| [`docs/15-showcase-iteration.md`](docs/15-showcase-iteration.md) | 89.1% → 90.2% fast-harness day: lone-letter statuses, W-bleed demotion, month-from-grid inference, roster completion, checksum sanity |
| [`docs/17-api-reference.md`](docs/17-api-reference.md) | **The HTTP surface** — all 20 endpoints, auth model, locking, caching, and what is deliberately *not* implemented |
| [`docs/revamp/00-DECISION-LOG.md`](docs/revamp/00-DECISION-LOG.md) | **The live record** — 99 decisions, every measurement, and every rejected change with the number that killed it |
| [`docs/revamp/01-NEXT-VERSION-BACKLOG.md`](docs/revamp/01-NEXT-VERSION-BACKLOG.md) | What is open, ranked, each item with its evidence |

---

## Layout

```
app/
  config.py         all tunables, env-overridable (TS_* variables)
  preprocess.py     PDF split, deskew, illumination flattening, resize
  ocr_engine.py     RapidOCR wrapper, confidence routing, printed-rule detection
                    NOTE: the text-direction classifier is OFF (D-073) -- it was
                    reading short numeric cells upside down ("09:00" -> "00:60")
  extract.py        template detection entry point
  aarvi_form.py     anchor extraction; row ladder; column recovery (the largest
                    module, 2.3k lines; thread-local anchor sets, D-093)
  form_profiles.py  per-client anchor sets (aarvi, samsung, kbr)
  generic_grid.py   structural reader for layouts no profile matches: finds the
                    day axis, reads multi-employee horizontal sheets
  split_fields.py   expands compound cells ("30 | 21") on layouts that pack them
  field_typing.py   type header values by CONTENT (month/name/title/code)
  vocab.py          closed-vocabulary matcher (444 client job titles)
  ordinal_match.py  ordinal/sequence matching helpers
  assignment.py     box-to-cell assignment costs
  roster.py         employee master matching (ambiguity flagged, not resolved)
  reconcile.py      self-repair from the sheet's stated totals + the calendar
  clocks.py         clock-grammar repair for in/out times -- PRESENT BUT OFF,
                    measured worse (D-072); kept with its measurement beside it
  vlm_header.py     local-VLM fallback for failed headers (optional, gated)
  pipeline.py       page -> validated record; content-addressed caching
  validate.py       THE VALIDATION ENGINE -- the business rules live here
  rowconf.py        per-row confidence + ok/review/must_fix with named reasons
  templates_spec.py per-template schemas; adding a template is a dict entry
  db.py             SQLite persistence, audit log, page locks
  eventlog.py       plain-language activity feed for the UI
  export_designs.py the 6 Excel layouts (incl. the full timesheet-detail sheet)
  export_excel.py   simple single-sheet export
  cloudcost.py      /cost page -- this GCP project's spend only
  main.py           FastAPI app + threaded worker pool (TS_WORKERS)
web/
  index.html        single-page review UI (no build step)
  cost.html         the hidden cost page
tools/
  guard.py          THE FLOOR -- run before shipping anything (see above)
  eval_fast.py      frozen-OCR replay for iterating on extraction (~1 s)
  eval_sample50.py  the 50-page hand-graded sample, real upload path
  eval_isgec.py     shared multi-employee sheets
  eval_times.py     in/out clock times against PDF text-layer truth
  eval_corpus.py    full corpus vs the client's Excel (~4 h, resumable)
  eval_100.py       older full-pipeline harness
  eval_desig.py     designation + 18-probe regression panel
  runboard.py       live dashboard for a long run (http://127.0.0.1:8099)
  build_*.py        test-set and roster builders
  doc_content_*.py  the .docx technical documentation, part by part
  build_tech_doc.py assembles TIMESHEET-TECHNICAL-DOCUMENTATION.docx
docs/
  revamp/00-DECISION-LOG.md       99 decisions, including every rejection
  revamp/01-NEXT-VERSION-BACKLOG.md  what is open, with evidence
  03..16-*.md                     research write-ups
Makefile            make run | fast | matrix | freeze | full | demo
```

---

## Design decisions worth knowing

**SQLite, not PostgreSQL.** A DB server is an install step, a support burden,
and something that can fail during a demo. 3,000 pages/month is nowhere near
SQLite's limits.

**Vanilla JS, no React.** No npm, no build step, no toolchain to break.

**Anchors, not fixed coordinates or grid cells.** Field positions shift with
every phone capture. Grid detection was built and measured — it works on flat
scans and *fails on curved pages* (52 rows but 2 columns on one warped sample).
Anchoring to the printed labels survives rotation, scale, crop and curl, because
it only relies on a value being *beside its own label*.

**Aggressive content-addressed caching.** Results are keyed by the hash of the
normalised page image. A page re-uploaded after a correction is served from
cache in **~1 ms** instead of re-running OCR — measured 9 of 12 pages on the
second run. The client's entire cost complaint came from a correction loop that
re-charged them for work already done.

**The extractor sits behind an interface.** Swapping the local OCR for a cloud
model later touches one module and nothing else.

**Don't fine-tune anything.** Multiple templates is a schema problem, not a
training problem.

---

## Known gaps

Current as of v52. The live list, with evidence, is
`docs/revamp/01-NEXT-VERSION-BACKLOG.md`.

- **Only Delhi can be measured against the client's records.** 278 of 1,218
  corpus pages score at all; Kolkata 0 of 29, HO 7 of 247. The same employee
  name recurs across months and the matcher refuses to guess between them.
  Fixing this needs **employee codes on the sheets** -- a client-side change,
  and the highest-value item on this list.

- **Some layouts yield no employee name** (292 of 1,218 corpus pages). These
  are not silent failures: every one is stopped with a blocking issue and the
  page's own heading quoted back to the reviewer (D-084). The cost is manual
  entry, not a wrong invoice. Four distinct families, diagnosed in the backlog:
  a leave-balance report that is not a timesheet at all, a statutory FORM D
  register marked with circled handwriting, and two multi-employee grids.

- **Three HO-layout fixes were built, measured, and rejected** (D-096..D-098):
  merged two-row "Weekly Off" cells, recorded hours beating a calendar remark,
  and a named `Present (Yes/No)` column. Each fixed its target page -- one
  recovered 25 days on a page that was almost entirely unread -- and each
  damaged the wider population or moved the unflagged-error count. They are
  kept behind flags with their measurements. **The lesson recorded there: a
  global rule is the wrong shape for these; `form_profiles` already supports
  per-layout anchors and that is where the next attempt belongs.**

- **Count checksums cannot detect a permutation.** The right number of each
  status on the wrong days reconciles perfectly with the sheet's own totals.
  Partly mitigated by a calendar check -- weekly offs cluster on one or two
  weekdays and scatter when rows drift (D-083) -- but nothing detects it in
  general.

- **Row merging on dense layouts.** Cells can return several rows' values at
  once ("4 4 4"), after which days slide against the calendar. Mitigated by
  refusing to call such rows confident (D-074); not fixed.

- **Designation is measured against a narrow set of titles.** Gated by an
  18-probe regression panel rather than a broad accuracy figure.

- **Excel export layouts are six sensible designs, not the client's own
  template.** The "Timesheet detail" sheet mirrors the paper form; mapping the
  client's exact format is still open.

- **Usage, not accuracy, is the real unknown.** As of 22 Oct 2026 the system
  has processed 197 pages in production, nearly all internal testing. Every
  accuracy figure here comes from archived corpora. No number yet reflects a
  client working at real volume on their own scans.

---

## Production

Live on GCP (project `timesheet-ocr-prod`, VM `timesheet-prod`,
`asia-south1-a`), behind Caddy with HTTPS and per-user logins. Operational
detail, including the deploy sequence and its traps, is in
`~/ocr_production/gcp/RUNBOOK.md`.

**Cost control.** The VM sleeps when nobody is using it:

```
gcp/autosleep.sh    cron every 15 min; stops the VM after 3 h with no HUMAN
                    action (read from the audit table, not web traffic -- the
                    public IP is probed constantly by scanners, and the UI
                    polls every 1.5 s, so neither is a usage signal)
gcp/wake.sh         starts it and waits until /api/health actually answers
```

Shutdown is clean: SQLite `wal_checkpoint(TRUNCATE)`, then `docker compose
stop`, then the instance stops. Verified across a full sleep/wake cycle with
the page table checksummed before and after -- identical. The boot disk is set
`auto-delete=false` and daily snapshots are retained for 7 days.


> **Status note — 22 Oct 2026.** This document was written at pipeline **v33**
> (20 Sep 2026). The architecture it describes is still accurate, but the
> measured figures in it are superseded. The system now runs **v52**; the
> current numbers are **95.8%** day rows against the paper, **93.8%** on in/out
> clock times, **100%** on shared multi-employee sheets, and **2 of 1,157** rows
> wrong without a flag.
>
> For current figures see `README.md`. For the full reasoning, including every
> rejected change, see `docs/revamp/00-DECISION-LOG.md` (99 decisions). For the
> HTTP surface see `docs/17-api-reference.md`.
>
> Subsystems added since v33 and not described below: `app/clocks.py`
> (clock-grammar repair, present but measured worse and switched off),
> `app/rowconf.py` (per-row confidence), `app/generic_grid.py` (structural
> reader for unknown layouts), `tools/guard.py` (the regression floor).

# Timesheet Extraction & Validation — Complete Technical Documentation

*For the client developer-team review. Covers the full pipeline, system
design, every major technology choice with its rationale and the measured
evidence behind it, the evaluation methodology, and the alternatives that
were tested and rejected. ~11,900 lines of Python/JS across 22 application
modules, 15 research write-ups in `docs/`.*

---

## 1. What this product is (and is not)

**The problem.** AARVI ENCON's site supervisors fill attendance timesheets by
hand at oil & gas refinery sites. Those sheets are retyped into Excel; a
typing slip becomes an invoice error, and one wrong field can freeze a
50-person invoice for months.

**The thesis.** Open-set handwriting OCR does not reach invoice-grade
accuracy, and never will on this paper quality. So the product is **not the
extractor — it is the validation system around it**. Every timesheet is
self-validating:

- day rows must sum to the totals the supervisor wrote at the bottom
- present + absent + leave + weekly-off + holidays must fit the month
- OT must sit in a plausible band
- the employee must exist in the master roster

This converts an unreliable *reader* into a reliable *system*: we may not
know a field is right, but we always know when something is wrong.

**The core guarantee** (this is the sentence to defend in any review):

> No page exits the system unvalidated. Every branch of the pipeline ends in
> a record AND a status. If any stage fails, the page is flagged with the
> reason attached — never dropped, never silently emitted as clean.

**The governing design principle**, discovered empirically and responsible
for every large accuracy gain:

> **Read the printed form, not the handwriting.** Row boundaries come from
> the form's printed rules, column positions from its fixed left-to-right
> order, row count from the calendar, repairs from the totals the supervisor
> signed, and identities/titles from the client's own spreadsheets. The
> handwriting is the unreliable part of these pages; the pre-printed
> structure is not.

---

## 2. Constraints (they explain half the design)

| Constraint | Consequence |
|---|---|
| Runs on a 16 GB, CPU-only Windows laptop | No GPU frameworks; ONNX Runtime; 4-worker cap sized to RAM, not cores |
| Fully local, zero cloud | No API-based OCR (Google Vision/Azure excluded by rule, not quality); verifiable: `grep -rn "https://" app/` returns nothing |
| Zero per-page cost | Content-addressed caching; the client's cost complaint was being re-charged for re-processing during correction loops |
| Government-adjacent client, worker PII | Data never leaves the machine; SQLite file + local folders; pull the network cable and nothing changes |
| ~3,000 pages/month, 34 client folders | Throughput target met at ~3 s/page × 4 workers ≈ 2.7 h for 3,000 pages |

---

## 3. Technology stack, with the "why" for each choice

| Layer | Choice | Why — and what it beat |
|---|---|---|
| OCR engine | **RapidOCR 3.9 (PP-OCRv6 ONNX)** on onnxruntime | Won a 5-engine head-to-head on the client's own pages (§10). PaddleOCR accuracy without installing PaddlePaddle — the classic Windows install failure. 3 model files, ~25–32 MB, CPU-only. |
| VLM (optional) | **Qwen3-VL 4B via Ollama** | Header-crop re-reads only. The 8B variant at Q4 wants ~12 GB and swaps on the target laptop. System runs fully without Ollama. |
| Web framework | **FastAPI + Uvicorn** | Async endpoints + a simple in-process worker pool; automatic request validation; no heavier framework needed for a single-box product. |
| Persistence | **SQLite** | A DB server is an install step, a support burden, and a demo-day failure mode. 3,000 pages/month is orders of magnitude inside SQLite's limits. Single file = trivial backup. |
| Frontend | **One HTML file, vanilla JS** | No npm, no build step, no toolchain to break on the client's machine. The entire review UI is `web/index.html`. |
| PDF | **pypdfium2** | Rasterises PDFs with no external binary dependency (no poppler install). |
| Imaging | **OpenCV (headless) + NumPy** | Deskew, illumination flattening, adaptive thresholding, printed-line detection. Code handles both cv2 4.x and 5.x HoughLinesP shapes. |
| Fuzzy matching | **RapidFuzz** | C++-backed scorers (token_sort, partial_ratio) used by anchors, roster, and vocabulary. |
| Excel | **openpyxl** (+ xlrd for the client's legacy .xls) | Generation of the 6 export designs; also reads the ground-truth Excels. |
| Total install | ~700 MB, dominated by onnxruntime | Exact pinned versions in requirements.txt; Python 3.11/3.12 target. |

**Explicitly rejected technologies** (each with measured or principled cause):
PostgreSQL (ops burden, zero benefit at this scale) · React/npm (build
toolchain risk on client hardware) · Tesseract 5 (2.6–7% on handwriting,
§10) · EasyOCR (64% + needs 5.9 GB RAM *per worker* — four workers cannot
fit in 16 GB) · cloud OCR APIs (violates the locality constraint) ·
fine-tuning any model (multiple templates is a schema problem, not a
training problem) · whole-page VLM extraction (563 s/page, 30% accuracy, and
a fabrication failure mode — §10).

---

## 4. End-to-end pipeline

```
Upload (PDF/JPG/PNG/TIFF, batch, multi-page PDFs split automatically)
   │
   ├─ 1. PREPROCESS   (app/preprocess.py)
   │     PDF split → deskew (≤15°, Hough) → illumination flattening
   │     → denoise/enhance → resize long edge to 1600 px
   │     → SHA-256 of the normalised image = the page's identity
   │
   ├─ 2. CACHE CHECK  (app/pipeline.py)
   │     key = page-hash + PIPELINE_VERSION → hit returns in ~1 ms
   │
   ├─ 3. OCR + ROUTE  (app/ocr_engine.py)
   │     RapidOCR → TextBoxes (text, confidence, geometry)
   │     confidence profile → route: confident | needs_escalation | unreadable
   │
   ├─ 4. EXTRACT      (app/aarvi_form.py — the core, ~1,600 lines)
   │     printed-label anchors → header fields
   │     printed row rules → row bands → calendar-fitted ladder
   │     column recovery from the form's fixed order
   │     content-based day-cell assignment; annotation detection (W/OFF, PH…)
   │
   ├─ 5. TYPE & CLEAN (app/field_typing.py)
   │     re-type header values by CONTENT (a month is a month wherever it sat)
   │     salvage codes glued to other text; drop form-phrase junk
   │
   ├─ 6. VLM FALLBACK (app/vlm_header.py — optional, gated)
   │     ONLY the header crop, ONLY when the header needs help
   │
   ├─ 7. RESOLVE      (app/vocab.py, app/roster.py)
   │     designation → 444-title closed vocabulary (client's own titles)
   │     identity → 1,863-employee roster (exact code, else guarded name)
   │
   ├─ 8. RECONCILE    (app/reconcile.py)
   │     self-repair from the sheet's own stated totals + the calendar
   │
   ├─ 9. VALIDATE     (app/validate.py — 23 rules)
   │     checksums, bounds, identity, sequence → BLOCK / WARN issues
   │     status: clean | review_optional | needs_review | error
   │
   ├─ 10. REVIEW UI   (web/index.html)
   │     only flagged pages surface; save → re-validate; audit every edit
   │
   └─ 11. EXPORT      (app/export_designs.py — 6 Excel designs)
```

### 4.1 Preprocessing — why these steps

Phone photos and photocopies dominate. Deskew is capped at 15° (beyond that
it's a different failure). Illumination flattening handles the shadow
gradient of a phone photo on a desk. Long-edge 1600 px is the measured
compromise: bigger reads handwriting slightly better but costs CPU
quadratically-ish. The **SHA-256 of the normalised image** (not the file!)
is the page identity — two scans of the same sheet with different filenames
hit the same cache entry.

### 4.2 Routing — why confidence, not a classifier

Two learned page-classifiers were built and rejected (docs/03). The shipped
router uses the OCR's own confidence profile: **p25** (the weakest quarter
of readings, where errors live) and **frac_low** (share of boxes below 0.8).
Thresholds (p25 ≥ 0.90, frac_low ≤ 0.15) sit in the measured *empty gap*
between typed pages (p25 ≥ 0.993) and handwritten ones (p25 ≈ 0.777), so
ordinary variation cannot flip a page across the boundary. Routing matters
because the paths differ ~1,000× in cost, and only ~16% of the real corpus
needs the expensive path.

### 4.3 Extraction — anchors, not coordinates; rules, not clustering

**Anchors.** Field positions shift with every phone capture, so fixed
coordinates fail. Grid-cell detection was built and measured: works on flat
scans, fails on curved pages (52 rows × 2 columns on one warped sample).
The shipped approach fuzzy-finds each **printed label** ("EMPLOYEE NAME",
"DESIGNATION") and reads the value beside it — survives rotation, scale,
crop and curl because it relies only on a value being next to its own label.

**Row bands from printed rules.** The form's horizontal rules are detected
in the image (engine-independent CV). Detected rules vote into a uniform
ladder of 26–31 rungs (a month has ≤31 rows — the calendar caps the
hypothesis space). The ladder is bounded below by the summary block's true
top edge. Measured: this replaced ink-clustering for +11 points; fixing the
lower bound (removing an over-cautious pad that amputated days 29–31 on
almost every page) was worth +7 more.

**Column recovery.** When a column header is unreadable, the column is
inferred as the gap between its known neighbours, using the form's fixed
left-to-right order. Rescued whole blank columns.

**Day-status inference.** The AARVI form has no status column; presence is
implied by hours, non-working days by annotations written across the row.
Order of evidence (each step measured): fuzzy weekday names ("Sinday",
"Sundoy", even upside-down "HOPUNS") → abbreviated markers (W/OFF, C/OFF,
P.H.) → explicit words (ABSENT…) → a lone status letter filling an entire
cell on a row with no work evidence → hours-based inference (either clock
time is enough; requiring both cost 11.4% of day cells).

### 4.4 Content-based typing — why geometry isn't trusted

On handwritten pages, values sit ~5 px from the *wrong* label and ~26 px
from their own. But the values themselves are unambiguous: "APRIL-2026" is a
month, "RAJEEV IYENGAR" is a name, "54789" is a code. `type_assign`
reclassifies header values by what they *are*. `salvage_code` recovers codes
glued to other text (13 of 24 codes on the frozen corpus were contaminated);
digit-less "codes" are dropped because 0 of 1,863 real roster codes are
letters-only.

### 4.5 The VLM's cage — the most important negative result

Asked to read a day grid, Qwen3-VL returned a **flawless-looking, entirely
fabricated 31-day series** — including four Sundays marked as worked.
Well-formed fake data passes validation; that is the worst possible failure
next to an invoice. Re-measured on demo day with a fixed harness (§10): the
VLM reads 74.8% of day cells but **17% of everything it asserts is wrong,
with no confidence signal on any of it**, at 19× RapidOCR's latency.

Rule shipped: **a VLM is used only where the answer is short and checkable**
— a header crop, only when the rule-based read failed, dual-pass, with
disagreement (not self-reported confidence) as the uncertainty signal, and a
summary pass that never sees the day grid so checksums can't validate
against themselves. All of that is in `config.py` as explicit flags
(`DUAL_PASS`, `INDEPENDENT_SUMMARY_PASS`, `VLM_HEADER_FALLBACK`).

### 4.6 Closed-set resolution — roster and vocabulary

Names and job titles are not free text; they come from closed sets the
client already maintains — in the Excel files sitting next to the scans.

- **Roster (1,863 employees)**: harvested by two tools — `build_roster.py`
  (list-style sheets) and `extend_roster.py` (attendance-grid sheets, reusing
  the eval harness's proven grid parser). Matching: exact code is
  authoritative; otherwise fuzzy name with **two safety gates** — minimum
  score 82 AND margin ≥6 over the nearest *different* name (duplicate rows of
  the same person don't count as ambiguity). A name match never overwrites a
  code read off the page, and only an exact code match may fill a missing
  code — measured incidents where anything looser attributed pages to the
  wrong employee. Below-threshold candidates surface as reviewer suggestions.
- **Vocabulary (444 titles, 13,453 employee rows)**: same idea for
  designations. Matcher passes: exact → embedded-title early exit (a title
  glued to a name) → abbreviation-aware ranking ("S.U.P" → Supervisor) →
  guarded token match → length-guarded substring → digit/bracket-noise strip
  retry. Every change gated by an 18-probe regression panel (distinct titles
  must resolve to themselves, junk must resolve to nothing).

### 4.7 Reconciliation — the sheet repairs itself

Pure arithmetic, no ML (`reconcile.py`). Sources of truth that cannot be
misread by OCR: the **stated totals** (short, label-anchored, read far more
reliably than 30 rows of script) and the **calendar** (weekly offs fall on
one weekday; the period line gives every day a weekday).

Repairs, in order, with their guards:
1. Fill empty rows on the off-weekday as W, up to the stated W/O count.
2. With ≥2 confirmed weekly offs, fill empty off-weekday rows even without a
   trusted count (a worked Sunday would carry hours and not be empty).
3. Demote a surplus W on a non-off weekday carrying work hours (an
   annotation bled across a row boundary) — count-based and adjacency-based.
4. If the month *name* is unreadable, infer the month from the year + the
   weekday footprint of the confirmed W days (unique candidate only).
5. Complete unreadable normal-hours cells on present days from the page's
   modal value — committed **only if the column then agrees with the stated
   total**, otherwise fully rolled back.
6. Stated counts that are impossible (P=97 in a 30-day month, C/O=170, OT
   above 24×days) are treated as unreadable, never as facts.

Universal rules: a stated total below 0.85 OCR confidence never drives a
repair (measured: a 'Nil' misread as '1' invented a public holiday);
everything repaired is marked `_inferred` and rendered as such in the UI and
the Excel; repairs are capped by the stated counts and the calendar.

### 4.8 Validation — the 23 rules

`validate.py` — the product's actual value. Severities: **BLOCK** (page
cannot pass) and **WARN**. The full rule set:

Identity: `identity_missing`, `identity_not_in_roster`,
`identity_ambiguous`, `identity_name_code_conflict`, `roster_absent`.
Sequence/structure: `day_unreadable`, `day_duplicate`, `row_count_mismatch`.
Per-day bounds: `normal_hours_out_of_band`, `ot_out_of_band` (0–12 h),
`present_but_zero_hours`, `nonworking_with_hours`, `status_unknown`,
`in_out_vs_hours_mismatch`.
Checksums vs the sheet's own summary: `normal_hours_sum_mismatch`,
`ot_sum_mismatch`, `man_hours_mismatch`, `present_days_mismatch`,
`leave_days_mismatch`, `mandays_vs_present_mismatch`,
`summary_normal_missing`, `summary_ot_missing`.
Extraction self-doubt: `pass_disagreement` + low-confidence field warnings.

Measurement-informed details: monthly sums compare with a **scale-aware
tolerance** (2% of stated — noise accumulates over ~30 hand-read cells;
a fixed 0.01 h tolerance flagged a 0.6% drift as a blocking error) while
integer day-counts stay exact; per-day sums ignore values >24 h (column-merge
artefacts — the per-day bounds rule flags the offending row instead of
poisoning the total); five-plus identical per-day warnings collapse into one
line naming the days (a wall of duplicates buries the one blocker — the
"reviewing takes as long as doing it" failure this engine exists to prevent).

Status mapping: any BLOCK → `needs_review`; only WARNs →
`review_optional`; nothing → `clean`. Saving a correction re-validates
immediately, so a fix that breaks a checksum is caught at save time, not at
invoice time.

### 4.9 Review UI

Single-page app: 4 steps (Upload / Processing / Review / Download). Scan
image left (zoomable), extracted record right, issues on top, roster
candidates as autocomplete on the name field. J/K page navigation, ⌘S save,
dirty-state guard, sticky save bar. A live plain-language activity feed
(`eventlog.py`) narrates what the system is doing — with an optional
"technical detail" toggle. Sessions survive a browser refresh (the latest
batch is restored). Every reviewer edit is written to the audit trail with
actor, field, old and new value.

### 4.10 Export — 6 Excel designs

One workbook or individually: **Timesheet detail** (the full sheet per
employee: every day row with in/out/hours/OT/remarks, weekday from the
calendar, inferred values italicised and labelled, the summary block, open
checks) · Invoice (finance; unverified rows tinted, "NO — review") ·
Attendance calendar (the grid shape the client's own sheets use; days beyond
the month's length stay blank) · Audit (every field with its OCR
confidence) · Payroll import (flat, machine-readable, no colour-as-meaning)
· Dashboard (rollups, issue frequencies). Design rules: nothing invented,
every cell traces to an extracted value or is blank; flagged rows stay
visibly tinted even after copy-paste; only vocabulary-verified designations
appear on finance sheets (raw junk stays on the detail/audit sheets where a
reviewer expects raw).

---

## 5. System design

**Process model.** One FastAPI process; a queue feeding **4 worker threads**
(sized to RAM on the 16 GB target — the OS takes 3–4 GB, each worker peaks
~1 GB with the ONNX models). Upload returns immediately; pages process
asynchronously; the UI polls batch state every 1.5 s and the event feed
every 1.2 s.

**Storage.** SQLite (WAL) with three tables: `batch`, `page` (record JSON,
issues JSON, status, image path, timings, cache flag), `audit` (append-only:
who did what to which field, when). Page images and normalised PNGs on
disk under `data/`.

**Caching.** Content-addressed: `sha256(normalised image)` +
`PIPELINE_VERSION` → cached record JSON. Re-uploading a corrected batch
costs ~1 ms/page. Bumping `PIPELINE_VERSION` (a string constant in
`pipeline.py`) invalidates everything at once — that is the deployment
story for extraction changes. A forced re-extract (`/reextract`) bypasses
and overwrites the entry.

**API surface** (all JSON): `GET /api/health` (includes the running
pipeline version — the defence against a server running stale code),
`POST /api/batches` (multipart upload), `GET /api/batches`,
`GET /api/batches/{id}/pages`, `GET /api/batches/{id}/export?design=`,
`GET/PUT /api/pages/{id}` (PUT = full-record save + re-validate + audit),
`POST /api/pages/{id}/reextract`, `GET /api/pages/{id}/image`,
`GET /api/log?after=seq` (activity feed), `GET /api/export-designs`,
`GET /api/audit`, `POST /api/roster`.

**Configuration.** Everything tunable is in `config.py`, every value
env-overridable (`TS_*`) so the same build runs on the demo laptop and a
bigger box with no code change.

**Failure containment.** OCR failure, extraction exception, VLM timeout,
unreadable page — every branch produces a page record with `status=error`
or a flagged record. Ollama absent → the fallback silently skips. The
worker pool survives individual page exceptions.

---

## 6. Data assets

| Asset | Size | Source | Build tool |
|---|---|---|---|
| Employee roster | 1,863 people (code, name, clients) | the client's own Excel files | `tools/build_roster.py` + `tools/extend_roster.py` |
| Designation vocabulary | 444 canonical titles across 13,453 employee rows | same | `tools/harvest_designations.py` |
| Ground truth | 49 scored pages → 1,090 field comparisons | folders where scan + the client's typed Excel coexist | parsed inside `tools/eval_100.py` |
| Frozen OCR corpus | 49 pages of RapidOCR output + printed-rule detections | one-time freeze | `tools/eval_fast.py --freeze` |

A key correction made mid-project: the first designation vocabulary was
harvested from OCR output (25 junk-prone entries). The client's own
spreadsheets had the real titles all along — rebuilding from that truth
source was worth +23 points on designation. Same lesson as the roster:
**the client's own data is the best model.**

---

## 7. Evaluation methodology (how we know any number)

**Two harnesses, two jobs:**

| | `tools/eval_fast.py` | `tools/eval_100.py` |
|---|---|---|
| Runtime | ~1 s | ~10–15 min |
| Covers | extraction logic on frozen OCR | the full pipeline incl. VLM, roster, vocab |
| Used for | choosing between hypotheses | the quotable number |

Plus `tools/eval_desig.py` (designation corpus + an 18-probe regression
panel) and `tools/demo_pack.py` (stages the best-reading pages with a
manifest recording each page's true score).

**The loop, enforced by a project skill file:** state the current number →
categorise failures before hypothesising → change ONE thing behind a flag →
measure → keep or revert → sweep parameters (a sharp spike means you're
fitting noise) → write rejections down. No accuracy claim without a harness
run.

**Metric choice.** Field-level accuracy against the Excel the client's own
team typed from the same scans — not CER (a page can be 99% CER-correct and
still fail on the one number that drives the invoice), and not self-reported
scores (an early version claimed 82.1% from five hand-picked pages; the
honest harness said 50.7%, which was published and worked from).

**Current measured state** (pipeline v33, 20 Sep 2026). Against the
paper, on a seeded 50-page sample graded by hand: **95.6%** of day rows
right (1,106 / 1,157 on 38 readable pages), 99.3% of errors flagged, names
~98%. Against the client's Excel on 292 truth-matched pages: day rows
**84.3%**, names 98.3%, 164 of 164 imperfect pages flagged, 0 escaped.
All 9,003 openable corpus pages run with 0 errors. Full account:
docs/revamp/01-REVAMP-REPORT.md §9; the earlier 88.2% (49 pages, Aug) is
superseded. (These figures are for engineering discussions; the product UI
deliberately shows no accuracy number — the demo argues from the checks.)

**Traps this project hit and now defends against** (docs + skill file):
cache serving stale results after code changes (bump PIPELINE_VERSION);
the server holding old code in memory (health endpoint reports the running
version); frozen inputs left at the last swept parameter value; a rejected
change re-entering as a side effect; implausibly *bad* results (a reasoning
VLM scored 0% because its answer was in the `thinking` channel — twice);
implausibly *good* results (fabrication); attributing a win to the wrong
change (one page cannot attribute a cause).

---

## 8. Security & deployment

- **Zero outbound connections** — verifiable live: `grep -rn "https://" app/`.
  No API keys anywhere. All models are files on disk.
- Worker attendance data (PII) never leaves the machine: SQLite + local
  folders under `data/`.
- Install: `run.bat` / `run.sh` — creates a venv, installs pinned
  dependencies (~700 MB), starts on `127.0.0.1:8077`. No Docker, no DB
  server, no internet after install.
- Hardware floor: 16 GB RAM, CPU-only, ~1 GB per worker + OS. Optional
  Ollama adds ~4.6 GB when in use.
- Throughput: ~3 s/page with 4 workers ≈ 2.7 h for 3,000 pages (the
  monthly volume), ~24× real-time headroom.

---

## 9. Accuracy engineering — what actually moved the number

| Change (all in docs/) | Mechanism | Worth |
|---|---|---|
| Printed row rules → banded ladder | rows from the form, not ink clustering | +11 pts |
| Summary-block true edge as grid bottom | stopped amputating days 29–31 | +7 pts |
| Roster resolution | closed-set identity | the single largest gain |
| Vocabulary from client's own sheets | closed-set titles | +23 pts designation |
| Column recovery by fixed order | survives unreadable headers | rescued whole columns |
| Calendar-fitted ladder (26–31 rungs) | month length caps hypotheses | fixed duplicated-day pages |
| Weekday periodicity + stated totals | self-repair | +1 pt corpus, decisive per-page |
| Month inference from W-day footprint | 'yue-2026' → June, uniquely | rescued calendar-less pages |
| Lone-letter status (guarded) | misplaced 'A' in a time column | catches real absences |
| Checksum sanity (0–24 clamp, scale tolerance, warn collapse) | signal over noise | reviewer time |

And the rejected changes, kept on record because they *measured worse*:
whole-page VLM (563 s, 30%) · VLM on the day grid (fabrication) ·
merged-row splitting (−2.9) · month-label rewriting (−2.6, destroyed
two-month labels) · full header bound (−6.4) · month-locked ladder (−3.8)
· blind ladder extension (−11.8) · including whole-row text in annotation
search (−1.8) · global trim-threshold raise (−1.8, rescoped per-field).

---

## 10. Engine benchmark (isolated lab, reproducible)

Lives in `~/ocr_bench_lab` (own folder, own port, never touches the
product). All engines read the same images of the same 10 handwritten
pages; box-producing engines are scored through the **identical** production
pipeline; truth is the client's own typed Excel (302 day cells).

| Engine | Day accuracy | Names | s/page | RAM |
|---|---:|---:|---:|---:|
| **RapidOCR + pipeline** | **100%** (81.1% on neutral ground) | 9/10 | 3.0 | 0.9 GB |
| Qwen3-VL 4B (VLM) | 74.8% — but 17% of its assertions are wrong, unflagged | 8/10 | 57.4 | ~4.6 GB |
| EasyOCR | 64.2% (best condition) | 1/10 | 6.5 | 5.9 GB |
| Tesseract 5 | 7.0% (best condition) | 0/10 | 0.5 | 0.1 GB |

A bias audit was run against our own methodology: a fairer line-grouped
Tesseract adapter (scored worse — concern refuted); a neutral-ground control
on non-demo pages *including the corpus's two worst* (ranking unchanged:
81.1 / 62.8 / 7.4); and a disclosed limitation — the pipeline is co-adapted
to RapidOCR's misread patterns, so this measures "engine inside this
product", which is the deployment-relevant question. Each engine ran in its
own process for clean RAM/time numbers. EasyOCR's 5.9 GB per worker is
disqualifying by itself: four workers cannot fit on the target machine.

---

## 11. Extension points (what the dev team will ask)

- **New client template**: an entry in `templates_spec.py` (per-template
  schema) + optionally `form_profiles.py` (per-client anchor labels). Most
  of the 34 clients share the base AARVI form.
- **Swap the OCR engine**: the extractor consumes `TextBox(text, conf,
  x0,y0,x1,y1)` lists — one adapter function per engine (the benchmark lab
  demonstrates Tesseract/EasyOCR adapters in ~20 lines each).
- **Bigger hardware / GPU later**: env vars only (`TS_VLM_MODEL` to the 8B
  model, worker count, page resolution). No code change.
- **The client's own invoice template**: their real format exists in the
  corpus; mapping it is an `export_designs.py` function (~100 lines,
  pattern established by six existing designs).
- **Code-based identity for more sites**: blocked on a data question, not
  code — several sites write a different code system on paper than in their
  typed Excel (measured on IOCL). Ask which code system each site uses.

## 12. Known limits (state them before they're asked)

1. Three of 34 scored pages remain structurally weak (58–65%): spurious row
   insertions cause drifting day offsets no global shift fixes. Diagnosed
   (docs/14); all three are *flagged*, not shipped.
2. Designation accuracy is only measured against one title (every scored
   ground-truth designation is "Safety Supervisor") — hence the regression
   panel as the real gate, and the ask for labelled pages from a second
   client folder.
3. 69% of pages auto-match a roster row; the rest need reviewer
   confirmation of identity (by design — wrong-person attribution is the
   worst error class).
4. Ground truth is 49 pages against a 2,500-page corpus — the scored subset
   is where the client's own typed Excel exists to compare against.
5. Remarks and free-text header fields (client/project/location) are kept
   as raw reads, flagged by confidence, not auto-corrected — there is no
   closed set to resolve them against.

---

*Companion documents: `README.md` (orientation), `DEMO-BRIEF.md` (demo
numbers and Q&A), `DEMO-SCRIPT.md` (the demo runbook), `docs/01–15` (the
full research trail, including every rejected idea and the measurement that
rejected it).*

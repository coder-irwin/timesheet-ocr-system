# Timesheet OCR — Handwritten Attendance Extraction

Reads handwritten and typed labour timesheets, checks the result against the
arithmetic the sheet states about itself, flags anything uncertain for human
review, and exports a payroll-ready Excel workbook.

Runs entirely on your own infrastructure. The text-recognition models are
bundled into the container and work with no network access at all. No document
or employee record is sent to any external service.

---

## The problem

Monthly labour timesheets arrive from contractor sites as scanned PDFs and
phone photographs, mostly filled in by hand, in dozens of layouts because every
client site uses its own form. Column orders differ, labels differ, some sheets
carry clock times and some do not, some hold one worker and some hold
thirty-three. Someone then types all of it into a spreadsheet for payroll —
slow work where a mistyped "P" instead of "A" pays a worker for a day they did
not work, and nothing in the spreadsheet looks wrong afterwards.

## What it does differently

It is not a bare OCR script. Roughly two thirds of the engineering is in the
layer that decides whether to *believe* what was read.

A timesheet is partly self-describing: it states its own monthly totals, it has
a month and therefore known weekday positions. The system reconciles the
day-by-day reading against those internal facts. A page is only marked `clean`
if it was read **and** corroborated — never merely because reading succeeded.

The design principle throughout:

> **When the system is not sure, it says so. It does not guess silently.**

An unread cell stays visibly unread. It is never filled with a plausible guess,
because a plausible guess is indistinguishable from a correct reading once it is
in a spreadsheet.

---

## Measured accuracy

Not one number, because one number would misrepresent both ends.

| Measurement | Result |
|---|---|
| Horizontal multi-employee sheets | **100%** (366/366 day cells), 0 unflagged errors |
| Same sheets, verified on a live deployment | **100%** (93/93), employee names 3/3 |
| 50-page hand-graded sample | **95.8%** (1,108/1,157), 2 unflagged, 0 missing |
| Handwritten pages only | **91.4%** (533/583), **0 unflagged** |
| Clock in/out times | **93.8%** (1,437/1,532) |
| Whole corpus | **89.5%** (7,114/7,945) |

Ground truth comes from sources independent of the system: the PDFs' own
embedded text layers, the client's own typed spreadsheets, or hand-grading
against the paper. Never from a previous run of the pipeline.

The figure that matters most is not in the table. On the 19 handwritten pages
above, **every page was flagged for review and zero wrong rows passed
unflagged.** That is the product's actual promise: a wrong value never reaches
a payroll run without a human being asked to look at it.

---

## How it works

Three stages, each existing because the one before it cannot solve the problem
alone.

**Pre-OCR** (`app/preprocess.py`) — rasterise, deskew within ±15°, flatten
shadow gradients, raise local contrast so faint pencil survives, resize.

**Reading** (`app/ocr_engine.py`, `app/aarvi_form.py`, `app/generic_grid.py`) —
text is located with RapidOCR / PP-OCRv6, then two readers compete. The profile
reader finds fields relative to *anchors* — printed labels discovered on each
page — so one profile tolerates sheets that are shifted, scaled or rotated. The
structural reader finds the day grid on a sheet it has never seen, with no
knowledge of the client, by locating the longest run of consecutive day numbers
and assigning each mark to its nearest column centre.

**Post-OCR** (`app/reconcile.py`, `app/validate.py`, `app/rowconf.py`) —
repair using the page's own stated facts, apply named validation rules, and
score every row individually with a confidence value and, where flagged, a
named reason.

Three recovery paths exist for pages that fail — re-reading at other
orientations, at higher resolution, and a locally-hosted vision model for
handwritten headers — all gated so a page that reads cleanly never pays for
them.

---

## Documentation

Fifteen documents, written to be read in order. `START-HERE.md` is the entry
point.

| Document | For |
|---|---|
| [`01-WHAT-THIS-IS.md`](01-WHAT-THIS-IS.md) | Anyone. No technical knowledge assumed |
| [`02-HOW-IT-WORKS.md`](02-HOW-IT-WORKS.md) | The architecture and the three stages |
| [`03-SETUP-ON-A-LAPTOP.md`](03-SETUP-ON-A-LAPTOP.md) | Running it, start to finish |
| [`04-DEPLOY-TO-CLOUD.md`](04-DEPLOY-TO-CLOUD.md) | Deploying to your own cloud project |
| [`05-WHAT-IT-COSTS.md`](05-WHAT-IT-COSTS.md) | Every cost line, with the arithmetic shown |
| [`06-ACCURACY-AND-TESTING.md`](06-ACCURACY-AND-TESTING.md) | **Read before changing extraction code** |
| [`07-CODE-REFERENCE.md`](07-CODE-REFERENCE.md) | Module by module |
| [`08-API-REFERENCE.md`](08-API-REFERENCE.md) | All 20 HTTP endpoints |
| [`09-DESIGN-DECISIONS.md`](09-DESIGN-DECISIONS.md) | Why things are as they are, and what was rejected |
| [`10-KNOWN-LIMITATIONS.md`](10-KNOWN-LIMITATIONS.md) | What it does not do |
| [`11-HOW-TO-EXTEND-IT.md`](11-HOW-TO-EXTEND-IT.md) | Adding a client form, an export, a rule |
| [`12-OPERATIONS-RUNBOOK.md`](12-OPERATIONS-RUNBOOK.md) | Day-to-day operation |
| [`14-VERIFICATION-RECORD.md`](14-VERIFICATION-RECORD.md) | What was tested, and what was not |

`engineering-history/` holds the development record, including a decision log
of 93 numbered decisions, each with the measurement that justified it. About a
third are things that were tried, measured, found worse, and turned off — kept
with their numbers so nobody rediscovers them.

---

## Quick start

```bash
cd source-code
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./run.sh                      # http://127.0.0.1:8077
```

Or with Docker, which needs no Python:

```bash
cd source-code
docker build -t timesheet-app:local .
docker run --rm -p 8077:8077 -v "$PWD/data:/data" timesheet-app:local
```

Full instructions, including the verification step, are in
[`03-SETUP-ON-A-LAPTOP.md`](03-SETUP-ON-A-LAPTOP.md).

---

## Not in this repository

**Employee data and client timesheets are deliberately excluded.** The system
was built against 13,791 real scanned sheets and a roster of 2,579 named
workers. That is personal data about real people and it is not published here.

Consequently this repository has no `data/` directory, no roster, and no test
fixtures — so the evaluation harnesses in `source-code/tools/` will not run
without them. Any real names and employee codes that appeared in code comments
or worked examples have been replaced with pseudonyms; where a worked example
demonstrates fuzzy name matching, both sides were regenerated and the scores
recomputed, so the examples remain internally truthful.

---

## Built with

Python · RapidOCR with PP-OCRv6 (processor-only, no graphics card required) ·
FastAPI · SQLite · openpyxl · pypdfium2 · Docker · Caddy. All open source, no
licence fees, no per-page charges. Exact pinned versions in
`source-code/requirements.txt`.

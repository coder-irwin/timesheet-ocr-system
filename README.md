# Timesheet OCR — Handwritten Attendance Extraction

Reads handwritten and typed labour timesheets, checks the result against the
arithmetic the sheet states about itself, flags anything uncertain for human
review, and exports a payroll-ready Excel workbook.

Runs entirely on your own infrastructure. The text-recognition models are
bundled into the container and work with no network access at all. No document
or employee record is sent to any external service.

---

# Contents

### Getting started
| | | |
|---|---|---|
| 1 | [**Running it on your computer**](RUN-IT-ON-YOUR-COMPUTER.md) | Every command to paste. 20 min |
| 2 | [**Putting it online**](PUT-IT-ONLINE.md) | Any provider, or your own hardware. ~1 hour |

### Understanding it
| | | |
|---|---|---|
| 3 | [What this is](01-WHAT-THIS-IS.md) | The problem, and what the accuracy figures honestly mean |
| 4 | [**Architecture**](ARCHITECTURE.md) | Diagrams, and the reason behind every technical choice |
| 5 | [How it works](02-HOW-IT-WORKS.md) | The three processing stages in detail |
| 6 | [Design decisions](09-DESIGN-DECISIONS.md) | Why things are as they are; what was tried and rejected |
| 7 | [Known limitations](10-KNOWN-LIMITATIONS.md) | What it does not do |

### Running it for real
| | | |
|---|---|---|
| 8 | [Local setup reference](03-SETUP-ON-A-LAPTOP.md) | The detailed version, including verification |
| 9 | [Deploy on Google Cloud](04-DEPLOY-TO-CLOUD.md) | Scripted, one command |
| 10 | [Deploy anywhere else](15-DEPLOY-TO-ANY-CLOUD.md) | AWS, Azure, VPS, bare metal |
| 11 | [What it costs](05-WHAT-IT-COSTS.md) | Every line, with the arithmetic shown |
| 12 | [Operations runbook](12-OPERATIONS-RUNBOOK.md) | Day-to-day running and troubleshooting |

### Working on the code
| | | |
|---|---|---|
| 13 | [**Accuracy and testing**](06-ACCURACY-AND-TESTING.md) | Read before changing any extraction code |
| 14 | [Code reference](07-CODE-REFERENCE.md) | Every module, generated from the source |
| 15 | [API reference](08-API-REFERENCE.md) | All 20 HTTP endpoints |
| 16 | [How to extend it](11-HOW-TO-EXTEND-IT.md) | Adding a form, an export, a rule |

### Record
| | | |
|---|---|---|
| 17 | [What was verified](14-VERIFICATION-RECORD.md) | What was tested — and what was not |
| 18 | [Package contents](13-PACKAGE-CONTENTS.md) | A map of every folder and file |
| 19 | [Reading order](START-HERE.md) | Suggested sequences for different purposes |
| 20 | `engineering-history/` | How it was built. 93 numbered decisions, each with its measurement |

If you read only one thing before promising anything to anyone, make it
[Known limitations](10-KNOWN-LIMITATIONS.md).

---

# The flow at a glance

What happens to a timesheet, and where each part lives.

| # | Stage | What happens | Code |
|---|---|---|---|
| 1 | **Arrives** | A PDF, scan or phone photo is uploaded — one, or a whole batch | `app/main.py` |
| 2 | **Made readable** | Rasterised, straightened within ±15°, shadows flattened, contrast raised so faint pencil survives, resized | `app/preprocess.py` |
| 3 | **Text located** | Every piece of text found with its position and confidence. Everything after this works from positioned text, never the image | `app/ocr_engine.py` |
| 4 | **Structure read** | Two readers compete: one finds fields relative to printed labels it discovers, the other finds the day grid on a sheet it has never seen | `app/aarvi_form.py`, `app/generic_grid.py` |
| 5 | **Rescued if failed** | Re-read rotated, at higher resolution, or with a local vision model for a handwritten header. Only pages that already failed pay this cost | `app/pipeline.py`, `app/vlm_header.py` |
| 6 | **Repaired** | The sheet states its own totals and has a known month; those facts repair the grid, or record a discrepancy | `app/reconcile.py` |
| 7 | **Checked** | Rows must sum to the stated total, no impossible day, identity must resolve, weekly offs must fall consistently | `app/validate.py` |
| 8 | **Scored** | Every row gets a confidence value, a verdict of ok / review / must_fix, and named reasons | `app/rowconf.py` |
| 9 | **Judged** | `clean`, `review_optional` or `needs_review`. `clean` requires corroboration, not merely successful reading | `app/pipeline.py` |
| 10 | **Reviewed** | A person sees the original beside the grid, uncertainty marked. Corrections are stamped with their name | `web/index.html`, `app/db.py` |
| 11 | **Exported** | One workbook: day detail, attendance grid, invoice, payroll import, dashboard, audit trail | `app/export_designs.py` |

Full diagrams in [Architecture](ARCHITECTURE.md).

---

# I want to…

| | Go to |
|---|---|
| See it working, fastest route | [`RUN-IT-ON-YOUR-COMPUTER.md`](RUN-IT-ON-YOUR-COMPUTER.md) |
| Put it online for my team | [`PUT-IT-ONLINE.md`](PUT-IT-ONLINE.md) |
| Add a login for someone | `deployment/user.sh`, or [`PUT-IT-ONLINE.md`](PUT-IT-ONLINE.md) §7 |
| Add a new client's form layout | `app/form_profiles.py` — recipe in [`11-HOW-TO-EXTEND-IT.md`](11-HOW-TO-EXTEND-IT.md) §1 |
| Add a validation rule | `app/validate.py` — [`11-HOW-TO-EXTEND-IT.md`](11-HOW-TO-EXTEND-IT.md) §3 |
| Change the Excel output | `app/export_designs.py` — [`11-HOW-TO-EXTEND-IT.md`](11-HOW-TO-EXTEND-IT.md) §2 |
| Change a default setting | `app/config.py`, or an environment variable — [`ARCHITECTURE.md`](ARCHITECTURE.md) §4 |
| Change what counts as `clean` | `app/pipeline.py`, `_page_status()` |
| Check I have not broken anything | `tools/guard.py` — run it before shipping |
| Check a deployment is sound | `tools/e2e_prod_test.py` — 32 checks over HTTPS |
| Cut the running cost | [`05-WHAT-IT-COSTS.md`](05-WHAT-IT-COSTS.md), then the stop/start table in [`PUT-IT-ONLINE.md`](PUT-IT-ONLINE.md) §8 |
| Find why a page read badly | `tools/probe_*.py` — [`12-OPERATIONS-RUNBOOK.md`](12-OPERATIONS-RUNBOOK.md) §4 |
| Know the real accuracy | [`06-ACCURACY-AND-TESTING.md`](06-ACCURACY-AND-TESTING.md) §7 |
| Know what was actually tested | [`14-VERIFICATION-RECORD.md`](14-VERIFICATION-RECORD.md) |
| Restore from a backup | `deployment/restore.sh` — [`12-OPERATIONS-RUNBOOK.md`](12-OPERATIONS-RUNBOOK.md) §3 |
| Take a backup | [`12-OPERATIONS-RUNBOOK.md`](12-OPERATIONS-RUNBOOK.md) §3 — and verify it |
| Understand a `D-0xx` flag I found in the code | Search its id in `engineering-history/revamp/00-DECISION-LOG.md` |
| Use a different cloud provider | [`15-DEPLOY-TO-ANY-CLOUD.md`](15-DEPLOY-TO-ANY-CLOUD.md) |

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

## Quick start

```bash
cd source-code
docker build -t timesheet-app:local .
mkdir -p data
docker run --rm -p 8077:8077 -v "$PWD/data:/data" timesheet-app:local
```

Then open **http://127.0.0.1:8077**.

Step by step, with every command explained and a troubleshooting table, in
[`RUN-IT-ON-YOUR-COMPUTER.md`](RUN-IT-ON-YOUR-COMPUTER.md).

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

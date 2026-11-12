# Index — the whole flow

A single map of this project: what happens to a timesheet from arrival to
payroll, which document covers each part, and which code does the work.

Use this when you know roughly what you want but not where it lives.

---

## 1. What happens to a timesheet

Each row is one stage. The module is where the work happens; the document
explains why it works that way.

| # | Stage | What happens | Code | Explained in |
|---|---|---|---|---|
| 1 | **Arrives** | A PDF, scan or phone photo is uploaded through the browser, one or a whole batch | `app/main.py` | `02-HOW-IT-WORKS.md` §1 |
| 2 | **Made readable** | Rasterised, straightened within ±15°, shadow gradients flattened, contrast raised so faint pencil survives, resized to 1,600px | `app/preprocess.py` | `02-HOW-IT-WORKS.md` §2 |
| 3 | **Text located** | Every piece of text found with its position and a confidence score. Everything after this works from positioned text, never the image | `app/ocr_engine.py` | `02-HOW-IT-WORKS.md` §3.1 |
| 4 | **Structure read** | Two readers compete: one finds fields relative to printed labels it discovers; the other finds the day grid on a sheet it has never seen | `app/aarvi_form.py`, `app/generic_grid.py` | `02-HOW-IT-WORKS.md` §3.2 |
| 5 | **Rescued if failed** | Re-read at other orientations, at higher resolution, or with a local vision model for a handwritten header. Only pages that already failed pay this cost | `app/pipeline.py`, `app/vlm_header.py` | `02-HOW-IT-WORKS.md` §3.3 |
| 6 | **Repaired** | The sheet states its own totals and has a known month. Those internal facts are used to repair the grid, or to record a discrepancy | `app/reconcile.py` | `02-HOW-IT-WORKS.md` §4.1 |
| 7 | **Checked** | Named rules: rows must sum to the stated total, no impossible day, identity must resolve, weekly offs should fall on a consistent weekday | `app/validate.py` | `02-HOW-IT-WORKS.md` §4.2 |
| 8 | **Scored** | Every day row gets a confidence value, a verdict of ok / review / must_fix, and named reasons | `app/rowconf.py` | `02-HOW-IT-WORKS.md` §4.3 |
| 9 | **Judged** | The page becomes `clean`, `review_optional` or `needs_review`. `clean` requires corroboration, not merely successful reading | `app/pipeline.py` | `02-HOW-IT-WORKS.md` §4.4 |
| 10 | **Reviewed** | A person sees the original beside the grid, with uncertainty marked and reasons given. Corrections are stamped with their name | `web/index.html`, `app/db.py` | `RUN-IT-ON-YOUR-COMPUTER.md` §6 |
| 11 | **Exported** | One workbook: day detail, attendance grid, invoice, payroll import, dashboard, audit trail | `app/export_designs.py` | `11-HOW-TO-EXTEND-IT.md` §2 |

**The rule that shapes all of it:** when the system is not sure, it says so.
An unread cell stays visibly unread — never filled with a plausible guess,
because a plausible guess is indistinguishable from a correct reading once it
is in a spreadsheet.

---

## 2. Reading paths

Pick the one that matches what you are trying to do. Each is a sequence, in
order.

### Just show me it working
1. `RUN-IT-ON-YOUR-COMPUTER.md` — 20 minutes, ends with it reading a sheet

### I need it online for my team
1. `RUN-IT-ON-YOUR-COMPUTER.md` — prove it works locally first
2. `PUT-IT-ONLINE.md` — any provider, or your own hardware
3. `12-OPERATIONS-RUNBOOK.md` — keeping it running
4. `05-WHAT-IT-COSTS.md` — what it will cost, and how to cut it

### I want to understand it
1. `01-WHAT-THIS-IS.md` — the problem and what the accuracy figures mean
2. `02-HOW-IT-WORKS.md` — the three stages
3. `09-DESIGN-DECISIONS.md` — why, and what was rejected
4. `10-KNOWN-LIMITATIONS.md` — what it does not do

### I am going to change the code
1. `02-HOW-IT-WORKS.md` — find the right stage
2. **`06-ACCURACY-AND-TESTING.md`** — not optional. Two serious regressions in
   this project both improved the metric they targeted and broke one nobody was
   watching
3. `07-CODE-REFERENCE.md` — find the module
4. `11-HOW-TO-EXTEND-IT.md` — the recipe for the common changes
5. `09-DESIGN-DECISIONS.md` — check it was not already tried and rejected

### I am taking over responsibility for it
1. `START-HERE.md` — the current state
2. `14-VERIFICATION-RECORD.md` — what was actually tested, and what was not
3. `10-KNOWN-LIMITATIONS.md` — the honest gap list
4. `engineering-history/revamp/01-NEXT-VERSION-BACKLOG.md` — what is open
5. `12-OPERATIONS-RUNBOOK.md` — and the "things not to do" section at the end

---

## 3. Every document

| Document | Lines | Covers |
|---|---|---|
| [`README.md`](README.md) | 180 | Overview and the task table |
| [`START-HERE.md`](START-HERE.md) | 109 | Entry point, reading order, current state |
| `INDEX.md` | 0 | This file — the whole flow in one map |
| [`RUN-IT-ON-YOUR-COMPUTER.md`](RUN-IT-ON-YOUR-COMPUTER.md) | 218 | Getting it working on one machine, every command given |
| [`PUT-IT-ONLINE.md`](PUT-IT-ONLINE.md) | 326 | Deploying to any provider or your own hardware |
| [`01-WHAT-THIS-IS.md`](01-WHAT-THIS-IS.md) | 160 | The problem, what it does, what the accuracy figures mean |
| [`02-HOW-IT-WORKS.md`](02-HOW-IT-WORKS.md) | 292 | Architecture and the three processing stages |
| [`03-SETUP-ON-A-LAPTOP.md`](03-SETUP-ON-A-LAPTOP.md) | 289 | Local setup in reference detail, including verification |
| [`04-DEPLOY-TO-CLOUD.md`](04-DEPLOY-TO-CLOUD.md) | 336 | Google Cloud, scripted, and the defects that route uncovered |
| [`05-WHAT-IT-COSTS.md`](05-WHAT-IT-COSTS.md) | 188 | Every cost line with the arithmetic shown |
| [`06-ACCURACY-AND-TESTING.md`](06-ACCURACY-AND-TESTING.md) | 285 | How accuracy is measured and the discipline that protects it |
| [`07-CODE-REFERENCE.md`](07-CODE-REFERENCE.md) | 363 | Every module, generated from the source |
| [`08-API-REFERENCE.md`](08-API-REFERENCE.md) | 175 | All HTTP endpoints, generated from the code |
| [`09-DESIGN-DECISIONS.md`](09-DESIGN-DECISIONS.md) | 213 | Why things are as they are; what was tried and rejected |
| [`10-KNOWN-LIMITATIONS.md`](10-KNOWN-LIMITATIONS.md) | 201 | What the system does not do |
| [`11-HOW-TO-EXTEND-IT.md`](11-HOW-TO-EXTEND-IT.md) | 230 | Adding a client form, an export, a validation rule |
| [`12-OPERATIONS-RUNBOOK.md`](12-OPERATIONS-RUNBOOK.md) | 260 | Day-to-day operation and troubleshooting |
| [`13-PACKAGE-CONTENTS.md`](13-PACKAGE-CONTENTS.md) | 109 | A map of every folder and file |
| [`14-VERIFICATION-RECORD.md`](14-VERIFICATION-RECORD.md) | 163 | What was tested before handover, and what was not |
| [`15-DEPLOY-TO-ANY-CLOUD.md`](15-DEPLOY-TO-ANY-CLOUD.md) | 330 | Provider-neutral deployment reference |
| | **4,427** | |

`engineering-history/` holds the development record: 24 documents, including a
decision log of 93 numbered decisions each carrying the measurement that
justified it. About a third are things tried, measured, found worse and turned
off — kept with their numbers so nobody rediscovers them.

---

## 4. The code

### Application — `source-code/app/`

| Module | Lines | What it does |
|---|---|---|
| `main.py` | 560 | FastAPI application: upload -> extract -> validate -> review -> export. |
| `config.py` | 83 | Central configuration. Everything is env-overridable so the same build runs on the 16GB CPU-only |
| `db.py` | 320 | SQLite persistence + audit log. |
| `eventlog.py` | 66 | A plain-language activity feed for the UI. |
| `preprocess.py` | 322 | Page preprocessing: PDF/image in, one normalised PNG per page out. |
| `ocr_engine.py` | 418 | OCR + spatial layout reconstruction. |
| `aarvi_form.py` | 2405 | Anchor-based field extraction for the AARVI ENCON timesheet family. |
| `generic_grid.py` | 578 | Find the day grid on ANY timesheet, without knowing the client. |
| `form_profiles.py` | 234 | Template profiles — one anchor set per form family. |
| `templates_spec.py` | 125 | Per-template field schemas. |
| `assignment.py` | 122 | 2-D assignment of value boxes to label anchors. |
| `ordinal_match.py` | 164 | Ordinal (sequence) matching of header labels to their values. |
| `field_typing.py` | 325 | Content-based field typing. |
| `split_fields.py` | 118 | Multi-value cell parsing. |
| `vocab.py` | 325 | Closed-vocabulary correction. |
| `vlm_header.py` | 203 | VLM fallback for the header block. |
| `extract.py` | 386 | Extraction: page image -> structured record. |
| `pipeline.py` | 1151 | The processing pipeline: one page in, a validated record out. |
| `reconcile.py` | 807 | Repair the day grid using facts the page already states about itself. |
| `validate.py` | 655 | Validation engine. |
| `rowconf.py` | 227 | Per-row confidence and review flags: the post-OCR evaluation layer. |
| `clocks.py` | 312 | Clock-time reading: grammar repair and sheet consensus for in/out times. |
| `roster.py` | 143 | Employee master roster matching. |
| `export_designs.py` | 679 | Six Excel export designs. |
| `export_excel.py` | 161 | Excel export. |
| `cloudcost.py` | 147 | Hidden cost page: what this project costs on Google Cloud, this month and last. |
| | **11,036** | across 26 modules |

### Tooling — `source-code/tools/`

| Script | Use it to |
|---|---|
| `guard.py` | **Run before shipping any accuracy change.** 16 checks; fails rather than printing a number |
| `e2e_prod_test.py` | Verify a live deployment. 32 checks over HTTPS |
| `eval_fast.py` | Score an extraction change in about a second |
| `eval_isgec.py` | Score the horizontal multi-employee sheets |
| `eval_sample50.py` | Score against the hand-graded sample |
| `eval_times.py` | Score clock in/out times |
| `eval_corpus.py` | Score everything, all regions |
| `probe_*.py` | Diagnose why a specific page or rule is failing |
| `truth*.py`, `*_truth.py` | Build ground truth from independent sources |

78 scripts in total. Most were written to answer one question during
development and are kept because they document how a number was arrived at.
Full list in `07-CODE-REFERENCE.md`.

### Deployment — `deployment/`

| Script | Use it to |
|---|---|
| `prepare-deploy.sh` | Arrange this repository into the layout a server expects. **Run first** |
| `setup-server.sh` | One command, run on the server: installs everything, sets your login, starts it |
| `deploy_gcp.sh` | Create an entire Google Cloud environment. Google Cloud only |
| `restore.sh` | Restore data and the application overlay onto a server. **Required after `deploy_gcp.sh`** |
| `wake.sh` | Start a stopped Google Cloud machine and wait until it is ready |
| `user.sh` | Add, remove and list logins |
| `autosleep.sh` | Stop the machine after three hours idle. Ships disabled |
| `Caddyfile`, `docker-compose.prod.yml`, `overlay/` | The production configuration. Provider-neutral |

---

## 5. Where things live

```
├── README.md                     start here
├── INDEX.md                      this file
├── START-HERE.md                 reading order and current state
├── RUN-IT-ON-YOUR-COMPUTER.md    get it working locally
├── PUT-IT-ONLINE.md              get it onto a server
├── 01 … 15 *.md                  the reference documents
├── source-code/
│   ├── app/                      the application
│   ├── tools/                    harnesses, diagnostics, build scripts
│   ├── web/                      the review interface
│   ├── deploy/                   packaged local Docker setup
│   ├── Dockerfile                builds the sealed container
│   └── requirements.txt          pinned dependencies
├── deployment/                   server scripts and configuration
└── engineering-history/          how it was built, and every decision
```

---

## 6. I want to… (A–Z)

| I want to | Go to |
|---|---|
| Add a login for someone | `deployment/user.sh`, or `PUT-IT-ONLINE.md` §7 |
| Add a new client's form layout | `app/form_profiles.py`; recipe in `11-HOW-TO-EXTEND-IT.md` §1 |
| Add a validation rule | `app/validate.py`; recipe in `11-HOW-TO-EXTEND-IT.md` §3 |
| Change a default setting | `app/config.py`, or an environment variable; list in `02-HOW-IT-WORKS.md` §7 |
| Change the Excel output | `app/export_designs.py`; `11-HOW-TO-EXTEND-IT.md` §2 |
| Change what counts as `clean` | `app/pipeline.py`, `_page_status()` |
| Check a deployment is sound | `tools/e2e_prod_test.py` — 32 checks |
| Check I have not broken anything | `tools/guard.py` — run it before shipping |
| Cut the running cost | `05-WHAT-IT-COSTS.md`, then the stop/start table in `PUT-IT-ONLINE.md` §8 |
| Find why a page read badly | `tools/probe_*.py`; `12-OPERATIONS-RUNBOOK.md` §4 |
| Know the real accuracy | `06-ACCURACY-AND-TESTING.md` §7 |
| Know what it cannot do | `10-KNOWN-LIMITATIONS.md` |
| Know what was actually tested | `14-VERIFICATION-RECORD.md` |
| Restore from a backup | `deployment/restore.sh`; `12-OPERATIONS-RUNBOOK.md` §3 |
| See it working, fastest route | `RUN-IT-ON-YOUR-COMPUTER.md` |
| Take a backup | `12-OPERATIONS-RUNBOOK.md` §3 — and verify it |
| Understand a flag I found in the code | Search its `D-0xx` id in `engineering-history/revamp/00-DECISION-LOG.md` |
| Use a different cloud provider | `15-DEPLOY-TO-ANY-CLOUD.md` |

---

## 7. Two things to know before changing anything

**Bump `PIPELINE_VERSION` in `app/pipeline.py`.** Results are cached on page
hash plus pipeline version. Without the bump, pages already processed keep
returning their old answer and your change appears to do nothing.

**Check the number nobody is watching.** The figure that matters is not
accuracy — it is *rows that are wrong and unflagged*, because that is a wrong
value reaching a payroll run with nobody asked to look. If your change improves
accuracy by two points and moves that count from 0 to 1, it is a bad change.
`tools/guard.py` exists to catch exactly this.


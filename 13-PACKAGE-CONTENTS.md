# 13 — Package Contents

A map of this package. Sizes and counts were taken from the package itself.

## Top level

| Item | Size | Files | What it is |
|---|---|---|---|
| `client-data/` | 6.6G | 13791 | The real client timesheets the system was built and measured against. |
| `deployment/` | 520K | 26 | Scripts and templates to deploy to your own cloud project. |
| `engineering-history/` | 2.1M | 39 | The original engineering documentation and the full decision record. |
| `reference-data/` | 68M | 184 | Employee roster, designation vocabulary, and the graded test fixtures that produce every accuracy figure. |
| `source-code/` | 1.7M | 137 | The complete application, tools and build files. This is the project. |
| 15 documents | — | 15 | The numbered guides, starting with `START-HERE.md` |

## The documents

15 documents, 3,326 lines in total.

| File | Lines | What it covers |
|---|---|---|
| `START-HERE.md` | 100 | Entry point and reading order |
| `01-WHAT-THIS-IS.md` | 161 | What the system is and what its figures mean |
| `02-HOW-IT-WORKS.md` | 292 | Reference |
| `03-SETUP-ON-A-LAPTOP.md` | 281 | Getting it working on one machine |
| `04-DEPLOY-TO-CLOUD.md` | 306 | Deploying to Google Cloud |
| `05-WHAT-IT-COSTS.md` | 188 | Costs, with the arithmetic |
| `06-ACCURACY-AND-TESTING.md` | 285 | Required before changing extraction code |
| `07-CODE-REFERENCE.md` | 363 | Reference |
| `08-API-REFERENCE.md` | 175 | The HTTP API |
| `09-DESIGN-DECISIONS.md` | 213 | Reference |
| `10-KNOWN-LIMITATIONS.md` | 201 | What it does not do |
| `11-HOW-TO-EXTEND-IT.md` | 230 | Reference |
| `12-OPERATIONS-RUNBOOK.md` | 260 | Day-to-day operation |
| `13-PACKAGE-CONTENTS.md` | 108 | A map of the package |
| `14-VERIFICATION-RECORD.md` | 163 | What was tested, and what was not |

## `source-code/`

| Item | Files | What it is |
|---|---|---|
| `app/` | 26 | The application. 26 modules, ~11,000 lines. |
| `deploy/` | 15 | Packaged local Docker setup with operator-facing docs. |
| `tools/` | 85 | 78 evaluation harnesses, diagnostics and build scripts. |
| `web/` | 2 | The review interface (single-page). |
| `.dockerignore` | 1 | Build context exclusions. |
| `Dockerfile` | 1 | Container build. Bakes the OCR models in so it runs offline. |
| `Makefile` | 1 | Named commands for the accuracy loop. |
| `requirements-dev.txt` | 1 | Extra packages for building documentation. |
| `requirements.txt` | 1 | Pinned runtime dependencies. |
| `run.bat` | 1 | Windows launcher. |
| `run.sh` | 1 | macOS/Linux launcher; creates the environment on first run. |
| `start.bat` | 1 |  |
| `start.command` | 1 |  |

## `deployment/`

| File | What it does |
|---|---|
| `Caddyfile` | HTTPS and the login gate. Passes the signed-in name to the app. |
| `autosleep.sh` | Scheduled job that stops the machine after 3 hours idle. Ships disabled. |
| `cost_collector.py` | Writes a cost snapshot the application reads. |
| `deploy_gcp.sh` | Creates the whole cloud environment. Idempotent. Needs PROJ and BILLING. |
| `docker-compose.prod.yml` | Production container definitions and the overlay mounts. |
| `enable_cost_scope.sh` | Grants the machine permission to read billing data (for exact cost reporting). |
| `overlay_index.html` | The production interface overlay. |
| `restore.sh` | Restores data and the application overlay onto a deployed machine. **Required after deploy_gcp.sh.** |
| `user.sh` | Add, remove and list logins. |
| `users.caddy.example` | Template for the login file. Real hashes are never shipped. |
| `wake.sh` | Starts a stopped machine and waits until the application is ready. |
| `overlay/` | The application files bind-mounted in production (14 files). |
| `templates/` | Configuration templates. |

## `reference-data/`

| Item | What it is |
|---|---|
| `roster.csv` | 2,579 employees: code, name, client. Needed for identity matching. |
| `designations.csv` | 444 job titles, harvested from the client's own spreadsheets. |
| `test-fixtures/testsets/` | Horizontal multi-employee sheets and clock-time sets, with truth derived from PDF text layers. |
| `test-fixtures/_sample50/` | The 50-page sample, 38 pages hand-graded against the paper. `truth.json` is the reference. |
| `test-fixtures/_manual_verify/` | Pages used for manual verification rounds. |

## `client-data/`

The real documents the system was built against. This is AARVI's own data.

| Folder | Size | Files | PDFs |
|---|---|---|---|
| `Timesheet - Delhi 2026-2027/` | 967M | 1024 | 708 |
| `Timesheet - HO 2026-2027/` | 2.0G | 2891 | 2367 |
| `Timesheet - KOLKATA 2026-2027/` | 885M | 795 | 658 |
| `handwritten_corpus/` | 2.8G | 9081 | 0 |

## `engineering-history/`

The record of how the system was built, kept because it is the evidence
behind every number quoted elsewhere.

| Item | Lines | What it is |
|---|---|---|
| `revamp/00-DECISION-LOG.md` | 2186 | **The most important file here.** 93 numbered decisions, each with its measurement. |
| `revamp/01-NEXT-VERSION-BACKLOG.md` | 304 | Open items with evidence. The live limitations list. |
| `revamp/01-REVAMP-REPORT.md` | 431 | The engineering report for the rebuild. |
| `README.md` | 370 | The original project README. |
| `TECHNICAL-DOC.md` | 541 | Original technical documentation. |
| `SCALE-AND-DEPLOYMENT.md` | 183 | Throughput measurements and deployment options. |
| `ORIGINAL-PRODUCTION-RUNBOOK.md` | 82 | The runbook for the instance that was deployed during development, kept as a record. |
| `03-*.md` … `17-*.md` | — | 16 stage reports, each documenting one phase of development and what it measured. |

# Timesheet OCR System — Project Handover

This package contains everything needed to run, understand, modify and deploy
the timesheet extraction system. Nothing is held back: the full source, the
real client data it was built against, the test fixtures that produce every
accuracy figure quoted here, the deployment scripts, and the record of why the
system is built the way it is.

---

## What this system does, in one paragraph

AARVI ENCON receives monthly labour timesheets from site contractors. They
arrive as scanned PDFs and phone photographs, mostly filled in by hand, in
dozens of different layouts because every client site uses its own form. Each
sheet records, for one or more workers, what they did on each day of the month
(present, absent, leave, weekly off, holiday), their clock-in and clock-out
times, and their hours. Someone then types all of this into a spreadsheet for
payroll. This system reads those sheets automatically, checks the result
against the arithmetic the sheet itself states, flags anything it is not
confident about, lets a human correct it on screen, and exports a payroll-ready
Excel workbook. It runs entirely on infrastructure you control. No document or
employee record is sent to any external service.

---

> **Public repository.** This copy contains the source, the deployment
> scripts, these documents and the engineering history. It does **not**
> contain the employee roster, the test fixtures or the client timesheets —
> that is personal data about real workers and is not published. See the
> "Not in this repository" section of `README.md`.

## Read in this order

| # | Document | Who it is for |
|---|---|---|
| 01 | `01-WHAT-THIS-IS.md` | **Anyone.** No technical knowledge assumed. Start here if you have never seen the system. |
| 02 | `02-HOW-IT-WORKS.md` | Developers. The architecture and the three processing stages. |
| 03 | `03-SETUP-ON-A-LAPTOP.md` | Whoever runs it first. Gets it working on one machine. |
| 04 | `04-DEPLOY-TO-CLOUD.md` | Whoever deploys it. Step by step onto your own Google Cloud project. |
| 05 | `05-WHAT-IT-COSTS.md` | Whoever pays for it. Every cost line, with the arithmetic shown. |
| 06 | `06-ACCURACY-AND-TESTING.md` | **Read before changing any extraction code.** How accuracy is measured and the rule that protects it. |
| 07 | `07-CODE-REFERENCE.md` | Developers. Every module, what it does, where to look. |
| 08 | `08-API-REFERENCE.md` | Anyone integrating with it. All HTTP endpoints. |
| 09 | `09-DESIGN-DECISIONS.md` | Developers. Why things are the way they are, and what was tried and rejected. |
| 10 | `10-KNOWN-LIMITATIONS.md` | **Everyone.** What this system does not do. Read it before promising anything to anyone. |
| 11 | `11-HOW-TO-EXTEND-IT.md` | Developers. Adding a new client form, a new export, a new validation rule. |
| 12 | `12-OPERATIONS-RUNBOOK.md` | Whoever keeps it running. Day-to-day operations and troubleshooting. |
| 13 | `13-PACKAGE-CONTENTS.md` | A map of every folder and file in this package. |
| 14 | `14-VERIFICATION-RECORD.md` | **What was actually tested before handover, and what was not.** Read before trusting any figure. |
| 15 | `15-DEPLOY-TO-ANY-CLOUD.md` | **AWS, Azure, any VPS, or your own hardware.** Read instead of 04 if you are not on Google Cloud. |

---

## If you only have ten minutes

1. Read `01-WHAT-THIS-IS.md`.
2. Follow `03-SETUP-ON-A-LAPTOP.md`. It takes about fifteen minutes and ends
   with the system running in your browser, reading a real timesheet.
3. Read the "What this system does not do" section of `10-KNOWN-LIMITATIONS.md`.

That is enough to hold a sensible conversation about the system.

---

## The one rule that matters most

This system reads handwriting. It is not perfect and it does not claim to be.
Its actual promise is narrower and more useful:

> **When the system is not sure, it says so. It does not guess silently.**

Every page comes out with a status. A page marked `clean` has been read *and*
cross-checked against the totals printed on the sheet itself. A page marked
`needs_review` has something a person must look at. Every row inside a page
carries its own confidence score and, when flagged, a named reason.

The number to defend is therefore not an accuracy percentage. It is the count
of rows that were **wrong and unflagged** — rows where a wrong value could
reach a payroll run with nobody asked to check it. On the most recent
measurement, that count was **zero** across 19 handwritten pages and 583 day
cells. `06-ACCURACY-AND-TESTING.md` explains how that is measured and how to
keep it at zero.

If you change extraction code and that number moves, you have made the system
worse even if the headline accuracy went up. There is an automated check
(`source-code/tools/guard.py`) that exists precisely to catch this, because it
has happened before.

---

## Current state at handover

| | |
|---|---|
| Pipeline version | `v52-no-silent-employee-loss` |
| Application code | 26 modules, approximately 11,000 lines |
| Supporting tools | 78 scripts (evaluation harnesses, diagnostics, build tooling) |
| Documented design decisions | 93, numbered D-000 to D-099 |
| Employee roster | 2,579 people |
| Client sheets included | 3,733 PDFs plus 9,081 extracted handwritten page images |
| Automated regression checks | 16 (`guard.py`) plus 32 end-to-end (`e2e_prod_test.py`) |

The system has been deployed to Google Cloud and verified working end to end.
It is not currently handed over as a running service — this package contains
what you need to stand up your own environment, which is the right arrangement
for a team taking ownership. `04-DEPLOY-TO-CLOUD.md` covers that.

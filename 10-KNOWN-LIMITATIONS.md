# 10 — Known Limitations

What this system does not do. Read before promising anything to anyone.

Everything here is stated because it is known and measured, not because it is
suspected. The live list with full evidence is
`engineering-history/revamp/01-NEXT-VERSION-BACKLOG.md`.

---

## 1. It does not remove the human

The system reads handwriting at roughly 90% on day statuses. It is designed so
that the remaining 10% is *visible* rather than hidden, but somebody still has
to look at the flagged items.

On the most recent handwritten measurement, **all 19 of 19 pages were flagged
for review.** That is the system working correctly, not failing — but it means
the workflow is "machine reads, human clears the flags", not "machine replaces
the typist".

Anyone budgeting on the basis of zero review effort will be disappointed.

---

## 2. Only one of three regions can be measured against client records

This is the most important limitation in this document, and the fix is not in
the code.

| Region | Corpus pages | Pages that can be scored |
|---|---|---|
| Delhi | — | 278 |
| HO | 247 | 7 |
| Kolkata | 29 | 0 |

The reason: scoring requires matching a page to its row in the client's own
spreadsheet, and the only reliable key would be an employee code. HO and
Kolkata sheets largely do not carry one, and the same employee *name* recurs
across months, so the matcher refuses to guess between them rather than
fabricate a match.

**Consequence:** the corpus-wide figure of 89.5% is substantially a Delhi
number. It is not dishonest, but it is narrower than it sounds, and it should
always be quoted with this caveat.

**The fix is a client-side change:** employee codes printed or written on the
sheets. That single change would make two thirds of the archive measurable. It
is the highest-value item on the backlog and it costs no engineering.

---

## 3. Some layouts yield no employee name at all

292 of 1,218 corpus pages produce no name.

These are **not silent failures.** Every one is stopped with a blocking issue,
and the page's own heading is quoted back to the reviewer so they can see what
the system was looking at (D-084). The cost is manual entry, not a wrong
invoice.

Four distinct causes, diagnosed in the backlog:

- a leave-balance report that is not a timesheet at all
- a statutory FORM D register marked with circled handwriting
- two multi-employee grid layouts the readers do not handle

---

## 4. Checksums cannot detect a permutation

The validation layer's strongest tool is comparing the day-by-day reading
against the totals the sheet states about itself. That catches a wrong *count*.

It cannot catch a wrong *order*. The right number of each status on the wrong
days reconciles perfectly.

Partly mitigated: weekly offs normally cluster on one or two weekdays, and
scatter when rows have drifted, which a calendar check detects (D-083). But
there is no general detection for a permutation, and there may not be one.

---

## 5. Rows merge on dense layouts

On tightly-spaced sheets a single cell can return several rows' values at once
— a cell reading `4 4 4` — after which days slide against the calendar.

Mitigated by refusing to call such rows confident (D-074), so they are flagged.
Not fixed.

---

## 6. Three HO layouts produce nothing, and the obvious fixes made things worse

Three HO layouts yield no usable extraction. Three targeted fixes were built,
measured, and **rejected** (D-096 to D-098) because each damaged the wider
population or moved the unflagged-error count — one of them took accuracy from
93.8% to 89.7%.

They remain in the code behind flags set to `False`, with their measurements in
the comments.

**The recorded conclusion matters more than the attempts:** a global rule is
the wrong shape for one layout's quirk. `form_profiles.py` supports per-layout
anchors, and that is where the next attempt belongs. Anyone who tries a global
rule here will repeat a week of measured failure.

---

## 7. Clock times are weaker than day statuses

93.8%, against roughly 95.8% for day statuses on the same hand-graded sample.
Times are harder: handwritten, often ambiguous (`9` could be 09:00 or 21:00),
and many sheets write hour-only times with no minutes.

A clock-grammar repair layer was built, passed 35 of 35 unit cases, and
**measured worse end to end** (D-072). It is off. This is a clean illustration
of unit tests passing while the product gets worse.

---

## 8. Designation is narrowly measured

Gated by an 18-probe regression panel rather than a broad accuracy figure.
There is no defensible overall designation accuracy number, and none should be
quoted.

---

## 9. The Excel layouts are our designs, not the client's

Six export designs are provided, and they are sensible, but they were not
derived from AARVI's existing payroll templates. If their payroll system
expects a particular column order, the export will need adapting —
`app/export_designs.py`, and `11-HOW-TO-EXTEND-IT.md` explains how.

---

## 10. Operational limitations

**The URL is the machine's IP address.** With the machine stopped, nothing
exists to receive a request and wake it. Automatic wake-on-request would need a
second always-on component. Cold start from stopped is 56 seconds, measured.

**Deploying needs two scripts, not one.** `deploy_gcp.sh` alone produces a
machine that will not start, because it does not upload the application overlay
or the login file, and Docker silently turns a missing bind-mount into an empty
directory. `restore.sh` must follow it. This is documented in
`04-DEPLOY-TO-CLOUD.md` and the scripts now fail loudly, but it is a sharp edge.

**Ten application files are bind-mounted rather than built into the image.**
This was a hot-fix mechanism that became permanent. It works, and `restore.sh`
verifies it, but folding those files into a proper image build would remove a
whole class of deployment failure. It is on the backlog.

**Exact cloud cost reporting is not switched on.** The `/cost` page shows
estimates, roughly 30% high because it uses list prices before the sustained-use
discount. Making it exact needs a console action that has no API. See
`05-WHAT-IT-COSTS.md` §8.

**One machine, one database file.** No horizontal scaling. Measured throughput
is 8–23 machine-hours for a 3,000-page month, so this is comfortable for the
current volume and would need rework for a much larger one.

---

## 11. Things deliberately not being worked on

Recorded so nobody mistakes them for oversights:

- **Trichy circled handwriting.** Statutory registers marked with circles
  rather than letters. Assessed as out of scope: the effort is large and the
  page count is small.
- **A trained custom recognition model.** No labelled data at the required
  scale — the hand-graded set is 38 pages — and it would need retraining per
  client layout.
- **Automatic wake-on-request.** Needs a second always-on component for a
  system used on a monthly cycle.

---

## 12. How to describe the system accurately

Safe to say:

- Typed and well-structured sheets read essentially perfectly (100% measured on
  the horizontal multi-employee family).
- Handwritten sheets read at roughly 90%.
- The system flags what it is unsure about rather than guessing, and on the
  most recent measurement **zero** wrong rows passed unflagged.
- Nothing leaves your infrastructure.
- No licence fees.

Not safe to say:

- Any single accuracy percentage for "the system".
- "95.8% accurate" — that is the mixed 50-page sample, not handwriting.
- That it eliminates manual review.
- That it handles every layout. Three HO layouts produce nothing.
- That accuracy is verified across all three regions. It is largely Delhi.

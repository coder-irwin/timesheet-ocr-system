# 06 — Accuracy and Testing

**Read this before changing any code that affects extraction.**

This is the most important document in the package for a developer. The system
is not hard to modify. It is hard to modify *without quietly making it worse*,
and this document exists because that has happened repeatedly, including to
people who knew the codebase well.

---

## 1. The failure mode this whole discipline exists to prevent

Every regression this project has shipped had the same shape:

> A change improved the number someone was looking at, and quietly moved a
> number nobody was looking at.

Two real examples, both recorded in the decision log:

**D-073 — switching off the angle classifier.** Clock-time accuracy went from
83.6% to 93.8%. Day-status accuracy looked flat. The change was clearly good
and was kept. But rows that were **wrong and unflagged** went from 10 to 15 —
five more places where a wrong value could reach a payroll run with nobody
asked to look. Nobody would have seen that without checking for it specifically.

**D-075 — not blocking pages whose checksums cannot be computed.** Half the
false alarms disappeared. The 50-page sample did not move at all. And two
pages began passing as `clean` while 15 of their 30 days were wrong. For this
system that is the worst possible outcome: a page marked finished, that is not.

Neither was caught by the metric the change was aimed at. Both were caught by
asking the same boring questions afterwards. Those questions are now written
down and run as one command.

---

## 2. The rule

**Change one thing. Measure. Keep it or revert it. Write down what you learned
either way — including the rejections.**

The rejections matter as much as the wins. Roughly a third of the entries in
the decision log are things that were tried, measured, found worse, and turned
off. They are left in the code behind a flag set to `False`, with the measured
numbers in the comment, so that nobody spends a week rediscovering them:

```python
NUMERIC_CELL_IS_PRESENT = False  # D-086: measured, no gain (+1 cell). OFF.
MERGED_CELL_SPANS_ROWS  = False  # D-096: MEASURED WORSE (93.8 -> 89.7). OFF.
CLOCK_REPAIR            = False  # D-072 measured worse
```

**Turning a flag off is not the same as reverting a change.** This bit the
project directly. One change had made three edits; only the flag was reverted,
and two edits to the physical column geometry were left behind. The regression
check caught it, but the lesson stands: when you revert, revert everything the
change touched.

---

## 3. The floor: `tools/guard.py`

Run before shipping anything that touches accuracy.

```bash
./.venv/bin/python tools/guard.py            # ~25 min, the full floor
./.venv/bin/python tools/guard.py --quick    # ~2 min, structural only
```

Sixteen checks. It fails rather than printing a number, and the thresholds are
the *measured floor*, not aspirations — it fails if the system gets **worse**,
not if it fails to get better.

### What it pins

**The measured-decision flags.** Seven settings whose current value *is* a
measured decision. A silent flip of any of them is a regression that no
accuracy run would attribute correctly, because the number would move and the
cause would be invisible.

**Unit behaviour that three separate defects have turned on:**

| Input | Must parse as | Why |
|---|---|---|
| `10Hrs` | 10.0 | A unit suffix is not a digit |
| `3 6` | *unreadable* | Two values in one cell, not 0.36 |
| `85` | 8.5 | |
| `42` | 0.42 | |
| `1000` | 10.0 | |
| `10:00` | 10.0 | |

**Clock grammar:** `8:30 AM` → 08:30, `7:30 Pm` → 19:30, `00:60` → *rejected*,
`9 AM` → 09:00 (hour-only is valid; many sheets write times that way).

**The cache path.** Every offline harness calls `process_page(force=True)`, so
**none of them exercises the cached branch** — and that branch rejoins the
common code with a different set of local variables defined. Twice something
added to the common path referenced a name that only existed on the fresh path,
and both times it reached production while every test was green. One such
defect was live across seven releases.

The guard therefore reads a real sheet twice, once fresh and once cached, and
requires an identical result. This check was validated by deliberately
reintroducing the defect and confirming it fails.

### The current floor

| Check | Floor |
|---|---|
| 50-page hand-graded sample, day status | ≥ 95.5% |
| 50-page sample, rows wrong **and unflagged** | ≤ 2 |
| 50-page sample, days missing | 0 |
| Horizontal multi-employee sheets, day status | 100% |
| Horizontal sheets, unflagged errors | 0 |
| Fast extraction harness, day status | ≥ 93.0% |
| Employee name | ≥ 30 of 31 |

Raise a floor **only** after a run proves the new value, and record the run in
the decision log. Lowering a floor to make a change pass is how this system
would rot.

---

## 4. The one number that must never move

> **Rows that are wrong AND unflagged.**

A wrong day on a page the system passed as `clean` is a wrong number reaching
an invoice with nobody asked to look at it. Every other figure in this
document is an accuracy measurement. That one is the product's promise.

If your change improves accuracy by two points and moves this number from 0 to
1, your change is bad. Revert it.

---

## 5. The harnesses

Different harnesses answer different questions. Using the wrong one wastes time
or, worse, produces a number that does not mean what you think.

| Harness | Question | Runtime |
|---|---|---|
| `tools/eval_fast.py` | Did my extraction change help? | ~1 s |
| `tools/eval_fast.py --matrix` | A/B the extraction switches | ~5 s |
| `tools/eval_isgec.py` | Horizontal multi-employee sheets | seconds |
| `tools/eval_sample50.py` | The 50-page hand-graded sample | minutes |
| `tools/eval_times.py` | Clock times, through the real upload path | minutes |
| `tools/eval_100.py` | Full pipeline vs the client's own spreadsheets | ~10 min |
| `tools/eval_corpus.py` | Everything, all three regions | hours |
| `tools/guard.py` | Have I broken anything? | ~25 min |
| `tools/e2e_prod_test.py` | Does the deployed server actually work? | ~5 min |

**`eval_fast.py` has a precondition.** It scores extraction against *frozen*
text-recognition output, which is what makes it return in a second. That is
only valid if you have not changed OCR or preprocessing. If you have, run
`make freeze` first (about eight minutes) to recapture, or you will be
measuring new logic against stale input.

**`guard.py` cannot see the deployment.** It calls the pipeline directly, so it
knows nothing about authentication, the identity header, the Excel export, or
the cached branch as the server exercises it. That is what
`tools/e2e_prod_test.py` is for — thirty-two checks against a live server over
HTTPS.

---

## 6. Where ground truth comes from

Truth is never taken from a previous run of the pipeline. Three independent
sources:

**PDF text layers.** Many client PDFs carry an embedded text layer from the
system that produced them. `tools/isgec_truth.py` and `tools/build_timeset.py`
read it. Completely independent of the OCR under test.

**The client's own spreadsheets.** `tools/truth.py` parses the typed Excel
files the client already maintains. `tools/eval_100.py` scores against these.

One caution that cost real time here: **the client's spreadsheet is sometimes
wrong.** On one corpus run, six pages looked like the system had let an error
through. Checked against the paper, **five of the six were the spreadsheet
being wrong**, not the system. `tools/truth_conflicts.py` exists to measure how
often that ground truth contradicts itself. Verify an apparent escape against
the original paper before believing it.

**Hand grading.** `reference-data/test-fixtures/_sample50/truth.json` is 38
pages read by eye against the paper. Each day holds a *list* of acceptable
values, because some cells legitimately read either way. Do not tighten that to
a single value — the grading was done that way deliberately.

---

## 7. Measured accuracy at handover

Every figure below comes from a harness run, with the source named. They are
not interchangeable and they must not be averaged.

| Measurement | Result | Source |
|---|---|---|
| Horizontal multi-employee sheets, day status | **100%** (366/366), 0 unflagged | `eval_isgec.py` |
| Same sheets, verified on the live server | **100%** (93/93), names 3/3 | `e2e_prod_test.py`, 10 Nov 2026 |
| 50-page hand-graded sample, day status | **95.8%** (1,108/1,157), 2 unflagged, 0 missing | `eval_sample50.py` |
| Handwritten pages only, on the live server | **91.4%** (533/583), 0 unflagged | 19 `_ha` pages, 10 Nov 2026 |
| Handwritten pages only, on a local machine | 89.5% (522/583) | same 19 pages, no header model |
| Clock times (in/out) | **93.8%** (1,437/1,532) | `eval_times.py` |
| Whole corpus, day status | **89.5%** (7,114/7,945) | `eval_corpus.py` under v49 |
| Employee name, corpus | 98.6% | `eval_corpus.py` |
| Pages passing as `clean` | 10.0%, with **0** wrong pages among them | D-083 |

### How to talk about these numbers honestly

**Do not quote a single accuracy figure.** 100% and 91.4% are both true, of
different sheet types. Averaging them misrepresents both.

**95.8% is not a handwriting figure.** It is the full 50-page sample, which
includes typed sheets. The handwriting-only number is 91.4%.

**The corpus figure is narrower than it looks.** 89.5% is across 1,218 pages,
but only 278 could be *scored* — Kolkata contributed zero and HO nine, because
without employee codes on the sheets there is no reliable way to match a page
to its row in the client's spreadsheet. So it is substantially a Delhi number.
An earlier figure of 77.2% is withdrawn: the scorer was broken, not the system.

**The defensible claim is not a percentage.** It is: *the system flags what it
is unsure about rather than guessing silently.* On the 19 handwritten pages,
all 19 were flagged for review and 31 cells were marked unread rather than
filled with a guess.

---

## 8. The workflow, start to finish

```bash
# 1. Know where you stand
./.venv/bin/python tools/guard.py --quick

# 2. Change ONE thing

# 3. Measure the thing you aimed at
make fast                       # (make freeze first if you touched OCR)

# 4. Check what you did NOT aim at
./.venv/bin/python tools/guard.py

# 5. Keep it or revert it — completely, not just the flag

# 6. Write it down in engineering-history/revamp/00-DECISION-LOG.md,
#    including the measured numbers. Rejections too.

# 7. Bump PIPELINE_VERSION in app/pipeline.py.
#    This invalidates the content-addressed cache automatically.

# 8. If deploying, verify the live server
./.venv/bin/python tools/e2e_prod_test.py --url https://<site>
```

Step 7 is easy to forget and causes confusing results: without it, previously
processed pages keep returning their old cached answer and your change appears
to do nothing.

---

## 9. Traps this project has already fallen into

Documented so nobody pays for them twice.

| Trap | What happened |
|---|---|
| Measuring code is code | Two separate truth bugs produced flattering numbers. One read the hours column as times; one scored 16 perfect pages as 0/23 by treating disjoint date ranges as errors. Suspect the harness before the pipeline |
| Symmetric normalisation | If a blank in the *output* maps to "weekly off" like a blank in the *truth*, accuracy rises as the reader gets worse. Keep `truth_norm` and `got_norm` separate |
| An improvement that is really a workaround | Raising resolution 1600→2400 "helped" by masking the angle-classifier defect. Once that was fixed, 1600 beat 2400 and ran faster |
| A flag off is not a revert | Reverting the flag but leaving the other edits in place left broken column geometry behind |
| Global rules for one client's quirk | Several per-client fixes made things worse globally. Such fixes belong in a form profile, not in a shared rule |
| Trusting the client's spreadsheet | Five of six apparent escapes were the spreadsheet being wrong |
| The cache branch | No offline harness touches it. A defect lived there across seven releases |

---

## Next

- Module detail: `07-CODE-REFERENCE.md`
- The full decision record: `engineering-history/revamp/00-DECISION-LOG.md`
- What is still open: `10-KNOWN-LIMITATIONS.md`

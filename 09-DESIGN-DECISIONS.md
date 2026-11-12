# 09 — Design Decisions

Why the system is built the way it is, and what was tried and rejected.

The full record is `engineering-history/revamp/00-DECISION-LOG.md` — 2,186
lines covering 93 numbered decisions, D-000 to D-099, each with the measurement
that justified it. This document is the orientation: the decisions that shape
everything else, and the reasoning patterns behind them.

---

## 1. How to read the decision log

Each decision has an identifier like `D-073`. Those identifiers appear
throughout the source as comments:

```python
OCR_USE_CLS = os.getenv("TS_OCR_USE_CLS", "0") == "1"   # D-073
CROSS_MONTH_RUN = True                                   # D-087
NUMERIC_CELL_IS_PRESENT = False  # D-086: measured, no gain (+1 cell). OFF.
```

When you find a flag you do not understand, search the decision log for its
identifier. You will find what was measured, on what data, and what the numbers
were. **Nothing in that log is an opinion** — if a decision has no measurement
behind it, that is stated.

---

## 2. The decisions that shape everything

### Everything runs locally

Nothing is sent to an external service. The text-recognition models are
bundled into the container and work with no network at all.

This was a constraint, not an optimisation. The documents are named workers'
attendance records. Once that constraint was accepted, several other things
followed: the choice of a locally-runnable OCR engine over a cloud vision API,
the decision to bake models into the image at build time, and the deliberate
avoidance of managed cloud services in the deployment.

It is also the system's commercial differentiator. Spend it knowingly if you
ever consider a cloud vision provider.

### Processor only, no graphics card

A graphics card would make the header model several times faster. It would also
add roughly $250 a month to a cloud deployment, which breaks the cost ceiling
this project was built to.

The trade taken instead: accept that a hard handwritten page takes one to two
minutes. A 3,000-page month is still an overnight job. See
`05-WHAT-IT-COSTS.md`.

### Quality before speed, explicitly

Where accuracy and latency conflicted, accuracy won. The header model is on in
production despite costing a minute per hard page. Two independent reading
passes run where one would do. Rescue paths re-read pages at other
orientations and higher resolutions.

All of it is configurable. If your priorities differ, `TS_VLM_HEADER=0` and
`TS_DUAL_PASS=0` buy speed back immediately, and the measured cost of doing so
is recorded.

### Anchors, not coordinates

Fields are found relative to labels discovered on each page, never at fixed
pixel positions. This is why one profile tolerates sheets that are shifted,
scaled or slightly rotated — and it is why adding a new client layout is
usually a data change in `form_profiles.py` rather than new code.

### A structural reader as well as profiles

`generic_grid.py` finds a day grid on a sheet it has never seen, with no
knowledge of the client. It exists because the long tail of layouts is
genuinely long, and writing a profile per layout would never finish.

The two readers are combined by a measured rule (`GRID_BEATS_WEAK_PROFILE`,
D-090): the structural result wins when the profile result is weak. That single
rule recovered 33 employees on one page.

### The system must know when it does not know

The most consequential design decision in the project. Rather than maximising
accuracy, the system maximises *honesty about* accuracy. Three mechanisms:

1. Page status, where `clean` requires corroboration against the sheet's own
   arithmetic, not merely successful reading.
2. Per-row confidence with named reasons.
3. An unread cell stays visibly unread, never filled with a plausible guess.

This is why the number the project defends is "rows wrong and unflagged", not
an accuracy percentage.

---

## 3. Four decisions worth understanding in detail

### D-073 — the angle classifier, the single biggest win

RapidOCR ships a classifier that decides whether each text box is upside down.
On short numeric cells it guesses wrong often, turning `09:00` into `00:60`.

Switching it off moved clock-time accuracy from **83.6% to 93.8%**.

Two lessons came with it. First, the biggest available win was a default
setting in a dependency, not anything in this codebase — worth remembering
before writing new logic. Second, it had been *masking* another finding:
raising resolution from 1,600 to 2,400 had appeared to improve handwriting
accuracy, but was only compensating for the classifier. With the classifier
off, 1,600 beat 2,400 and ran faster.

> An improvement that is really a workaround for an unfound defect will mislead
> you about everything downstream.

### D-071 — the day-column assignment, found by the client

The structural reader padded each day column by half its width and took the
first match. On a real sheet, day 24's column claimed day 25's mark and then
discarded it. The 25th went missing for every employee on three sheets.

**The client reported it before we found it.** The fix — assign each mark to
the *nearest* column centre — took those sheets from 98.9% to 100%.

The lesson is about test data, not geometry. The defect was invisible in the
test set because the test set's columns were evenly spaced. Real sheets are
not.

### D-075 — the fix that created the worst possible bug

Pages whose checksums could not be computed (because the sheet states no total)
were being blocked. `UNCOMPUTABLE_IS_NOT_FAILED = True` stopped that and
removed about half the false alarms. The 50-page sample did not move.

It also let two pages pass as `clean` with 15 of their 30 days wrong.

The resolution is instructive: the flag was **not** reverted, because it was
correct. A second, separate requirement was added — an unread row blocks
`clean` (`UNREAD_ROW_BLOCKS_CLEAN`, D-091). Both flags must stay as they are.
The right fix for "my change had a bad side effect" is often a second
constraint, not a revert.

### D-096 to D-098 — three fixes built, measured, and rejected

Three changes aimed at difficult HO layouts: merged two-row "Weekly Off" cells,
recorded hours overriding a calendar remark, and a named `Present (Yes/No)`
column. Each fixed its target page — one recovered 25 days on a page that was
almost entirely unread — and each either damaged the wider population or moved
the unflagged-error count.

All three are in the code behind flags set to `False`, with their measurements
in the comments:

```python
MERGED_CELL_SPANS_ROWS = False  # D-096: MEASURED WORSE (93.8 -> 89.7). OFF.
```

The conclusion recorded there is the useful part: **a global rule is the wrong
shape for a single layout's quirk.** `form_profiles.py` already supports
per-layout anchors, and that is where the next attempt belongs. This is the
most common way to waste a week on this codebase.

---

## 4. Rejected approaches, and why

| Approach | Why not |
|---|---|
| Cloud vision API | Documents would leave the premises. Non-negotiable |
| A graphics card | ~$250/month, breaks the cost ceiling |
| Fine-tuning a recognition model on this handwriting | No labelled data at the required scale; the hand-graded set is 38 pages. Would also need retraining per new client layout |
| Running the vision model on whole pages | Measured: slower and no better than using it on the header block alone |
| Treating a numeric cell as "present" | D-086: measured, gained one cell. Off |
| Clock-grammar repair | D-072: 35 of 35 unit cases passed, and it measured worse end to end. Off. A good illustration that unit tests passing is not evidence of product improvement |
| Raising working resolution to 2,400 | Measured worse once D-073 was fixed, and slower |
| A per-client rule for an HO quirk | D-096–098: fixed one page, damaged the population |

---

## 5. The reasoning patterns

Worth internalising, because they are what kept the system honest:

**Measure one change at a time.** Two changes at once and you cannot attribute
the result. Every entry in the log is one change.

**Check what you did not aim at.** Both serious regressions improved their
target metric. `tools/guard.py` exists to ask the boring questions afterwards.

**Write down rejections with their numbers.** A third of the log is things that
did not work. That is the part that saves the next person time.

**Suspect the measurement first.** Two separate truth bugs in this project
produced flattering numbers. When a result looks too good, verify the harness
before celebrating.

**Verify an escape against the paper.** Six pages once looked like errors that
had slipped through. Five of the six were the *client's spreadsheet* being
wrong.

**Prefer a general fix to a patch.** The angle classifier, the day-column
assignment and the cross-month day axis were all root causes. Each fixed a
whole class of failures rather than the page in front of us.

---

## Next

- The complete record: `engineering-history/revamp/00-DECISION-LOG.md`
- What is still open: `10-KNOWN-LIMITATIONS.md` and
  `engineering-history/revamp/01-NEXT-VERSION-BACKLOG.md`

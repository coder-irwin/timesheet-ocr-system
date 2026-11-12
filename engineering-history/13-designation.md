# Stage 13 — Designation, and a Vocabulary Built From the Wrong Source

> The worst field in the product, stuck at 48% while everything else moved. The
> cause was not the matcher. It was that the closed vocabulary had been
> harvested from our own OCR output instead of from the client's spreadsheets —
> on the strength of a claim that turned out to be false.

---

## 1. The false premise

`tools/build_designations.py` opens with its own justification:

> *"the client has no designation column in any of their 289 spreadsheets, so
> there was no list to use"*

That is wrong. Every one of those files has a designation column. The
ground-truth parser reads a fixed column index that only matches the IOCL
layout, so the values were never seen — and the absence of *parsed* values was
recorded as an absence of *data*.

Scanning all 289 files for a header cell reading "Designation" or "Service
Category":

```
scanned 289 spreadsheets (0 unreadable)
547 raw -> 444 canonical designations
13,453 labelled employees
```

```
1316  Engineer Gr. III (Civil)
 973  Engineer Gr. III (Mechanical)
 792  Engineer Gr. IV (Welding NDT)
 703  Engineer Gr. III (Electrical)
 369  Controller Gr. E (EDMS/ERP/MIS)
```

The vocabulary in use held **25** generic titles ("Civil Engineer", "Store
Keeper") reconstructed from OCR readings — **almost none of which are what this
client writes.** Closed-vocabulary correction is the technique that took
employee names to 97%. It had been matching against the wrong closed set for
the entire project. A vocabulary that does not contain the right answer cannot
produce it, however good the matcher is.

**The lesson is not "check the data".** It is that *"the data does not exist"*
is a claim like any other, and this one was recorded in a docstring and then
inherited as fact by every later decision.

---

## 2. A bigger vocabulary made things worse first

Swapping 25 entries for 444 did not help — it hurt, and in the most dangerous
direction:

```
'sds h'  ->  'Mess Helper'   (score 80)
```

A junk OCR fragment now resolved to a confident job title. With 444 entries
there is always a near-neighbour, so:

- the **margin test** rejected correct answers ('SAFETY S.UP' scored 95.2 and
  returned nothing, because a variant scored close behind)
- the **partial_ratio fallback** admitted garbage, because a 5-character query
  finds a good window *somewhere* in a large vocabulary

Both had been safe at 25 entries and became unsafe at 444. **A change that is
correct in isolation can invalidate the tuning of everything downstream.**

---

## 3. Three matcher defects, each fixed on its own evidence

### a. `partial_ratio` needs a length guard, not just a score threshold

`'sds h'` matching `'MESS HELPER'` at 80 is not a weak signal, it is *no*
signal: any short string aligns well against something in a long list. The
score was never evidence. Substring matching now requires a query of at least
10 characters.

> This is the product's worst possible output — a wrong value that looks
> certain, passes validation, and reaches an invoice. Missing data is visible.
> Confident wrong data is not.

### b. The margin test was asking the wrong question

Its purpose is to refuse a coin-flip between two *different* answers. But a
real-world vocabulary is full of near-duplicates: `Safety Supervisor` vs
`Safety Supervisor (Structural)`, `Engineer Gr. III (Welding NDT)` vs
`(Welding/NDT)`. Refusing those is not caution — it is discarding a correct
answer because a variant of it also scored well.

The margin now only bites when the top two candidates are *dissimilar to each
other*. When one contains the other, or they are near-identical, the answer is
taken.

### c. Whole-string similarity is the wrong tool for abbreviations

Supervisors write `SAFETY S.UP`, `SAFETY S.U.P`, `Sgjety. sup`. Against those,
`token_sort_ratio` ranks **SAFETY OFFICER (56) above SAFETY SUPERVISOR (43)** —
so the plain matcher confidently prefers the wrong title. An abbreviation pass
aligns token-by-token and lets a query token count as a prefix of a vocabulary
token (`SUP` → `SUPERVISOR`), which reverses the ranking. A single letter only
counts as an initial and is worth less, so `S` alone cannot carry a match.

| | Designation |
|---|---:|
| 444-entry vocabulary, old matcher | 41.7% |
| + length guard, family-aware margin, abbreviation pass | 58.3% |
| + floor 74 → 70 | 62.5% |

Regression panel: 18/18 throughout.

---

## 4. The bug that was fixed once, in one of the two places it lived

With the matcher working, the largest remaining bucket was **6 pages where
designation came back empty**. The anchor was found on all six; the value was
located on four of them; and then it was deleted.

`extract_header` trims at the next label so a header row's neighbouring pair is
not swallowed. It compared at `MATCH_THRESHOLD` (80). And:

```
_matches('Safety Supervisor', ('SUPERVISOR NAME',))  ==  81
_matches('Site Supervisor',   ('SUPERVISOR NAME',))  ==  80
```

The designation's own value tripped the break on the first box, `trimmed`
stayed empty, and the field was set to `None`.

This is precisely the bug `FURNITURE_THRESHOLD = 92` was introduced to fix — and
the comment explaining it sits 120 lines above the loop that still ran at 80.
The fix was applied inside `_is_form_furniture()` only. The same box survives
the furniture filter and is killed 25 lines later by the un-fixed copy of the
same test.

**The perverse consequence: the cleaner the OCR read, the more likely the field
was destroyed.** `Sofsty Superwiser` scores 75 and survived. `Safety
Supervisor` scores 81 and was deleted.

### Why the obvious fix was wrong

Raising the whole loop to 92 measured **worse overall** (78.4% → 76.6%): a
permissive stop let other fields swallow the neighbouring label and value, and
one page stopped matching its row entirely.

The first box is different in kind from the rest. A header row reads
`LABEL value LABEL value`, so the box immediately right of our own anchor *is*
our value, by construction — it cannot be the next label. The strict bar now
applies only to the first box, and only for fields whose values legitimately
contain label words.

---

## 5. Two more, from the same investigation

**The form's own heading was being typed as a job title.** `ATTENDANCE SHEET`
scores **0.84** as a designation, because ATTENDANCE is one edit-cluster from
ATTENDANT. On a page where OCR missed the real title, the form's heading was
promoted into the field and reported confidently. Form phrases are now
excluded before job-word scoring.

**A value sitting slightly above its label was stolen.** On one page
`SAFETY SUPERVISOR` sat 0.30 label-heights above the EMPLOYEE CODE label, just
inside the `-0.35` above-penalty cutoff, so employee_code won it at cost 3.21
and took *both* the title and the code while designation starved. Sweeping the
tolerance: −0.35 and −0.30 give 19/24; −0.28 through −0.10 all give 20/24 with
day-status and employee-name unchanged.

---

## 6. A field nobody was measuring

The adversarial reviewer caught what the diagnosis missed: **no harness scored
`employee_code` at all.** Checking it directly:

```
13 of 24 extracted codes were contaminated
  'Sayety Suyp. 54789'
  'Safety Superwisor 150698 PRO,ECT: Deptt'
  'Saltry Suppaui sar1 57078 NORMAL OVER TIME ATTENDANCR SHEET ...'
```

Every one was then discarded, because `score_code()` returns 0 for anything
over two words. That rule is right as a *classifier* and wrong as an
*extractor* — the value is present and readable in all 13. `salvage_code()` now
scores each token separately and takes the best one that looks like a code
alone, refusing when none is convincing rather than guessing at the longest
number on the line.

It cannot be scored against ground truth — the client's Excel holds their
internal codes (`IOCLMS900`) while the scans carry the vendor's (`54789`), two
different systems. Contamination is measurable without truth; correctness is
not. That limitation is worth stating rather than papering over.

---

## 7. Result

| | Before | After |
|---|---:|---:|
| Designation (full pipeline) | 48.4% | **67.7%+** |
| Designation (fast harness, +vocab) | 41.7% | **83.3%** |
| Day status | 78.8% | 78.8% (unchanged) |
| Employee name | 97.1% | 97.1% (unchanged) |
| Regression panel | — | **18/18** |

---

## 8. Why "100% on designation" is not a number to quote

**Every designation in the scored ground truth is "Safety Supervisor"** — all
24 of them, and all 45 across every Excel the ground-truth parser can read.
There is no diversity to be right about.

A change that hard-coded that one string would score 100% here and be worthless
in production. So would a matcher loosened until every vaguely safety-ish
string resolves to the most frequent entry. That is why every step above was
gated on an 18-probe regression panel checking that *distinct* titles still
resolve to themselves and that junk still resolves to nothing — a panel drawn
from the real 444-entry vocabulary, not from the scored subset.

The honest position for the client:

- **83.3%** on the subset we can score, with no regression on distinct titles
- the vocabulary now contains the **444 titles their own spreadsheets use**,
  covering 13,453 employees, so the correction has the right target for the
  other 33 client folders
- what remains unmeasured is accuracy on those other titles, because no scan of
  them is paired with a typed Excel. Getting that number needs labelled pages
  from a second client folder — a data request, not a code change.

**The remaining 4 of 24 are not matcher failures.** One is an OCR miss (the
title is legible on the page; no text box was emitted). Two are junk fragments
correctly refused. One is `'SAFETY S.(1.P'`, too corrupted to identify without
guessing. Refusing to guess on those is the designed behaviour, not a shortfall.

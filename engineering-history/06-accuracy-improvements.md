# Stage 6 — Accuracy Improvements

> Every change made to raise end-to-end accuracy, the measurement before and
> after, and the two changes that were **reverted because they made things
> worse**. Includes the failures, which are the more useful half.

---

## The scoreboard

End-to-end field accuracy on the hand-labelled pages — *"did the pipeline put
the right value in the right field?"*

| # | Change | Overall | Handwritten | Printed |
|---|---|---:|---:|---:|
| 0 | Baseline | **57.6%** | 40% | 65% |
| 1 | Fix summary-anchor cross-binding | **66.7%** | 60% | 70% |
| 2 | Tighten header value bands | **69.7%** | 60% | 74% |
| 3 | Inline `LABEL: VALUE` + `NAME [CODE]` parsing | **78.8%** | 60% | 87% |
| 4 | Roster auto-correction (naive) | 75.8% ⬇ | 60% | 83% |
| 5 | Roster with overwrite guard | **78.8%** | 60% | 87% |
| — | Competitive anchor assignment (2 variants) | 66.7% ⬇ | 50% | 74% → **reverted** |

**Net: 57.6% → 78.8%**, a 21-point gain. Printed pages improved most (65% → 87%).

> **Why "accuracy" here is not a single headline number.** Two of the five test
> pages are templates the extractor was never written for. Their inclusion drags
> the average down but keeps it honest — the client's corpus contains those
> layouts, so pretending otherwise would mislead.

---

## 1. Summary-anchor cross-binding — the one that mattered most

**Symptom.** The row-sum checksum — the entire basis of the product's
"we always know when something is wrong" claim — could only run on **8% of
pages**. `total_man_hours` was `None` almost everywhere.

**Diagnosis.** Dumping the OCR boxes for one page showed both labels present and
read perfectly:

```
y=381   'TOTAL HOURS'          <- day-grid COLUMN HEADER
y=1197  'Total Man Hours'      <- summary label, 800px lower
```

The anchor matcher was using `fuzz.token_set_ratio`, which treats a token
**subset** as a perfect match. `{TOTAL, HOURS} ⊂ {TOTAL, MAN, HOURS}` scores
100, so "Total Man Hours" bound to the grid's column header instead of its own
label, and then looked for a value beside the *grid header* — where there is
none.

**Fix, two parts:**

1. **`token_sort_ratio` instead of `token_set_ratio`.** Sort-ratio compares the
   full sorted token strings, so a missing word costs score. It also still fixes
   the earlier EMPLOYEE CODE / EMPLOYEE NAME confusion (they differ in their
   last token).
2. **A positional band.** Summary labels always sit *below* the day grid. The
   band start is found by locating `"P (Total Present Days)"` — unique on the
   page and printed, so it reads reliably — and searching only below it.

**Result:** `total_man_hours` and `total_ot_hours` went **0% → 100%**.

> **Lesson.** Fuzzy string matching has *several* similarity functions and they
> are not interchangeable. `partial_ratio`, `token_set_ratio` and
> `token_sort_ratio` each failed differently here. Where two labels legitimately
> share words, no scorer alone is sufficient — a positional constraint is what
> actually makes it robust.

---

## 2. Header value bands — overlap is not membership

**Symptom.** `employee_name` = `'Shiv Shankan Apsinl -2026'` — the name field
swallowing the month/year value from the row above.

**Diagnosis.** The rule was "keep boxes overlapping the label's vertical band by
≥35% of the label height". Handwriting is written large and slanted, so a value
on line 2 overlaps the label on line 1 by well over a third of its height.

**Fix.** Require the candidate's **centre** to sit within the band
(`|value.cy − label.cy| ≤ 0.75 × label height`), not merely to overlap it. A
centre is unambiguous; an overlap is not.

**Result:** SAFEARTH01 went 75% → 88%.

---

## 3. Inline and bracket parsing — the invisible 0%

**Symptom.** KBR02 and SAMS01 both scored a flat **0%** on identity fields.

**Diagnosis.** Not an OCR failure at all. The values were read *perfectly*; we
were looking in the wrong place:

```
KBR02   'EMPLOYEE ID: 20000001'          label and value in ONE box
SAMS01  'ASHOK VARMA [30000001]'       no label at all
```

The extractor's only strategy was "find the label, then look to its **right**".
When the label and value occupy the same OCR box, there is nothing to the right.

**Fix.** Two general capabilities, not one-off hacks:

1. `inline_value()` — if the anchor box itself matches `LABEL: VALUE`, and the
   part before the colon is the label we wanted, take the part after it.
2. `find_bracket_identity()` — recognise `NAME [CODE]` in the top 30% of the
   page, requiring the bracketed part to contain a digit so
   `"Store Keeper (Senior)"` is not mistaken for an ID.

**Result:** SAMS01 **0% → 100%**, KBR02 **0% → 50%**. Overall 69.7% → 78.8%.

> **Lesson.** A 0% score usually means a wrong assumption, not a hard problem.
> Both pages were *easy*; the extractor simply never looked inside the label box.

---

## 4. The employee roster — built from the client's own data

The project plan called the employee master roster *"your biggest accuracy
lever"* and listed it as a blocker: the client hadn't supplied it.

**They didn't need to.** They have already typed thousands of these names into
the Excel files that ship alongside the scans. `tools/build_roster.py` harvests
them:

```
scanned 289 Excel files
DISTINCT EMPLOYEES    : 1,861
with an employee code : 1,394 (75%)
```

Against a ~3,000-person workforce, that is most of it — obtained with zero
client involvement.

### It resolves handwriting that OCR cannot read

| OCR read (handwritten) | Roster resolved to | Score |
|---|---|---:|
| `Lokesh Khurans` | **Lokesh Khurana** | 92.3 |
| `Naveen Trivedl` | **Naveen Trivedi** | 92.3 |
| `Vikran Prasad Sethl` | **Vikram Prasad Sethi** | 88.2 |
| `ANIR LAI RATHORF` | **Anil Lal Rathore** | 78.6 (via code) |

This works because names are **not free text**. They come from a closed set, so
OCR does not need to *read* the name — only to get close enough to identify
which of 1,861 people it is.

### The guard that had to be added

Naive auto-correction made accuracy **worse** (78.8% → 75.8%). On ADANI02 the
code `9100955164` had been extracted perfectly, then was overwritten with
`ISL900` — because a *different* employee with the same name exists at another
client.

**Rule adopted:** a name match is **not evidence about the code**. Personal names
are not unique across 1,861 people spanning 34 clients. The roster may therefore
**fill in a missing code, never replace one that was read off the page.**

> **Lesson.** "Correct the data using a trusted reference" is only safe where the
> reference is actually authoritative *for that field*. Here it is authoritative
> for spelling, not for identity.

---

## 5. Reverted: competitive anchor assignment

Two variants were implemented, measured, and **reverted**. Recorded because the
failure is instructive and to stop it being re-attempted.

**The problem being solved.** On handwritten pages, values sit ~20 px below
their label while form rows are only ~35 px apart, so every value falls within
tolerance of *two* labels.

**Variant A — nearest label wins.** Made it worse (78.8% → 66.7%), and in a
revealing way: values shifted *down* one row.

```
'Apsinl -2026'  cy=218
   MONTH & YEAR label   cy=197   distance 21   <- its true owner
   EMPLOYEE NAME label  cy=232   distance 14   <- nearer!
```

Because handwriting drops into the cell, a value is often physically **nearer to
the next label down** than to its own.

**Variant B — nearest label at or above.** Fixed the direction problem, but
still measured 66.7%, because these forms carry **two label/value pairs per
row**:

```
MONTH & YEAR: [value]   |   CLIENT: [value]
```

With only a y-ordering rule, the left column's label competes for the right
column's value. `client`, `project` and `location` all started coming back
empty.

**Conclusion.** Correct assignment needs **x-distance and y-distance together** —
a proper 2-D assignment problem (Hungarian algorithm over a label×value cost
matrix), not a 1-D heuristic. That is the right fix and it is not a large job,
but it was out of scope for the time available and the two cheap approximations
both regressed.

The code is left in the file, unapplied, with the measurement in the comment.

> **Lesson.** A change that fixes the page you are staring at can easily break
> four you are not. This is the entire argument for keeping a scored test set
> and re-running it after every change — without it, all three of these
> "improvements" would have shipped as regressions.

---

## What is still wrong

| Issue | Effect |
|---|---|
| Handwritten header bleed (IOCL30) | name/code/designation contaminated; stuck at 60% on handwritten pages |
| `present_days` missed on SAFEARTH01 | its summary block uses a different layout ("25 Days" in a merged cell) |
| KBR02 `employee_name` | inline parse gets the ID but not the name on that layout |
| Trailing-punctuation mismatches | `'…India Ltd'` vs `'…India Ltd.'` scored as wrong; arguably over-strict |

**The single highest-value remaining fix is the 2-D anchor assignment** — it
would address the handwritten bleed, which is the whole gap between 60% and the
87% already achieved on printed pages.

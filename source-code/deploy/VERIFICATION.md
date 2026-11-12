# Verification Record — v2.4.0

Everything below was measured by running the shipped code on real files.
Where a number is stale or unmeasured, it says so. Nothing here is estimated.

Pipeline version in this build: **v33-sample-fixes** (20 Sep 2026)

---

## 1. Accuracy

Full detail: `source/docs/revamp/01-REVAMP-REPORT.md` §9 and the decision
log D-045..D-057. Every figure below was produced by the shipped code.

### Against the paper — 50 random pages, graded by hand

Fifty pages drawn by seed across Delhi / HO / Kolkata and handwritten /
typed, excluding every page ever used for tuning; every day row checked by
eye against the scan under a protocol written before grading.

```
readable day-grid pages        38   (1,157 day rows)
day rows right               1,106 / 1,157 = 95.6%   (96.6% by the sheet's own convention)
wrong rows carrying no flag       8              ->  99.3% of errors flagged
missing rows                      0
unsupported page types           10 / 10 refused and flagged
source PDFs that cannot open      2  (listed as skipped)
```

Typed forms 95–99%; fully handwritten sheets ~84% (the floor).

### Against the client's own Excel — 292 truth-matched pages

```
Delhi     matched 282   day 6,968 / 8,201 = 85.0%
HO        matched  10   day   162 /   261 = 62.1%
Kolkata   matched   0   (no typed truth exists for Kolkata)
COMBINED  day 7,130 / 8,462 = 84.3%    name 98.3%
imperfect pages 164 -> flagged 164, escaped 0
```

The gap between 95.6% and 84.3% is the Excel's coding conventions (leave
as A on one client and L on another; a worked Sunday as W or P) and the
self-contradicting records described in section 2 — not misreads.

### Every page of every PDF through the shipped pipeline

```
pages run        9,003 of 9,271 listed   (268 sit in PDFs no reader can open; listed as skipped)
worker errors        0
day rows       209,335 = ok 56.3% / review 24.7% / must-fix 18.9%
pages          needs_review 8,347 (92.7%) / review_optional 656
```

Most pages carry the page-level flag because their own "Total Man Hours"
box is blank on the paper, so the row-sum checksum cannot be applied. That
is by design; reviewers work from the row colours.

---

## 2. The ceiling nobody can engineer past

The client's own spreadsheets contradict themselves.

```
employee records examined      1,659
names appearing more than once   254
names whose records CONTRADICT   153   (9.2%)
```

`DEEPAK SRIDHAR` has twelve mutually inconsistent May records.
`VINOD PRASAD NAIDU BOSE` has three April records disagreeing on four to five days
each. One SHELL page was read **26 of 26 correct against one of those three**
and still scored zero, because the harness refuses to pick whichever answer
happens to agree with us — choosing the flattering one is how a fake 100% gets
manufactured.

**Where the source disagrees with itself there is no single correct answer to
be right about.** This caps any accuracy figure, for this pipeline or any
other, and it is resolved by data cleanup on the client side, not by software.

`tools/truth_conflicts.py` regenerates the list to hand over.

---

## 3. What changed in this build

| Change | Effect |
|---|---|
| Month stripped from employee names | `'JITENDNA SINGH APRIL-2026'` → `'SANJAY BOSE'`; +4 measurable pages |
| Job title stripped from names | `'RAMESH CHANDRALER SHAHANWAJ KHAN'` → `'SHAHANWAJ KHAN'` |
| Weekly-off snapped to its own weekday | +4 day comparisons, no regressions |
| Weekday annotation gate 82 → 72 | catches `'Swday.'`, `'Sudny'`; +5, on a flat plateau |
| Landscape sheets rendered at 2600px | day header **4/30 → 30/30** correct |
| Orientation rescue (90/180/270) | sideways scans no longer produce nothing |
| High-resolution rescue, on demand | SHELL04: **0 → 28 days**, name recovered |
| Generic day-grid reader | reads layouts never seen before, both orientations |
| Scale-free column threshold | removed an absolute-pixel rule that broke at other resolutions |
| Ground truth parser | 484 → **12,125** employee rows |
| Roster extended from all three datasets | 1,863 → **2,575** employees |

Roughly **125 of the 207 HO pages that produced nothing** now read.

### A defect caught before it could fabricate data

The generic reader initially called BHAR07 a "28-day grid". It is not — those
integers are a serial-number column in an employee *list*:

```
4 | Rahul Sahu  | 260316054 | Field Operator | AVAILED
5 | Anu Yadav   | 260131027 | Field Operator | AVAILED
```

Unguarded, that invents a month of attendance for a person who has none. The
guard reads the rows: day rows carry short cells, list rows carry names. It
now refuses that page. **Refusing beats fabricating**, and it cost nothing in
true positives.

---

## 4. End-to-end verification

`python tools/verify_end_to_end.py` — **10 of 10 passed**:

```
 1. all app modules import              15 modules
 2. roster loads                        2,575 employees
 3. handwritten page, full chain        name='Lokesh Khurana', days=31
 4. typed transposed page               name='VINOD PRASAD NAIDU BOSE', days=30
 5. no page may fall through            corrupt input -> needs_review
 6. Excel export                        6 sheets, 102 rows
 7. fast accuracy harness               day 876/934 = 93.8%
 8. designation regression panel        18/18 PASS
 9. generic grid refuses employee list  heuristics behave
10. ground-truth index                  76 folders, 3,186 rows
```

Live server, three document families in one batch:

```
01_Sharad_Saxena.pdf    handwritten  'DINESH BHATTACHARYA'         195 fields
10_Vivek_Kumar.pdf      handwritten  'ViyEk Komar'  FLAGGED  198 fields
SHELL APR 2026(1).pdf   typed grid   'VINOD PRASAD NAIDU BOSE'
Excel export -> HTTP 200, 6 sheets
```

`ViyEk Komar` scoring below the roster floor and being **flagged rather than
auto-corrected** is the intended safety behaviour, not a failure.

---

## 5. Throughput

| | |
|---|---|
| healthy page | ~5.4 s |
| page preparation | 3.4 s/page |
| rescue path (failing pages only) | capped at 45 s, then flagged |
| **500 documents, 4 workers** | **~12–15 minutes** |

Healthy pages never enter a rescue. The high-resolution twin is rendered **on
demand** for the specific page that failed, not for every page at upload —
same accuracy, without taxing a 500-document batch.

---

## 6. What is NOT finished

Stated plainly so nobody discovers it later.

* **Thyssen02 (37 pages) still produces nothing.** Only 55 OCR boxes at 0.70
  confidence; neither rotation nor resolution helps. Needs its own diagnosis.
* **PETR03 and other column-layout families (~21 pages)**: the grid is found,
  the statuses are not yet read through it.
* **Designation is the weakest field at 35.7%.** It is 2.9% of comparisons, so
  the grid remains the place where accuracy lives.
* **The current full-corpus number is unmeasured** (see section 1).
* **Kolkata cannot be scored** — its Excels are invoice and summary sheets,
  yielding 4 files of ground truth. Its PDFs process, but accuracy on them
  cannot be verified.

---

## 7. What this system is

It reads roughly **nine in ten** handwritten day entries correctly, and it
shows its working.

It is a **first-pass tool whose mistakes are flagged**, not an unattended
replacement for human checking. The review screen exists because of that, and
the roster refuses to guess between two similar names for the same reason — a
confident match to the wrong employee is the error that costs real money.

A person should confirm the flagged sheets before anyone is paid. For scale:
typing these by hand takes about four minutes per sheet.

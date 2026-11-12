# Revamp decision log

Every decision, with the measurement that justified it. Newest at the bottom.
Format: date · decision · evidence · consequence.

---

## D-000 · 2026-09-13 · Freeze v25 before touching anything
**Decision.** Copy app/ tools/ Dockerfile requirements.txt and the clean eval
result into versions/v25-baseline/, with a RECALL.md that restores it in one
command.
**Evidence.** Clean v25 corpus run: day 73.2% / name 97.0% / overall 74.0% on
300 pages; safety 254/254 flagged, 0 escaped. This is the floor the revamp
must beat, measured the same way.
**Consequence.** Any later regression is one copy away from undone.

## D-001 · 2026-09-13 · State the ceiling before the target
**Decision.** The target "98-100%" is recorded as an aspiration, not a
commitment. The measurable ceiling is set by the ground truth.
**Evidence.** tools/truth_conflicts.py: 9.2% of the client's own ground-truth
rows contradict each other (same employee, same day, two answers). A pipeline
that is right on every page still scores wrong on ~9% of rows.
**Consequence.** Report accuracy two ways from here on: raw against the truth
file, and against the non-conflicting subset. The second is the honest
measure of the pipeline; the first is what the client will compute.

## D-002 · 2026-09-13 · Fix the measurement before the pipeline
**Decision.** The eval harness matched pages to truth at token_sort >= 80 with
no margin against the runner-up. Re-scored under the product's own rule
(score >= 82, margin >= 6 vs nearest different name).
**Evidence.** "Girish Kulkarni" vs "Mukesh Malhotra" = 80.0 exactly; "Sunit" vs
"Sumit" = 90.9. 9 of 300 matches were a different person and every one of
their days was scored as a pipeline error. Kept 291; day accuracy 74.9%.
**Consequence.** Harness will adopt the product rule (D-004). The gain is
real but small (+1.7 pts); the pipeline problem is genuine.

## D-003 · 2026-09-13 · The ceiling does not bite on this eval set (corrects D-001)
**Evidence.** 0 of the 291 kept pages have a self-contradicting truth
employee. The 9.2% conflict rate lives in HMEL19 / Thyssen02, which are not
in the scored set.
**Consequence.** D-001 stands for the full truth file; for the currently
scored 291 pages the measurable ceiling is ~100%. No excuse available here.

## D-004 · 2026-09-13 · Failure categories, measured (the step the skill demands)
**Fast set, 934 comparisons:** ok 853 · status_wrong 60 · status_empty 12 ·
row_missing 9. Row structure is essentially solved (9 misses). The loss is
in the VALUE read for a row that was found.
**Top confusion: W<->P = 38 of 81 misses (47%).** Then W->H 7.
**Corpus, 291 kept pages:** 44 perfect · 86 with <=2 wrong · 42 with >=15
wrong. Top-10 pages carry only 13% of residual -- errors are spread, but the
42 near-total failures (14% of pages) are a distinct structural block.
**Coverage:** 818 unmatched = 634 absent from truth (unscorable) + 184
near-miss, mostly abbreviated truth names ("Aswin R." for ASWIN
RAJALINGAM). Filename code recovers 33.
**Consequence.** Two levers, in order: (1) the 42 structural-failure pages --
find the layout families; (2) W<->P -- a post-OCR calendar/reconciliation
problem, not an OCR one. "Better OCR" is NOT the first move.

## D-005 · 2026-09-13 · The lever is ROW ALIGNMENT, not OCR
**Evidence.** ADN900 diff: 5:W/P 6:P/W 12:W/P 13:P/W -- Sunday's W landed on
Monday; every status slid one row. Frozen set: 27 of 81 errors are
got==truth[day-1], 8 are got==truth[day+1]: **43% of all day errors are a
one-row slide.** Structural failures cluster in GRSE01 (17) + ADANI02 (16).
Root causes seen in the images: (a) merged cells ("SUNDAY", "LEAVE") whose
box centre falls at a band edge; (b) GRSE01's form prints the date column
one row above the value columns because its middle header is 3 lines tall.
**Consequence.** Stage 3 (post-OCR) gets a calendar-alignment check: if
extracted W/SUN/SAT land on non-weekend calendar days but do after a +-1
shift, the shift is applied and the page is flagged for review. The
calendar is the arbiter. "Better OCR" would not have touched this.

## D-006 · 2026-09-13 · Ground truth uses different status conventions per client
**Evidence.** ADN900: the sheet says LEAVE on 14 days; truth records A on all
14. GRSE01: sheet says LEAVE; truth records L. Same word, two codes.
**Consequence.** Score two ways: strict, and with a per-client convention map
derived FROM the truth file (a client whose truth never contains L records
LEAVE as A). The second is the honest pipeline measure; the first is what
the client's spreadsheet would compute. Neither is "gaming" -- both are
reported. Per-client vocabulary measured next.

## D-007 · 2026-09-13 · The corpus loss is TWO clients, and the fast harness cannot see them
**Evidence.** Corpus checkpoint, 291 kept pages: ADANI02 880 errors (38% of
all), GRSE01 721 (31%). Together 69% of every day error in the corpus.
Frozen fast set: convention map moved it +1/934 -- the set has almost no
ADANI02/GRSE01 pages. Every "fast-to-fast" decision so far was made blind to
where the corpus actually loses.
**Consequence.** Build a second frozen set, eval_fast_v2, sampled to mirror
the corpus (ADANI02 + GRSE01 + IOCL + a control of the current set). Keep
the old one for regression only. Trap logged: a frozen set frozen before the
corpus grew measures the old corpus.

## D-008 · 2026-09-13 · Day number must come from the printed date cell, not band order
**Evidence.** ADN900: rules 406,427,451,475,498,522 -- six rules above the
05.04 row because the day-3 LEAVE merged cell is double-ruled. Date cell
"05.04" (y=532) and "SUNDAY" (y=534) land together in band index 5, which
the ordinal scheme calls day 6. The date TEXT says 5. The form already tells
us the day; the code counts bands instead.
**Consequence.** Stage-2 fix: parse the day from the date cell when readable
(typed sheets read it at ~1.0 confidence); use the band ordinal only as a
fallback, and flag the row when the two disagree. This is "read the printed
form" applied to the one column the code was still inferring.

## D-009 · 2026-09-13 · Exact mechanism of the slide (ADN900)
**Evidence.** af.extract on ADN900 emits 31 days for April; every row has
date=None although the OCR read "01.04.2026".."30.04.2026" at ~1.0. With no
anchors and n=31 in the 27..32 window, infer_days_by_position takes the
"trust POSITION over the ink, deliberately" branch and numbers rows 1..31.
Row 1 has no in_time (a spurious top band); row 2 holds real day 1. Every
status is therefore one row late, which is precisely the 5:W/P 6:P/W diff.
**Why it was never caught.** That branch was adopted on measured evidence
from handwritten IOCL grids, where dates merge across rows. The fast set is
41/49 IOCL30. A typed sheet with perfect dates was never in the loop.
**Consequence.** Three changes, each measurable on its own: (1) capture the
date column when it is readable -- today it is dropped; (2) when many anchors
agree on one offset, trust the anchors over position even inside 27..32;
(3) drop a leading band that has no date, no time and no status. Then the
calendar check (D-005) as the safety net for whatever remains.

## D-009a · 2026-09-13 · Correction to D-009: the date column was never the problem
**Evidence.** Wrapping learn_columns/extract_day_rows on ADN900: date column
learned at x 173..230; rows 1..30 carry '01.04.2026'..'30.04.2026'; only row 0
is None. My "date=None everywhere" came from printing the final day dicts,
which have no date key. 30 anchors, unanimous on offset 0, were discarded by
the 27..32 positional branch, which then numbered from offset +1.
**Consequence.** D-009 change (1) is withdrawn -- nothing to fix there.
Change (2) is the whole fix and (3) falls out of it: with offset 0 the
spurious row 0 maps to day 0 and is dropped. Implemented behind
trust_anchors=True (consensus: >=max(12, n/2) anchors, >=90% on one offset).
PIPELINE_VERSION -> v26-anchor-consensus. Measure old fast set first: must
not fall below 91.3% (the IOCL guard), then frozen_v2.

## D-010 · 2026-09-13 · Anchor consensus: right on target, fails the guard as first written
**Evidence.** ADN900: 10/17 -> 17/17 correct on days 1-17, 31 -> 30 days,
5=W 6=P 12=W 13=P. Old fast set (IOCL guard): 853 -> 845 day hits
(91.3% -> 90.5%). A/B is clean: trust_anchors=False reproduces 853 exactly.
**Decision.** NOT accepted at (frac>=0.5, agree>=0.9). Per the loop, a
change that lands below the guard is swept, not shipped. Two candidate
discriminators: tighten the bar, or require anchors to step by exactly one
row-to-row (a typed-sheet property that merged handwriting cannot fake).
Sweep results recorded in D-011.

## D-011 · 2026-09-13 · Sweep result: unanimity is the only guard-safe bar
**Evidence (old fast set, baseline 853 day hits).**
    agree 0.90 / 0.95 / 1.00
    frac>=0.5, 0.7, 0.9        -> 845 / 845 / 853   (flat in frac)
    step-by-one variant, same  -> 845 / 845 / 853   (flat; no extra signal)
Only ANCHOR_AGREE=1.0 returns the baseline; every change on the old set
vanishes (IOCLMS MAY p3 -8, p6 +2, Timesheet p3 -2 all gone). A flat
surface in frac means that value is safe; the cliff sits entirely on agree.
**Decision.** Ship ANCHOR_AGREE=1.0, ANCHOR_MIN_FRAC=0.5 as constants.
ADN900 stays 17/17 at unanimity (its 30 anchors agree completely).
**Open risk, to be measured not assumed.** A typed sheet with ONE misread
date has 29/30 agreement and would fall back to the slide. frozen_v2
(ADANI02 30, GRSE01 25, IOCL30 15, Avaada01 4) decides whether 1.0 holds or
a "step-by-one over the anchored run" relaxation is needed there.

## D-012 · 2026-09-13 · v26 anchor consensus ACCEPTED on the corpus-faithful set
**Evidence (frozen_v2: ADANI02 30, GRSE01 15, IOCL30 12, Avaada01 4; 50 matched, 1,456 comparisons).**
    trust_anchors     strict            convention
    False (old)       1142/1456 78.4%   1194/1456 82.0%
    True  (new)       1165/1456 80.0%   1220/1456 83.8%
    ADANI02           79.9 -> 83.2%     86.7 -> 90.3%
    GRSE01            66.0 -> 66.0%     (different mechanism; untouched, as predicted)
    IOCL30            90.7 -> 90.1%     (-0.6 on 12 pages, ~2 comparisons)
    Sweep ANCHOR_AGREE 0.90 / 0.95 / 1.00 -> 1160 / 1160 / 1165 strict.
Unanimity is best on BOTH sets: on ink it is inert (old set 853=853), on
print it is the top setting. The brittleness concern in D-011 did not
materialise. ADANI02's 7-point strict-vs-convention gap is entirely the
LEAVE-as-A convention (D-006), not the pipeline.
**Decision.** Keep v26-anchor-consensus. Next lever: GRSE01 (31% of corpus
errors, 66.0%), whose failures are merged SAT/SUN cells emitted as None and
a one-row skew between the date column and the value columns.

## D-013 · 2026-09-13 · GRSE01 and Avaada01 mechanisms, exactly
**GRSE01 (31% of corpus errors, 66.0% on v2).** Two causes, measured on p3:
  (a) _WEEKOFF_RE matches SUNDAY and W/O but not the bare "SAT"/"SUN" this
      form prints as a merged cell across the time columns -> 5 weekly-off
      rows per page emit None.
  (b) The value grid sits ~0.75 row below the date column ("SAT" for the
      4th at y=410; date 04 at 392, date 05 at 416) because the middle
      header block is three lines tall. Rule bands are page-wide, so the
      date cell and its own value fall in adjacent bands.
**Avaada01 (4 pages, 0/123).** A sideways-scanned THREE-employee grid: days
down the page with weekday labels, employees across. The pipeline read the
first name ("MD ATIF"), zero days, no grid. The orientation rescue never
ran: its gate required no anchors found, and the header gave a name.
**Decisions.** (1) WEEKDAY_WORD_OFF: a bare SAT/SUN/W-O filling a VALUE
cell with no positive hours => W. Value fields only -- the date field on
Avaada-style forms carries the weekday on every row and a worked Sunday
must stay P. (2) Orientation gate widened to "zero days", regardless of
anchors. (3) The skew (b) is left to Stage 3's calendar-alignment check
first; if a residual remains, column-aware banding (pair date-column and
value-column bands by ordinal) is the structural fix. Each measured alone.
**Noted.** IOCL30 'Timesheet.pdf' p3 lost 2 comparisons on v2 under
unanimity; 2 of 302, recorded, not chased.

## D-014 · 2026-09-13 · WEEKDAY_WORD_OFF ACCEPTED; PIPELINE_VERSION -> v27-weekday-word
**Evidence (frozen_v2, 1,456 comparisons).**
    WEEKDAY_WORD_OFF   strict          convention    GRSE01   ADANI02  IOCL30
    False              1165  80.0%     83.8%         66.0%    83.2%    90.1%
    True               1207  82.9%     86.7%         76.8%    83.2%    90.1%
    Old fast set (guard): 853/934 = 91.3%, unchanged.
Every gained comparison is on GRSE01; the other two clients did not move
by a single comparison. That is what an isolated fix looks like.
**Cumulative since v25 on v2:** strict 78.4 -> 82.9 (+4.5), convention
82.0 -> 86.7 (+4.7). GRSE01 66.0 -> 76.8. ADANI02 79.9 -> 83.2.
**Orientation gate:** widened; Avaada01 now rotates (rotated=90) but still
yields 0 days -- the failure moved one stage downstream. Diagnosed next.

## D-015 · 2026-09-13 · Avaada01: parser gap closed; a wrong-person risk exposed
**Evidence.** generic_grid._as_day('1-Jul') was None: the reader had no
day-month form. Added (general, not client-specific). Rotated page now:
axis=(row, 22), 3 blocks. Full pipeline: name='BHASKAR BHANDARI', 22 days,
rotated=90, grid=row -- from 0 days.
**New defect surfaced.** All three blocks carry the SAME name. The reader's
name picker looks LEFT of each band; on this transposed sheet the names sit
in the header row ABOVE each column, so every block gets the first person-
like string it finds. The pipeline then keeps max(blocks by days) = MD ATIF's
column of 21 L, and files it under BHASKAR BHANDARI (truth: 31 P). A wrong
person's attendance under a right name is the one outcome the safety
posture exists to prevent. Status check below decides urgency.
**Also.** My import of re was missing from generic_grid -- the first v2/guard
run after the edit was inert because every grid call raised inside a bare
except. Fixed; re-measured: v2 1207/853 unchanged (grid path is not
exercised by either fast set), Avaada verified directly.

## D-016 · 2026-09-13 · GRSE01's Sundays are killed in RECONCILE, not in reading
**Evidence (GRSE01 p3, v27).** day 12: nh='SUN', status was W from
WEEKDAY_WORD_OFF, then reconcile set status='P' with _inferred "worked day:
marked W but falls [off the modal off-weekday]". Same on days 5, 19, 26.
The snap logic assumes ONE weekly-off weekday; it votes Saturday from the
SAT rows and flips every Sunday to P -- on rows with no in/out/hours at all.
**Also.** The stated totals on this form are misread: W/O=2 PH=8 (sheet:
8 and 2), Leaves='08:30'. The label column and value column are skewed by
the same header-height offset as the day grid, so reconcile is filling
from wrong numbers. Summary anchoring measured next.
**Also.** ±1 slide is still 33% of residual v2 errors under v27 (down from
43%). Whether whole-page or local decides if a calendar shift is a tool or
a hazard -- measured, not assumed.
**Decision.** Evidence guard on the flip: a W is never overridden to P
unless the row carries positive work evidence. Zero-evidence W stays W.
General, one condition, measured on v2 next.

## D-017 · 2026-09-13 · Whole-page calendar shift REJECTED as a tool; evidence definition fixed
**Slide concentration (frozen_v2, v27).** Pages whose errors are >=70% a
consistent +-1 slide with >=5 rows: 3 (ADANI02 p1, GRSE01 p3, IOCL30 p3).
Pages with only local slides: 23. A whole-page shift would fix three pages
and could damage twenty-three. D-005's proposed Stage-3 shift is withdrawn
on this measurement. The residual slide is local -- merged cells and the
top-of-grid skew -- and is structural work, not a post-hoc correction.
**Evidence bug.** reconcile._work_evidence counted any non-empty value in
the four work cells. GRSE01's merged "SAT"/"SUN" lands in normal_hours, so
a weekly-off row scored as "carries recorded hours" and the demotion rule
(1b) flipped it to P. Redefined: evidence is a clock reading or a positive
number of hours. A word is not work. Flag EVIDENCE_POSITIVE_ONLY.
**Summary block.** On GRSE01 the label/value geometry is CORRECT by nearest
y (Leaves 1044->'2' 1051, W/O 1070->'8' 1074, PH 1094->'2' 1100), yet the
record holds W/O=2 PH=8 Leaves='08:30'. The picker is not pairing by
nearest y. Located next; the misread totals are what licensed the
demotion in the first place, so this is the second half of the same fix.

## D-018 · 2026-09-13 · EVIDENCE_POSITIVE_ONLY ACCEPTED at 852 (one named row below 853)
**First draft (regex clock + hours, four cells):** v2 1245 (85.5%), guard
851. Two rows lost, both VSPL p1: day 26 hours='C/O$$', day 27 hours='140/5'.
**Repair:** all five cells restored (ot_hours had been dropped); evidence =
carries a digit AND first number > 0. Admits '19100', '8:', '0800', '140/5'.
Guard 852; v2 unchanged at 1245 / 85.5%, GRSE01 86.6%.
**The one remaining row.** VSPL day 26, hours='C/O$$', truth P. The sheet
says comp-off; the client's truth counts it present. The OLD rule kept it P
only because junk text counted as work. That is an accidental pass, not a
capability. Accepted, above the skill's documented floor (90.2%), with the
row named here so nobody later mistakes it for a regression to chase.
**Cumulative since v25 on frozen_v2:** strict 78.4 -> 85.5 (+7.1),
convention 82.0 -> 89.3 (+7.3). GRSE01 66.0 -> 86.6 (+20.6).
PIPELINE_VERSION -> v28-evidence-summary (reconcile, generic_grid, summary
picker all changed since v27).

## D-019 · 2026-09-13 · Summary picker: nearest-line, summary cells ONLY. ACCEPTED.
**First attempt** re-sorted value_right_of by (column, |dy|) for every
caller. Summary W/O and PH came right (8, 2) but Leaves still took a grid
cell ('08:30' at x=830, nearer column than the true '2' at x=966), and the
HEADER path -- which concatenates every box right of a label in reading
order -- pulled a same-line designation into a name on VSPL p1 ('Ghanshyam
Goutam Safety Officer'). The page fell out of matching: old set went to
829/903, names 29/30. A moved denominator, the trap the skill names.
**Fix.** nearest_line= parameter, passed True by extract_summary alone,
sorting by (|dy|, x). Header order untouched.
**Evidence.** Old set 852/934, names 30/31 (restored). v2 1245/1456 =
85.5% (held). GRSE01 p3 totals W/O=8 PH=2 Leaves=2 (sheet: 8/2/2).
Flag SUMMARY_NEAREST_LINE for A/B.

## D-020 · 2026-09-13 · v28 residual, categorised (frozen_v2: 211 errors of 1,456)
    status_wrong 151 (72%) · row_missing 41 (19%) · status_empty 19 (9%)
    top pairs: A->L 54 · P->W 33 · P->missing 27 · W->P 21 · C->P 16 ·
               A->empty 15 · W->missing 11 · C->None 6 · A->W 6
    per client: ADANI02 wrong 109 (54 are A->L) / GRSE01 missing 28, wrong 24 / IOCL30 wrong 18, missing 9
    end-to-end suite: 10/10 at v28
**Reading.** 54 errors (26%) are the ADANI02 LEAVE-as-A convention: the
pipeline reads LEAVE, the client's file says A. Correct reads, scored
wrong; visible as the strict/convention gap and NOT a pipeline target.
Fixable blocks, by size: P<->W 54 (26%), row_missing 41 (19%, GRSE01's
skewed top rows and tail), comp-off 22 (10%). 51 of the 151 wrong are
still a +-1 slide, i.e. local structure.
**Ceiling, restated with numbers.** If every fixable block were closed, v2
strict lands near 93-94% and convention near 97-98%. Strict cannot reach
98% on ADANI02 while its truth file encodes LEAVE as A. That is the
client's data, and the report says so.

## D-021 · 2026-09-13 · P<->W decomposed; comp-off is an OCR-garbling problem; GRSE01 is misaligned throughout
**P->W (33).** Sun 15 / Mon 14. The Mondays are Sunday's W slid one row
(local slide, D-017). The Sundays: truth P, pipeline W, 21 of 33 with
hours -- the employee worked. IOCL's truth records an inked Sunday as W
(the existing rule 1b deliberately never demotes the off-weekday, measured
on IOCL); ADANI02's truth records it as P. Two clients, two conventions.
**W->P (21).** Sun 12 / Sat 3, ALL with hours. GRSE01 9: the SAT/SUN merged
row absorbs the next row's 09:00 through the skew and scores as worked.
IOCL 8: handwritten Sunday with times and no W marker -> P; truth W.
**Comp-off (23, all ADANI02).** Regex matches 3 of 23. OCR yields 'C/0',
'COff', 'Agaunst', or splits 'C/O against duty on <dates>' so the row's
cells hold only the dates ('15.03. 2026 24.03. 2026'). A fuzzy rule: a
comp-off head (C/O, C/0, COFF, COMP) OR a row whose value cells hold >=2
calendar dates and no clock reading.
**GRSE01 missing rows (28).** Scattered over days 1..20 across 15 pages,
not just the top and tail. Page-wide rule bands cannot serve a form whose
date column and value grid are offset; the structural fix is column-aware
banding: detect rules inside the date column and inside the value columns
separately, pair by ordinal.
**Order.** (1) comp-off rule, small and isolated. (2) column-aware banding.
(3) per-row confidence layer, which is additive and does not move the
metrics. Worked-Sunday convention goes in the report as a per-client
setting, not a rule.

## D-022 · 2026-09-13 · Column-aware banding REFUTED before it was built; comp-off gate corrected
**Comp-off.** First gate was "no positive hours"; _positive_hours reads
'15.03. 2026' as 15 hours, so the rule was blocked on exactly its target
rows and the fall-through inferred P from the same "hours". Re-gated on
"no clock reading". Unit shapes all correct (dates-only, C/0, COff, C.
Off, remarks phrase -> C; worked rows -> P). v2 still 1245: the C is being
lost somewhere between _infer_status and the score. Instrumented.
**Banding.** detect_row_rules_in() added (rules inside one x-band). On
GRSE01 p3: date-column rules [404, 428] vs value-column [406, 429] -- a
2px difference. The first "SAT" (y=410) sits in the SAME ordinal band as
the 05-Apr date cell (y=416) in BOTH sets. The offset is not in the rules;
the form prints the weekday label one row below its calendar date, and the
client's truth was made from the calendar (Apr 4 2026 IS Saturday).
**Decision.** Column-aware banding withdrawn -- it would have reproduced the
form's own error faithfully. The recoverable signal is the WORD: a row
whose value cell says SAT/SUN names its own weekday; snap it to the nearest
calendar Sat/Sun within +-1 day. Word-snap is general, evidence-based, and
replaces the modal-weekday vote for rows that carry the word.

## D-023 · 2026-09-13 · Two "pipeline" errors that were the harness
**Comp-off.** Instrumented end to end on ADANI02's 23 truth-C rows:
    (raw, final) = ('C','C') x14   ('P','P') x9
So 14 rows were read C by _infer_status AND survived reconcile as C -- and
were scored wrong, because eval_fast.norm_status('C') returned None while
norm_status('C/O') returned 'C'. The scorer knew the long form and not the
letter. Fixed in the harness; the pipeline change (D-022) had been working.
The other 9 carry full clock times (12:00-22:00, 10h): worked days the
client's file codes as C -- the duty side of a comp-off. A truth
convention, alongside LEAVE-as-A (D-006) and worked-Sunday (D-021).
Three of those nine also show the annotation's year fragment ('2026')
sitting in the hours cell and being read as 2,026 hours by
_positive_hours; a year is not hours. Noted for a separate guard.
**GRSE01 missing rows (28).** 23 come from ONE page: p3 of 'Adobe Scan 03
Aug 2026 (1).pdf', 11 physical rows, days 24-29 -- a month photographed
across three pages, each scored against the full 31-day truth. The other
five are single dropped rows on full pages. The pipeline read the paper.
**Consequence.** The eval harness needs a partial-page flag (day_rows < 20
with a 28+ day truth) so split scans are reported, not charged. Logged as
harness work; not a pipeline target.

## D-024 · 2026-09-13 · Harness normaliser fixed (tools/eval_100.py); comp-off gain confirmed
**Where it was.** eval_fast imports norm_status from tools/eval_100, not
tools/truth. Its STATUS_ALIASES knew "CO" and "C/O" and not "C". Aliases
added ("C", "COFF", "COMP OFF", ...). tools/truth.py table aligned; the
clause I had wedged into truth.norm_status removed -- one mechanism.
**Evidence (frozen_v2).** strict 1245 -> 1259 (85.5 -> 86.5%), convention
1300 -> 1314 (89.3 -> 90.2%). ADANI02 strict 83.2 -> 85.0, conv 90.3 ->
92.2. GRSE01 and IOCL30 unchanged to the comparison; old set 852/934
unchanged (no comp-off rows there). Exactly the 14 rows D-023 predicted.
**Cumulative v25 -> v28 on frozen_v2:** strict 78.4 -> 86.5 (+8.1),
convention 82.0 -> 90.2 (+8.2). GRSE01 66.0 -> 86.6. ADANI02 79.9 -> 85.0
(86.7 -> 92.2 with its conventions). IOCL30 90.7 -> 90.1 (-2 comparisons,
named in D-013/D-018).

## D-025 · 2026-09-13 · Weekday-word snap ACCEPTED; per-row confidence layer built
**Word snap (reconcile, WEEKDAY_WORD_SNAP).** A bare SAT/SUN in a value
cell is carried on the day dict (_weekday_word) and, if the row's calendar
day is not that weekday but an adjacent day is and that neighbour holds no
W and no work evidence, the W moves there. Trigger is the WORD, not the
row's status: through GRSE01's skew the merged "SUN" shares a band with
the next row's 09:00, so that row is a worked Monday carrying a Sunday's
label -- the label still names the adjacent day.
    v2 strict 1259 -> 1260 (GRSE01 86.6 -> 86.9); guard 852 -> 856 (+4:
    handwritten IOCL Sundays written one row off). GRSE01 p3 21 -> 23/30,
    days 4 (Sat) and 5 (Sun) both right for the first time.
**Row confidence (app/rowconf.py).** score in [0,1] + flag ok/review/
must_fix + named reasons, from signals the pipeline already holds: empty
status, day-level validation issues, status-vs-evidence contradiction (P
with no hours; W/A/L/H with hours), inferred-not-read, cell OCR
confidence, reconcile moves. Wired after validate in process_page and
after re-validate in save_page, so a reviewer's edit clears its own flag.
Exposed on every day dict (_row_conf, _review, _review_why) and as
record._row_summary. UI: Conf column, row tint for must_fix, summary strip.
PIPELINE_VERSION -> v29-rowconf-wordsnap (cached records lack the fields).

## D-026 · 2026-09-13 · Evaluation layer verified end to end; v29 frozen
**Verification.** Browser extension unavailable, so verified at the API:
page 13 re-read under v29 -> _row_summary {ok 6, review 20, must_fix 5};
per-row _row_conf / _review / _review_why present on all 31 rows (e.g.
day 3: P, 0.45, review, "low OCR confidence on a cell (0.51)"). Edited
review-page script passes `node --check`. Audit export emits one row per
day with the row score and reason (smoke-tested: day_2 W 0.6 warn, day_3
None 0.0 block). Server health reports v29-rowconf-wordsnap.
**Snapshot.** versions/v29-revamp with RECALL.md (one-command restore),
alongside versions/v25-baseline. Both recallable.

## D-027 · 2026-09-13 · Year-is-not-hours guard: MEASURED WORSE, REVERTED (flag off)
**Hypothesis.** '2026' in an hours cell (a comp-off annotation's date
fragment) is read as 2,026 hours and makes a comp-off row Present; a
4-digit 19xx/20xx value with no separator is a year.
**Evidence.** frozen_v2 strict 1260 -> 1259 (-1); ADANI02 85.0 -> 84.9.
The 3 target rows do not gain (with no hours they fall to None, not C --
the fragment is not two dates), and one genuine worked row loses: a clock
time 20:00 reaches the cell from OCR as '2000', which the guard calls a
year. '1930', '2000', '2026' are indistinguishable without a separator.
**Decision.** Reverted: YEAR_IS_NOT_HOURS = False, code retained behind
the flag. A measured failure is a result. The 3 rows stay in the
comp-off convention block (D-023) where they belong.

## D-028 · 2026-09-13 · Two contained changes: one reverted (no effect), one kept (identity)
**MERGED_OFFSET_FOLLOW (reconcile) — REVERTED, flag off.** Hypothesis: on a
form whose SAT/SUN snaps establish a one-row offset, LEAVE/PH/A merged
cells sit the same way and can follow. Measured: frozen_v2 1260 -> 1260,
guard 856 -> 856. Mechanism: each displaced annotation occupies the row
the previous one vacated (GRSE01 p3: 2:L 3:L where truth is 1:L 2:L 3:H),
so no target row is ever empty and the follow never fires. A correct
version must shift the whole run atomically; ~3 rows per page on one
client does not justify it unmeasured. Code retained behind the flag.
**NAME_NEAREST_BLOCK (generic_grid) — KEPT.** On a dense multi-employee
sheet the +-4*tol name window spans neighbouring blocks and "longest"
handed one name to all three (D-015). Nearest-to-centre now: Avaada01
blocks read MD ATIF / BHASKAR BHANDARI / BHASKAR BHANDARI (third should be Shankar --
a single word, outside _looks_like_person). Harness-neutral (Avaada pages
are unmatched in v2). Kept because the block the pipeline RETURNS (most
days = MD ATIF's) now carries the right name: a wrong person's attendance
under a right name was the safety risk, and it is closed for that block.

## D-029 · 2026-09-13 · Stage 1 probe, first pass: CLAHE REJECTED; run killed by memory
**Setup.** tools/probe_preocr.py: the 32 handwritten pages of the guard
set, each re-OCR'd from its stored image under one technique, re-extracted
and re-scored on the same 571 day comparisons. Structural fixes (D-011..
D-025) already in place, so any gain here is Stage 1's own.
    baseline (current preprocess)     528/571 = 92.5%
    CLAHE (clip 2.0, 8x8)             494/569 = 86.8%   -> REJECTED (-5.7)
CLAHE amplifies the paper texture and the bleed-through as much as the
ink; the OCR engine's own normalisation was already doing the useful
part. Adaptive threshold completed its OCR but the result line was lost:
the run was piped through grep, which buffers to a file, and the process
was killed by the OS for low memory before the flush.
**Memory.** free 0.1 GB, swap 11.5/12.3 GB. Ollama is resident at 3.2 GB
(needed for the GCC demo; not touched). Non-local-means denoise dropped
from the re-run as the heaviest technique. Re-run: adaptive, unsharp,
morphological close, `python -u` straight to a log.
**Consequence.** Nothing heavy (image build, corpus eval) starts until
the probe finishes; both would contend for the same ~1 GB headroom.

## D-030 · 2026-09-13 · Adaptive threshold REJECTED: it breaks matching, not just reading
    adaptive (Gaussian, block 31, C 12)   86/149 = 57.7%
The denominator is the finding. 571 comparisons became 149: hard
binarisation damaged the printed header enough that most pages lost their
employee name and fell out of matching altogether, and the pages that
survived read at 57.7%. On handwriting this OCR engine wants grey levels;
a binarised stroke loses the anti-aliased edge the recogniser was trained
on. Rejected without reservation. (975s under swap pressure; free 0.08 GB.)
**Stage 1 verdict so far.** baseline 92.5% > CLAHE 86.8% >> adaptive
57.7%. The existing preprocess -- deskew, illumination flattening, resize
-- is the best of the tested set. Unsharp and morphological close are
running; adopted only if they beat 92.5% here AND hold on frozen_v2.

## D-031 · 2026-09-13 · Unsharp mask REJECTED
    unsharp (sigma 2.0, gain 1.6)   505/569 = 88.8%   (baseline 92.5%)
Sharpening lifts halo noise around every stroke; the recogniser reads the
halo as extra ink on the digit forms it is least sure about. -3.7 points,
and two comparisons lost to matching. Rejected.

## D-032 · 2026-09-13 · Stage 1 verdict: the existing preprocess stays
    morph_close (2x2 ellipse)   455/511 = 89.0%   (baseline 92.5%; 60 comparisons lost to matching)
Bridging broken strokes also bridges adjacent digits ('1' and '0' become
one glyph) and thickens printed labels enough to cost name matches.
**Verdict, 32 handwritten pages, same comparisons throughout:**
    baseline   92.5%   (528/571)
    morph      89.0%   (455/511)   -3.5, and 60 comparisons unmatched
    unsharp    88.8%   (505/569)   -3.7
    CLAHE      86.8%   (494/569)   -5.7
    adaptive   57.7%   ( 86/149)  -34.8, and 422 comparisons unmatched
    denoise    not run (memory)
Every technique tested made handwriting WORSE for this engine, and the
aggressive ones broke the printed header too. This is consistent with
D-004/D-009: the loss was never in the pixels. Stage 1 keeps deskew,
illumination flattening and resolution-by-shape (ADR-7) and adds nothing.
A measured null result closes the question the brief opened.

## D-033 · 2026-09-13 · v29 corpus eval: killed for memory at 125 rows; interim Delhi 85.2%
**Interim, first 100 matched Delhi pages (v29):** day 2510/2946 = 85.2%.
The v25 clean run finished Delhi at 74.1% (289 pages). Same folders in
the same order, so the comparison is fair for the stretch scored; the
first folders are ADANI02, where the fixes landed hardest, so the final
Delhi figure will likely be lower than 85.2 and still well above 74.1.
**Why it died.** The host had 0.07 GB free with Ollama serving two models
(3.68 + 3.12 GB) for another project. eval_corpus is single-process
(~1 GB); it was the process the OS chose. Not restarted by hand and Ollama
not touched: the earlier permission to stop it was for a different moment.
**Mechanism to finish anyway.** tools/eval_corpus_supervised.sh relaunches
the eval after each kill; the checkpoint (version-stamped, D-002) means
each attempt resumes where the last died. Ollama's footprint has swung
between 0.1 and 6.8 GB over the afternoon, so progress accrues in the gaps.
Cost: wall time, not correctness.

## D-034 · 2026-09-14 · Avaada01 blocks fully named; harness-neutral
The nearest candidate within one row-height of a block's centre may win
even when it is a single word: "Shankar" fails the two-word person test,
and a two-word neighbour a row away used to be preferred. Guarded: clean
alphabetic, >= 4 chars, not form furniture.
    Avaada01 blocks: MD ATIF / BHASKAR BHANDARI / Shankar   (was: all BHASKAR BHANDARI)
    frozen_v2 1260 (unchanged) · guard 856 (unchanged) · e2e 10/10
Closes the wrong-person risk raised in D-015 for the whole page.

## D-035 · 2026-09-14 · v29 corpus eval: Delhi FINAL
    Delhi, 942 pages, 295 matched (v25: 289):
        day_status      6848/8589 = 79.7%   (v25: 6231/8414 = 74.1%)   +5.6
        employee_name    285/295  = 96.6%   (v25: 280/289  = 96.9%)   -0.3
        OVERALL         7133/8884 = 80.3%   (v25: 6481/8703 = 74.8%)   +5.5
The interim 81.8% at 282 pages settled to 79.7% over the last 13 matched
pages -- the harder tail, as predicted in D-033. Six more pages matched
than under v25 (better names => more pages scorable), which widens the
denominator and is the honest direction. HO (247 pages, thin truth) and
Kolkata (29) still scoring; blended final will sit below Delhi's.


## D-036 · v29 corpus eval FINAL
    Delhi   295 matched   day 6848/8589 = 79.7%
    HO      11 matched   day 146/292 = 50.0%
    Kolkata 0 matched   day 0/0 = n/a
    COMBINED 306 matched, 8,881 comparisons: day 78.8%  name 96.7%   (v25: 73.2 / 97.0)
    SAFETY: imperfect 207, flagged 207, ESCAPED 0; clean-and-correct 99/99
    Elapsed 72,348s (20.1h, supervised through Ollama contention; 1 attempt, 0 kills after 15:32).
    Two safety counts appear and both are correct: the eval's own printout
    (205/205, clean-and-correct 1/1) counts a page imperfect on DAYS only and
    "clean" as status==clean; finalize_report.py (207/207, 99/99) counts a
    wrong NAME as imperfect too and "clean" as zero errors. Escaped = 0 under
    both. HO/Kolkata unchanged from v25 (11 and 0 matched): thin truth, not
    pipeline movement. Release: tools/release_v29.sh built 2.2.0 arm64+amd64,
    2 OCR models baked in each, ZIP 598 MB / 152 entries, integrity verified.

## D-037 · 2026-09-19 · Manual verification on 7 unseen pages; summary-P fix ACCEPTED
**Method.** Seven pages the pipeline was never tuned on (no frozen set, no
diag page), run through process_page, every day row graded by eye against
the image. Record: data/_manual_verify/grades.md.
**Result vs the paper.** Day status 160/183 = 87.4% on the six readable
pages (74.8% counting a rotated biometric printout the pipeline cannot
read and correctly refused). Wrong 23: blank/worked-Sunday convention 13,
merged W/O one row early on a new Siemens form 8, dropped/spurious row 2.
**Silent wrong rows: 5 of 23** (mv03 x1, mv05 x4). Page-level: 7/7 flagged.
Times on typed values ~150/155 right; the P total read on 1/7 pages.
**Fix 1 (accepted).** extract_summary stopped collecting at the first
other-field label; sorted by nearest line that label came first and P was
None. Now candidates are bounded LEFT of the next label. P correct 6/6
readable pages (31,30,31,23,27,28); mv05 man-hours 4 -> 216; mv06 leaked
"2" -> None. frozen_v2 1260 / guard 856 unchanged. Flag
SUMMARY_BOUND_BY_NEXT_LABEL.

## D-039 · 2026-09-19 · Hours bound split: >12 WARN, >24 BLOCK. ACCEPTED.
Haldia (mv06) writes the day's total hours (15:07) in the NORMAL WORKING
HOURS column; config.NORMAL_HOURS_MAX_PER_DAY=12 raised BLOCK on 29/31
rows and the two genuinely wrong rows (14, 28: worked Sundays) were
indistinguishable from the noise. Twelve is a policy figure; twenty-four
is the physical limit. After: mv06 rows ok 26 / review 2 / must_fix 3, and
days 14 and 28 are among the 3. e2e 10/10. Flag precision, not recall,
was the problem; recall is unchanged.

## D-038 · 2026-09-19 · Siemens (mv05): date column, header band, two-date bands
**Chain of causes on one unseen typed sheet (8 wrong, 4 silent):**
  1. "Total OT Hours" (summary, y=1414) fuzzy-matched the TOTAL HOURS column
     header; the column landed at x 67..266 over the date column.
     -> COLUMN_HEADERS_IN_BAND: headers learned within +-6 row-heights of the
     DATE header. Removes the bogus column. Costs 4 on frozen_v2 (5 ADANI
     pages, numbering identical, value cells change) -- under examination.
  2. The DATE header box (189..240) is narrower than the left-aligned dates
     (109..203). -> DATE_COL_TO_LEFT_EDGE: the learned date column extends
     left to the grid's left edge. Harness-neutral.
  3. rule_bands fitted a 32px ladder to 27.5px rules; one band swallowed
     dates 05 and 06; anchors split 25/5; positional numbering ran one low.
     -> SPLIT_TWO_DATE_BANDS: a band holding two date cells is split on the
     printed rule between them. First draft (any two "dates") over-
     segmented handwriting: guard 856 -> 809. Gated on consecutive day
     numbers, both cells >= 0.85 confidence, and a real rule between:
     guard 855, mv05 22/31 -> 31/31 (all four W/O on the right day).
**State.** e2e 10/10. frozen_v2 1256 (-4 vs 1260, item 1). Guard 855 (-1).
Both residuals named and being traced before acceptance.

## D-040 · 2026-09-19 · Header-band learning WITHDRAWN on the number; stacked-header merge retained (inert)
With COLUMN_HEADERS_IN_BAND on, the inferred TOTAL HOURS column landed on
ADANI's employee-signature block ("my", "owy", "QUH" became hours). Two
fixes were tried and both worked as designed: INFER_COL_CAP_WIDTH (an
inferred column is 1.2x median width beside its left neighbour) and a
stacked-header merge ("TOTAL"+"HOURS" -> one box; first draft dropped the
pair on x-order, fixed). With the merge, ADN903 learns EVERY column
correctly (ot 516..642, total 607..737). And frozen_v2 still reads 1255
vs 1260 with the flag off: with correct columns the "C/O against duty on
<dates>" merged annotation distributes across ot/total cells and the
comp-off rule no longer sees it in normal_hours. The bogus bottom-of-page
match had been, by accident, keeping that text together.
**Decision.** Flag OFF, code retained. The comp-off detector's dependence
on WHICH cell the annotation lands in is the real defect, logged for a
later pass. Withdrawing beats shipping a correct column model that
scores worse today.
**Final state after the manual-verification fixes (D-037..D-040):**
frozen_v2 1260 / 1315 (86.5 / 90.3), guard 856 (91.6), Siemens mv05
22/31 -> 31/31, e2e 10/10. PIPELINE_VERSION -> v30-manual-verified.

## D-041 · 2026-09-19 · Two evidence rules from the paper, ACCEPTED (reconcile)
**EMPTY_SUNDAY_IS_OFF.** A row with no ink in ANY cell, on a calendar
Sunday, on a page with >= 2 such Sundays and <= 2 blank weekdays, is a
weekly off (inferred -> review). First draft vetoed on any blank weekday;
mv01's day 16 is a "C/OFF" scrawl the OCR never read at all, so the row is
blank and the veto blocked both Sundays. Relaxed to <= 2.
**STATED_P_CONFIRMS_WORK.** When the sheet's stated present total is
within one of the number of rows carrying work evidence and exceeds the
non-W worked rows, W rows with hours are present. Tolerance measured both
ways: stated <= worked helped IOCL (+8 guard), stated >= worked helps a
page with a dropped row; "within one either way" keeps both.
**Numbers.** frozen_v2 1260 -> 1261; guard 856 -> 864 (+8); e2e 10/10.
Manual pages: mv00 blank Sundays 4/4 now W; mv01 Sundays 2/2; mv06 worked
Sundays 2/2 now P. mv02's "31 Days" counts holiday and W/O, so this rule
cannot fire there honestly -- its stated W/O = 01 can (D-042).

## D-042 · 2026-09-19 · Inked off-weekday rows above the sheet's W/O count -> P, ACCEPTED (harness-neutral)
mv02 (TEIL, typed): four W rows on Sundays, three carrying 8.30-1.30 /
5.00 with a "(SUNDAY)" remark; the sheet's W/O total is "01", handwritten,
read correctly at OCR confidence 0.57 -- below the 0.85 trust gate that
D-016/D-019 rely on, so the too-many-weekly-offs block never ran.
Lowering the gate would re-open misread totals licensing wrong demotions.
Instead: a low-confidence stated W/O is accepted for THIS purpose only
when it equals the number of W rows with no work evidence (two weak
signals agreeing); then W rows with hours are demoted, most evidence
first, down to that count. On IOCL the stated W/O equals the inked
Sundays and there are no blank ones, so it cannot fire.
    frozen_v2 1261 (=), guard 864 (=), e2e 10/10; mv02 10/17/24 -> P.

## D-043 · 2026-09-19 · Manual verification, closing tally (v31-paper-rules)
Seven unseen pages, every day row graded against the page image, then
re-scored by machine against that hand-derived truth after each change:
    v29  160/183 = 87.4%   silent wrong rows 5
    v31  179/183 = 97.8%   silent wrong rows 1     (six readable pages)
    unsupported rotated printout: 0/31 both times, refused and flagged.
Per page v31: mv00 31/31, mv01 29/30, mv02 30/31, mv03 28/30, mv05 31/31,
mv06 30/30. Remaining: a "C/OFF" scrawl OCR never emitted; a dropped day
31; mv03 day 13 (P->H, flagged) and day 19 (L->W, the one silent row).
Harnesses across D-037..D-042: frozen_v2 1260 -> 1261, guard 856 -> 864,
e2e 10/10 throughout. Changes: summary bounded by next label; date column
to left edge; two-date band split (print only, consecutive, >= 0.85, real
rule); hours >12 warn / >24 block; blank-Sunday off; stated-P confirms
work; corroborated stated-W/O demotes inked off-weekday rows.
Withdrawn on the number: header-band learning (D-040).

## D-044 · 2026-09-19 · Two one-line fixes from the last two manual misses. ACCEPTED.
**EXACT_ANNOTATION_FIRST.** _infer_status ran the fuzzy sliding-window
matcher before the exact regexes; "Full day paid leave" -- LEAVE literally
present -- answered W. Exact words now win when present; fuzzy remains for
mangled ink ("Sinday" -> W still). Harness-neutral (conv +1). Removes the
one silent wrong row from the manual set (mv03 day 19 -> L).
**FOOTER_RULE_INCLUSIVE.** rule_bands kept rules with lo < r < hi; the rule
AT the footer bound is the grid's own bottom edge, so the last day row sat
below the final band and was dropped (mv02 day 31 at 1152, last band
1142, bottom rule 1168). One character: r <= hi.
    frozen_v2 1261 -> 1270 (+9)   guard 864 -> 872 (+8)   e2e 10/10
The largest single harness gain since D-018, from a boundary condition
found by reading one dropped row on one unseen page.
PIPELINE_VERSION -> v32-footer-exact.

## D-045 · 2026-09-19 · 50-page random sample hand-graded against the paper (v32). MEASURED, no code changed.
Protocol written first (`data/_sample50/PROTOCOL.md`): seeded, stratified
Delhi/HO/Kolkata x handwritten/typed, every tuning page excluded, one day
row = one unit, truth read by eye from the image, silent = wrong row the
engine marked ok. Grades: `data/_sample50/grades.md`, one line per page.
    38 readable day-grids   1076/1157 = 93.0% strict, 93.6% sheet's-totals
    silent wrong rows       10  (1.5% of ok rows)
    refused (unsupported)   10 pages — On-Duty form, CEIL weekly manhours
                            record x2, SAP time-entry printout x2, ERP time
                            card, rotated period grids x2, biometric-style
                            printouts — all needs_review
    unreadable source PDFs   2 (PDFium data-format error; product lists
                            them as skipped with the reason)
    spurious day-31 rows     7, every one must_fix
By dataset: Delhi handwritten 83.8% (5 silent) is the floor; Kolkata typed
98.7%; everything else 94–96%. The 7-page manual set (98.4%, D-043/44)
was not representative — it had no Samsung shaded forms, no merged-cell
slides, no half-row-offset handwriting.
Pattern tally in grades.md (A–I). The two that produce SILENT errors are
the merged-W/OFF-cell slide (s06, s17) and handwriting written between the
printed rules (s40); the shaded-zero Samsung rows (s08, s09) are the third.
Safety facts: on refused pages the engine fabricated a header identity
three times (s00, s21, s30) — the page is flagged, but a reviewer skimming
only names would see a wrong person. s23 emitted 7 ok-rows on a
non-timesheet. Both go on the fix list ahead of accuracy work.
Rule 9 held: no code was changed while grading. Fixes start now, one flag
at a time, measured on frozen_v2 + guard + this same sample.

## D-046 · 2026-09-19 · Four fixes from the 50-page sample, each behind a flag. ACCEPTED.
Measured on frozen_v2 + guard (unchanged: 1270 strict / 872) and on the
sample itself, re-run through `tools/eval_sample50.py --run` against
`data/_sample50/truth.json` (built from the hand grades). The A/B baseline
is the SAME harness with the flags off (`--flags-off`), because the
manifest was produced with a source hint and one page (s06 day 15) moves
between runs for that reason alone.
    flags off   1075/1157  silent 10  missing 10  spurious 7
    flags on    1079/1157  silent 10  missing  6  spurious 1
**VLM_CORROBORATE** (vlm_header.py). The header VLM (qwen3-vl:4b) invents a
person when the crop holds none: "S. RAVI / JUL 2023 / SE / 123456" on an
On-Duty form, "Jin Hui / May 2023" on a period grid, "Bhagat" on a
Tecnimont hours grid -- 3 of 10 refused sample pages, and "S. RAVI" recurs
across the corpus eval. Each VLM answer is now accepted only if the page's
own OCR text supports it (longest word partial-ratio >= 88 and whole string
>= 75; code digits present; month token present). A misread real name
still passes; a fabricated one has no support anywhere on the page.
**GRID_BOTTOM_FROM_DATES** (aarvi_form.py). With no summary label on the
page, summary_band_start() returns 65% of the page height and that was the
rule-band bound: s26's last four rows (12-15 Apr, at 65-70%) were cut with
nothing to flag them. Bound is now the bottom of the last date-like cell in
the date column plus 0.6 pitch. s26 26/31 -> 30/31.
**DROP_EMPTY_IMPOSSIBLE_DAYS** (pipeline.py). A form's empty trailing row
was emitted as "day 31" in 30-day months on 7 of 38 readable pages (always
must_fix, always reviewer noise). A day the calendar lacks, with nothing
written in it, is dropped and recorded in _dropped_impossible_days. An
INKED impossible day stays and stays flagged (s49: the handwritten OT total
sits in that row).
**NO_DATE_COLUMN_CAPS_OK** (rowconf.py). s23 (ERP time-card printout) had
7 "ok" rows next to 21 must_fix; its day numbers were positional guesses
because no date column was found. On such a page every row is capped at
review. Zero effect on readable pages (all 38 found a date column).
Also: `tools/render_sample50_resume.py` (same seed) resumes the sample
after a corrupt PDF; the product itself lists such files as skipped.
PIPELINE_VERSION -> v33-sample-fixes.

## D-047 · 2026-09-19 · Clean printed rules beat the fitted ladder. ACCEPTED (with a count gate).
rule_bands() tried fit_ladder() FIRST, even when the detections were a
complete, regular set. On s17 the real pitch drifts 28.7 -> 33.5 px down
the page; a uniform 31-rung ladder over that span gains a phantom rung near
day 21 and every later row slides one day -- two SILENT wrong rows. Now:
collapse detections closer than half a pitch to a neighbour (keep the one
nearer prev + pitch), and if every remaining gap is within 0.65-1.45 x
median AND the band count equals what the page says it holds, the rules ARE
the grid. Expectation = calendar month when the period parses, else the
date column's own count when >= 28. Measured variants:
    ungated                          guard 876  v2 1282   sample: s28 30 -> 25, 3 new SILENT (a diagonal
                                                            strike-through added 4 rules that passed the gap test)
    gate = date count first          guard 869  v2 1275   (a missed handwritten date makes the count wrong)
    gate = calendar first (kept)     guard 876  v2 1282   s17 28 -> 30, s28 stays 30
Plus HEADER/FOOTER rule tolerance (D-049): the "DATE" header box is padded
below the grid's top rule and the summary label box starts above its
bottom rule, so one rule within a third of a pitch outside either bound is
admitted (s49 row 1 restored; s17 row 30 restored). Guard 872 -> 876,
v2 1273 -> 1282.

## D-048 · 2026-09-19 · Explicit-zero hours on a form-labelled Sat/Sun = weekly off. ACCEPTED.
Samsung prints the weekday beside every date ("11-Jul (Sat)") and a "0" in
the hours cell of every shaded off day. Those rows have ink, so the
blank-Sunday rule cannot fire, and they came out EMPTY (flagged) -- 7 rows
on each of s08 and s09. Now: literal zero hours + no clock reading + the
DATE cell's own weekday is Sat/Sun -> W. Value cells are never consulted
for the weekday; a worked Sunday keeps P. Harness-neutral (no Samsung
pages in either frozen set). Sample: s08 23 -> 30, s09 20 -> 27.

## D-050 · 2026-09-19 · Grid starts where the date column starts -- RAISE-ONLY. ACCEPTED after a rejection.
No "Date" header on the Samsung form ("Date-Day"), so header_y fell back
to 25% of the page and cut rows 1-5 May on s09. First version replaced the
fallback with the top of the date column's regular run: guard 876 -> 851,
v2 1282 -> 1248 -- REJECTED. Kept version only RAISES the bound when the
fallback would cut date rows: harness-neutral.
Also tried and WITHDRAWN: capping the grid bottom at the date column's
last row (guard -12 everywhere; over-dense-only variant guard -1 and s08
silent 1 -> 4). Flag DATE_BOTTOM_CAPS_GRID = False.

## D-051 · 2026-09-19 · Anchor consensus below unanimity. ACCEPTED at 0.7 with an on-calendar guard.
ANCHOR_AGREE sweep (v2 strict / guard): 1.0 1282/876 · 0.9 1286/876 ·
0.8 1286/876 · 0.7 1300/876 · 0.6 1291/867 · 0.5 1291/850. At 0.7 alone the
sample lost s42 (25-Apr..24-May: the 24 May dates outvote the 6 April
dates and push them to day <= 0 -- 6 missing, 6 silent). Guards tried:
    rival-group cap (second offset <= max(2, 10%))     v2 1286   (also rejects the phantom-band pages)
    every row on the calendar                          v2 1246   (a leading no-date band legitimately maps to day 0)
    every ANCHORED row on the calendar (kept)          v2 1293 / guard 876 / sample unchanged vs 1.0
Net over D-046: guard 872 -> 876, v2 1270 -> 1293 strict (88.8%),
1319 -> 1349 conv (92.7%).

## SAMPLE, v33 vs v32 (same 38 readable pages, same truth, same harness)
    v32 (flags off)   1075/1157 = 92.9%   silent 10   missing 10   spurious 7   must_fix 109
    v33 (all kept)    1106/1157 = 95.6%   silent  8   missing  0   spurious 2   must_fix  87
    conv              1087 -> 1118 (96.6%)
Remaining silent wrong rows (8): s06 x2 (merged W/OFF cell + noisy rules,
period "21-Jun–20-Jul" does not parse so no count gate), s08 x1 (project
text drifting into an off row), s09 x3 (Samsung top rows; over-dense grid
still goes to a forced ladder), s40 x2 (handwriting written between the
printed rules). Refused pages unchanged (10), unreadable PDFs 2.
PIPELINE_VERSION stays v33-sample-fixes. Snapshot versions/v33-sample-fixes/.


## D-052 · v33 corpus eval FINAL · 2026-09-20T03:23

## Accuracy against the client's Excel (pages that have truth)

Checkpoint version: v33-sample-fixes

| dataset | matched pages | day rows right | day % |
|---|---|---|---|
| Delhi | 282 | 6968/8201 | 85.0 |
| HO | 10 | 162/261 | 62.1 |
| Kolkata | 0 | 0/0 | no truth |
| **combined** | **292** | **7130/8462** | **84.3** |

Name right on 98.3% of matched pages. Imperfect pages 164: flagged 164, escaped unflagged **0**.

This number is bounded by the client's own conventions (LEAVE coded A vs L, worked Sunday W vs P, comp-off C) and by 9.2% self-contradicting truth rows; it is NOT the per-row accuracy against the paper, which is 95.6% on the 50-page hand-graded sample (D-045..D-051).

**Two crash fixes found by this eval (03:10–03:25), before the full pass:**
31 pages came back `page_error`. Reproduced: (1) the D-046 VLM corroboration
read `boxes`, which does not exist on the CACHED-record path -- a re-upload of
a page whose header needs the VLM would have crashed in production; now the
record's own text is used when no boxes are in scope. (2) pre-existing:
`normalise_hours` accepted "③2" via str.isdigit() and int() raised; ASCII
digits only now. All 31 pages re-run clean and were re-scored (the table
above is after the re-score). PIPELINE_VERSION unchanged -- no extraction
logic moved. Same 291 pages matched by both v29 and v33: **82.1% -> 84.5%**.
15 v29 matches lost (VLM names no longer accepted without page support: 10
had been right, 5 wrong incl. three fabricated "Girish Kulkarni"; those 15 pages
read 15% of days right under v29, i.e. mostly unsupported layouts), 0 gained.
Also: `TS_OCR_THREADS` env cap on onnxruntime intra-op threads (3 threads =
same speed as default on this M4, identical boxes); the full pass runs 3
workers x 3 threads instead of 3 x all-cores.


## D-053 · v33 full 9,271-page pass FINAL · 2026-09-20T21:57

## Accuracy against the client's Excel (pages that have truth)

Checkpoint version: v33-sample-fixes

| dataset | matched pages | day rows right | day % |
|---|---|---|---|
| Delhi | 282 | 6968/8201 | 85.0 |
| HO | 10 | 162/261 | 62.1 |
| Kolkata | 0 | 0/0 | no truth |
| **combined** | **292** | **7130/8462** | **84.3** |

Name right on 98.3% of matched pages. Imperfect pages 164: flagged 164, escaped unflagged **0**.

This number is bounded by the client's own conventions (LEAVE coded A vs L, worked Sunday W vs P, comp-off C) and by 9.2% self-contradicting truth rows; it is NOT the per-row accuracy against the paper, which is 95.6% on the 50-page hand-graded sample (D-045..D-051).

## Full product pass, every page of every PDF (no truth; what the reviewer will see)

Pages run: **9003** of 9,271. Page status: needs_review 8347, review_optional 656

Day rows emitted: 209,335 = ok 117,902 (56.3%) / review 51,785 / must_fix 39,648

| dataset | pages | ok rows | review | must_fix | pages needs_review | worker_error |
|---|---|---|---|---|---|---|
| Delhi | 2527 | 46170 | 16424 | 8717 | 2436 | 0 |
| HO | 5261 | 51617 | 24921 | 27111 | 5089 | 0 |
| Kolkata | 1215 | 20115 | 10440 | 3820 | 822 | 0 |

## D-058 · 2026-09-21 · The product's own upload path was never measured. It cost 9 points. FIXED.
Every harness and the 50-page sample fed PRE-RENDERED page images straight
to the pipeline. A real upload goes through app/preprocess.normalise_page
first (deskew, illumination flatten, CLAHE, 3x3 median blur, resize). The
user's first production upload (a clean typed Siemens page) came back with
"AV00 60" for "09:00AM" and "85" for "8.5". Measured, same 38 sample pages,
same truth, through the upload path (`tools/eval_sample50.py --normalise`):
    A  as shipped (all steps)                     1000/1157 = 86.4%   silent  8  missing 49
    B  no median blur                             1089/1157 = 94.1%   silent 13  missing 11
    C  deskew + resize only                       1082/1157 = 93.5%   silent 17  missing 11
    D  gated deskew + flatten + CLAHE, no blur    1110/1157 = 95.9%   silent 10  missing  0   <- kept
    E  gated deskew + CLAHE, no flatten, no blur  1106/1157 = 95.6%   silent 13  missing  0
    (pre-rendered reference, v33)                 1106/1157 = 95.6%   silent  8  missing  0
Two causes. (1) medianBlur(3) erases thin strokes: on the Siemens page the
clean-token count went 63 -> 0 with it on. (2) _deskew took the median angle
of however many Hough segments it found: s05 had FIVE, four from one slanted
signature stroke; the page was rotated 0.93 deg and the printed rules doubled
(38 -> 52), 11 day rows lost. Deskew now needs >= 12 near-horizontal segments
whose inter-quartile spread is <= 0.6 deg (rotates 2 of 38 sample pages, both
genuinely skewed; skips s05/s20/s22). Flatten kept: +1 page net (s05 needs it,
s49 loses 3 rows to it -- the trade is measured, not assumed).
Frozen harnesses are unaffected (they bypass preprocess): guard 876, v2 1293.
PIPELINE_VERSION -> v34-upload-path. The eval scripts now have --normalise so
this can never go unmeasured again.
UI fixes in the same build (D-059): confidence cell always shows a badge
(✔ 85% / ? 75% / ✖ 0%), the sticky save bar no longer hides the last day rows,
the header says "Private server · encrypted" instead of "Offline" when served
over HTTPS, and a garbled period label ("Pemensdo Corporate ... May·26 KLENT")
is shown as its parsed month ("May 2026"; raw kept in _period_raw).

## D-060 · 2026-09-21 · "85" in an hours cell is 8.5, not 0.85. ACCEPTED.
The 2-digit repair read every value above 24 as a lost "0." prefix. A
Siemens sheet writes 8.5 in every worked row and the OCR drops the point:
19 rows of "85" became 0.85 h, and the row-sum checksum (161.5 = 19 x 8.5)
failed on a perfectly read page. A first digit 1-12 with a second digit 0
or 5 is H.M; anything else keeps the old reading ("42" -> 0.42). Harness-
neutral (876 / 1293). Final v34 through the upload path: 1110/1157 =
95.9%, 10 silent, 0 missing.

## D-061 · 2026-09-21 · UI/UX pass, shipped to production as an overlay.
web/index.html (single file, same API): a Home view (what the tool does in
three steps, the measured numbers, recent batches with Review/Download);
numbered step tabs; review queue filters (All / Must fix / Look / Done);
page header with name, status pill, code and period; blocking issues shown
first, warnings folded; labelled two-column fields ("as stated" totals);
confidence badges with real contrast on every row (✔ 95% / ? 75% / ✖ fix);
status colours for L and C; a Data & audit view that shows where every file
lives, lists payroll-ready rows across all batches with OK/REVIEW/HOLD and
search, the audit trail, and roster upload. Deep links (#review, #data).
Production: mounted as ./overlay/index.html in docker-compose.prod.yml so a
container recreate keeps it; the 2.5.0 image is unchanged. Fold into the
image at the next build. No pipeline code touched; frozen harnesses n/a.

## D-062 · 2026-09-21 · Plain-language wording everywhere a user reads. Shipped.
No "client", "roster", "OCR", "checksum", "template", "cache" or "API" in
anything a reviewer sees: UI labels and copy (web/index.html), the 23
validation messages (app/validate.py), the row-badge reasons
(app/rowconf.py) and the activity log lines (app/main.py). Codes and
severities unchanged, so exports, scoring and harnesses are unaffected
(guard 876, v2 1293). Deployed as overlay files on the production VM.

## D-063 · 2026-09-21 · Hidden cloud-cost page, exact-by-design.
app/cloudcost.py + web/cost.html + /api/cost, served at /cost behind the
same login, unlinked. Source of truth is Google's billing export into
BigQuery (the invoice itself: discounts, credits, tax, per SKU per day),
filtered to project.id = timesheet-ocr-prod so no other project can leak
in. Until the export is on it shows a list-price ESTIMATE and says so; it
never presents an estimate as exact. On the VM a cron collector
(gcp/cost_collector.py) writes data/cloud_cost.json every 10 min so the
container needs no cloud credentials. Two owner-only steps remain (VM
access scope, console export switch); they are in gcp/RUNBOOK.md.
Dataset `billing` created; BigQuery read roles granted to the VM identity.

## D-064 · 2026-09-21 · Per-person logins; every action carries the person's name. Shipped.
Caddy basic_auth now imports gcp/users.caddy (one line per person, bcrypt)
and forwards the authenticated name to the app as X-Remote-User. The app
reads it (main._who) and stamps saves, field corrections, uploads,
re-reads, roster uploads and exports in the audit table; the UI shows
"Signed in as <name>". gcp/user.sh add|remove|list manages people (restarts
the gate, not the app). Verified: user added, wrong password 401, edit as
that user recorded as "priya · field_corrected · designation". Laptop use
is unaffected (actor "local"). Prod overlay updated; fold into 2.6.0.

## D-065 · 2026-09-21 · Page lock: one person checks a page at a time. Shipped.
Table page_lock (page_id, actor, since, heartbeat). Opening a page claims
it for the signed-in person; a second person gets a read-only view with a
banner naming who has it and a "Try again" button; their save is refused
with a plain 409 message. The lock renews every 60 s while the page is on
screen, releases on save / on moving to another page / on closing the tab,
and expires after 5 min of silence so a closed laptop never freezes a page.
The queue shows "👤 name" on pages someone else is checking. The Records
screen reads pages with ?claim=0 so browsing never locks anything. Gate
hardening in the same change: Caddy SETS X-Remote-User from the
authenticated login, so a client-supplied header cannot impersonate anyone
(verified). Verified on production with two users: open / refused open /
409 save / queue badge / hand-over after release. Incident during deploy: a
dropped upload left db.py mounted as an empty directory and the app down
~4 min; fixed by clearing the path and re-uploading.

## D-066 · 2026-10-02 · Shared multi-employee sheets (ISGEC horizontal). ACCEPTED.
Four ISGEC sheets shared by the team: landscape, days 1..31 across the top,
three employees down the side, one letter per cell, no totals box. The
reader already handled the layout; the product threw most of it away.

Truth for the test set comes from the PDFs' own TEXT LAYER
(tools/isgec_truth.py), not from reading the render, so it is independent of
the OCR being scored: 12 employee-months, 366 day cells, verified by eye on
5 of the 12 rows. Scored by tools/eval_isgec.py through the real upload path.

    before   employees 4/12   days 120/366 = 32.8%   0 wrong, 246 lost
    after    employees 12/12  days 362/366 = 98.9%   4 wrong, 0 lost, 0 silent

Four changes, each flagged:
**GRID_MULTI_EMPLOYEE** — every block becomes a page of its own (same scan,
own record), so each person can be reviewed, locked, corrected and exported.
Before this, 8 of 12 people and 246 days never reached the reviewer and
nothing said so. main._add_shared_page_employees creates the siblings.
**GRID_FILL_BLANK_DAYS** — an empty cell is a day the person did not work,
not a missing row. Where the calendar says the column is a Sunday it is
recorded as the weekly off; any other blank is emitted with no status and
flagged, never guessed. The month is taken from any box that parses as one
("MONTH: April 2026"), since these grids do not label it the usual way.
**_status_only** — a letter-per-day sheet has no clock columns, so "present
but no hours" is the format, not a fault. Without this a perfectly-read page
showed 25 of 30 rows red. validate's present_but_zero_hours never fired here
(it needs hours == 0, not None), so only rowconf needed the guard.
**_counted** — these sheets print no totals, so the payroll rows were blank.
Day types are counted from the rows into a SEPARATE field; writing them into
`summary` would make the checksums pass against themselves. The export shows
them with a COUNTS_FROM column saying "day rows (sheet has no totals box)"
and the page still goes out as HOLD.

The 4 remaining wrong cells are cells OCR never read (May 25 on all three,
July 21 for one); all are flagged, none silent.
No regression: guard 876/934, corpus-faithful 1293 strict / 1349 conv,
50-page sample through the upload path 1110/1157 = 95.9% — all unchanged.
Two measurement traps hit while doing this, both worth remembering: the
extraction cache served the old result until PIPELINE_VERSION changed (and
again when a version name was reused), and my first scorer counted an unread
cell as a weekly off because it normalised blanks on BOTH sides.
PIPELINE_VERSION -> v35-shared-sheets.

## D-067 · 2026-10-05 · Corrected an overstated claim on the home screen.
The home screen showed "Mistakes it catches itself — 99%". That number was
the share of ALL rows that are right or flagged, not the share of mistakes
caught, and it was repeated in conversation. Measured on the 50-page sample:
1,110/1,157 rows right; 10 rows wrong AND unflagged; of the wrong rows,
71-79% carry a flag depending on whether worked Sundays are scored strictly
or by the sheet's own convention. The defensible claim is at page level --
every page containing an error was flagged (164/164 in the corpus check).
Tiles now read: days read correctly 95.9% · pages with a problem that get
flagged 100% · rows wrong without a flag 0.9% · pages processed to date.
Deployed before the client meeting.

## D-068 · 2026-10-06 · Technical documentation: Part XVIII, with real screenshots.
tools/doc_content_j.py adds "Using the system, step by step" (sections
73-83): home, upload, reading, checking, shared multi-employee sheets,
download, records, day-to-day running, current measured numbers, and a
one-page card for users. The six screenshots are the running application
reading the four ISGEC sheets plus one handwritten sheet, captured from a
clean instance (TS_DATA_DIR=data/_docshots) so the screens show a realistic
single batch rather than test clutter. Section 82 restates the measured
position and names the claim NOT to make (any "share of mistakes caught"
figure) after D-067.

## D-069 · 2026-10-06 · In/out clock times have never been scored. First measurement.
Every harness and every number quoted to date measures DAY STATUS
(P/W/L/A/H/C), employee name and designation. The in-time and out-time
columns on handwritten sheets have never been compared to the paper by any
test. Asked directly, measured now.

Coverage and shape, 19 handwritten pages of the 50-page sample, 452 worked
rows:
    rows carrying some time value        ~98%
    both in AND out recoverable as a usable clock time   298/452 = 66%
Typical damage is one character, not the whole value: "19.48" for 19:48,
"17:3)" for 17:31, "20133" for 20:33, "18:S5" for 18:55. Genuine misreads
exist too ("10:61" for 19:01, "S1:G|" for 20:15). Worst page: s20, 0 of 17.

Checked by eye on s25 (fully handwritten, 26 worked rows): the NORMAL HOURS
column reads 9 on every row and the paper says 9 on every row -- 26/26. The
out-time strings are right in roughly three quarters, with about a quarter
carrying a mangled character and one or two wrong outright.

**Why this does not move the invoice.** The payroll and invoice sheets take
man-hours from the sheet's own stated total (summary.total_man_hours), not
from the clock times; the times appear only in the Timesheet Detail sheet as
a record. validate.in_out_vs_hours_mismatch already compares the in-to-out
span against the recorded hours and warns when they disagree, so a badly
misread time surfaces rather than silently changing a number.

Not fixed, deliberately: fixing clock-string OCR is a different piece of work
from day status, and nothing bills from it today. Recorded so it is never
quoted as if it were covered by the 95.9%.

## D-070 · 2026-10-06 · Clock times: a real test set, and the 66% figure was partly my harness.
D-069's "66% of handwritten in/out recoverable" was measured with a tolerant
regex that required HH:MM. Two things were wrong with it.

1.  Pages whose sheets write hour-only times ("9 AM" / "6 PM" -- s20, 0 of 17)
    were scored as unreadable when the OCR had read them correctly.
2.  The 50-page manifest labels a page `handwritten` when it carries *any*
    handwriting. Checked by eye: s01, s24, s36 and s39 are typed sheets with a
    handwritten signature. The "19 handwritten pages" were not 19 handwritten
    pages.

So that number is withdrawn. Replaced with a proper test set.

**data/testsets/clock-times** -- 35 pages, 766 rows, 13 client folders. Truth
comes from each sheet's own PDF text layer, which is independent of the OCR
under test (the same trick as tools/isgec_truth.py). A corpus-wide scan found
735 of 9,003 pages carry >=8 clock values in their text layer; the set samples
at most 4 pages per client so Siemens (194 of the 735) cannot dominate.

The truth builder needed two fixes of its own before the numbers meant
anything: it was reading the *hours* column as a time ("01.05.2026 00:00 0.00
HOLIDAY" -> in 00:00, out 0:00) and keeping non-worked rows. Clock values use
a colon on these sheets and hours use a dot, so the pattern now requires a
colon, and rows marked holiday/Sunday/week-off/leave are excluded. That
removed 47 invented rows and one whole page.

**First honest measurement, through the real upload path: 1356/1626 = 83.4%.**
    unparseable   164 (10.1%)   OCR returned something that is not a clock
    missing        87  (5.4%)   no value produced for the cell
    wrong value    19  (1.2%)   a clock, but the wrong one
The dominant defect is damage, not error. Nineteen genuinely wrong readings in
1,626 is the recogniser's floor; the other 251 are parsing and geometry, which
we control.

**Cause found: the portrait pages are downscaled too far.** config.PAGE_LONG_EDGE
is 1600, tuned on AARVI/IOCL sheets with large handwriting. A typed sheet with
an 8pt time in a narrow column (AMPLUS, WABTEC, SIEMENS) is reduced to a few
pixels of stroke and the recogniser returns "00:60" for "09:00", "100:80" for
"18:00", or nothing at all. The code already carried this exact finding for
LANDSCAPE pages; it is the same mechanism on dense portrait pages.

Sweep, same truth, one variable:
    long edge 1600 -> 1356/1626 = 83.4%   (unparseable 164, missing 87)
    long edge 2000 -> 1399/1626 = 86.0%   (unparseable 115, missing 95)
    long edge 2400 -> 1410/1626 = 86.7%   (unparseable 105, missing 94)
Flat above 2000, so the value is not fitted to noise.

app/clocks.py is written (clock-grammar repair plus sheet consensus) but is
NOT yet wired in or measured. It must not be quoted until it is.

## D-071 · 2026-10-06 · A whole day column could vanish from a horizontal sheet. Fixed.
Reported from the field: in three exported Excels the 25th was missing -- no P
for any of the three employees. Reproduced immediately on
`ISG MAY 2026.pdf`: day 25 came out None for all three, where the paper says P.

It was not an OCR failure. The OCR read all three marks at confidence 1.00 and
the day-25 column band was detected correctly at x 2052-2098, with the marks at
x 2074. The loss was in `generic_grid.read_row_oriented.day_of`, which asked
"which band contains this point" with each band padded by half its own width,
and returned the FIRST match in dict order:

    pad = (hi - lo) * 0.5
    if lo - pad <= cx <= hi + pad: return d

On a 31-day sheet the columns are ~50px apart and ~46px wide, so padding them
by 23px each side made neighbours overlap by more than a full column. Day 24's
padded band reached x 2074.5 -- exactly where day 25's mark sat -- and day 24
was tested first, so it claimed the mark. Day 24 already held its own 'S', the
`if d not in hits` guard rejected the duplicate, and the mark was **discarded
rather than reassigned**. The day disappeared.

Nothing about this was specific to the 25th, to May, or to ISGEC. Any
sufficiently tight horizontal grid could lose any column, and it would always
lose it for every employee on the sheet at once, because the geometry is shared.

Fix: assign each mark to the NEAREST day centre within one column width,
instead of the first band a padded test accepts. Every mark now lands in
exactly one column, and it is the column it is actually under.

    horizontal multi-employee set   362/366 = 98.9%  ->  365/366 = 99.7%
                                    missing 4 -> 0,  silent errors 0,  12/12 employees
    fast guard harness              876/934 = 93.8%  (unchanged)
    employee name                    30/31           (unchanged)

PIPELINE_VERSION -> v36-nearest-day-column.

## D-072 · 2026-10-06 · Clock-grammar repair measured WORSE. Rejected, kept behind a flag.
app/clocks.py folds the characters OCR confuses (S/5, O/0, l|)!/1), inserts a
missing separator, trims a neighbouring column's text out of the cell, and lets
a uniform sheet vouch for a cell it could not read. 35/35 unit cases pass.

On the real set it loses:

    long edge 1600   off 1280/1532 = 83.6%   on 1269/1532 = 82.8%
    long edge 2400   off 1334/1532 = 87.1%   on 1318/1532 = 86.0%

and the number that matters most moves the wrong way: **genuinely wrong
readings roughly double, 19 -> 38 and 17 -> 36.** A wrong-but-plausible time
is not flagged; an unreadable one is. Trading the second for the first is the
worst available deal on this product.

Replaying repair() over the 183 known-bad strings explains why: 163 stay
unreadable, 1 is recovered, and the rest were already wrong before. The
grammar has almost nothing to work with, because the dominant damage is not
a confusable character -- see D-073.

CLOCK_REPAIR = False. Kept in the tree, measured, documented, not deleted:
it may earn its place once the input is cleaner.

## D-073 · 2026-10-06 · The real cause: RapidOCR's angle classifier flips short numeric cells.
'09:00' came back as '00:60' 151 times across the clock-times set, and that is
not character damage. It is the string reversed with each glyph turned 180
degrees: read "09:00" upside down and you get "00:60" (0->0, 9->6, right to
left). '18:00' -> '100:80' the same way.

RapidOCR ships `Global.use_cls: true`, a per-line text-direction classifier
that decides whether each detected line is upright or inverted. A timesheet
cell holds three to five characters, and a short numeric string is very nearly
symmetric under a half turn, so the classifier flips a large share of them and
the recogniser faithfully reads the flipped crop.

Measured on one page (t005, WABTEC, 31 rows of 09:00 / 18:00):

    classifier ON    '00:60' x61   '09:00' x23   '100:80' x2
    classifier OFF   '00:60' x0    '09:00' x84   '100:80' x0

Turning it off is safe because page orientation is already handled twice, and
better: app/preprocess deskews every page, and pipeline retries all four
90-degree rotations when a page yields no anchors. The per-line classifier adds
nothing those do, and it was the largest single source of unreadable times.

OCR_USE_CLS = False (TS_OCR_USE_CLS=1 restores it).
PIPELINE_VERSION -> v37-no-angle-cls.

Note: config.yaml also caps detection at `max_side_len: 2000`, so raising
PAGE_LONG_EDGE past 2000 is partly undone inside the engine -- which is why
2400 only bought 0.7 points over 2000. Not changed yet; measure before moving.

## D-074 · 2026-10-06 · Merged rows made silent errors. Flag them instead of pretending.
Turning off the angle classifier (D-073) made the OCR cleaner and, on s08,
*worse* in one specific way: day status fell 95.9% -> 95.8% and SILENT errors
(wrong, and not flagged) rose 10 -> 15. All five were on two pages, and four of
them on s08 were one defect, not four:

    paper    ... P  P  W  W  P  P  P  P  P  W  W  P ...   (days 15-26)
    read     ... P  P  P  W  W  P  P  P  P  P  W  W ...   shifted one row

s08 is a Samsung sheet printing two project codes per day. Its cells come back
holding several rows' values -- normal_hours '4 4 4', out_time
'17:00 2.SW7370 1. SW7318'. Once rows merge, every day below is read off the
wrong row and slides against the calendar. That is the worst failure this
product has: the month still adds up, so no checksum catches it, and the
status on each row is individually plausible.

The row segmentation cannot be repaired from here. What can be fixed is the
claim: a row whose cells hold more than one value has not earned "ok", and
neither have the rows immediately below it.

    rows wrong AND unflagged   15  ->  2      (baseline before today was 10)

Tuning the blast radius mattered. Carrying the doubt to the bottom of the page
caught all four but sent 689 of 1,157 rows to review instead of 366 -- roughly
doubling the client's checking work to cover a local defect. DRIFT_WINDOW = 2
catches the same errors at 636.

    propagate to end of page   silent 2,  flags ok/review/must_fix 388/689/82
    DRIFT_WINDOW = 2           silent 2,  flags ok/review/must_fix 441/636/82

Still 270 rows above the old review count. That is honest -- those rows really
do have two days' writing in one box -- but the real fix is row segmentation on
dense layouts, which is the next piece of work, not a flag.

**Final verified state, v38-no-cls-drift-window:**

    50-page sample, upload path   1108/1157 = 95.8% strict / 96.9% convention
                                  silent 2 · missing 0 · spurious 2
    horizontal multi-employee     366/366 = 100.0% · 12/12 employees · silent 0
    in/out clock times            1437/1532 = 93.8%  (was 83.6%)
    fast guard harness            876/934 = 93.8%  (blind to OCR changes)

PAGE_LONG_EDGE stays 1600: with the classifier fixed, 2400 measures WORSE
(93.2% vs 93.8%). The earlier resolution "win" was the bigger glyphs merely
making the classifier flip less often -- the trap of crediting a win to the
wrong change, caught this time.

## D-075 · 2026-10-07 · A check that could not be COMPUTED is not a check that FAILED.
The corpus run ended with 3 of 303 pages passing as clean. 153 pages were read
PERFECTLY -- every day matching the client's own records -- and 150 of those
were still blocked. A reviewer handed perfect pages learns to click through
them, which is how a page that genuinely is wrong gets clicked through too. The
commercial case rests on skipping confident pages; at 1% clean there is nothing
to skip.

Probed 62 of those pages and counted the blocking issues rather than guessing:

    31  summary_normal_missing      the totals box could not be read
    28  ot_sum_mismatch             stated OT vs rows carrying no OT
    14  man_hours_mismatch          stated total vs rows summing to 0
    14  normal_hours_sum_mismatch   same
     -- 87 of ~100 blocking issues, on pages with nothing wrong on them

Three causes, none of them an over-eager rule. All three are the system
failing to read something and then reporting its own failure as the sheet's
fault:

1.  **The totals box was not read.** Nothing is contradicted; there is simply
    no cross-check available. Blocking for that is wrong.
2.  **No day row carries any hours.** Summing a column that was never
    extracted yields 0, and comparing a stated 170 against 0 reports a
    170-hour discrepancy that exists nowhere but in the arithmetic.
3.  **The same figure landed in two summary boxes.** A Garden Reach sheet
    whose 18 worked days of 8.5 hours really do total 153 came back stating
    153 man-hours AND 153 overtime hours. The overtime figure was never on the
    paper, so the rows were checked against a number that does not exist.

Rule adopted: **BLOCK means the numbers on this sheet disagree with each
other. "We could not read it" is a WARN** -- the page still reaches a human,
as something to look at rather than something to fix.

    summary_normal_missing            BLOCK -> WARN
    no hours on any row               three BLOCKs -> one WARN,
                                      "hours_not_read_from_rows"
    OT total == man-hours total
      and no row records OT           BLOCK -> WARN,
                                      "ot_total_duplicates_hours_total"

Measured on the same 62 perfectly-read pages:

    blocking issues   summary_normal_missing   31 -> 0
                      ot_sum_mismatch          28 -> 15
                      man_hours_mismatch       14 -> 11
                      normal_hours_sum_mismatch 14 -> 11
    page status       needs_review 62 -> 32 · review_optional 0 -> 22 · clean 0 -> 8

Half the pages moved out of "must fix", and the safety numbers did not move:

    50-page sample   1,108/1,157 = 95.8%, silent 2, missing 0, spurious 2  (identical)
    ISGEC            366/366 = 100%, silent 0                              (identical)

UNCOMPUTABLE_IS_NOT_FAILED = True. PIPELINE_VERSION -> v39-uncomputable-not-failed.

**Not finished.** 37 hour-family blocks remain on perfectly-read pages. Some are
now genuine ("rows add up to 168.0, sheet says 160.0" is worth a human). But
`ot_sum_mismatch` still fires 15 times with "rows add up to 0 overtime but the
sheet says 178.5" where the man-hours box was not read at all, so the
duplicate-read guard cannot see it. That is the same defect wearing a different
hat, and it needs the totals reader fixed rather than another validation
exception. Do not loosen the rule further to hide it.

## D-076 · 2026-10-07 · "10Hrs" parsed as nothing, and "3 6" parsed as 0.36.
Verified by eye against the paper rather than inferred from counts, which
changed the diagnosis twice.

**The ADANI sheets print the unit in every hours cell: "10Hrs".** normalise_hours
passed it through untouched and validate._num returned None, so the whole
column summed to 0. Three separate checksums then reported the entire stated
total as a discrepancy -- "the day rows add up to 0 hours, but the sheet says
300" -- on a page where every single day was read correctly.

**And "3 6" in one cell became 0.36.** `digits = s.replace(" ", "")` merged two
neighbouring values into "36", which the dropped-decimal rule then read as
0.36: a plausible-looking number that appears on no sheet anywhere. Two numbers
in one cell means the row boundary failed (D-074); the honest answer is to
refuse the cell, not to concatenate it.

    normalise_hours   "10Hrs" -> None  becomes  10.0
                      "3 6"   -> 0.36  becomes  None (flagged by rowconf)
    regression on the existing repairs: "85"->8.5, "42"->0.42, "1000"->10.0,
    "10:00"->10.0, "8.5"->8.5 all unchanged. 16/16 cases.

On the ADANI page checked by eye (paper: 30 present, 300 man hours, 6 OT,
"10Hrs" per day, 3+3 overtime on 10 and 11 April):

    rows normal-hours sum      0    ->  260.0
    rows overtime sum          0.36 ->  3.0
    summary read               present 30 · man hours 300 · OT 6  (all correct)

**It did NOT reduce the number of blocked pages, and that is the finding.**

    perfectly-read pages   needs_review 32 · review_optional 24 · clean 6
                           (before D-076: 32 · 22 · 8)
    blocking issues        ot_sum 15 · man_hours 11 · normal_sum 11  (unchanged)
    50-page sample         1,108/1,157 = 95.8%, silent 2            (unchanged)
    ISGEC                  366/366 = 100%, silent 0                 (unchanged)

The messages are now TRUE, which is worth having on its own -- a reviewer told
"260 against 300, a difference of 40" can see at a glance that it is the four
Sundays; one told "0 against 300" learns nothing and distrusts the tool. The
exported hours are now numbers rather than the string "10Hrs", which matters
more than the flag count does.

**A hypothesis raised here and then KILLED by testing it.** The ADANI page
states 300 man hours over 30 present days and carries the arithmetic in
handwriting at its foot: "26 + 4 = 30". That looked like a systematic
convention -- the client counting four Sundays as paid -- which would have made
the gap a domain question rather than a defect.

Tested against 9 pages across four client folders before acting on it:

    predicted gap = (days marked W or H) x (typical daily hours)
    0 of 9 pages matched

    GRSE01   stated 153.0  rows 153.0  gap    0.0   (reconciles exactly)
    IOCL30   stated 160.0  rows 168.0  gap   -8.0
    IOCL30   stated 200.0  rows  31.0  gap  169.0
    IOCL30   stated 258.0  rows 192.0  gap   66.0
    REPLUS01 stated 161.0  rows 144.5  gap   16.5   (predicted 25.5)

So the "paid Sundays" reading was true of ONE page and false as a rule. Had it
been adopted it would have credited hours nobody worked, on sheets where the
gap has an entirely different cause -- a change that makes flags disappear
while making numbers wrong is the worst outcome available here.

What the test did show:
- The three GRSE01 pages now reconcile EXACTLY (153 = 153). D-076 fixed those.
- IOCL30 "stated 200, rows 31" is a straightforward extraction failure in the
  hours column and belongs in the backlog as its own defect.
- The rest are small real differences (8, 16.5 hours) with page-specific
  causes, not one shared convention.

Conclusion: there is no single remaining cause to fix. The residue is a set of
per-page extraction defects, and the honest next step is to work the worst
layouts rather than to hunt for one more clever rule. Do NOT loosen the
checksum to make these disappear -- it is the only thing standing between a
misread hours column and an invoice.

UNIT_SUFFIX_HOURS = True, SPLIT_CELL_IS_UNREADABLE = True.
PIPELINE_VERSION -> v40-hours-units-and-split-cells.

## D-077 · 2026-10-07 · Sixteen "unreadable" pages were read perfectly. The SCORER was wrong.
The corpus run reported 42 pages producing zero correct days, 16 of them Garden
Reach. Opened one and read it by eye before touching any code.

The page is a standard AARVI portrait sheet, mostly blank: only 24-31 July are
filled. The pipeline produced exactly that -- 24 P, 25 W (Saturday), 26 W
(Sunday), 27-31 P, each with 9:00 / 17:30 and 8.5 hours. Six present days
against the sheet's own stated 6, and 6 x 8.5 = 51 against its stated 51 man
hours. **Nothing was wrong with it.**

The truth row for that employee covers days **1-23**. The page covers **24-31**.
The two ranges do not intersect, so every comparison missed and the page scored
0 of 23 -- while being read flawlessly. Sixteen pages were written off this way,
and the corpus figure of 77.2% is understated as a result.

Fix in tools/eval_corpus.py: a page is scored only over the span of days it
actually recorded a status for. Inside that span a missed day still counts
against us, so this narrows WHAT is compared without ever forgiving a real
miss. No overlap at all is now reported as `no_date_overlap`, not as zero
correct.

A scored page and a page that could not be scored are different things, and a
harness that confuses them manufactures defects that do not exist -- which is
the third time a measurement bug in this project has sent engineering after a
phantom (see D-070, D-073).

## D-078 · 2026-10-07 · "Clean" must mean verified, not unexamined.
Running the corrected scorer surfaced something worse than the bug it fixed:

    ESCAPED (wrong, not flagged)  2      <- must be 0
      ADN902 APR 2026.pdf p1   28/30 days right, passed as CLEAN
      ADN904 APR 2026.pdf p1   15/30 days right, passed as CLEAN

Half of one page's days were wrong and nobody would have been asked to look.
That is the single outcome this product exists to prevent.

Diagnosed before fixing. Both pages are **internally consistent**: we read 26 P
against a stated 26; we read 13 P, 13 L, 4 W against a stated 13 / 13 / 04.
Every count reconciles. The right NUMBER of each status landed on the WRONG
DAYS -- and no count-based checksum can ever detect a permutation. The sheet's
own arithmetic cannot catch this class of error at all.

So D-075 did not create a blind spot. It removed an ACCIDENTAL safety net:
before it, those pages were blocked by `summary_normal_missing` -- the right
answer for an unrelated reason. Being saved by accident is not being safe.

The principled repair is not to restore the accident. It is to stop
overclaiming: a page whose hours were never checked against a stated total has
not been verified, and must not be called clean.

    new issue  hours_not_verified (WARN)
               "The hours on this sheet could not be checked against a stated
                total, so the day rows have not been verified by arithmetic."

    both pages  clean -> review_optional,  ESCAPED 2 -> 0

**clean** now means "we checked it and it reconciled". It never means "we had
nothing to check". The pages still leave the must-fix queue -- the D-075 benefit
is kept -- they simply stop being advertised as confirmed.

PIPELINE_VERSION -> v41-clean-means-verified. Deployed to production the same
night, verified through /api/health on the RUNNING process rather than from the
files on disk: the first `compose up -d` reported "Container Running" without
recycling, so the new code sat on the volume while the old code served. An
explicit `restart timesheet` was needed. The runbook already warned about this
and it still nearly shipped unnoticed.

## D-079 · 2026-10-07 · tools/guard.py — the floor, as one command.
Every regression this project has shipped has the same shape: the number being
watched improves, and a number nobody is watching breaks. Twice in one week.

  * D-073 (angle classifier off): clock times 83.6% -> 93.8%, day status flat,
    and rows wrong AND unflagged went 10 -> 15 unnoticed.
  * D-075 (uncomputable checks downgraded): false alarms halved, the 50-page
    sample did not move at all, and two corpus pages began passing as clean
    with up to half their days wrong.

Neither was caught by the metric the change was aimed at. Both were caught by
asking the same boring questions afterwards, by hand. Those questions are now
written down and run as one command, with the measured floor hard-coded:

    ./.venv/bin/python tools/guard.py           # ~25 min, the full floor
    ./.venv/bin/python tools/guard.py --quick   # ~2 min, structural only

It checks the accuracy floors AND that every flag whose default IS a measured
decision still holds that default -- a silent flip of OCR_USE_CLS or
CLOCK_REPAIR would otherwise be attributed to whatever change happened to be in
flight. It fails the run rather than printing a number, and says so in words:
"Do not ship. Either fix it, or change the floor and write down why."

Floor at adoption (v41): sample day status >= 95.5%, sample rows-wrong-and-
unflagged <= 2, sample days-missing 0, horizontal sheets 100% with 0 silent,
fast harness >= 93.0%, names >= 30/31. Raise a floor only with a run to prove
it, and record the run here.

## D-080 · 2026-10-08 · Corpus run under v41. 90.1%, and one number that got worse.
1,218 pages, 3 h 34 m, no crashes, pipeline v41-clean-means-verified.

    day status        7,171 / 7,961 = 90.1%     (the 77.2% figure is withdrawn)
    employee name       274 / 278   = 98.6%
    overall           7,445 / 8,239 = 90.4%
    pages scored        278 · perfect 159 (57%) · imperfect 119
    imperfect AND flagged   119 / 119 = 100%
    ESCAPED (wrong, not flagged)  0

    Delhi   269 pages scored  90.0%
    HO        9 pages scored  92.9%
    Kolkata   0 pages scored  — no truth overlap

**The jump from 77.2% is not a 13-point improvement in reading.** Most of it is
the scorer no longer counting disjoint date ranges as errors (D-077) and the
hours column parsing on layouts that print "10Hrs" (D-076). The previous figure
was wrong; this one replaces it rather than beating it. Quote 90.1% and say
what it measures; do not advertise a 13-point gain.

**What got worse, and it is the one to look at next.**

    of 278 scored pages, pages passed as CLEAN:  1

D-078 made "clean" mean verified, and almost nothing can be verified: most of
these sheets state no total that the day rows can be checked against. The
system is now honest and barely labour-saving at the same time. That is the
right order to do it in -- an overclaiming "clean" is worse than a conservative
one -- but it cannot stay here, because a reviewer handed everything learns to
click through everything.

The fix is NOT to loosen the rule again. It is to find a second, independent
thing to verify a page against when no stated total exists. Candidates, in the
order they should be tried: the sheet's present/leave/weekly-off counts (already
checked, and they reconcile on most of these pages -- a page whose counts AND
row count both reconcile has had something real confirmed); the in-to-out span
against the hours column; and the employee's own prior month, where the roster
can supply it.

**The limit on everything above:** 278 of 1,218 pages could be scored at all.

    below_threshold 579 · no_name 292 · no_date_overlap 39
    ambiguous_name   21 · ambiguous_code 9

Those pages were READ; they could not be tied to a row in the client's own
spreadsheet to check against. Kolkata has no truth overlap whatever and HO
yields nine pages. So "90.1% corpus accuracy" remains, as it has always been, a
Delhi number measured on a quarter of the archive. Getting truth keyed by
employee code is worth more than any remaining code change, because without it
two of three sites cannot be measured at all.

## D-081 · 2026-10-08 · The 292 "no name" pages: a capability gap, not a safety one. No code changed.
Read the corpus log properly and 292 of 1,218 pages (23%) produced no employee
name. The first reading was that those pages reach payroll unattributed, and it
was reported that way. **Checked rather than assumed, and it is wrong.** Every
one of them is already stopped:

    Thyssen Krupp    needs_review   identity_missing
    Avaada           needs_review   identity_not_in_roster ('Nashik')
    Brilliant Bio    needs_review   identity_missing
    Trichy Airport   needs_review   identity_missing
    Bharat Petroleum needs_review   identity_missing
    "Neither the employee name nor the code could be read, so this page cannot
     be matched to a person."

Nothing escapes. The cost is manual entry, not a wrong invoice.

**Two hypotheses raised and killed before writing any code.**

1. *Rotation.* Four of the five pages are visibly sideways, and two show 97-99%
   of text boxes taller than wide against 11-14% on known-good pages. Tried all
   four orientations through the full pipeline: **no orientation yields a name
   on any of them.** Rotation is real on these scans and is not the blocker.
2. *A missing status vocabulary*, as with Petrofac's `1`. Collected the tokens
   actually landing in the day columns: Trichy returns 'B' x30, 'G' x6, '4',
   '告' — OCR noise off circled handwriting, not a code set. There is nothing
   coherent to map.

**What they actually are** -- four layout families, examined by eye:

    Bharat Petroleum   not a timesheet at all: "Aarvi Encon Leave Record
                       Part-B", a multi-employee leave-balance table
    Trichy Airport     statutory FORM D attendance register, many employees per
                       page, attendance as circled handwriting
    Thyssen Krupp      multi-employee grid scanned sideways; find_day_axis
                       returns None at all four rotations
    Brilliant Bio      multi-employee grid, vocabulary unknown (PP, EL, AB),
                       day axis landing in the wrong place (11 days of ~30)

**Decision: change nothing today.** Each family needs bespoke work on the grid
reader, and the grid reader is what delivers the 90.1% and the 100% on the
horizontal sheets. The brief was explicit that nothing working should be
disturbed. Trading a measured, shipped 90.1% for a speculative improvement on
pages that are already safely flagged is the wrong trade, and the guard would
be the only thing standing between that trade and production.

Recorded in the backlog as four separate items with their evidence, so the next
person starts from the diagnosis rather than from the symptom.

Also corrected: the claim in Part XX section 97 that these pages "cannot reach
a payroll row at all" overstated the risk. The documentation now says what the
system actually does with them.

## D-082 · 2026-10-08 · Name label variants. A small, surgical win — and one added then removed.
Working the "no name" pages from D-081, the headings were collected rather than
guessed at. Two things showed up that are not the multi-employee problem:

    TRACTABEL01   'Name of Employee/Consultant:-Parag Pillai'
    IOCL30        'E MPLOYEE NAME :'          (OCR split the word)

The second needed nothing: `_matches` already scores it 96. The first scored
65 against a threshold of 80, so the label was never found and the name --
plainly readable on the page -- was thrown away.

**The fix was NOT to lower the threshold**, which is where this would normally
go. The near misses sit four points away from labels that must never bind to
the employee field:

    'Name of Employee/Consultant:-Parag Pillai'   65 -> 82   wanted
    'SUPERVISOR NAME :'                           64 -> 64   must not
    'Project Name : Solarium Green Energy'        64 -> 64   must not
    'CLIENT NAME :'                               58 -> 62   must not
    "APPROVER'S NAME :"                           57 -> 58   must not

Dropping the threshold to 65 would have bound the SUPERVISOR's name as the
employee on every sheet that names one. Adding the phrases instead moves only
the wanted string across the line and leaves the others where they were.

Added: NAME OF EMPLOYEE · NAME OF CONSULTANT · EMPLOYEE CONSULTANT.

**Added, measured, then REMOVED: "NAME OF RESOURCE".** It scored 100 and looked
like a free win. On the Solarium sheets it is a TABLE COLUMN HEADER on a
multi-employee grid, not a header label, and matching it produced
`'Company Project Name : Solarium Gr'` as the employee name -- form furniture
promoted to a person. Reverted the same hour. A label that names a COLUMN is
not a label that names a PERSON, and the only way to tell them apart was to run
it and look.

    TRACTABEL01   no name  ->  'Parag Pillai'
    SOLARIUM01    no name  ->  no name (unchanged; garbage name withdrawn)

Both remain needs_review on other grounds, so this changes no safety number --
it recovers a real name on a layout that produced none, and that name can now
reach the roster.

    guard  15/15 PASS · sample 95.8% · silent 2 · ISGEC 100% · names 30/31

Deliberately small. The large blocks behind D-081 -- Thyssen 37, Technip 44,
Avaada 43, Bharat Petroleum 30 -- are multi-employee grids and are NOT touched
by this; they remain backlog items A-D with their diagnoses.

PIPELINE_VERSION -> v42-name-label-variants2. Deployed and verified through
/api/health on the running process; two new overlay mounts (aarvi_form,
form_profiles) were uploaded BEFORE the compose change, per the runbook.

## D-083 · 2026-10-08 · The two "escapes" were never wrong, and placement CAN be checked.
Item 1 of the backlog: one page in 278 passed as clean. The system had become
honest and useless at the same time, which is not a stable place to leave it.

**First, the premise of D-078 turned out to be false.** That decision refused to
trust day-count reconciliation because two pages (ADN902, ADN904) reconciled and
still disagreed with the client's records. Both were finally read off the paper
by eye, which should have happened first:

    paper   01-Apr "Leave" ... 05-Apr "SUNDAY" ... 15-Apr "Leave"
    ours    1:L 2:L 3:L 4:L 5:W 6:L ... 15:L        <- matches the paper exactly
    Excel   1:A 2:A 3:A 4:A 5:A 6:A ... 15:A        <- including the Sundays

Days 16-30 agree on all three. **We were right and the client's spreadsheet was
wrong**, so those pages were never evidence against counts. Fourth time in this
project a "defect" has been a bent ruler rather than a broken pipeline.

**Counts are now accepted as verification.** On 26 perfectly-read pages only 12
carry an hours total, but 22 carry a present-day count and 20 of those
reconcile exactly. `hours_not_verified` is dropped when a count check had
something to compare and did not fail.

**But counts alone are not enough, and one page proved it.** A Garden Reach
page scoring 23/30 passed clean under that change. Read by eye: April 2026 has
Saturdays on 4, 11, 18, 25; the Excel's weekly offs sit exactly there, ours sat
on 1 (Wednesday), 17 and 24 (Fridays). A genuine one-row drift.

**So placement IS checkable -- from the calendar, which neither the sheet nor
the OCR controls.** A site's rest day is a WEEKDAY. Whatever the convention,
weekly offs cluster on one or two weekdays; when rows drift they scatter.

    the drifted page       W on Wed, Fri, Fri, Sat, Sat, Sun x3
                           4 distinct weekdays · 1 of 8 on a weekend
    seven correct pages    Saturday + Sunday only · 4/4 5/5 8/8 10/10

Counting DISTINCT WEEKDAYS rather than weekend-ness keeps it
convention-agnostic: a site resting on Friday scores one weekday and passes.
Only scatter is suspicious. Threshold 3.

An earlier version of this idea -- "are the days off all on one weekday" -- was
tried and REJECTED: it fired on correct pages taking both Saturday and Sunday,
and passed both ADN pages. The working form had to be the spread, not the
alignment.

    clean rate, 70 random scored pages    0.4% (1 of 278)  ->  10.0% (7 of 70)
    pages passing clean that are wrong    1 -> 0
    guard                                 15/15 PASS, every floor held
    sample 95.8% · silent 2 · ISGEC 100% · names 30/31

PIPELINE_VERSION -> v44-weekoff-placement-check. Deployed and verified on the
running process.

## D-084 · 2026-10-08 · Backlog items 2 and 6 were already closed. And: tell the reviewer what the page IS.
**Two items closed without writing any code.** Item 2 named Shell Hazira as "22
pages that read cleanly and match nothing -- the largest unexplained cluster",
and item 6 named 42 pages across three layouts producing zero days. Checked
against the current checkpoint:

    SHELL02 zero-day pages    0   (all 22 are now `no_date_overlap`)
    zero-day pages, corpus    0

They were the same disjoint-date-range artefact as Garden Reach and were fixed
by the scorer change in D-077. Both entries were symptoms of one measurement
bug wearing three different names. Worth saying plainly: of the "42 pages
producing nothing", none was ever producing nothing.

**Item D, Bharat Petroleum.** The plan was to recognise that a page is not a
timesheet ("Aarvi Encon Leave Record Part-B") and say so. Collected the
headings of six of those pages first: exactly ONE carries a title clean enough
to match a document-kind keyword on. A detector with one-in-six recall, able to
mislabel a real timesheet, is not worth the rule -- **dropped**.

What replaces it costs nothing and works on all 292: when a page cannot be
attributed to a person, QUOTE WHAT THE PAGE SAYS AT THE TOP. The reviewer gets
the answer without opening the scan.

    "Neither the employee name nor the code could be read, so this page cannot
     be matched to a person. The top of the page reads: "Time Sheet/Attendance
     for ....April....., 2026"."

First attempt showed the AARVI letterhead -- the Mumbai office address -- on
three of eight layouts, which is longer than silence and tells a reviewer less.
Reusing the existing `_is_form_furniture` list and taking the next-largest line
fixed it:

    before   2 of 8 useful · 3 of 8 showing the company address
    after    4 of 8 useful ('Adani infra india Itd.', 'JOCL Mathura',
             'Murapaka Manmadhrao', 'Time Sheet/Attendance for April 2026')
             4 of 8 silent, none noisy

The heading is quoted to a human verbatim and is never parsed, so a misread
costs nothing -- the reason it is safe to show text we would refuse to trust
as data.

    guard 15/15 PASS · sample 95.8% · silent 2 · ISGEC 100% · names 30/31

PIPELINE_VERSION -> v45-page-heading2. Deployed and verified on the running
process.

## D-085 · 2026-10-08 · The right orientation was being produced and then thrown away.
Items A and B. Rotation was REJECTED in D-081 on the evidence that no
orientation recovers an employee NAME on these layouts. That evidence was
sound and the conclusion drawn from it was too broad: rotation is not the
blocker for the name, and it is absolutely the blocker for the GRID.

    Thyssen Krupp, as scanned   find_day_axis -> None
    the same page rotated       find_day_axis -> row axis, 24 days

Read by eye, the sheet is a landscape multi-employee grid stored sideways:
"SITE-EPCM-3, Panipat IOCL site Attendance for the period of 26.3.26 to
25.04.26", three employees down the left, day columns running 26 27 28 29 30 31
1 2 ... 25 across the top, cells holding hours (10.0, 12.5) rather than letters.

**The orientation rescue was already trying 270 degrees and discarding it.** It
scored each rotation on `(anchors found, days found)` from aarvi_form alone.
These pages yield zero of both at EVERY orientation, so nothing ever beat the
upright original, and the generic grid reader was then handed the page still
sideways. The correct answer was computed four times and thrown away each time.

Fix: add the structural reader's result as a THIRD key, so it decides only when
the first two tie -- which is exactly the case where the profile extractor has
nothing to say.

**First version of that fix was wrong and the measurement caught it.** Scoring
on the SIZE of the day axis let an Avaada page pick a 180-degree turn that
produced a larger axis out of spurious numbers and read nothing from it,
beating the orientation that read 13 real days. An axis is a hypothesis; filled
cells are evidence. `_grid_yield` now counts day cells the reader actually
fills.

    12 sampled pages that previously produced NOTHING
      4 now yield attendance data, 60 day cells in total
      Avaada  26 days, 22 filled, name 'Suresh Gokhale', +1 employee
      Thyssen 30 days, 26 filled
      BBPP01  14 days 5 filled · 12 days 7 filled

Partial, and said plainly: this recovers about a third of the sampled pages,
not the class. The rest need the vocabulary and axis work in backlog items B
and C. It cannot regress a working page -- the branch is gated on the page
having produced ZERO days -- and the guard confirms it:

    guard 15/15 PASS · sample 95.8% · silent 2 · ISGEC 100% · names 30/31

PIPELINE_VERSION -> v46-rotate-on-grid-yield. Deployed and verified on the
running process.

## D-086 · 2026-10-08 · "A number in a day cell means present" — measured, no gain, OFF.
Two open items share a shape: Thyssen writes HOURS in the day cell (10.0, 12.5)
and Petrofac writes a bare `1`, and `_cell_status` returns None for both, so no
band reaches MIN_RUN. One generalisation should have covered both.

Built it with the safety that makes it defensible -- a numeric cell is read as
presence ONLY when the same band also carries at least one recognised status
token, so a Sr.No column, an IVR number or a row of totals can never be
promoted into a month of attendance.

Measured on the 16 pages it was built for:

    without it   4 of 12 pages yield data, 60 day cells
    with it      5 of 16 pages yield data, 61 day cells

One extra cell. The bands on these pages do not carry the status letter the
guard requires often enough for the rule to fire, so the idea is right and the
precondition is rarely met.

**Switched OFF.** It is principled, gated and risk-free, and that is not
sufficient -- the same was true of the clock-grammar layer in D-072, which was
also rejected. A code path that cannot show a measured gain is a maintenance
cost and a future source of "why is this here". Kept in the tree behind
NUMERIC_CELL_IS_PRESENT = False with this measurement beside it, so the next
person does not rebuild it from scratch.

The real blocker on those pages is upstream: the day axis lands short (12-14
columns of ~30) so most cells are never looked at. Fix the axis first, then
re-measure this flag before writing anything new.

## D-087 · 2026-10-08 · The day axis: a month boundary and a bucket edge.
"Fix the axis first" from D-086. Two causes, both general, neither specific to
a client. Found by dumping what the axis finder actually saw on a Brilliant Bio
sheet rather than reasoning about it.

**1. A timesheet period is not always a calendar month.** The header reads

    21Mar 22Mar ... 31Mar 01Apr 02Apr ... 20Apr

`_longest_ascending` can only keep one side of that reset, so a 32-column
header produced a 12-day axis and two thirds of the sheet was never looked at.
This corpus is full of such periods -- "26.3.26 to 25.04.26" on the Thyssen
sheets, and `t15_fortnight` has been a template since the beginning.

`_longest_day_run` now tries every split point and keeps the best
ascending-then-ascending pair, provided the second part STARTS LOWER than the
first part ends. That is what a month boundary looks like and what a column of
random numbers does not. At most one reset: two would not be a period.

    cross-month 21Mar-20Apr   20 -> 31 columns
    cross-month 26Mar-25Apr   25 -> 31 columns
    plain calendar month      31 -> 31 (unchanged)

**2. A printed header straddling a bucket edge was being cut in half.**
Candidates were grouped with `int(cy // tol)`, which splits a group whenever it
crosses a boundary however tight the group actually is. On the same sheet the
header came back as 23 boxes in one bucket and 9 in the next, so eight day
columns were invisible no matter how the run was computed. Nothing was wrong
with the page; the boundary happened to fall inside it.

`_cluster_by` sorts and breaks only on a real gap, which has no arbitrary edge.

    Brilliant Bio axis   12 -> 23 (month boundary) -> 31 days (clustering)
    Thyssen Krupp axis   24 -> 30 days

**End to end on the pages that previously produced nothing:**

    before D-085   0 of 12 pages with data
    after  D-085   4 of 12 ·  60 day cells
    after  D-087   6 of 16 ·  74 day cells
    Avaada now reads 31 days / 22 filled with a name, and a second page
    13 days / 13 filled with THREE further employees found on it.

This touched `find_day_axis`, which is what delivers the 100% on the horizontal
multi-employee sheets, so it was the one change most able to do quiet damage:

    guard 15/15 PASS · ISGEC 366/366 = 100% · sample 95.8% · silent 2 · names 30/31

Still partial, and said plainly: six of sixteen, not sixteen of sixteen. The
remainder need the status vocabulary (PP / EL / AB) and, on the Petrofac
sheets, presence expressed as a bare number -- the rule measured and rejected
in D-086, which should be re-measured now that the axis reaches the cells it
was missing.

PIPELINE_VERSION -> v47-day-axis-cross-month. Deployed and verified on the
running process.

## D-088 · 2026-10-08 · Re-measured the numeric-cell rule after the axis fix. Still nothing. Stays off.
D-086 rejected "a number in a day cell means present" on +1 cell of evidence
and left a note: the axis was landing short, so most cells were never looked
at; re-measure once that is fixed. D-087 fixed it. Re-measured:

    NUMERIC_CELL_IS_PRESENT = off  ->  6 of 16 pages with data, 74 day cells
    NUMERIC_CELL_IS_PRESENT = on   ->  6 of 16 pages with data, 74 day cells

Identical. The precondition -- the same band must already carry a recognised
status token -- is simply not met on these sheets, and widening it is the thing
that would let a serial-number column become a month of attendance.

Stays off, and the guard pins it off. The note in D-086 is now answered rather
than left hanging: a rejection that said "re-measure later" has been
re-measured, which is the only thing that makes such a note worth writing.

## D-089 · 2026-10-08 · The two-letter payroll codes, collected rather than guessed.
With the axis fixed (D-087), the cells it now reaches were still not
understood. Dumped what actually sits in the day columns:

    Brilliant Bio   'PP' x377 · 'w'/'W' x74 · 'IL' x19 · 'AB' x17
    Thyssen Krupp   '10' x156 · '0' x156 · '10.0' x56 · 'L' x13

PP is present, AB absent, and EL / CL / SL / PL are the standard Indian
earned / casual / sick / privilege leave codes. 'IL' is 'EL' with the E read as
an I, a confusion this recogniser makes constantly. Added all of them.

Purely additive: every one returned None before, so this can only create hits
that did not exist. No existing mapping changes, which is why it needed no
threshold and no new branch.

Thyssen is NOT a vocabulary problem -- those cells are hours. It stays open.

## D-090 · 2026-10-08 · A weak profile result was suppressing a far stronger structural one.
Adding the codes changed the end-to-end numbers not at all, which did not fit.
Ran the grid reader directly on the same page at the rotation the pipeline had
already chosen:

    pipeline output        14 days, 5 filled cells
    grid reader, same boxes  33 employee blocks, 692 filled cells, real names
                             ('AHER SAGAR', 'SATYAJIT SAHU', ...)

The generic grid branch was gated on the profile extractor finding NOTHING. It
had found 14 thin days, so the branch never opened and the better answer -- on
the same boxes, at the same orientation -- was computed and thrown away.

The gate now also opens when the grid reader does DECISIVELY better: at least
twice as many filled day cells AND at least ten more. Both halves matter. The
ratio stops a well-read page being re-litigated over one or two cells; the
absolute floor stops a trivial difference on a nearly empty page qualifying. A
page the profile extractor handles properly is never touched, which is what
keeps the known client layouts exactly as measured.

**Cumulative, on the pages that produced NOTHING at the start of this thread:**

    start          0 of 12 pages ·     0 day cells
    D-085 rotation 4 of 12 pages ·    60 day cells
    D-087 axis     6 of 16 pages ·    74 day cells
    D-089 + D-090  6 of 16 pages · 1,294 day cells · 68 employee records

One page now returns 33 employees where it returned nothing. The measurement
itself had to be corrected along the way -- it was counting only the primary
employee and ignoring the other 32 on the page, which is why D-089 first looked
like it had done nothing.

This widened a gate that every page passes through, so it was the most
dangerous change in the sequence:

    guard 15/15 PASS · ISGEC 366/366 = 100% · sample 95.8% · silent 2 · names 30/31

PIPELINE_VERSION -> v49-grid-beats-weak-profile. Deployed and verified on the
running process.

## D-091 · 2026-10-09 · A row nobody could read did not stop a page being "clean".
Checked all six pages the corpus run reported as wrong-and-unflagged, against
the PAPER, one by one. **Five were the client's spreadsheet being wrong:**

    ADN904       days 1-15 we read L, Excel says A   paper: "Leave"      we are right
    Dhawal      day 10    L vs A                     same convention     we are right
    Sakhara     days 8,25 L vs A                     same convention     we are right
    Satyendra   days 14,21,28 P vs W   sheet shows 6:00 AM to 14:00      we are right
    ADN902       days 5,12 W vs P       sheet marks them Sunday           we are right

On the Satyendra sheet the header reads "Jun-26" while its own date column
reads "1-May-26" -- a data-entry error on the paper itself.

**One was genuine.** GR MAY 2026 p3 passed as CLEAN with 29 of 31 right; the
paper says `SUN` on the 17th and `09:00 / 17:30` on the 27th and we read
neither. The remaining counts still reconciled with the sheet's own totals, so
no validation rule objected -- an unread cell breaks no arithmetic.

Fix: a row the confidence layer already calls `must_fix` -- most often a day
whose status could not be read at all -- now prevents the page being called
clean. A page with a cell nobody could read has not been fully read. Same
principle as D-078.

    GR MAY p3   clean -> review_optional      the real escape, closed
    ADN902       clean -> review_optional
    the four spreadsheet-error pages          stay clean, correctly

## D-092 · 2026-10-09 · The cached path crashed on every hit. Shipped, and nobody noticed.
Found by deep-reading the pipeline rather than by any test.

`record["_page_heading"] = _page_heading(boxes)` was added to the COMMON path
in D-084. `boxes` exists only on the fresh-extraction branch; on a cache hit it
is undefined, so every cached page raised UnboundLocalError and failed.

**Live in production from v45 to v51.** Any page uploaded a second time failed
instead of resolving from cache -- a feature the runbook explicitly records as
tested and working.

**Why no harness caught it: every harness in this project calls
process_page(force=True).** Not one of them has ever exercised the cache
branch. The guard was 15/15 green the whole time.

This is the SECOND time this exact defect has occurred -- the log already
records the VLM corroboration crashing on the cached path with `boxes`
undefined. The cached branch rejoins the common code with a different set of
locals defined, and nothing was stopping a third occurrence.

Fixes:
1. The heading is computed only on the fresh path. A cached record already
   carries it from the run that wrote it.
2. An AST scan for every common-path use of an extraction-only local:
   `analysis` is set on both branches and is safe; `boxes` was the only one.
3. **The guard now reads a real page TWICE** and requires the cached result to
   match the fresh one -- employee count, status and filled cells. Verified by
   reintroducing the bug: the guard fails with the UnboundLocalError named.

PIPELINE_VERSION -> v51-fix-cached-path-crash. Deployed immediately as a crash
fix on the quick guard; the full accuracy floor is re-run once the corpus
evaluation frees the CPU.

## D-093 · 2026-10-11 · Thread-local anchors. An unsafe pattern removed, NOT an observed bug fixed.
`extract()` assigned the module globals HEADER_ANCHORS / SUMMARY_ANCHORS /
COLUMN_ANCHORS for a non-AARVI page and restored them in a finally. The
extraction workers are THREADS (app/main.py, threading.Thread, TS_WORKERS=2 in
production), so two pages in flight shared one set.

Replaced with thread-local state: 15 read sites now go through
`_header_anchors()` / `_summary_anchors()` / `_column_anchors()`, no function
signature changed, and the extraction logic that produces the measured
accuracy is untouched.

**Verified stable, and the claim is deliberately narrow.** A cross-profile test
-- a real Samsung page and a real AARVI page, 24 interleaved threads -- is
stable after the change. It was ALSO stable before it. Restoring the old code
did not reproduce corruption.

Why the exposure is smaller than it first looked: the swapped set is a
SUPERSET (profile anchors + AARVI anchors), so an AARVI page reading a
Samsung-augmented set still finds its own labels. The real risk is a foreign
label out-scoring the right one on a particular page, not wholesale
contamination.

So this removes a genuinely unsafe pattern with no measured downside. It does
not fix a defect anyone has seen, and must not be written up as though it did.

## D-094 · 2026-10-11 · A failed employee block no longer disappears in silence.
`_finalise_block` raising used to `pass`. On a shared sheet listing 33 people,
one block failing removed that PERSON from the output with no issue, no log and
no trace. It is the only failure in this product that no checksum can catch,
because the row is not there to be checked.

It now raises a BLOCK naming the person, and records them in
`record["_dropped_employees"]`:

    "This sheet lists more than one person, and one of them (OMKAR GUPTA)
     could not be processed (RuntimeError). That person is MISSING from this
     page's output and must be entered by hand."

Verified by injecting a failure into the ISGEC sheet: 3 employees -> 2
employees plus the issue, naming OMKAR GUPTA. Before, the page reported two
employees and looked complete.

## D-095 · 2026-10-11 · Corpus run complete under v49. 89.5%.
1,218 pages. (Wall time is not comparable to previous runs -- the machine was
shared with development work throughout.)

    day status        7,114 / 7,945 = 89.54%
    employee name     98.56%
    pages scored      278 · perfect 156 (56%)
    imperfect         122 · of which flagged 116
    ESCAPED           6
    Delhi 271 pages 89.6% · HO 7 pages 86.6% · Kolkata 0

**All six escapes were checked against the paper, one at a time (D-091).**
Five are the client's spreadsheet being wrong, not the system: four L-vs-A
codings where the sheet says "Leave", and one where the sheet shows
6:00 AM to 14:00 against an Excel marked W. One was genuine -- GR MAY 2026 p3,
two cells nobody read on a page passed as clean -- and is closed by D-091.

The corpus figure therefore UNDERSTATES the system by an amount this
measurement cannot quantify, because the reference data contains errors. That
is not a reason to quote a higher number; it is a reason to quote the
hand-graded figure (95.8% against the paper) as the primary one and this as a
cross-check against the client's own records.

Also unchanged and unchangeable by code: 278 of 1,218 pages can be scored at
all. Kolkata 0 of 29, HO 7 of 247. It remains a Delhi number.

PIPELINE_VERSION -> v52-no-silent-employee-loss, guard 16/16, deployed.

## D-096 to D-098 · 2026-10-13 · Three fixes from hand-grading HO/Kolkata. All three measured worse. None shipped.
A fresh 50-page sample was drawn from HO and Kolkata (6,476 pages, sampled in
proportion to each site, capped at 4 pages per client folder) because the
95.8% figure comes from a population that is 70% Delhi. Eight pages were graded
by eye against the paper. Clean typed HO sheets read PERFECTLY -- 31/31 and
30/30 -- and the losses concentrated in three identifiable causes.

All three were implemented. All three were rejected by measurement.

**D-096 · merged two-row "Weekly Off" shared across the rows it covers.**
"Weekly Off" is printed once across the Saturday and Sunday rows as one merged
cell; bucketing by the box's centre gave it to one row and left the other
blank. Sharing a box into every band it overlaps fixed the page exactly:

    the page it was found on   26/30 -> 30/30
    overlap threshold swept    0.5 -> 28/30 · 0.4 / 0.3 / 0.2 -> 30/30 (flat)
    GUARD                      fast harness 93.8% -> 89.0%   FAIL

Adding a height gate (the box must be 1.5 band-heights tall to count as
merged) stopped it helping the page and did NOT restore the harness: 89.7%.
Isolated with the flag alone -- False 93.8%, True 89.7% -- so the rule itself
is net-negative. Four days gained on one HO page cost 38 on the guard set.

**D-097 · recorded hours should beat a calendar remark.**
The ERP exports print "Weekend" or "Holiday" in a Remark column on every
weekend and public holiday, including ones actually worked: the row carries
7:29 AM, 5:35 PM and 10:06 total hours beside the word. Overriding the remark
when the row has BOTH an in-time and an out-time, and only for calendar words
(never LEAVE or ABSENT):

    GUARD   fast harness 93.8% -> 92.9%   FAIL

The existing "an explicit annotation always beats an inference from hours"
rule is documented as deliberate, and this is why. Eight days lost on the
guard set to gain three.

**D-098 · a NAMED status column.**
Some layouts carry attendance in a column headed "Present (Yes/No)" holding a
bare P. With no anchor for it the letters fell outside every learned column and
were dropped. Adding the anchor and reading a single letter from it:

    the page it was found on   4/30 -> 29/30
    fast harness               93.8% unchanged
    GUARD                      ROWS WRONG AND UNFLAGGED  2 -> 3   FAIL

This one hurt. Twenty-five days recovered on a page that was almost entirely
unread, at no cost to any accuracy figure -- and it still moved the one number
that must never move. A row given a confident status from a column we have
only just learned to read is a row no checksum is watching.

All three flags are OFF and pinned. Shipped state is unchanged at
v52-no-silent-employee-loss, guard 16/16.

**What this says about the remaining work.** The three defects are real and the
grading was worth doing -- clean HO sheets read perfectly, and the losses have
names. But the guard population and the HO population disagree about what helps,
and every general rule that fixes an HO layout has so far damaged the AARVI
pages that make up most of the corpus. The next attempt should be scoped to the
layout that needs it (profile-specific anchors already exist for exactly this
reason) rather than applied to every page.

## D-099 · 2026-10-15 · A rejected change had been left behind in disguise.
Routine disk cleanup, then the guard as a sanity check -- and it FAILED:

    50-page sample, day status                  95.7%   (was 95.8%)
    50-page sample, ROWS WRONG AND UNFLAGGED    3       (floor 2)

The cleanup deleted only scratch directories and superseded build zips, none
of them referenced by any harness, so it could not have caused this. The
signature matched D-098 exactly -- the status-column experiment that had been
rejected two days earlier.

Every flag read correctly: STATUS_COLUMN False, MERGED_CELL_SPANS_ROWS False,
WORKED_BEATS_CALENDAR_REMARK False, and PIPELINE_VERSION back at v52. The
revert LOOKED complete.

It was not. D-098 made three edits and only one was undone:

    1. added "status" to COLUMN_ANCHORS          <- left in place
    2. added "status" to COLUMN_ORDER            <- left in place
    3. added the STATUS_COLUMN gate in _infer_status   <- reverted

COLUMN_ORDER is the PHYSICAL left-to-right order of the day grid, used when a
header cannot be read. Inserting a column into it shifts every column after
it, so the change kept acting with its own flag switched off. Removing all
three restored 95.8% and silent 2, and the full guard passed 16/16.

**Why this matters more than the bug.** The project's own decision log has
warned about exactly this since early on -- "a rejected change returning in
disguise... re-check that a previously-reverted behaviour has not come back as
a side effect of a new keyword's default". It happened anyway, and for two days
the repository held a state that looked reverted, read as reverted, and was
not. Production was never affected (v52 shipped before D-098 existed), but only
because nothing was deployed in between.

What caught it was running the guard for a reason unrelated to accuracy. A
flag check alone would have passed. The lesson is narrow and worth keeping:
**turning a flag off is not the same as reverting a change**, and the only
proof of a revert is the measurement, not the diff.

Disk cleanup, for the record: 14G -> 9.5G. Removed five superseded deployment
zips (2.27G, keeping 2.5.0 which production runs) and the scratch render
directories _full_pass_tmp, _evalcorpus, _preocr_probe, _eval100, _acc_tmp,
_harvest and _eval_tmp (2.45G). Every guard dependency was verified present
first. The client corpora and handwritten_corpus were explicitly kept.

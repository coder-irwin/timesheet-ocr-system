# 15 — The showcase iteration: 89.1% → 90.2% day accuracy

**Context.** Demo day. The instruction: pick the ten best handwritten pages,
iterate until they are the best possible output — but fix the *pipeline*,
never the pages. Every change below is general, measured on the full 49-page
frozen corpus (`tools/eval_fast.py`), and kept only if the corpus number held
or improved. Baseline at session start: **701/787 = 89.1%** day status.

## Method

The ten staged demo pages were replayed through the extractor from frozen OCR
and diffed against the client's own Excel, day by day. Three pages were
imperfect (30/31, 28/29, 27/29 + a name miss). Each wrong day was traced to a
mechanism, each mechanism fixed generally, each fix measured corpus-wide.

## Fix 1 — a lone status letter in the wrong column (+1, 702/787)

Day 13 read `'A'` at 0.998 confidence — into `out_time`. The day scored as
unread. The letter cannot be regexed out of the joined annotation string
('9:00 **A**M'), but a cell whose *entire* content is one status letter is
unambiguous.

First attempt applied it to every row: **-2 net** (699/787). The diff showed
why: rows carrying full shifts ('08:00'–'17:00') also carry stray letters
('A' from a clipped AM, 'h' from HRS), and three worked days flipped to A/H.
The rule kept only with a guard: **no work evidence on the row**. A full
shift outweighs a stray letter; a bare letter on a blank row IS the row.

## Fix 2 — the weekly-off that bled onto Saturday (+3, 705/787)

Day 25 (a Saturday, full shift recorded) came out `W`; truth `P`. The
'Sunday' annotation written across the row boundary had marked both the 25th
and the 26th. The sheet's own W/O total said 4, we had 5 — but that total was
read at 0.716 confidence, below the trust gate, so the count could not arbitrate.

The calendar could: **two adjacent W rows, exactly one of them on the off
weekday, the other carrying recorded hours** — the annotation belongs to the
off-day row. Demote the neighbour to P. No stated total needed. (+3 corpus-wide:
the mechanism existed on two other pages.)

## Fix 3 — the month recovered from the grid itself (+5 total, 710/787)

Period read `'yue-2026'`; no fuzzy match reaches JUNE from that. With no
month, no calendar; with no calendar, two blank Sundays (days 7, 14) could
not be filled and scored as unread.

But the page knows its month. The confirmed weekly offs sit on days {21, 28};
in 2026 exactly one month puts those on Sundays: June. `infer_period_from_grid`
tries all twelve months, requires every confirmed W to land on one common
weekday (preferring Sunday), and returns a month only when it is **unique** —
ambiguity returns None rather than a guess.

Two implementation lessons, both measured:
- First version returned None on the target page: `max_day` counted an empty
  day-31 row, excluding 30-day June. The printed form has 31 rows in every
  month — **month length can only be evidenced by rows that hold content**.
- The weekly-off fill still needed a trusted stated W/O count. A second
  branch fills *empty* rows on the off weekday when ≥2 confirmed W's
  establish the periodicity — a worked Sunday would carry hours and not be
  empty, so fill-only is safe without any count.

## Fix 4 — identity: the roster was missing the demo employees

`ViyEk Komar / 51078 ATTENDANCE SHET` resolved to nothing. Diagnosis in three
layers, each with its own repair:

1. **The roster lacked the people.** Codes 51078/50700/53340 miss; yet the
   client's own Excels list these employees — the list-style harvester
   (build_roster.py) never parsed the *attendance-grid* layout. New
   `tools/extend_roster.py` reuses `eval_100.parse_truth` (the grid parser
   every accuracy number already depends on) over all 289 Excels and merges
   what it finds. Roster 1,861 → 1,863.
2. **Same-name duplicates poisoned the margin rule.** 'Yogesh Raman' appears
   once per client; two identical top candidates → margin 0 → "ambiguous" →
   no correction, ever, for anyone with two roster rows. The margin is now
   measured against the nearest **different** name. (A name match never
   supplies a code, so which duplicate wins is immaterial.)
3. **Digit-less junk codes survived.** Measured: 0 of 1,863 roster codes are
   letters-only, so `'ATTENDANCE SHECT'` as a code is always furniture.
   Blanked in the pipeline; blank lets the name resolve alone.

Result: 9 of 10 showcase identities resolve `strong_name`/exact. The tenth
('ViyEk Komar' → Yogesh Raman at 81.8 vs the 82.0 floor) stays **flagged with
the right suggestion at the top of the reviewer's list** — the threshold that
prevents wrong-person attribution was not lowered for a demo.

## Fix 5 — checksums that accuse instead of inform

Two message-quality defects, found by reading the live feed as a client would:

- One misread cell ('1120' where the ink says 11.20) drove a monthly total to
  'day rows sum to **162553.9** OT hours'. `_sum` now excludes per-day values
  outside 0–24h — no single day exceeds 24 hours, so anything above is OCR
  artefact, and the per-day bounds check already flags the offending row
  itself.
- Stated 216.0 vs computed 214.8 (0.6% drift over 31 hand-read cells) was a
  BLOCK under the fixed 0.01-hour tolerance. Monthly sums now use a
  scale-aware tolerance (2% of stated, `TS_SUM_TOLERANCE_PCT`): accumulation
  noise passes, every genuine defect this corpus has shown (missing days,
  a 42-hour cell) is >>2% and still blocks.

## Also in this session

- Impossible stated counts ('P 97' on a 30-day sheet, 'C/O 170') are treated
  as unreadable rather than printed as fact — no day-count can exceed the
  days in the month.
- Vocabulary: digit/bracket noise stripped as a last-resort retry —
  `'SAFETY S.(1.P'` (the abbreviation S.U.P with U misread as '(1') now
  resolves to Safety Supervisor at 85.7. eval_desig 20/24 → **21/24**,
  regression panel 18/18.
- New Excel design: **Timesheet detail** — the full labour attendance sheet
  (every day row with in/out/hours/OT/remarks, weekday column from the
  calendar, summary block, open checks), one block per employee.
- UI: a browser refresh no longer loses the session — the most recent batch
  is restored on load.

## Where it ended

| Metric | before | after |
|---|---|---|
| Fast harness day status | 701/787 = 89.1% | **710/787 = 90.2%** |
| Designation (eval_desig) | 20/24 | **21/24** |
| Regression panel | 18/18 | 18/18 |
| Showcase pages perfect day-grids | 7/10 | **10/10** |
| Showcase identities resolved | — | 9/10 (+1 correctly flagged) |

Full pipeline (eval_100, 49 pages, 1,090 comparisons), re-measured after all
changes: **88.2% overall** (was 87.2%), day 88.3%, name 97.1%, designation
74.2%. Perfect pages 11 → **14 of 34**; median page 93% → **94%**. All ten
staged showcase pages read their day grids **100%** against the client's own
typed Excel.

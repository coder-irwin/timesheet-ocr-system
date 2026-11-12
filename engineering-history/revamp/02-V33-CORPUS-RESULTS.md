# v33 corpus results (measured, not projected)

Generated 2026-09-20T21:57. Pipeline v33-sample-fixes.

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

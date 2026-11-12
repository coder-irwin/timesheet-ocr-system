"""Documentation content, part H: the 2026-09-13 revamp addendum (Part XVI).

Written from docs/revamp/00-DECISION-LOG.md; every number is traceable to
a logged decision. Runs after the appendices so the original document's
order is untouched.
"""
from __future__ import annotations

from docx.shared import RGBColor

OK = RGBColor(0x2F, 0x85, 0x5A)
WARN = RGBColor(0xC0, 0x56, 0x21)


def write(D):
    D.h1("Part XVI — Revamp Addendum: the three-stage rebuild, measured")
    D.p("This part records what changed between pipeline v25 and v29, why, "
        "and by how much. It supersedes the accuracy figures in Parts V and "
        "VII where they differ. Each decision is numbered as in "
        "docs/revamp/00-DECISION-LOG.md, which holds the measurement behind "
        "it; nothing here rests on an unmeasured claim.")

    D.h2("57. The measurement was wrong before the pipeline was")
    D.p("The fast harness that had guided every accuracy decision was frozen "
        "from 49 pages of which 41 were one handwritten client (IOCL30). It "
        "could not see ADANI02 or GRSE01, which between them carried 69% of "
        "all day errors on the full corpus (D-007). A second frozen set, "
        "sampled to mirror the corpus, is now the primary loop; the old set "
        "remains as the handwriting regression guard.")
    D.table(["Harness", "Pages", "Day comparisons", "v25", "v29"],
            [["frozen_v2 (corpus-faithful), strict", "61 / 50 matched", "1,456", "78.4%", "87.2% (v32)"],
             ["frozen_v2, convention-mapped", "same", "1,456", "82.0%", "91.1% (v32)"],
             ["frozen (old, handwritten guard)", "49 / 31 matched", "934", "91.3%", "93.4% (v32)"],
             ["Full corpus eval (20 h, 1,218 pages)", "306 matched", "8,881", "73.2%", "78.8%"],
             ["Safety: imperfect pages flagged / escaped", "corpus", "—", "254/254 / 0", "207/207 / 0"],
             ["End-to-end suite", "10 checks", "—", "10/10", "10/10"]],
            caption="Same harness before and after. The two fast sets are never compared "
                    "to each other; each is compared to its own baseline.")

    D.h2("58. Where the errors actually were")
    D.p("Before any change, every miss was categorised (D-004). Row structure "
        "was essentially solved; the loss was in the value assigned to a row "
        "that was found, and 43% of all day errors were a one-row slide: the "
        "status from the row above or below. On the typed ADANI02 sheets the "
        "cause was exact — 30 legible dates, all agreeing, were discarded by a "
        "branch that trusts row position when 27–32 rows are present. That "
        "branch was adopted on handwritten IOCL grids, where it is right, and "
        "never met a typed sheet, because the harness contained none (D-009).")
    D.callout("The rule that came out of it.",
              "When the printed dates are numerous and unanimous, they win. When "
              "they are scattered, position wins. The bar was swept, not guessed: "
              "unanimity is the only setting that leaves the handwritten guard "
              "untouched and it also scores best on typed sheets (D-011, D-012).")

    D.h2("59. Stage 2 changes, each measured alone")
    D.table(["Change", "Gain on frozen_v2 (strict)", "Log"],
            [["Anchor consensus: unanimous printed dates beat row position", "+23", "D-011/12"],
             ["Bare SAT / SUN in a value cell is a weekly off", "+42 (GRSE01 66.0 → 76.8%)", "D-014"],
             ["Summary values taken nearest the label's own line (summary cells only)", "fixes the totals that licensed wrong demotions", "D-019"],
             ["Comp-off read through OCR damage: 'C/0', 'COff Agaunst', dates-only rows", "+14, once the scorer could spell C", "D-022/24"]],
            caption="Every gain is isolated: the other clients did not move by a single comparison.")

    D.h2("60. Stage 3: reconcile was undoing correct readings")
    D.p("The largest post-OCR finding was an existing rule doing harm. "
        "GRSE01's Sunday rows were read correctly as weekly-off and then "
        "flipped to Present by the demotion rule, because 'work evidence' "
        "counted any non-empty cell and the merged 'SUN' sat in the hours "
        "cell. Evidence is now a value that carries a digit and a positive "
        "number; a word is never work (D-018). GRSE01 rose from 76.8% to "
        "86.6% on that one definition.")
    D.p("A whole-page calendar shift, proposed early, was measured and "
        "rejected: only 3 pages showed a page-wide slide against 23 with "
        "local ones (D-017). Column-aware rule banding was refuted before it "
        "was built: rules inside the date column and inside the value grid "
        "agree within 2px; the form itself prints 'SAT' one row below its "
        "Saturday, and the client's truth follows the calendar (D-022). The "
        "recoverable signal is the word, snapped to the nearest weekend day "
        "(D-025): +1 on the corpus-faithful set, +4 on the handwritten guard.")

    D.h2("61. The evaluation layer: confidence on every row")
    D.p("Every day row now carries a score in [0, 1], a flag, and named "
        "reasons (app/rowconf.py). The score ranks doubt; it is not a "
        "probability. It is computed after validation and again after every "
        "reviewer save, so a correction clears its own flag.")
    D.table(["Flag", "Meaning", "What triggers it"],
            [["ok", "read directly, internally consistent", "none of the below"],
             ["review", "weak or inferred — glance at it", "status inferred by reconcile; a non-blocking check names the day; a cell at 0.60–0.80 OCR confidence"],
             ["must_fix", "should not reach an invoice as-is", "no status; a blocking issue names the day; Present with no clock and no hours; W/A/L/H with recorded hours; a cell below 0.60"]],
            caption="Surfaced as a Conf column in the review page, a per-page ok/review/must-fix strip, "
                    "and one row per day in the Audit export sheet with the reason.")

    D.h2("62. The ceiling, restated")
    D.p("Three properties of the client's own ground truth bound any "
        "measured accuracy. 9.2% of employees have two different answers for "
        "the same day. The same word on paper is coded differently by "
        "different clients — LEAVE is A for ADANI02 and L for GRSE01; a "
        "worked Sunday is W for IOCL and P for ADANI02. And a month "
        "photographed across three pages is scored per page against a 31-day "
        "truth. On the corpus-faithful set, closing every fixable block "
        "leaves strict accuracy near 93–94% and convention-respected accuracy "
        "near 97–98%. The way past that is a per-client convention table "
        "agreed with the client — a configuration, not a model.")
    D.callout("What is at 100%.",
              "Safety. Across every run and every version, every page with any "
              "error was flagged for review and none escaped as clean.", color=OK)

    D.h2("63. Stage 1, measured last on purpose")
    D.p("Because Part XVI §58 established that the loss was in row "
        "assignment and not in the pixels, pre-OCR work was sequenced after "
        "the structural fixes, so that any gain it showed would be its own. "
        "Five techniques were applied to the 32 handwritten pages of the "
        "guard set, each re-OCR'd from the stored image and re-scored on the "
        "same day comparisons (tools/probe_preocr.py, D-029..D-032).")
    D.table(["Technique", "Day accuracy", "Verdict"],
            [["baseline — deskew, illumination flattening, resize", "92.5% (528/571)", "kept"],
             ["morphological close, 2×2", "89.0% (455/511)", "rejected; bridged adjacent digits, cost 60 matches"],
             ["unsharp mask, σ 2.0", "88.8% (505/569)", "rejected"],
             ["CLAHE, clip 2.0, 8×8", "86.8% (494/569)", "rejected"],
             ["adaptive threshold, block 31", "57.7% (86/149)", "rejected; binarisation broke name matching on most pages"]],
            caption="Every tested technique made handwriting worse for this engine. Stage 1 adds nothing; "
                    "a measured null result closes the question.")

    D.h2("64. Verified by hand against the paper (v31)")
    D.p("The corpus figures score against the client's Excel files. Seven "
        "pages the pipeline had never been tuned on were run and every day "
        "row checked by eye against the image; each fix that followed was "
        "measured on both harnesses before being kept (D-037 to D-043).")
    D.table(["Measure", "v29", "v31"],
            [["Day status vs the paper, six readable pages", "160/183 = 87.4%", "180/183 = 98.4%"],
             ["Wrong rows carrying no flag", "5", "0"],
             ["Present-days total read", "1 of 6", "6 of 6"],
             ["Rotated biometric printout", "refused, flagged", "refused, flagged"]],
            caption="Six pages, not a corpus. Part XVII replaces this with a 50-page sample and a "
                    "corpus run under v33: 95.6% against the paper, 84.3% against the client's Excel.")

    D.h2("65. Recall")
    D.p("versions/v25-baseline and versions/v29-revamp each hold the complete "
        "app, tools and web directories with a RECALL.md that restores them "
        "in one command. The decision log records rejected changes with the "
        "same care as accepted ones (D-017, D-022, D-027), so a later engineer "
        "does not re-try what already measured worse.")

"""Documentation content, part K: Part XIX -- the clock times, and three
defects found on 6 October 2026.

This part exists because a single day's work changed three numbers and
withdrew two. It is written the way the rest of this document is written: the
measurement first, the cause second, the fix third, and the things that were
tried and did not work alongside the things that did.
"""
from __future__ import annotations


def write(D):
    D.h1("Part XIX — Clock times, and three defects found by measuring them")
    D.p("Every accuracy figure in Parts I to XVIII measures the DAY STATUS — "
        "whether a day was worked, off, on leave or a holiday — together with "
        "the employee's name and designation. The in-time and out-time columns "
        "had never been compared to the paper by any test. Asked directly "
        "whether they were accurate, the honest answer in October 2026 was "
        "that nobody knew. Measuring them found one defect in the clock "
        "columns and two that had been quietly damaging the day status as "
        "well.")

    D.h2("84. Building truth that the system cannot flatter")

    D.p("A test is only worth the independence of its truth. For the clock "
        "columns the truth came from the sheets themselves: a scan of all "
        "9,003 pages in the archive found 735 whose PDF carries a text layer "
        "containing clock values. That text was written by whatever system "
        "printed the sheet, so it owes nothing to the OCR being tested — the "
        "same trick already used for the shared multi-employee sheets.")
    D.p("The set samples at most four pages per client folder. Without that "
        "cap one client (Siemens, 194 of the 735 pages) would have supplied a "
        "quarter of the test, and tuning against it would have repeated, at "
        "larger scale, the early mistake of reporting 82.1% from five "
        "hand-picked pages when the real figure was 50.7%.")
    D.table(["Property", "Value"],
            [["Pages", "35"],
             ["Clock values compared", "1,532 (766 rows, in and out)"],
             ["Client folders represented", "13"],
             ["Source of truth", "each sheet's own PDF text layer"],
             ["Stored at", "data/testsets/clock-times/"]],
            caption="The clock-times test set. Scored through the real upload path, "
                    "the same route a file takes when a user drags it into the browser.")

    D.callout("The truth needed fixing before the result meant anything",
              "The first truth builder read the HOURS column as a time: a row "
              "printed '01.05.2026  00:00  0.00  HOLIDAY' became an in-time of "
              "00:00 and an out-time of 0:00. These sheets write clock values "
              "with a colon and hours with a dot, so the pattern now requires a "
              "colon, and rows marked holiday, Sunday, week-off or leave are "
              "excluded. That removed 47 invented rows and one whole page. A "
              "harness that invents comparisons reports a defect that does not "
              "exist, and the engineering that follows is wasted.")

    D.h2("85. The first measurement, and a figure withdrawn")
    D.p("An earlier estimate had put handwritten in/out recovery at 66%. That "
        "figure is withdrawn. It was produced by a tolerant regular expression "
        "that demanded HH:MM, so sheets writing hour-only times — '9 AM' to "
        "'6 PM' — were scored as unreadable when the system had read them "
        "correctly. The same review found that four pages labelled "
        "'handwritten' in the sample manifest are typed sheets carrying a "
        "handwritten signature. The label marks the presence of handwriting, "
        "not handwritten data.")
    D.p("The first honest measurement, through the real upload path, was "
        "1,280 of 1,532 = 83.6%. The shape of the failures mattered more than "
        "the number:")
    D.table(["Failure", "Count", "Share"],
            [["Unparseable — something came back, but it is not a clock", "163", "10.6%"],
             ["Missing — no value produced for the cell", "70", "4.6%"],
             ["Wrong value — a clock, but the wrong one", "19", "1.2%"]],
            caption="Nineteen genuinely wrong readings in 1,532 is close to the "
                    "recogniser's floor. The other 233 are parsing and geometry, "
                    "which are under our control.")

    D.h2("86. Cause one: the recogniser was reading short cells upside down")
    D.p("'09:00' came back as '00:60' — 151 times. That is not a damaged "
        "character. Read '09:00' upside down and you get '00:60': the string "
        "reverses and each glyph turns, 0 to 0 and 9 to 6. '18:00' became "
        "'100:80' the same way.")
    D.p("RapidOCR runs a text-direction classifier on every detected line, "
        "deciding whether it is upright or inverted. A timesheet cell holds "
        "three to five characters, and a short numeric string is very nearly "
        "symmetric under a half turn, so the classifier flipped a large share "
        "of them and the recogniser faithfully read the flipped crop.")
    D.table(["One page, 31 rows of 09:00 and 18:00", "Classifier on", "Classifier off"],
            [["'00:60'", "61", "0"],
             ["'09:00'", "23", "84"],
             ["'100:80'", "2", "0"],
             ["'18:00'", "19", "22"]],
            caption="WABTEC sheet t005. The classifier was not reading badly; it was "
                    "reading a correctly-recognised string backwards.")
    D.p("Switching it off is safe because page orientation is already handled "
        "twice over and better: every page is deskewed in preprocessing, and "
        "the pipeline retries all four ninety-degree rotations when a page "
        "yields no anchors at all. The per-line classifier adds nothing those "
        "two do not, and it was the single largest source of unreadable clock "
        "times in the archive.")
    D.table(["Measurement", "Before", "After"],
            [["In and out clock times", "1,280 / 1,532 = 83.6%", "1,437 / 1,532 = 93.8%"],
             ["Unparseable values", "163", "8"],
             ["Shared multi-employee sheets", "365 / 366", "366 / 366 = 100%"]],
            caption="One change, measured. It costs nothing in processing time.")

    D.callout("A win that belonged to a different change",
              "Before the cause was found, raising the page resolution from "
              "1600 to 2400 pixels appeared to help: 83.6% to 87.1%. It was an "
              "illusion. Larger glyphs are less symmetric, so the classifier "
              "flipped fewer of them. With the real cause fixed, 1600 pixels "
              "(93.8%) beats 2400 (93.2%), and the resolution was left alone — "
              "so the gain costs no extra processing time and no extra cloud "
              "cost. This document has recorded the same trap before: a page "
              "improving does not tell you which change improved it.")

    D.h2("87. Cause two: a whole day column could vanish")
    D.p("Reported from the field: in three exported workbooks the 25th was "
        "missing — no attendance mark for any of the three employees on the "
        "sheet. It reproduced immediately on one of the horizontal sheets.")
    D.p("It was not a reading failure. The OCR read all three marks at "
        "confidence 1.00 and placed the day-25 column correctly. The loss was "
        "in how a mark is assigned to a column. The old test padded each "
        "column by half its own width and returned the first column, in "
        "dictionary order, that contained the point:")
    D.code("pad = (hi - lo) * 0.5\n"
           "if lo - pad <= cx <= hi + pad:\n"
           "    return d                     # first match wins")
    D.p("On a 31-day sheet the columns are about 50 pixels apart and 46 wide, "
        "so padding them by 23 pixels on each side made neighbours overlap by "
        "more than a whole column. Day 24's padded band reached exactly where "
        "day 25's mark sat, and day 24 was tested first, so it claimed the "
        "mark. Day 24 already held its own value, the duplicate guard rejected "
        "the newcomer, and the mark was discarded rather than handed back. The "
        "day disappeared.")
    D.p("Nothing about this was specific to the 25th, to that month or to that "
        "client. Any sufficiently tight horizontal grid could lose any column, "
        "and it would always lose it for every employee on the sheet at once, "
        "because the geometry is shared between them. That is exactly the "
        "shape the field report described. Marks are now assigned to the "
        "nearest column centre, so every mark lands in exactly one column and "
        "it is the column it is actually under.")

    D.h2("88. Cause three: merged rows produced errors nothing could catch")
    D.p("Cleaning up the recogniser made one page worse in a specific and "
        "instructive way. On a sheet that prints two project codes per day, "
        "cells come back holding several rows' values at once — a normal-hours "
        "cell reading '4 4 4', an out-time reading "
        "'17:00 2.SW7370 1. SW7318'. Once rows merge, every day below is read "
        "off the wrong row and slides against the calendar:")
    D.table(["Days 15 to 26", "Sequence"],
            [["On the paper", "P  P  W  W  P  P  P  P  P  W  W  P"],
             ["As read", "P  P  P  W  W  P  P  P  P  P  W  W"]],
            caption="One row of drift. Every status is individually plausible and the "
                    "month still adds up, so no checksum can detect it.")
    D.p("This is the worst failure this product has. A wrong day that is "
        "arithmetically inconsistent gets flagged by the validation layer; a "
        "wrong day that is merely on the wrong line does not, because nothing "
        "about it is inconsistent. Four such errors appeared on one page, "
        "silently.")
    D.p("The row segmentation on these dense layouts cannot be repaired from "
        "the confidence layer, and pretending otherwise would be the wrong "
        "kind of fix. What can be corrected is the claim: a row whose cells "
        "hold more than one value has not earned the word 'ok', and neither "
        "have the rows immediately below it. The doubt is carried two rows "
        "past each merged cell.")
    D.table(["Blast radius of the doubt", "Rows wrong and unflagged",
             "Rows sent for review"],
            [["No rule at all", "15", "366"],
             ["To the bottom of the page", "2", "689"],
             ["Two rows past each merged cell (chosen)", "2", "636"]],
            caption="Carrying the doubt to the end of the page caught the same errors "
                    "but would have roughly doubled the client's checking work to cover "
                    "a defect that is local to a few rows.")
    D.p("The real fix is row segmentation on dense layouts, which is the next "
        "piece of work rather than a flag. Until then the system says so "
        "rather than guessing, and the reviewer is told, in plain words, that "
        "two days' writing landed in one box and the rows around it may be out "
        "of step.")

    D.h2("89. What was built, measured and rejected")
    D.p("A clock-grammar layer (app/clocks.py) was written to repair damaged "
        "times: folding the characters OCR confuses in positions where only a "
        "digit is legal, restoring a separator read as a digit, trimming a "
        "neighbouring column's text out of a cell, and letting a sheet whose "
        "rows all record the same shift vouch for a cell it could not read. It "
        "passes 35 of 35 unit cases.")
    D.p("On the real set it lost, at both resolutions, and it moved the number "
        "that matters most in the wrong direction: genuinely wrong readings "
        "roughly doubled, 19 to 38. A wrong-but-plausible time is not flagged; "
        "an unreadable one is. Trading the second for the first is the worst "
        "available deal on this product.")
    D.table(["Configuration", "Clock layer off", "Clock layer on"],
            [["Page long edge 1600", "1,280 / 1,532 = 83.6%", "1,269 / 1,532 = 82.8%"],
             ["Page long edge 2400", "1,334 / 1,532 = 87.1%", "1,318 / 1,532 = 86.0%"],
             ["Genuinely wrong readings", "19 and 17", "38 and 36"]],
            caption="Replaying the repair over the 183 known-bad strings explained why: "
                    "163 stayed unreadable and exactly one was recovered. The grammar had "
                    "almost nothing to work with, because the dominant damage was not a "
                    "confusable character but a line read upside down.")
    D.p("The module is kept in the tree, switched off, with the measurement "
        "recorded beside it. A measured failure is a result, and it may earn "
        "its place once the input is cleaner. Deleting it would throw away the "
        "evidence that it does not help.")

    D.h2("90. Running the archive-wide check")
    D.p("The wide accuracy pass covers the 1,218 pages that have ground truth "
        "in the client's own spreadsheets, and takes six to seven hours. Two "
        "things make it usable rather than merely long.")
    D.p("It needs no internet. This was verified rather than assumed: every "
        "non-loopback socket and DNS lookup was blocked and a page was run end "
        "to end, with zero external calls attempted. The recognition models "
        "are on disk and the header model runs on the loopback interface.")
    D.p("And it reports while it runs. A live state file is rewritten "
        "atomically after every page, and a local dashboard "
        "(tools/runboard.py, port 8099) shows progress, pages per minute, time "
        "remaining, running accuracy, the per-site breakdown and — the number "
        "that matters — how many pages hold a wrong day without being flagged. "
        "The rate is measured over a sliding window of at least fifteen "
        "minutes, never over the last page: page times range from seconds to "
        "two minutes, and a short window yields an estimate that swings so "
        "wildly it is worse than none.")
    D.p("The checkpoint is stamped with the pipeline version and is discarded "
        "automatically when that version changes, so a resumed run can never "
        "blend pages scored by two different extractors and report the average "
        "as though it measured one thing. That has happened once in this "
        "project's history and the guard exists because of it.")

    D.h2("91. The state of the system after this work")
    D.table(["What was measured", "Before 6 October", "After"],
            [["Day status, 50 hand-graded pages", "1,110 / 1,157 = 95.9%",
              "1,108 / 1,157 = 95.8%"],
             ["Rows wrong AND unflagged, same sample", "10", "2"],
             ["In and out clock times", "not measured, then 83.6%", "93.8%"],
             ["Shared multi-employee sheets", "362 / 366 = 98.9%", "366 / 366 = 100%"],
             ["Handwriting regression guard", "876 / 934 = 93.8%", "unchanged"]],
            caption="Pipeline v38-no-cls-drift-window, deployed to production on "
                    "6 October 2026. The day-status figure moved by two rows, which is "
                    "noise; the figure that moved meaningfully is the one below it.")
    D.p("The claim this supports is unchanged in character and stronger in "
        "degree: about 96 day rows in 100 are read exactly as written, in and "
        "out times about 94 in 100, and of 1,157 hand-checked rows two were "
        "wrong without carrying a flag. The system's promise was never that it "
        "does not misread. It is that a misreading does not reach payroll "
        "without someone being asked to look at it.")

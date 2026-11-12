"""Documentation content, part L: Part XX -- what the corpus run taught, the
regression it exposed, and the guard that now stops both recurring.

Written the morning after. Three of the findings here are corrections to
earlier findings in this same document, which is the point: the parts that
teach are the ones where the first answer was wrong and the measurement said so.
"""
from __future__ import annotations


def write(D):
    D.h1("Part XX — Measuring the measurement")
    D.p("Part XIX ended with a corpus run under way. It finished: 1,218 pages "
        "in four hours and twenty minutes, no crashes. The headline fell from "
        "84.3% to 77.2%, and chasing down why produced three findings, two of "
        "which are corrections to things stated confidently earlier.")

    D.h2("92. The headline fell because the measurement got more honest")
    D.table(["", "v33 run", "v41 run"],
            [["Pages matched to truth", "292", "338"],
             ["Day status", "84.3%", "77.2%"],
             ["Employee name", "98.3%", "98.2%"],
             ["Pages with a wrong day that were flagged", "164 / 164", "185 / 185"],
             ["Pages with a wrong day NOT flagged", "0", "0"]],
            caption="More pages qualified for scoring because names are read better. "
                    "Forty-six of them had previously been invisible to the measurement.")
    D.p("Forty-two of the matched pages produced zero correct days. They "
        "contribute 1,075 compared days, every one counted wrong — eleven per "
        "cent of the entire denominator. Removing them:")
    D.table(["Scope", "Day status"],
            [["All matched pages", "7,527 / 9,745 = 77.2%"],
             ["Excluding the 42 zero-day pages", "7,527 / 8,670 = 86.8%"],
             ["Delhi, excluding them", "86.8%"],
             ["HO, excluding them", "86.9%"]],
            caption="Two sites agreeing to within a tenth of a point is the signal that "
                    "86.8% is the real figure for pages the system reads at all, and that "
                    "the remainder is a small number of specific faults.")

    D.h2("93. Sixteen of those pages were read perfectly")
    D.p("The first of the three was opened and read by eye before any code was "
        "touched. It is a standard portrait sheet, mostly blank: only 24 to 31 "
        "July carry anything. The pipeline produced exactly that — 24 present, "
        "25 and 26 weekly off, 27 to 31 present, each with 9:00 to 17:30 and "
        "8.5 hours. Six present days against the sheet's own stated six; six "
        "times 8.5 equals the 51 man-hours it states. Nothing was wrong with "
        "it.")
    D.p("The truth row for that employee covers days 1 to 23. The page covers "
        "24 to 31. The two ranges do not intersect, so every comparison missed "
        "and a flawless page scored zero out of twenty-three. Sixteen pages "
        "were written off that way.")
    D.callout("A scored page and an unscorable page are different things",
              "A harness that confuses them manufactures defects that do not "
              "exist, and the engineering that follows is spent on phantoms. "
              "This is the third time this project has been sent after one: the "
              "66% clock-time figure (Part XIX), the apparent gain from raising "
              "page resolution, and now this. In each case the pipeline was "
              "fine and the ruler was bent.")
    D.p("The scorer now compares only the span of days a page actually recorded "
        "a status for. Inside that span a missed day still counts against us, "
        "so this narrows what is compared without ever forgiving a real miss. "
        "No overlap at all is reported as such, rather than as zero correct.")

    D.h2("94. The corrected scorer immediately found something worse")
    D.code("ESCAPED (wrong, not flagged)  2      <- must be 0\n"
           "  ADN902 APR 2026.pdf p1   28/30 days right, passed as CLEAN\n"
           "  ADN904 APR 2026.pdf p1   15/30 days right, passed as CLEAN")
    D.p("Half of one page's days were wrong and nobody would have been asked to "
        "look at it. That is the single outcome this product exists to "
        "prevent, and it had been introduced two sections earlier by a change "
        "that looked unambiguously good.")
    D.p("Diagnosed before being fixed. Both pages are internally consistent: "
        "twenty-six present days read against a stated twenty-six; thirteen "
        "present, thirteen leave and four weekly off read against a stated "
        "13 / 13 / 04. Every count reconciles. The right NUMBER of each status "
        "landed on the WRONG DAYS — and no count-based checksum can detect a "
        "permutation. The sheet's own arithmetic cannot catch this class of "
        "error at all.")
    D.p("So the earlier change had not created a blind spot. It had removed an "
        "ACCIDENTAL safety net: before it, those pages were blocked because "
        "their totals box could not be read — the right answer for an entirely "
        "unrelated reason. Being saved by accident is not the same as being "
        "safe, and restoring the accident would not have made it so.")
    D.callout("What 'clean' is allowed to mean",
              "A page whose hours were never checked against a stated total has "
              "not been verified, and must not be called clean. The repair is "
              "not a new detector — we cannot detect a permutation — it is to "
              "stop overclaiming. 'Clean' now means we checked it and it "
              "reconciled. It never means we had nothing to check.")
    D.table(["", "Before", "After"],
            [["ADN902 / ADN904 page status", "clean", "worth a look"],
             ["New issue raised", "—", "hours_not_verified (warning)"],
             ["Pages wrong AND passed as clean", "2", "0"]],
            caption="The pages still leave the must-fix queue, so the reduction in false "
                    "alarms is kept. They simply stop being advertised as confirmed.")

    D.h2("95. The guard: the floor as one command")
    D.p("Every regression this project has shipped has the same shape. The "
        "number being watched improves, and a number nobody is watching "
        "breaks. Twice in one week:")
    D.table(["Change", "What was watched", "What broke unwatched"],
            [["Angle classifier turned off",
              "clock times 83.6% → 93.8%, day status flat",
              "rows wrong AND unflagged 10 → 15"],
             ["Uncomputable checks downgraded",
              "false alarms halved, 50-page sample unmoved",
              "two pages began passing clean with half their days wrong"]],
            caption="Neither was caught by the metric the change was aimed at. Both were "
                    "caught afterwards, by hand, by asking the same boring questions.")
    D.p("Those questions are now written down and run as one command, with the "
        "measured floor hard-coded rather than remembered:")
    D.code("./.venv/bin/python tools/guard.py           # ~25 min, the full floor\n"
           "./.venv/bin/python tools/guard.py --quick   # ~2 min, structural only")
    D.p("It checks the accuracy floors, and it also checks that every flag "
        "whose default IS a measured decision still holds that default. A "
        "silent flip of the angle-classifier switch, or of the rejected "
        "clock-repair layer, would otherwise be attributed to whatever change "
        "happened to be in flight — which is precisely how a rejected "
        "behaviour re-entered this codebase once before. The guard fails the "
        "run rather than printing a number, and says so in words: do not ship; "
        "either fix it, or change the floor and write down why it moved.")
    D.table(["Check", "Floor at adoption (v41)"],
            [["50-page sample, day status", ">= 95.5%"],
             ["50-page sample, rows wrong AND unflagged", "<= 2"],
             ["50-page sample, days missing", "0"],
             ["Horizontal multi-employee sheets", "100%, 0 silent"],
             ["Fast extraction harness, day status", ">= 93.0%"],
             ["Employee name", ">= 30 of 31"]],
            caption="A floor is raised only with a run that proves the new value, and the "
                    "run is recorded in the decision log. The guard asks whether the "
                    "system got WORSE, not whether it got better.")

    D.h2("96. The corpus run under v41, and what its log showed")
    D.p("The run was repeated after the scorer fix. 1,218 pages, three hours "
        "thirty-four minutes, no crashes.")
    D.table(["Measure", "Result"],
            [["Day status", "7,171 / 7,961 = 90.1%"],
             ["Employee name", "274 / 278 = 98.6%"],
             ["Pages scored", "278 — of which 159 perfect (57%)"],
             ["Pages with a wrong day that were flagged", "119 of 119 = 100%"],
             ["Pages with a wrong day NOT flagged", "0"]],
            caption="The 77.2% figure it replaces is withdrawn. Most of the difference is "
                    "the scorer no longer counting disjoint date ranges as errors and the "
                    "hours column parsing on layouts printing '10Hrs' -- the earlier number "
                    "was wrong, not merely lower.")
    D.p("Two findings came out of the log that are worth more than the headline.")

    D.h2("97. Twenty-three per cent of pages yield no employee name — and are correctly stopped")
    D.p("292 of 1,218 pages produced no name. The first reading of that was "
        "that a page nobody can be identified on would reach payroll "
        "unattributed. Checked rather than assumed, and it is wrong: every one "
        "of those pages is already stopped, with a blocking issue and a plain "
        "sentence — \"Neither the employee name nor the code could be read, so "
        "this page cannot be matched to a person.\" Nothing silently escapes.")
    D.p("So this is a CAPABILITY gap, not a safety one. These are layouts the "
        "system cannot read automatically, and it says so. The cost is manual "
        "entry, not a wrong invoice — a materially different problem from the "
        "one it first appeared to be, and one that should not be allowed to "
        "justify risky changes to the paths that work. It is not spread thinly; "
        "whole layouts fail outright:")
    D.table(["Client folder", "Pages with no name read"],
            [["Thyssen Krupp", "37 of 37"],
             ["Trichy International Airport", "12 of 12"],
             ["Brilliant Bio Pharma", "12 of 12"],
             ["Avaada / Giriraj Renewable", "43 of 57"],
             ["Bharat Petroleum", "30 of 39"],
             ["Shell Hazira", "37 of 79"],
             ["Sunsure Energy", "16 of 24"]],
            caption="A layout at 37 of 37 is not a recognition problem. The header reader "
                    "does not understand that form, and no amount of OCR tuning will "
                    "change it.")
    D.p("Four of them were examined by eye. They are not one defect with one "
        "fix, which is what the single number suggested:")
    D.table(["Layout", "What it actually is"],
            [["Bharat Petroleum", "not a timesheet — an 'Aarvi Encon Leave Record Part-B', "
              "a multi-employee leave-balance table"],
             ["Trichy Airport", "a statutory FORM D attendance register: many employees per "
              "page, attendance marked as circled handwriting that OCR reads as "
              "'B', 'G', '4'"],
             ["Thyssen Krupp", "multi-employee grid, scanned sideways; the day-axis finder "
              "returns nothing at any of the four rotations"],
             ["Brilliant Bio Pharma", "multi-employee grid using a vocabulary the reader does "
              "not know (PP, EL, AB) with the day axis landing in the wrong place"]],
            caption="Rotating the page was tried first and rejected: none of the four "
                    "yields a name at 90, 180 or 270 degrees either. Each family needs its "
                    "own work, and none of it is a quick win.")

    D.h2("98. Two different problems wearing one number")
    D.p("Only 278 of 1,218 pages could be scored at all, and it is tempting to "
        "file that as one thing — missing ground truth. Separating the folders "
        "shows it is two, with opposite remedies.")
    D.table(["Client folder", "Truth rows", "Pages", "Scored", "What it actually is"],
            [["Technip Energies", "23", "490", "2", "ground truth covers 23 people of hundreds"],
             ["Bharat Petroleum", "457", "39", "0", "ample truth — the NAMES are not being read"],
             ["Thyssen Krupp", "154", "37", "0", "ample truth — no name read on any page"],
             ["Shell Hazira", "374", "79", "2", "ample truth — names not read"],
             ["Adani Infra", "250", "194", "143", "healthy: truth and pages align"],
             ["Garden Reach", "70", "89", "69", "healthy"],
             ["IOCL", "45", "41", "31", "healthy"]],
            caption="Where truth rows roughly match page count, 74-78% of pages score. Where "
                    "truth is plentiful and nothing scores, the fault is ours, not the "
                    "client's.")
    D.callout("The ask to the client is narrower than it looked",
              "Only Technip genuinely needs more ground truth. For Bharat "
              "Petroleum, Thyssen Krupp and the Shell sites the records are "
              "already there in quantity — those pages fail because this system "
              "cannot read a name off those layouts. Asking the client to supply "
              "data we already have would waste their goodwill and fix nothing.")

    D.h2("99. A small win, and the one that was taken back")
    D.p("Working those pages produced one genuine recovery. The Tractebel "
        "sheets label the field 'Name of Employee/Consultant:-Parag Pillai'. "
        "The name is plainly readable; the label scored 65 against a threshold "
        "of 80, so it was never found and the name was discarded.")
    D.p("The obvious move — lower the threshold — would have been a serious "
        "mistake. The near misses sit four points away from labels that must "
        "never bind to the employee field:")
    D.table(["Text on the page", "Before", "After", "Intent"],
            [["Name of Employee/Consultant:-Parag Pillai", "65", "82", "wanted"],
             ["SUPERVISOR NAME :", "64", "64", "must not match"],
             ["Project Name : Solarium Green Energy", "64", "64", "must not match"],
             ["CLIENT NAME :", "58", "62", "must not match"],
             ["APPROVER'S NAME :", "57", "58", "must not match"]],
            caption="Adding the phrase moves only the wanted string across the line. "
                    "Lowering the threshold to 65 would have bound the supervisor's name "
                    "as the employee on every sheet that names one.")
    D.callout("A label that names a COLUMN is not a label that names a PERSON",
              "'NAME OF RESOURCE' was added in the same change. It scored 100 "
              "and looked free. On the Solarium sheets it is a table column "
              "header on a multi-employee grid, and matching it produced "
              "'Company Project Name : Solarium Gr' as the employee — form "
              "furniture promoted to a person. It was removed the same hour. "
              "The only way to tell the two apart was to run it and look at "
              "what came out.")

    D.h2("100. Making 'clean' mean something again")
    D.p("One page in 278 passed as clean. The system had become honest and "
        "useless at the same time, which is not a stable place to leave it — a "
        "reviewer handed everything learns to click through everything.")
    D.p("The decision blocking it was the refusal to trust day-count "
        "reconciliation, taken because two pages reconciled and still "
        "disagreed with the client's records. Both were finally read off the "
        "paper, which should have happened first:")
    D.table(["Source", "Days 1 to 15 of April"],
            [["The paper", "'Leave' on 1-4, 6-11, 13-15; 'SUNDAY' on 5 and 12"],
             ["What we read", "L on 1-4, 6-11, 13-15; W on 5 and 12"],
             ["The client's spreadsheet", "A (absent) on all fifteen, Sundays included"]],
            caption="Days 16-30 agree on all three. We were right and the records were "
                    "wrong, so those pages were never evidence against counts. The fourth "
                    "time in this project that a defect has been a bent ruler.")
    D.p("Counts are now accepted as verification — on 26 perfectly-read pages "
        "only 12 carry an hours total, but 22 carry a present-day count and 20 "
        "of those reconcile exactly. One page then proved counts are not "
        "sufficient on their own: a sheet scoring 23 of 30 passed clean, and "
        "April 2026's Saturdays are the 4th, 11th, 18th and 25th while its "
        "weekly offs sat on a Wednesday and two Fridays. A real one-row drift.")

    D.h2("101. Placement can be checked after all — from the calendar")
    D.p("Section 94 concluded that a permutation cannot be detected, because "
        "the right number of each status reconciles with the sheet's own "
        "totals however the rows are arranged. That is true of everything ON "
        "the sheet. It is not true of the calendar, which neither the sheet "
        "nor the recogniser controls.")
    D.p("A site's rest day is a WEEKDAY, not a date. Whatever the local "
        "convention, weekly offs cluster on one or two weekdays; when rows "
        "drift against the dates, they scatter across the week.")
    D.table(["Page", "Weekly offs fell on", "Distinct weekdays"],
            [["the drifted page (23 of 30)", "Wed, Fri, Fri, Sat, Sat, Sun x3", "4"],
             ["seven correctly-read pages", "Saturday and Sunday only", "2"],
             ["a page resting on one day", "Sunday x4", "1"]],
            caption="Counting DISTINCT WEEKDAYS rather than weekend-ness keeps the test "
                    "convention-agnostic: a site that rests on Friday scores one weekday "
                    "and passes. Only scatter is suspicious. Threshold three.")
    D.callout("The version that did not work",
              "The first form of this idea asked whether the days off all fell "
              "on ONE weekday. It fired on correct pages that take both "
              "Saturday and Sunday, and passed both of the pages it was built "
              "to catch. The working test had to measure the SPREAD, not the "
              "alignment — and the difference between the two was only visible "
              "by running both.")
    D.table(["", "Before", "After"],
            [["Pages passing as clean", "0.4% (1 of 278)", "10.0% (7 of 70)"],
             ["Pages passing clean that are wrong", "1", "0"],
             ["Guard", "15/15", "15/15"]],
            caption="Every accuracy floor held unchanged: 95.8% day status, 2 rows wrong "
                    "and unflagged, 100% on the horizontal sheets.")

    D.h2("102. Telling a reviewer what a page IS")
    D.p("292 pages cannot be attributed to a person, and the layouts behind "
        "them are not all timesheets. A reviewer told only that the name could "
        "not be read has to open the scan to find out which. The plan was a "
        "detector for document kinds — 'Leave Record', 'Muster Roll'. "
        "Collecting the headings first killed it: exactly one of six carries a "
        "title clean enough to match on. A rule with one-in-six recall that "
        "can mislabel a real timesheet is not worth having.")
    D.p("What replaced it claims nothing and works on all of them: quote what "
        "the page says at the top.")
    D.code('"Neither the employee name nor the code could be read, so this page\n'
           ' cannot be matched to a person. The top of the page reads:\n'
           ' \"Time Sheet/Attendance for ....April....., 2026\"."')
    D.p("The first attempt quoted the AARVI letterhead — the Mumbai office "
        "address — on three of eight layouts, which is longer than silence and "
        "says less. Reusing the existing form-furniture list and taking the "
        "next-largest line gave four useful headings of eight and four silent "
        "ones, with no noise. The heading is shown to a human and never "
        "parsed, which is why it is safe to display text we would refuse to "
        "trust as data.")

    D.h2("103. The orientation that was computed four times and thrown away")
    D.p("Rotation had been rejected on sound evidence: no orientation recovers "
        "an employee NAME on these layouts. The conclusion drawn from it was "
        "too broad. Rotation is not the blocker for the name. It is absolutely "
        "the blocker for the GRID.")
    D.table(["Thyssen Krupp sheet", "find_day_axis"],
            [["as scanned", "nothing"],
             ["the same page rotated", "a row axis, 24 days"]],
            caption="Read by eye it is a landscape multi-employee grid stored sideways: "
                    "three employees down the left, day columns running 26 27 28 29 30 31 "
                    "1 2 ... 25 across a cross-month period, cells holding hours rather "
                    "than letters.")
    D.p("The orientation rescue was already trying that rotation and "
        "discarding it. It scored each candidate on anchors and days found by "
        "the profile extractor, and these pages yield zero of both at every "
        "orientation — so nothing ever beat the upright original, and the "
        "structural reader was handed the page still sideways. The right "
        "answer was computed four times per page and thrown away each time.")
    D.p("The structural reader's result is now a third key, consulted only "
        "when the first two tie, which is precisely the case where the profile "
        "extractor has nothing to say.")
    D.callout("A hypothesis is not evidence",
              "The first version scored a rotation on the SIZE of the day axis "
              "it produced. An Avaada page then chose a 180-degree turn that "
              "built a larger axis out of spurious numbers and read nothing "
              "from it, beating the orientation that read thirteen real days. "
              "An axis is a hypothesis; filled cells are evidence. The measure "
              "is now the number of day cells the reader actually fills.")
    D.p("Of twelve sampled pages that previously produced nothing, four now "
        "yield attendance data — sixty day cells in total, one of them "
        "recovering a name and a second employee. That is about a third of the "
        "class, and is worth stating as a third rather than as a fix. The "
        "branch is gated on the page having produced zero days, so no working "
        "page can enter it.")

    D.h2("104. One generalisation that should have worked, and did not")
    D.p("Two of the remaining layouts share a shape: one writes the HOURS "
        "worked in the day cell, another writes a bare 1, and the status "
        "reader returns nothing for both. A single rule — a number in a day "
        "cell means the person worked — should have covered both.")
    D.p("It was built with the guard that makes such a rule defensible: a "
        "numeric cell counts as presence only when the same band also carries "
        "a recognised status token, so a serial-number column or a row of "
        "totals can never be promoted into a month of attendance.")
    D.table(["", "Pages yielding data", "Day cells"],
            [["without the rule", "4 of 12", "60"],
             ["with the rule", "5 of 16", "61"]],
            caption="One extra cell. The bands on these pages do not carry the status "
                    "letter the guard requires often enough for the rule to fire: the idea "
                    "is right and its precondition is rarely met.")
    D.p("It was switched off. Being principled, gated and risk-free is not "
        "sufficient — the same was true of the clock-grammar layer, which was "
        "also rejected. A code path that cannot show a measured gain is a "
        "maintenance cost and a future source of 'why is this here'. It stays "
        "in the tree behind a flag with the measurement beside it, and the "
        "guard now pins that flag off so it cannot drift back on unnoticed.")
    D.p("The real blocker on those pages is upstream: the day axis lands short "
        "— twelve to fourteen columns of about thirty — so most cells are "
        "never looked at. Fix the axis first, then re-measure this flag before "
        "writing anything new.")

    D.h2("105. Fixing the day axis: a month boundary and a bucket edge")
    D.p("The remaining layouts were blocked upstream — the day axis was "
        "landing on twelve columns of about thirty, so most cells were never "
        "looked at. Dumping what the finder actually saw, rather than "
        "reasoning about it, gave two causes. Neither is specific to a client.")
    D.p("**A timesheet period is not always a calendar month.** One header "
        "reads 21Mar 22Mar … 31Mar 01Apr 02Apr … 20Apr. The run ascends, "
        "resets once, and ascends again, and the longest-ascending search can "
        "only keep one side of that reset. This corpus is full of such "
        "periods, and a fortnightly template has existed since the beginning.")
    D.table(["Header", "Columns found before", "After"],
            [["21 March to 20 April", "20", "31"],
             ["26 March to 25 April", "25", "31"],
             ["a plain calendar month", "31", "31 (unchanged)"]],
            caption="At most ONE reset is allowed, and only when the second part starts "
                    "lower than the first part ends. That is what a month boundary looks "
                    "like and what a column of random numbers does not.")
    D.p("**And a printed header straddling a bucket edge was being cut in "
        "half.** Candidates were grouped with integer division, which splits a "
        "group whenever it crosses a boundary, however tight the group "
        "actually is. On the same sheet the header came back as 23 boxes in "
        "one bucket and 9 in the next, so eight columns were invisible no "
        "matter how the run was computed. Nothing was wrong with the page; the "
        "boundary happened to fall inside it. Grouping on a real gap has no "
        "such arbitrary edge.")
    D.table(["Sheet", "Axis before", "After month boundary", "After clustering"],
            [["Brilliant Bio Pharma", "12 days", "23 days", "31 days"],
             ["Thyssen Krupp", "24 days", "30 days", "30 days"]],
            caption="This touched find_day_axis, which is what delivers 100% on the "
                    "horizontal multi-employee sheets — the change most able to do quiet "
                    "damage. The guard held at 15 of 15, ISGEC still 366 of 366.")
    D.p("End to end, of the pages that previously produced nothing: none, then "
        "four of twelve with sixty day cells after the orientation fix, then "
        "six of sixteen with seventy-four after the axis fix. One Avaada sheet "
        "now reads 31 days with a name, another reads 13 days and finds three "
        "further employees on the same page. Six of sixteen is worth stating "
        "as six of sixteen.")
    D.callout("A rejection that says 're-measure later' has to be re-measured",
              "The numeric-cell rule was rejected on one cell of evidence with "
              "a note that the axis was starving it. The axis is now fixed, so "
              "it was run again: six of sixteen pages and seventy-four cells "
              "with the rule ON, and exactly the same with it OFF. The "
              "precondition it needs is not met on these sheets. It stays off, "
              "and the guard pins it off — but the note is answered rather than "
              "left hanging, which is the only thing that makes such a note "
              "worth writing.")

    D.h2("106. Where the system stands")
    D.table(["What was measured", "Result"],
            [["Day rows correct — 50 random pages graded by hand against the paper",
              "1,108 of 1,157 = 95.8%"],
             ["Rows wrong and carrying no flag", "2 of 1,157"],
             ["In and out clock times", "1,437 of 1,532 = 93.8%"],
             ["Shared multi-employee sheets", "366 of 366 = 100%, all 12 people"],
             ["Employee name, corpus-wide", "98.2%"],
             ["Pages containing a wrong day that were flagged", "185 of 185"],
             ["Pages containing a wrong day NOT flagged", "0"],
             ["Whole archive processed", "9,003 pages, no failures"]],
            caption="Pipeline v41-clean-means-verified, running in production since "
                    "7 October 2026. The corpus figure is in section 96: 90.1% against "
                    "the client's own records, measured on the 278 pages that could be "
                    "scored at all.")
    D.p("The claim this supports has not changed in character since the "
        "beginning of this document, and should not be stretched: about 96 day "
        "rows in 100 are read exactly as written, in and out times about 94 in "
        "100, and of 1,157 rows checked by hand against the paper, two were "
        "wrong without carrying a flag. The promise was never that the system "
        "does not misread. It is that a misreading does not reach payroll "
        "without someone being asked to look at it — and section 94 is what "
        "that promise costs to keep when a change quietly threatens it.")

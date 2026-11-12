"""Documentation content, part J: Part XVIII -- how to use the system, with
screenshots of the running application, and the v35 changes (sheets that list
several people, per-person logins, page locks, records and running costs).

Every screenshot was taken from the application itself on 6 Oct 2026, reading
the four ISGEC sheets and one handwritten sheet. Nothing here is a mock-up.
"""
from __future__ import annotations


def write(D):
    D.h1("Part XVIII — Using the system, step by step")
    D.p("This part is written for the people who will use the tool rather "
        "than build it: what each screen does, what the colours mean, and "
        "what to do when something is flagged. Every picture is the real "
        "application reading real timesheets. Parts I to XVII explain how it "
        "works inside; this part explains how to work it.")

    D.h2("73. What the system is for, in one paragraph")
    D.p("Paper timesheets arrive as scans or phone photos. The system reads "
        "every page, checks each sheet's own totals against its day rows, and "
        "holds back anything that does not add up for a person to confirm. "
        "What comes out is an Excel file with a payroll sheet, an attendance "
        "grid, an invoice sheet and a full record of every change. The "
        "promise is not that it never misreads; it is that a misread does not "
        "reach payroll without someone seeing it first.")

    D.h2("74. The home screen")
    D.figure("ui_home.png",
             "The home screen: what the tool does, how accurate it is, and the "
             "batches uploaded so far. Each batch can be re-opened for checking "
             "or downloaded again at any time.")
    D.p("The four figures on the right are measured, not estimated, and are "
        "explained in Part XVII. 'Rows wrong without a flag' is the honest "
        "counterpart to the accuracy figure: about one row in a hundred can be "
        "wrong without being marked, which is exactly why the checking step "
        "exists and should not be skipped.")

    D.h2("75. Step 1 — Upload")
    D.figure("ui_upload.png",
             "Drop a whole month of scans at once, or click to choose files. "
             "PDF, JPG, PNG and TIFF are accepted.")
    D.bullets([
        "A PDF with many pages is split automatically; each page is read on its own.",
        "A page that has been uploaded before is recognised and not read again, "
        "so re-uploading a corrected batch costs nothing.",
        "Files that cannot be opened at all are listed as skipped, with the reason, "
        "rather than failing silently.",
    ])

    D.h2("76. Step 2 — Reading")
    D.figure("ui_done.png",
             "The reading screen. Progress, a count of what came out clean, and a "
             "plain-language log of what the system is doing, newest at the bottom.")
    D.p("The log is deliberately in ordinary words. A line such as "
        "\"This sheet lists 3 people — added 2 more to check\" is the system "
        "telling you it found a shared sheet and created a record for each "
        "person on it. Ticking 'show technical detail' adds the engineering "
        "detail behind each line for anyone who wants it.")
    D.table(["Tile", "What it counts"],
            [["Pages scanned", "Every page read in this batch"],
             ["All good", "Pages where every arithmetic check passed"],
             ["Worth a look", "Pages with a minor warning only"],
             ["Must fix", "Pages where a total does not match the day rows, "
                          "or the sheet's own total box was left blank"],
             ["Boxes read", "Individual values lifted off the paper"],
             ["Typing time saved", "At four minutes a sheet, the manual equivalent"],
             ["Already read before", "Pages recognised from a previous upload"]],
            caption="Most pages land in 'Must fix' on sites that leave the "
                    "'Total Man Hours' box blank; that is the single biggest "
                    "lever the client has to reduce review work.")

    D.h2("77. Step 3 — Check")
    D.figure("ui_review.png",
             "The checking screen: the list of pages on the left, the original scan "
             "in the middle, and what was read on the right, editable.")
    D.p("The three panels line up so a reviewer never has to remember "
        "anything. Problems are listed in red at the top of the right-hand "
        "panel, in the words of the sheet rather than the code. Smaller "
        "warnings are folded away behind a single line so they do not drown "
        "the real ones.")
    D.table(["On the screen", "Meaning"],
            [["Green badge, ✔ with a percentage", "Read clearly; nothing to check"],
             ["Amber badge, ? with a percentage", "Worth a glance — hover it to see why"],
             ["Red badge, ✖", "Fix this before downloading"],
             ["Red box around a field", "That field failed a check"],
             ["Blue box around a field", "You changed it and have not saved yet"],
             ["👤 a name in the page list", "Someone else is checking that page right now"]],
            caption="Hovering any badge shows the reason in plain words, for example "
                    "'the handwriting here was hard to read'.")
    D.p("Keyboard: J and K move to the next and previous page, Ctrl+S (or "
        "⌘S) saves. 'Save and check again' re-runs every arithmetic check on "
        "the corrected figures, so a fix that breaks a total is caught "
        "immediately rather than at invoice time. Every change is recorded "
        "with who made it, what it was before and what it became.")

    D.h2("78. Sheets that list several people on one page")
    D.p("Some sites use a landscape sheet with the days running across the "
        "top and several employees down the side — one letter per cell, and "
        "often no totals box anywhere on the page. Four such sheets were "
        "provided by the client's team on 2 October 2026.")
    D.p("Each person on the sheet now becomes a record of their own, "
        "pointing at the same scan, so each can be checked, corrected, locked "
        "and exported exactly like anyone else. Before this change only one "
        "person per sheet survived and the rest were dropped without a word.")
    D.table(["On the four shared sheets", "Before (v34)", "After (v35)"],
            [["People reaching the reviewer", "4 of 12", "12 of 12"],
             ["Day cells read correctly", "120 of 366 = 32.8%", "366 of 366 = 100%"],
             ["Days lost without a word", "246", "0"],
             ["Wrong rows carrying no flag", "0", "0"]],
            caption="Truth taken from the PDFs' own text layer, which is a different "
                    "source from the reader being measured. Test set and method: "
                    "data/testsets/horizontal-multi-employee. Decision D-066.")
    D.bullets([
        "A blank cell means the person did not work that day. Where the "
        "calendar says the column is a Sunday it is recorded as the weekly "
        "off; any other blank is left unset and flagged rather than guessed.",
        "These sheets carry no clock columns, so 'present with no hours' is "
        "the format, not a fault, and is no longer flagged on them.",
        "They carry no totals box either, so the payroll sheet shows day "
        "counts worked out from the rows, with a COUNTS_FROM column saying "
        "so. Those counts are deliberately kept separate from what the sheet "
        "states, because the checks compare the two.",
    ])

    D.h2("79. Step 4 — Download")
    D.figure("ui_download.png",
             "One Excel file, six sheets. The payroll sheet is the one most teams use.")
    D.table(["Sheet", "What it holds"],
            [["Payroll_Import", "One line per employee per month, with a status: "
                                "OK, REVIEW or HOLD"],
             ["Attendance", "The day-by-day grid, in the shape the client's own "
                            "spreadsheets already use"],
             ["Invoice", "Billing view: mandays, man-hours and overtime"],
             ["Timesheet Detail", "Every row of every sheet, with the sheet's own "
                                  "summary as written"],
             ["Audit", "Who changed what, from what, to what, and when"],
             ["Dashboard", "How much came in, how much is clean, and which sites "
                           "generate the problems"]])
    D.callout("The rule for payroll",
              "Take the lines marked OK. Have someone confirm REVIEW and HOLD "
              "lines on the checking screen first, then download again. This "
              "is what makes the figures that reach payroll trustworthy even "
              "though the reader itself is not perfect.")

    D.h2("80. Records — where everything is kept")
    D.figure("ui_records.png",
             "The records screen: where the files live, the monthly totals ready for "
             "payroll, the change history, and the employee list.")
    D.p("Everything lives in one folder on the server, outside the "
        "application, and is backed up every night. Nothing is stored "
        "anywhere else and nothing leaves the server.")
    D.table(["Where", "What"],
            [["timesheets.db", "Every page's reading and corrections, its review "
                               "status, and the change history"],
             ["uploads", "The PDFs and photos exactly as received"],
             ["pages", "One cleaned-up image per page, as shown on the checking screen"],
             ["exports", "Every Excel file downloaded"],
             ["roster.csv", "The employee list used to recognise names and codes"],
             ["cache", "Pages already read, so uploading them again is instant"]],
            caption="Payroll can take the Payroll_Import sheet, read the database "
                    "directly, or call the same interface the screens use.")

    D.h2("81. Running it day to day")
    D.table(["Task", "How"],
            [["Add a person who can sign in", "./gcp/user.sh add <name> — prints a "
                                              "password once and records it"],
             ["Remove someone", "./gcp/user.sh remove <name>"],
             ["Add or change employees", "Records → Employee list → upload a new CSV "
                                         "(name, code, site, designation)"],
             ["Two people on one page", "The first to open it has it; the second sees "
                                        "a read-only view naming who has it. A page "
                                        "frees itself after five minutes of inactivity"],
             ["See what it costs", "/cost — this project's Google Cloud spend only"],
             ["Daily backup", "Automatic, 20:00 UTC, seven days kept"],
             ["Upgrade", "Copy the new image to the server and restart; data is "
                         "untouched because it lives outside the application"]])
    D.p("Every action a person takes — opening, correcting, re-reading, "
        "uploading an employee list, downloading — is recorded under that "
        "person's name, which is what makes the audit sheet worth anything.")

    D.h2("82. Where the numbers stand today")
    D.p("These supersede the figures in Parts V, XVI and XVII where they "
        "differ. All were re-measured on 6 October 2026 on pipeline "
        "v38-no-cls-drift-window, which is the code running in production.")
    D.table(["What was measured", "Result"],
            [["Day rows correct — 50 random pages graded by hand against the paper",
              "1,108 of 1,157 = 95.8% (96.9% counting worked Sundays the way the "
              "sheets' own totals do)"],
             ["Rows wrong and carrying no flag, same sample", "2 of 1,157 = 0.2%"],
             ["Pages containing a mistake that were flagged", "12 of 12 — none escaped"],
             ["In and out clock times", "1,437 of 1,532 = 93.8%"],
             ["Shared multi-employee sheets", "366 of 366 days = 100%, all 12 people"],
             ["Handwriting regression guard", "876 of 934 = 93.8%"],
             ["Whole archive processed", "9,003 pages, no failures"]],
            caption="Measured 6 October 2026 on pipeline v38-no-cls-drift-window. "
                    "The wider pass against the client's own Excel is being re-run on "
                    "this pipeline; the previous figure (88.8% over 292 pages) was "
                    "measured before the three defects in Part XIX were fixed and is "
                    "withdrawn rather than carried forward.")
    D.p("The same sample, split by site and by whether the values are typed "
        "or handwritten. Nothing in the system is tuned per site; the "
        "differences are differences in the paper.")
    D.table(["Site", "Values on the sheet", "Day rows correct", "Allowing for coding convention"],
            [["HO", "typed", "98.9%", "98.9%"],
             ["Kolkata", "typed", "97.9%", "97.9%"],
             ["Kolkata", "handwritten", "97.8%", "98.9%"],
             ["Delhi", "typed", "96.3%", "98.8%"],
             ["HO", "handwritten", "94.3%", "95.1%"],
             ["Delhi", "handwritten", "91.7%", "93.1%"],
             ["All", "", "95.8% (1,108 of 1,157)", "96.9%"]],
            caption="These supersede the per-site figures quoted in Part XVII, which were "
                    "measured two versions earlier. Handwritten Delhi sheets remain the "
                    "hardest paper in the corpus and are where the remaining work is.")
    D.callout("What the accuracy figure does and does not say",
              "95.8% is the share of individual day cells read exactly as written "
              "on the paper, counted over 50 pages chosen at random and checked by "
              "hand. It is not a page score, not an average of good pages, and not "
              "measured on pages the system was built against. The figure that "
              "protects an invoice is a different one: every page containing a "
              "mistake was flagged for a person, 12 out of 12 on this sample. It covers the day status only -- in and out clock times are a separate measurement, 93.8%, and must never be quoted under this number.")
    D.p("The claim to make is: 'about 96 rows in 100 are read correctly, and "
        "every page containing a mistake is flagged for a person'. The claim NOT "
        "to make is any figure for the share of individual mistakes caught: of "
        "the rows that are wrong, roughly three in four carry a flag, which is "
        "precisely why the page-level check, not the row-level one, is the "
        "guarantee worth giving.")

    D.h2("83. A one-page card for the people who use it")
    D.bullets([
        "Upload a whole month at once. Scans or phone photos both work.",
        "Wait for the reading to finish. It is about ten seconds a page.",
        "Go to Check. Work the red ones first, then the amber ones.",
        "Look at the scan on the left and the reading on the right. Correct the "
        "right-hand side where they disagree, then press Save and check again.",
        "When nothing red is left, go to Download and take the Excel.",
        "Give payroll the lines marked OK. Hold the rest until someone has confirmed them.",
        "If a sheet is not a timesheet at all, the system refuses it rather than "
        "guessing. That is correct behaviour, not a failure.",
    ], numbered=True)

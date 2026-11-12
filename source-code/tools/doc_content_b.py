"""Documentation content, part B: low-level design, algorithm by algorithm."""
from __future__ import annotations

from docx.shared import RGBColor

OK = RGBColor(0x2F, 0x85, 0x5A)
WARN = RGBColor(0xC0, 0x56, 0x21)


def write(D):
    D.h1("Part III — Low-Level Design")
    D.p("This part walks the pipeline stage by stage. Each chapter states what "
        "the stage receives, what it must produce, the algorithm, the "
        "parameters that matter, and the failures that shaped it.")

    # ------------------------------------------------------------------ 9
    D.h2("9. Preprocessing")
    D.p("Input is a phone photograph taken inside a refinery: skewed, "
        "shadowed, sometimes curved. Every step exists to remove a specific "
        "failure that cannot be fixed later.")

    D.h3("9.1 Rasterisation")
    D.p("PDFs are rendered by pypdfium2 at scale 2, roughly 144 dpi from a "
        "72 dpi page. That is enough for handwriting without producing an "
        "image that must then be shrunk. Landscape pages are an exception and "
        "are rendered larger — see 9.4.")

    D.h3("9.2 Deskew")
    D.p("Skew is estimated from the dominant near-horizontal ruling lines "
        "using a probabilistic Hough transform, not from text baselines. "
        "Ruled forms give a far more stable estimate, and these sheets are "
        "always ruled. The median angle of all near-horizontal segments is "
        "taken; rotations below 0.2° are skipped as not worth resampling, and "
        "anything beyond ±15° is refused because a wrong rotation is worse "
        "than none.")
    D.callout("A compatibility trap.",
              "OpenCV 4 returns HoughLinesP results shaped (N,1,4) and OpenCV 5 returns "
              "(N,4). The code reshapes defensively, because the failure mode is a hard "
              "TypeError on every single page, not a degraded result.")

    D.h3("9.3 Illumination flattening")
    D.p("The page is divided by a heavily blurred copy of itself. The blur "
        "approximates the lighting field, so dividing it out leaves "
        "reflectance. This is what stops faint pencil in a shadowed corner "
        "from disappearing when the image is later thresholded.")
    D.code(
        "blur = cv2.GaussianBlur(gray, (0, 0), sigmaX=max(gray.shape) / 20.0)\n"
        "flat = cv2.divide(gray, blur, scale=255)      # app/preprocess.py")

    D.h3("9.4 Resolution — a measured, shape-dependent decision")
    D.p("Portrait pages are resized to a 1,600 px long edge. That value was "
        "swept and re-confirmed during this work: larger is not better for "
        "handwriting.")
    D.table(["Long edge", "Day accuracy", "Matched pages"],
            [["1600", "853/934 = 91.3%", "31"],
             ["2000", "843/963 = 87.5%", "32"],
             ["2400", "854/994 = 85.9%", "33"]],
            caption="Resolution sweep on the handwritten evaluation. Higher resolution "
                    "surfaces slightly more pages but reads the grid less well. 1600 stands.")
    D.p("Landscape pages are the opposite case and needed a change. A "
        "landscape sheet carries thirty day-columns across its width, so each "
        "cell is a few pixels wide at 1,600 px and OCR destroys it. "
        "Resolution has to be won at rasterisation — upscaling the raster "
        "afterwards interpolates and recovers nothing.")
    D.table(["Render", "Day header 1..30 read correctly"],
            [["scale 2, long edge 1684", "4 of 30"],
             ["scale 3, long edge 2526", "30 of 30"]],
            caption="Measured on a SHELL sheet. The stated PRESENT total also went from "
                    "'B3' to '23'. Landscape pages now target a 2,600 px long edge.")

    # ----------------------------------------------------------------- 10
    D.h2("10. OCR Engine and Page Routing")
    D.h3("10.1 The engine")
    D.p("RapidOCR runs PaddleOCR's PP-OCRv6 detection and recognition models "
        "converted to ONNX, plus a text-line orientation classifier. Three "
        "model files totalling about 32 MB are baked into the container at "
        "build time so a running container needs no network. Each text box "
        "returns its polygon, its text, and a confidence in [0,1].")

    D.h3("10.2 The confidence profile")
    D.p("Four statistics summarise a page. The load-bearing one is p25 — the "
        "weakest quarter of readings, where errors concentrate. A mean hides "
        "exactly the tail that matters.")
    D.code(
        "{'n': len(boxes),\n"
        " 'mean': mean(conf),\n"
        " 'p25': percentile(conf, 25),        # the load-bearing statistic\n"
        " 'frac_low': fraction(conf < 0.80)}  # app/ocr_engine.py")

    D.h3("10.3 Routing")
    D.p("A page is 'confident' when p25 ≥ 0.90 and frac_low ≤ 0.15; otherwise "
        "it needs escalation, meaning the handwriting-tolerant extraction path. "
        "The thresholds sit in the gap measured between typed pages "
        "(p25 ≥ 0.993) and handwritten ones (p25 = 0.777), not at the edge of "
        "either cluster, so ordinary variation cannot flip a page across the "
        "boundary.")
    D.callout("Where this routing does NOT work.",
              "It classifies pages, not content. On a printed FORM filled in by hand the "
              "crisp printed labels dominate the average, and a genuinely handwritten "
              "IOCL sheet scored p25 = 0.9236 — indistinguishable from a typed SHELL "
              "sheet at 0.9357. Measuring confidence in the page BODY only, below the "
              "header band, separates them cleanly: 23 and 42 weak readings versus 0.")

    D.h3("10.4 Printed rule detection")
    D.p("Horizontal rules are found by morphological opening with a kernel "
        "30% of the page width. A structure that long can only be a table "
        "rule; text is deleted entirely by the operation. This is "
        "deterministic, takes milliseconds and uses no model, which is why it "
        "is affordable on every page.")

    # ----------------------------------------------------------------- 11
    D.h2("11. Extraction — Recovering the Day Grid")
    D.p("This is the core of the product and the largest module. The task: "
        "from a bag of text boxes with positions, produce up to 31 day rows, "
        "each with date, in, out, hours, overtime and remarks.")
    D.figure("04_extraction.png",
             "Figure 4 — Day-grid recovery. Structure comes from the printed form; "
             "the handwriting supplies only values.")

    D.h3("11.1 Anchors: finding the header fields")
    D.p("Header labels are located by fuzzy matching against known patterns "
        "with a threshold of 80 on a rapidfuzz ratio, restricted to the top "
        "35% of the page so that look-alike words further down cannot bind. "
        "A value is then taken from the boxes to the right of the label, "
        "requiring the value's vertical centre to lie within the label's line "
        "band.")
    D.callout("Why the centre, not overlap.",
              "Overlap alone is too permissive for handwriting: a value written large on "
              "line 2 overlaps the label on line 1 by more than a third of its height. "
              "The measured symptom was employee_name coming back as "
              "'Shiv Shankan Apsinl -2026' — the month from the row above swallowed into "
              "the name.")

    D.h3("11.2 Content typing beats geometry")
    D.p("Six attempts to assign header values by geometry failed. Reading the "
        "actual scans explains why: on one page the handwriting is large "
        "enough that values sit almost exactly between their own label and the "
        "next one.")
    D.code(
        "MONTH & YEAR    label cy=231    'APRIL-2026'         cy=257  (+26)\n"
        "EMPLOYEE NAME   label cy=262    'RAJEEV IYENGAR'      cy=292  (+30)\n"
        "DESIGNATION     label cy=292    'SAFETY SUPERVISOR'  cy=324  (+32)\n"
        "\n"
        "'APRIL-2026' is 5 px from the WRONG label and 26 px from its own.")
    D.p("The geometry is genuinely ambiguous; the values are not. "
        "'APRIL-2026' is obviously a month and 'RAJEEV IYENGAR' is obviously a "
        "person. Each candidate is therefore scored by what it contains, and "
        "a small assignment problem gives every candidate to the field that "
        "wants it most, at most one per field. A value that looks like nothing "
        "scores low everywhere and is left unassigned, which is the safe "
        "outcome.")

    D.h3("11.3 Row bands")
    D.p("Rows come from the printed rules when they form a regular ladder. A "
        "uniform ladder is fitted across the detected rules using the month "
        "length as a prior, requiring 82% alignment before it is accepted. "
        "Where rules are absent or irregular the fallback is clustering ink by "
        "the grid's row pitch — not by box height, because handwriting varies "
        "in size far more than the row spacing does.")
    D.callout("An empty band is data.",
              "When rows come from printed rules, a band with no ink is a genuine blank "
              "row and must be kept as a placeholder. Dropping it is precisely the bug "
              "that shifts every later day by one and corrupts the rest of the month.")

    D.h3("11.4 Columns")
    D.p("Column x-ranges are learned from the printed headers, widened by 35% "
        "of the header's own width because values are often written wider than "
        "their label. When the date header is unreadable — 'Dale', 'Dote' are "
        "real examples — the column is derived from the left edge of the other "
        "columns that were found, since the date is always leftmost in this "
        "form family. Losing a header is recoverable; losing the grid is not, "
        "and without a date column no day rows are emitted at all.")
    D.callout("A generalisation defect fixed during this work.",
              "That fallback used absolute pixel thresholds (a 20 px gap, a 5 px pad) "
              "tuned when every page was 1,600 px wide. Landscape pages are now rendered "
              "at 2,600 px, where '20 pixels' means something different. They are now "
              "expressed as fractions of page width, so the same rule holds at any "
              "resolution.", color=OK)

    D.h3("11.5 Day numbers from position, not from ink")
    D.p("Rows whose handwritten date is illegible still carry perfectly good "
        "in/out and hours cells. Discarding them was the single largest source "
        "of error in the product: 35.1% of day-status comparisons failed "
        "purely because a row had been dropped — more than misreads and empty "
        "statuses combined. The requirement for a readable date was removed; "
        "the day number is recovered from row order against the calendar "
        "instead.")

    D.h3("11.6 Status inference")
    D.p("The AARVI form has no status column. Presence is implied by whether "
        "the row carries hours, and non-working days are annotated across the "
        "row or in Remarks. Order matters, because a row can carry both — "
        "'SUNDAY' written across a row that still shows a shift.")
    D.bullets([
        "A fuzzy weekday annotation wins first. OCR mangles these constantly: 'Sinday', 'Sumday', 'Sundoy', 'Swday', 'Sudny'.",
        "Then abbreviated markers: W/OFF, C/OFF, P.H. — frequently written into the hours column rather than Remarks.",
        "Then explicit words: absent, holiday, comp-off, leave, week-off.",
        "Then a lone status letter filling an entire cell, but only on a row with no work evidence.",
        "Finally, presence inferred from positive hours or either clock reading.",
    ], numbered=True)
    D.p("The fuzzy gate for weekday words was swept during this work. Two real "
        "rows read 'Swday.' and 'Sudny' — single-letter deletions that score "
        "72.7 against SUNDAY and so fell through a gate set at 82, reporting a "
        "marked weekly off as a worked day.")
    D.table(["Threshold", "68", "70", "72", "74", "76", "78", "80", "82", "84"],
            [["Day comparisons correct", "825", "825", "825", "819", "819",
              "820", "820", "820", "816"]],
            caption="Sweep of the annotation fuzzy gate. 68–72 is a flat plateau rather "
                    "than a spike, so 72 is not fitted to noise. Five pages change, four "
                    "up and one down by a single day.")

    # ----------------------------------------------------------------- 12
    D.h2("12. The Generic Grid Reader")
    D.p("The profile-based extractor knows three client layouts. Any page "
        "matching none of them yields nothing at all — measured on the HO "
        "dataset, 207 of 247 pages produced no employee name. Adding a fourth "
        "anchor set does not generalise; the next client arrives with a fifth.")
    D.h3("12.1 The invariant")
    D.p("Whatever else differs between clients, a monthly timesheet must "
        "enumerate its days. Somewhere on the page there is a run of the "
        "integers 1 to 28–31 in order. That run is either a column (days down "
        "the page, one row per day) or a row (days across the page, one column "
        "each). So instead of asking 'which client is this?', the reader asks "
        "'where are the day numbers, and which way do they run?' — a question "
        "that has an answer on a layout nobody has seen before.")
    D.h3("12.2 Finding the run")
    D.p("Candidate boxes are those whose text parses as a day number. That "
        "parser accepts far more than plain integers, because clients head "
        "their columns very differently and handwritten dates arrive mangled.")
    D.code(
        "7   7.0   07              plain\n"
        "'7 Mon'                   day plus weekday\n"
        "'2026-05-01 00:00:00'     an Excel datetime  (Kolkata LTMM)\n"
        "'21May Thu'               day + month + weekday, 21st-to-20th cycle\n"
        "'01426'  '0314126'        handwritten dates, separators lost to OCR")
    D.p("Candidates are clustered by y (for a row-oriented grid) or by x (for "
        "a column-oriented one), and the longest strictly ascending run is "
        "taken by a classic longest-increasing-subsequence pass. Tolerating "
        "strays matters because OCR misreads headers — a real example read "
        "'10' as '20' and '15' as '13'.")
    D.callout("Why ascending, and why that is elegant.",
              "A constant column — '17.00' repeated on every row — cannot form an "
              "ascending run, so the hours columns reject themselves. No hardcoded rule "
              "about where the date column sits is needed.", color=OK)
    D.h3("12.3 Refusing an employee list")
    D.p("An ascending column of integers is not necessarily days. A serial "
        "number column in an employee list looks identical. The first version "
        "of this reader confidently called one a 28-day grid:")
    D.code(
        "4 | Rahul Sahu     | 260316054 | Field Operator | AVAILED\n"
        "5 | Anu Yadav      | 260131027 | Field Operator | AVAILED\n"
        "6 | Pratham Prajap | 260201044 | Field Operator | AVAILED")
    D.p("Left alone, that invents a month of attendance for a person who has "
        "none. The guard reads the rows rather than the header: a day row "
        "carries short cells — statuses, clock times, hours — while an "
        "employee-list row carries a person's name. Two or more alphabetic "
        "words is the test, so 'AVAILED', 'Sunday' and 'P' still pass as "
        "legitimate day content while 'Rahul Sahu' does not.")
    D.table(["Page", "Detector verdict", "Correct?"],
            [["SHELL02 (typed, days across)", "row grid, 30 days", "yes"],
             ["IOCL (handwritten, days down)", "column grid, 17 days", "yes"],
             ["Vikram Solar", "column grid, 16 days", "yes"],
             ["BHAR07 (employee list)", "no day grid found", "yes — correctly refused"]],
            caption="One detector, four layouts, no client-specific knowledge.")

    # ----------------------------------------------------------------- 13
    D.h2("13. Reconciliation")
    D.p("Every other stage reads pixels. This one reads nothing: it takes the "
        "record already extracted and asks whether it is self-consistent, then "
        "repairs what is not, using two sources that cost nothing and cannot "
        "be misread by OCR.")
    D.bullets([
        ("The summary block.", "The supervisor writes the totals by hand at the bottom. Those numbers are short, anchored to printed labels, and read far more reliably than thirty rows of handwriting. If the grid yields 24 present days and the sheet says 26, the grid is wrong — and by exactly how much."),
        ("The calendar.", "Weekly offs are not scattered at random; they fall on the same weekday. Given the period, every day number has a known weekday, so one confirmed Sunday implies the others."),
    ])
    D.h3("13.1 Three safety rules")
    D.bullets([
        "It only fills rows that are empty — no status and no clock times. A row that was actually read is never overwritten by an inference.",
        "It only fills up to the stated count, never beyond it.",
        "Everything it changes is marked, so the reviewer sees inferred values as inferred.",
    ], numbered=True)
    D.h3("13.2 Establishing the period")
    D.p("All calendar reasoning is gated on knowing (year, month). Three "
        "sources are tried. The printed label is parsed with a fuzzy month "
        "rescue, because 'Apsil' scores 80 against APRIL while traps stay "
        "below 70. Failing that, the month is inferred from the grid itself: "
        "confirmed weekly offs fall on specific day numbers, and only some "
        "months of that year put all of those numbers on the same weekday. "
        "Finally the file path is consulted.")
    D.callout("Why the path is now consulted first.",
              "OCR can return a month that is not merely unreadable but confidently "
              "wrong. One sheet whose label OCR'd as 'ELENT Lowes Parel, Mumbst 400819 "
              "VIERAM SOLAR UMITED' resolved to March 2025 for a page that is plainly "
              "April 2026. A wrong period aims every weekday calculation at the wrong "
              "days. The path states it without an OCR step in the way.")

    D.h3("13.3 An assumption the new data destroyed")
    D.p("The module previously stated that Sunday 'is the off day on every "
        "sheet in this corpus', and defaulted to it. Measured across 10,385 "
        "ground-truth employee rows, that is false:")
    D.table(["Weekday", "Rows", "% weekly-off"],
            [["Sunday", "7,530", "27.8%"],
             ["Saturday", "8,842", "6.0%"],
             ["Monday–Friday", "~8,000 each", "~2%"]],
            caption="Sunday is PRESENT 65% of the time. The convention is per-client, "
                    "not global.")
    D.code(
        "ADANI02      Sun off  79-94%     strong convention\n"
        "Thyssen02    Sun off  65-73%\n"
        "HMEL19       Sun off     14%\n"
        "SHELL02      Sun off    6-8%     no convention\n"
        "SHELL04      Sat/Mon      3%     continuous site, works Sundays\n"
        "AFCON08      none         0%")
    D.p("A 'Sunday is weekly off' rule would have been wrong about two-thirds "
        "of the time and would invent days off for employees on continuous "
        "sites. Voting from the sheet's own confirmed weekly offs remains "
        "correct everywhere; only the blind fallback was in question, and it "
        "is now behind a switch.")

    D.h3("13.4 Snapping a misplaced weekly off")
    D.p("Comparing our weekly offs against the client's typed Excel revealed "
        "the shape of the two commonest confusions:")
    D.code(
        "truth W: 5(Sun) 12(Sun) 19(Sun) 26(Sun)\n"
        "ours  W: 5(Sun) 12(Sun) 19(Sun) 27(Mon)     one row late\n"
        "ours  W: 5(Sun) 11(Sat) 19(Sun) 26(Sun)     one row early")
    D.p("The annotation is written across a row boundary and binds to the "
        "neighbour. Each misplacement costs two comparisons — a W→P on the "
        "true day and a P→W on the neighbour — which is why those were the top "
        "two confusions at 21 and 15 occurrences. The repair moves the weekly "
        "off back, but only when the sheet's own offs agree on a weekday by "
        "a clear majority, and only from a row showing work onto a row that "
        "shows none. Without that evidence condition the rule also moved "
        "weekly offs that were already correct and one page lost four "
        "comparisons.")

    # ----------------------------------------------------------------- 14
    D.h2("14. Validation and Status")
    D.figure("05_safety.png",
             "Figure 5 — Checks, the three-state status lattice, and the measured "
             "escaped-error rate.")
    D.table(["Check", "Severity", "What it catches"],
            [["row-sum vs stated total", "block", "grid disagrees with the sheet's own arithmetic"],
             ["day count vs calendar", "block", "more or fewer rows than the month has days"],
             ["OT / normal hours bounds", "warn", "impossible per-day hours (>12)"],
             ["in/out span vs hours", "warn", "clock times inconsistent with recorded hours"],
             ["roster identity", "block/warn", "unknown employee, or an ambiguous name match"],
             ["OCR confidence floors", "warn", "a field read below its confidence threshold"],
             ["implausible summary value", "info", "a stated total exceeding the days in the month"]],
            caption="The validation suite. 'block' forces needs_review; 'warn' alone "
                    "produces review_optional.")
    D.p("A monthly total is allowed to differ from the sum of the day rows by "
        "a configurable fraction, default 2%. This is not sloppiness: reading "
        "roughly thirty handwritten cells accumulates small errors, and "
        "demanding an exact match would flag almost every sheet, which would "
        "make the review queue useless.")
    D.callout("The measured safety property.",
              "Across 301 scored pages, 256 were imperfect and 256 of those were "
              "flagged. Zero wrong pages passed as clean. That guarantee, not the "
              "accuracy percentage, is what makes the system safe in front of payroll.",
              color=OK)

    # -------------------------------------------------------------- 15-17
    D.h2("15. Roster and Identity")
    D.p("The roster is a CSV of 2,575 employees with codes, names and "
        "designations, loaded at start-up and replaceable through the UI "
        "without a restart. Matching is by exact code first — authoritative, "
        "but the name is still scored against it so a code/name conflict "
        "surfaces rather than passing silently. Otherwise a fuzzy name match "
        "runs with two thresholds.")
    D.table(["Parameter", "Default", "Meaning"],
            [["TS_ROSTER_MIN_SCORE", "82", "minimum similarity to accept a name match"],
             ["TS_ROSTER_MIN_MARGIN", "6", "the best candidate must beat the second by this much"]],
            caption="Roster matching thresholds. The margin is the important one.")
    D.callout("Why a margin, not just a threshold.",
              "'Nitin Deshmukh' and 'Yogesh Raman' are both real employees. A threshold alone "
              "would happily pick whichever scored a fraction higher. The margin makes "
              "ambiguity a review item instead of a silent, confident, wrong payment. "
              "One demo page reads 'ViyEk Komar' at 81.8 against a floor of 82 and is "
              "deliberately flagged rather than auto-corrected.")

    D.h2("16. Vocabulary and Designation Correction")
    D.p("Designations are drawn from a vocabulary of 445 job titles harvested "
        "from the client's own spreadsheets. A misread title is snapped to the "
        "nearest vocabulary entry when similarity is high enough — "
        "'Safity Supisvisar' resolves to 'Safety Supervisor' at 76.7. A "
        "regression panel of 18 probes guards this behaviour and is run on "
        "every accuracy-affecting change.")
    D.callout("A correction to an earlier belief.",
              "An earlier document in this project stated the client had no designation "
              "column in any of their 289 spreadsheets. That was false — every file has "
              "one; the parser was looking at a fixed column index that only matched the "
              "IOCL layout. Scanning all sheets for a header cell found 250 distinct "
              "designations.")

    D.h2("17. Export")
    D.p("One upload produces one workbook containing six sheets, each shaped "
        "for a different reader rather than one generic dump.")
    D.table(["Sheet", "Audience", "Contents"],
            [["Timesheet Detail", "operations", "one block per employee, the full sheet as typed today"],
             ["Invoice", "finance", "one row per employee with billable days and hours"],
             ["Attendance", "site / HR", "a calendar grid, one column per day"],
             ["Audit", "compliance", "every correction with actor, field, old and new value"],
             ["Payroll_Import", "systems", "flat machine-readable rows for payroll ingest"],
             ["Dashboard", "management", "counts, exceptions and totals"]],
            caption="The six export designs. Flagged pages are tinted so a reviewer "
                    "cannot miss them in the workbook either.")

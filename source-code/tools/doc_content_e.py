"""Documentation content, part E: foundations primer, from first principles."""
from __future__ import annotations

from docx.shared import RGBColor

OK = RGBColor(0x2F, 0x85, 0x5A)
WARN = RGBColor(0xC0, 0x56, 0x21)


def write(D):
    D.h1("Part XI — Foundations: The Techniques, From First Principles")
    D.p("This part explains every non-obvious technique the system uses, "
        "starting from nothing assumed. If you already know a topic, skip it. "
        "Each section says what the idea is, why this system needs it, and "
        "where in the code it appears.")

    # ------------------------------------------------------------------
    D.h2("40. What OCR Actually Does")
    D.h3("40.1 Two separate problems")
    D.p("Optical Character Recognition is usually two models, not one. "
        "**Detection** finds where text is, returning polygons around each "
        "text region but not reading them. **Recognition** then takes each "
        "cropped region and produces characters. PP-OCRv6 ships one model for "
        "each, plus a small classifier that decides whether a crop is upside "
        "down.")
    D.p("This split matters here. Detection failures and recognition failures "
        "look identical in the output — a missing value — but have opposite "
        "fixes. If detection missed the box, no amount of image sharpening "
        "helps; the region was never cropped. If recognition read it wrongly, "
        "the crop exists and resolution or contrast is the lever. The "
        "confidence profile in Chapter 10 is how the system tells them apart: "
        "a page with few boxes had a detection problem, a page with many "
        "low-confidence boxes had a recognition problem.")

    D.h3("40.2 What a confidence score is, and is not")
    D.p("Each recognised string carries a number in [0,1]. It is the model's "
        "own estimate of how sure it is — roughly, the product of per-character "
        "probabilities. It is useful for ranking and thresholding.")
    D.callout("It is not a probability of being correct.",
              "A model can be confidently wrong, and on handwriting it frequently is. "
              "This is why the system never trusts a single confidence value alone: it "
              "cross-checks against arithmetic (does the column sum match?), against the "
              "calendar (is this day a Sunday?), and against the roster (is this a real "
              "employee?). Independent evidence beats a self-reported score.")

    D.h3("40.3 Why handwriting is hard for these models")
    D.p("Printed text has consistent glyph shapes, spacing and baselines. "
        "Handwriting has none of those. In addition, these forms are filled "
        "with digits and short codes — 'P', 'W', '8:00' — which carry almost "
        "no linguistic context. A language model can repair 'teh' to 'the'; "
        "nothing can repair '18:00' misread as '10:00', because both are "
        "perfectly plausible times.")

    # ------------------------------------------------------------------
    D.h2("41. Image Preprocessing Concepts")
    D.h3("41.1 The Hough transform, in plain terms")
    D.p("A line in an image can be described by two numbers: its angle and its "
        "distance from the origin. The Hough transform takes every edge pixel "
        "and asks 'which lines could pass through me?', voting for each "
        "candidate. Real lines accumulate many votes because many pixels "
        "agree on them; noise does not. The probabilistic variant used here "
        "samples pixels rather than using all of them, which is much faster "
        "and sufficient for finding table rules.")
    D.p("The system uses it for two things: estimating skew (the median angle "
        "of near-horizontal lines) and finding the printed row rules that "
        "define the day grid.")

    D.h3("41.2 Morphological opening")
    D.p("Morphology treats an image as shapes rather than pixels. **Erosion** "
        "shrinks white regions, **dilation** grows them back. Doing one then "
        "the other — an **opening** — removes anything smaller than the "
        "structuring element while leaving larger shapes intact.")
    D.p("Choosing a structuring element 30% of the page width means only "
        "structures at least that long survive. Text is annihilated; table "
        "rules remain. That is the entire row-rule detector, and it costs "
        "milliseconds with no model.")

    D.h3("41.3 Adaptive thresholding")
    D.p("Converting grey to black-and-white with one global cut-off fails on "
        "phone photographs, where one corner is in shadow: the threshold that "
        "preserves the bright side erases the dark side. Adaptive "
        "thresholding computes a local cut-off for each neighbourhood "
        "instead, so each region is judged against its own surroundings.")

    D.h3("41.4 Why divide by a blur")
    D.p("A heavily blurred copy of a photograph approximates its illumination "
        "field — the slow variation caused by lighting, not by content. "
        "Dividing the original by that blur cancels the lighting and leaves "
        "reflectance: what the paper and ink actually look like. It is a "
        "one-line operation that recovers pencil in shadowed corners.")

    # ------------------------------------------------------------------
    D.h2("42. String Matching Under Noise")
    D.h3("42.1 Edit distance and the ratio")
    D.p("Levenshtein distance counts the single-character insertions, "
        "deletions and substitutions needed to turn one string into another. "
        "A **ratio** converts that to a 0–100 similarity, so 'SUNDAY' versus "
        "'SUMDAY' scores high and 'SUNDAY' versus 'MONDAY' scores lower.")
    D.p("The library used here, rapidfuzz, provides several scorers. Two "
        "matter in this codebase:")
    D.bullets([
        ("ratio", "compares the strings as written. Sensitive to word order."),
        ("token_sort_ratio", "splits into words, sorts them, then compares — so 'KUMAR VINAY' matches 'NITIN DESHMUKH'. Used for names, where word order genuinely varies."),
    ])
    D.callout("Why deletions score worse than substitutions.",
              "'Swday' against 'SUNDAY' scores 72.7, while 'Sunday' against 'Sumday' "
              "scores 83.3 — both are one character wrong. A deletion shortens the "
              "string, so it damages the ratio more than a substitution does. That is "
              "exactly why the annotation gate had to come down from 82 to 72: the real "
              "failures were dropped letters, not swapped ones.")

    D.h3("42.2 Thresholds and margins")
    D.p("A threshold answers 'is this good enough?'. A **margin** answers a "
        "different and more important question: 'is this clearly better than "
        "the runner-up?'. The roster requires both, because with two real "
        "employees named 'Nitin Deshmukh' and 'Yogesh Raman', a threshold alone "
        "would confidently pick whichever scored a fraction higher.")

    # ------------------------------------------------------------------
    D.h2("43. Algorithms Used in Extraction")
    D.h3("43.1 Longest increasing subsequence")
    D.p("Given a sequence of numbers, find the longest subset that is strictly "
        "increasing while keeping the original order. The generic grid reader "
        "uses it to find the run of day numbers among candidates that include "
        "OCR misreads.")
    D.code(
        "candidates in x-order:  1 2 3 4 6 7 8 9 20 11 12 13 14 13 16 17 ...\n"
        "                                        ^^        ^^\n"
        "                                   '10' misread   '15' misread\n"
        "longest increasing run: 1 2 3 4 6 7 8 9 11 12 13 14 16 17 ...\n"
        "  -> the strays are excluded automatically, no special-casing")
    D.p("The implementation is the textbook O(n²) dynamic program, which is "
        "ample: n is at most a few dozen boxes on a page.")

    D.h3("43.2 The assignment problem")
    D.p("Given candidates and fields, and a score for how well each candidate "
        "fits each field, choose a one-to-one pairing that maximises the total "
        "score. This is what header typing solves in 11.2: 'APRIL-2026' scores "
        "high as a month and low as a name, 'RAJEEV IYENGAR' the reverse, and "
        "the solver assigns each to the field that wants it most.")
    D.p("Crucially, a candidate that fits nothing well scores low everywhere "
        "and is left unassigned rather than forced somewhere. Leaving a field "
        "empty is a review item; filling it wrongly is a wrong payment.")

    D.h3("43.3 Clustering by pitch, not by size")
    D.p("Grouping ink into rows sounds like a clustering problem, and it is — "
        "but the distance that matters is the grid's **row pitch**, the "
        "regular vertical spacing between rules, not the height of individual "
        "text boxes. Handwriting varies enormously in size while the printed "
        "row spacing does not, so clustering on box height splits tall "
        "handwriting across two rows and merges small handwriting into one.")

    D.h3("43.4 Ladder fitting")
    D.p("Detected rules are noisy: some are missed, some spurious. Rather than "
        "trusting them individually, the system fits a uniform ladder — an "
        "evenly spaced set of lines — across them, using the month length as a "
        "prior on how many rungs to expect, and requires 82% of detected rules "
        "to align with the fitted ladder before accepting it. This turns a "
        "noisy observation into a regular structure, or rejects it entirely.")

    # ------------------------------------------------------------------
    D.h2("44. Validation Concepts")
    D.h3("44.1 Checksums as independent evidence")
    D.p("A checksum is any quantity computable two different ways, where "
        "agreement is evidence and disagreement is proof of an error "
        "somewhere. These sheets contain several for free: the supervisor "
        "writes monthly totals that should equal the sum of the day rows; the "
        "number of day rows should equal the days in the month; present plus "
        "absent plus leave plus weekly-off plus holiday should account for "
        "every day.")
    D.p("The system does not know which side of a disagreement is wrong — but "
        "it knows something is, and that is enough to flag the page. This is "
        "the single most valuable property of the domain and the reason the "
        "safety guarantee is achievable at all.")

    D.h3("44.2 Why tolerance is not sloppiness")
    D.p("Monthly hour totals are compared with a 2% tolerance. Reading thirty "
        "handwritten numeric cells accumulates small errors; demanding exact "
        "agreement would flag essentially every sheet, and a review queue "
        "containing everything is equivalent to no review queue at all. The "
        "tolerance is chosen so that genuine transcription drift passes while "
        "a whole missing or duplicated day does not.")

    D.h3("44.3 Severity levels")
    D.table(["Severity", "Meaning", "Effect on status"],
            [["block", "the record is internally inconsistent or identity is unsafe",
              "forces needs_review"],
             ["warn", "something is doubtful but the record may still be correct",
              "review_optional if no blocks"],
             ["info", "recorded for the audit trail; no action implied", "none"]],
            caption="Severity semantics. Only a block prevents a page being treated as done.")

    # ------------------------------------------------------------------
    D.h2("45. Measurement Concepts")
    D.h3("45.1 Precision, recall, and why this project uses neither")
    D.p("Classification tasks are usually scored with precision and recall. "
        "This system is not a classifier: it is a transcription task where "
        "every cell has a correct value. The natural measure is simply the "
        "fraction of cells transcribed correctly, computed per field, which is "
        "what the harnesses report.")
    D.p("The one place classifier language applies is the safety property: of "
        "pages that are wrong, what fraction get flagged? That is recall on "
        "the 'needs review' decision, and it is measured at 100% on 256 "
        "imperfect pages.")

    D.h3("45.2 The denominator problem")
    D.p("When a fix makes previously-unreadable pages readable, they enter the "
        "scoring — usually as hard pages that score below average. The "
        "percentage can fall while the system strictly improves.")
    D.code(
        "before   26 pages matched   day 710/787 = 90.2%\n"
        "after    30 pages matched   day 820/903 = 90.6%\n"
        "         +4 pages visible, +110 correct days, percentage barely moved\n"
        "\n"
        "a later fix:\n"
        "before   30 matched   day 829/903 = 91.8%\n"
        "after    31 matched   day 853/934 = 91.3%   <- percentage FELL\n"
        "         but +24 correct days and zero regressions")
    D.callout("Always report counts alongside percentages.",
              "A percentage alone cannot distinguish 'we got worse' from 'we can now see "
              "harder pages'. Both hit this project, and only the counts told them apart.")

    D.h3("45.3 Held-out data and why the two numbers differ")
    D.p("The 49-page evaluation is not held-out: the extractor was tuned "
        "against it. The full-corpus figure includes hundreds of pages from "
        "clients the system had never seen. The gap between 91.3% and 72.6% "
        "is therefore the honest estimate of generalisation error, and it is "
        "the number to quote when someone asks how the system will perform on "
        "documents you have not shown it.")

    D.h3("45.4 Ceiling effects")
    D.p("No measurement can exceed the quality of its reference. When 9.2% of "
        "the reference records contradict each other, no system can score "
        "100% against them — not because it is wrong, but because the question "
        "has more than one answer. Recognising a ceiling effect prevents "
        "months of effort chasing an unreachable number.")

    # ------------------------------------------------------------------
    D.h2("46. Systems Concepts Used Here")
    D.h3("46.1 Content-addressed caching")
    D.p("Cache keys here are the SHA-256 of the normalised page image plus the "
        "pipeline version. Two consequences follow. The same page re-uploaded "
        "is free, however it is named. And bumping the version invalidates "
        "everything at once without deleting anything — the old entries remain "
        "on disk, so a rollback re-uses them instantly instead of re-reading "
        "thousands of pages.")

    D.h3("46.2 Idempotence and resumability")
    D.p("Long batch jobs on a contended machine get interrupted. The "
        "evaluation and harvest tools therefore append each result to a "
        "checkpoint file the moment it is produced, and skip completed work on "
        "restart. The cost of an interruption is one page, not the whole run. "
        "This is worth building before you need it, not after.")

    D.h3("46.3 Bounded work")
    D.p("The rescue path — retrying other orientations and re-reading at "
        "higher resolution — can help a failing page, but unbounded it "
        "converts one slow page into an unbounded one. It is therefore capped "
        "by a per-page time budget, after which the page is returned as-is and "
        "flagged. That is the correct outcome anyway: a human was going to "
        "look at it either way.")

    D.h3("46.4 Process pools and thread oversubscription")
    D.p("Running N worker processes, each of which internally uses all "
        "available cores for numerical work, produces N× oversubscription: the "
        "operating system thrashes between threads and total throughput falls "
        "even though every core is busy. The fix is to constrain each worker "
        "to a small fixed number of threads so the processes cooperate rather "
        "than compete.")
    D.callout("A related operational trap.",
              "Killing a pool's parent Harish Jhaveri matching its script name does NOT kill "
              "its workers — their command line is just 'python -c from "
              "multiprocessing.spawn'. Orphaned workers then consume a core each, "
              "invisibly, until the machine is rebooted. Match on the spawn pattern too.")

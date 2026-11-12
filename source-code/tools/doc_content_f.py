"""Documentation content, part F: domain reference and decision records."""
from __future__ import annotations

from docx.shared import RGBColor

OK = RGBColor(0x2F, 0x85, 0x5A)
WARN = RGBColor(0xC0, 0x56, 0x21)


def write(D):
    # ============================================ DOMAIN
    D.h1("Part XII — Domain Reference")
    D.p("Everything in this part is about the business, not the software. An "
        "engineer who does not know what 'C/O' means cannot tell a correct "
        "extraction from an incorrect one, and will not spot that a rule is "
        "wrong.")

    D.h2("47. Day Status Codes")
    D.table(["Code", "Meaning", "Payroll effect", "How it appears on the sheet"],
            [["P", "Present", "paid, counts toward man-hours",
              "clock times and hours written in the row"],
             ["A", "Absent", "unpaid", "row blank or annotated 'ABSENT'"],
             ["W", "Weekly off", "paid, no hours", "'W/O', 'WO', or the weekday written across the row"],
             ["H", "Public holiday", "paid, no hours", "'P.H.', 'HOLIDAY'"],
             ["L", "Leave", "paid or unpaid per leave type", "'CL', 'SL', 'PL', 'LEAVE'"],
             ["C", "Compensatory off", "paid; offsets earlier extra work", "'C/O', 'COMP OFF'"]],
            caption="The six statuses. The system normalises many written variants to "
                    "these codes; 'WO', 'W/O', 'OFF' and 'WEEKLY OFF' all become W.")
    D.callout("Why W versus P is the expensive confusion.",
              "It was the top error pair in the corpus — 21 W→P and 15 P→W. Getting it "
              "wrong in one direction pays for a day not worked; in the other it "
              "withholds pay for a day that was. Both are visible to the employee, which "
              "is why so much of Chapter 13 is devoted to it.")

    D.h2("48. The Summary Block")
    D.p("The bottom of every sheet carries handwritten totals. They are the "
        "system's most valuable signal because they are short, anchored to "
        "printed labels, and independently computed by the supervisor.")
    D.table(["Field", "Label on the form", "Cross-check it enables"],
            [["total_present_days", "P (Total Present Days)", "count of P rows"],
             ["total_absent_days", "A (Total Absent Days)", "count of A rows"],
             ["total_leave_days", "Leaves (Total Leaves)", "count of L rows"],
             ["total_weekly_off", "W/O (Total Weekly Off)", "count of W rows; drives calendar repair"],
             ["total_public_holiday", "P.H. (Total Public Holiday)", "count of H rows"],
             ["total_comp_off", "C/O (Total Compensatory Off)", "count of C rows"],
             ["total_man_hours", "Total Man Hours", "sum of normal hours"],
             ["total_ot_hours", "Total OT Hours", "sum of overtime hours"]],
            caption="Summary fields and what each one lets the system verify.")
    D.p("Every one of these is bounded by the calendar: no day-type total can "
        "exceed the days in the month. A stated 'P 97' on a 30-day sheet is a "
        "misread regardless of OCR confidence, and is blanked with the "
        "original kept for audit rather than being allowed to drive a repair.")

    D.h2("49. Identity: Codes, Names and Why Both")
    D.p("An employee is identified by a code and a name. Codes are "
        "authoritative when present, but the corpus shows they cannot be "
        "relied on alone.")
    D.bullets([
        ("Codes vary by client.", "The IOCL scanned sheets carry codes like 50700, 53340, 51078, while the client's own typed Excel for the same people uses IOCLMS-prefixed codes. Code-based matching cannot bridge those two systems, so the name has to carry the match."),
        ("Names are misread.", "'ViyEk Komar' for Yogesh Raman, 'Jitendna Singh' for Sanjay Bose. Fuzzy matching handles most of it."),
        ("Names collide.", "Nitin Deshmukh and Yogesh Raman are both real. This is why a margin, not just a threshold, governs acceptance."),
        ("A code and a name can disagree.", "When both are present the name is still scored against the code's roster entry, so a conflict surfaces as an issue rather than passing silently."),
    ])

    D.h2("50. The Billing Consequence")
    D.p("The output feeds an invoice. That is the reason for the safety "
        "posture throughout this document: a transcription error does not "
        "produce a slightly wrong report, it produces a wrong payment to a "
        "named individual, and it is discovered by that individual.")
    D.p("The chain is: day statuses determine present days; present days and "
        "hours determine billable amounts; the employee identity determines "
        "who is paid. An error anywhere in that chain has a person on the "
        "other end of it.")

    # ============================================ ADRs
    D.h1("Part XIII — Architecture Decision Record")
    D.p("Each entry states the context, the decision, and the consequences "
        "including the ones that hurt. They are ordered roughly as they were "
        "taken.")

    D.h2("ADR-1 — Rule-based extraction rather than a trained model")
    D.p("**Context.** The obvious approach to reading a form is to train a "
        "model on labelled examples. At project start there were no labels, "
        "and the client's ground truth turned out to be both scarce and "
        "internally inconsistent.")
    D.p("**Decision.** Build a rule-based extractor that exploits the printed "
        "structure of the form, and use OCR only for the values.")
    D.p("**Consequences.** Every decision is inspectable and every failure is "
        "explainable, which matters when an invoice is disputed. There is no "
        "training pipeline to maintain and no GPU requirement. The cost is "
        "that each genuinely new layout needs engineering rather than data — "
        "mitigated later by the generic grid reader (ADR-6).")

    D.h2("ADR-2 — Local-only execution")
    D.p("**Context.** Cloud OCR services are more accurate on handwriting than "
        "anything runnable on a laptop.")
    D.p("**Decision.** Run entirely on the client's hardware, CPU-only.")
    D.p("**Consequences.** Accuracy is lower than a cloud API would give. In "
        "exchange there is no per-page cost, no data leaving the client's "
        "network, no API key management, and the system works in a refinery "
        "office with poor connectivity. For a client whose documents contain "
        "employee personal data, this was judged decisive.")

    D.h2("ADR-3 — Flag rather than guess")
    D.p("**Context.** Any extraction system must decide what to do when it is "
        "unsure.")
    D.p("**Decision.** Surface doubt as a review item. Never emit a confident "
        "value the system cannot justify.")
    D.p("**Consequences.** The review queue is larger than a more permissive "
        "system would produce — on the demo batch, nine of ten pages carry at "
        "least one issue. That is the intended trade: measured across 301 "
        "scored pages, zero wrong pages passed as clean. A reviewer confirming "
        "a good page takes seconds; an unflagged wrong payment does not.")

    D.h2("ADR-4 — Two harnesses, not one")
    D.p("**Context.** A full-pipeline evaluation takes hours, which is too "
        "slow to choose between hypotheses.")
    D.p("**Decision.** Keep a fast harness that replays frozen OCR for "
        "iteration, and a full harness for the quotable number.")
    D.p("**Consequences.** Iteration is seconds rather than hours. The risk is "
        "comparing across the two, which produces apparent ten-point swings "
        "that are pure artefact; the discipline is fast-to-fast, full-to-full. "
        "The frozen file must also be rebuilt after any OCR or preprocessing "
        "change, or it measures the old pixels.")

    D.h2("ADR-5 — The VLM is off by default")
    D.p("**Context.** A local vision-language model can re-read headers the "
        "rule-based extractor fails on, and was enabled during early "
        "development.")
    D.p("**Decision.** Ship with it disabled.")
    D.p("**Consequences.** Measured without it, the pipeline scored 89.5% "
        "overall — at least as good as the configuration demonstrated with it "
        "enabled. Disabling it removes a 3 GB model, a second service, "
        "roughly 24 seconds per unclear page, and a substantial memory "
        "requirement. It also removed a serious failure mode: on one test the "
        "VLM returned a flawless, entirely fabricated 31-day attendance "
        "series, including four Sundays marked as worked. Well-formed fake "
        "data passes validation.")
    D.callout("The rule that came out of that.",
              "Use a generative model only where the answer is short and checkable "
              "against something else. Never where it can invent a plausible whole.")

    D.h2("ADR-6 — Structural grid detection over per-client profiles")
    D.p("**Context.** Extraction knew three client layouts. On the HO dataset, "
        "207 of 247 pages produced no employee name at all — not wrong data, "
        "no data.")
    D.p("**Decision.** Detect the day grid structurally, from the run of day "
        "numbers, rather than by recognising the client.")
    D.p("**Consequences.** One reader now handles both orientations across "
        "clients it has never seen; a SHELL page that previously produced "
        "nothing was read at 26 of 26 comparable days against the client's own "
        "Excel. The risk is false positives — a serial-number column looks "
        "exactly like a day column — which required the employee-list guard "
        "described in 12.3. Refusing beats fabricating.")

    D.h2("ADR-7 — Resolution decided by page shape")
    D.p("**Context.** A single render resolution has to serve portrait "
        "handwritten forms and landscape typed grids with thirty columns.")
    D.p("**Decision.** Choose the render scale from the page's aspect ratio, "
        "and keep an on-demand high-resolution re-read for pages that still "
        "produce nothing.")
    D.p("**Consequences.** The landscape day header went from 4 of 30 read "
        "correctly to 30 of 30. Portrait pages are byte-identical to before, "
        "because the sweep showed more resolution makes handwriting worse, not "
        "better. The high-resolution twin is rendered only for the specific "
        "page that failed, so a 500-document batch does not pay for it.")

    D.h2("ADR-8 — Checkpoint every long job")
    D.p("**Context.** Corpus-scale jobs run for hours on a contended machine "
        "and are routinely interrupted.")
    D.p("**Decision.** Append each unit of work to a checkpoint file as it "
        "completes, and skip completed work on restart.")
    D.p("**Consequences.** An interruption costs one page. This was added "
        "after a multi-hour evaluation was lost, and has since paid for itself "
        "many times — including allowing a mid-run code fix to be applied by "
        "restarting rather than starting over.")

    D.h1("Part XIV — Operational Runbook")
    D.h2("51. Daily Operation")
    D.table(["Task", "Command", "Notes"],
            [["Check it is alive", "curl -s localhost:8077/api/health", "roster_size and pipeline should be populated"],
             ["Start", "./start.sh  /  start.bat", "starts automatically on server reboot"],
             ["Stop", "./stop.sh  /  stop.bat", "data in /data is untouched"],
             ["Restart after config change", "./restart.sh", "config.env changes need a restart"],
             ["Watch logs", "./logs.sh", "read-only; Ctrl+C to exit"],
             ["Back up", "copy the data/ folder", "that is the entire backup"]],
            caption="Everything an operator needs day to day.")

    D.h2("52. Release Checklist")
    D.bullets([
        "Run tools/verify_end_to_end.py — all ten checks must pass.",
        "Run tools/eval_fast.py and confirm no accuracy regression against the recorded baseline.",
        "Run tools/eval_desig.py — the 18-probe panel must be 18/18.",
        "Bump PIPELINE_VERSION if extraction changed.",
        "Rebuild both container images; the build gates must pass.",
        "Rebuild the ZIP with tools/package_release.py — it refuses to package client data.",
        "Extract the ZIP to an empty folder, delete the loaded images, and run the installer as a client would.",
        "Upload the ten demo sheets and confirm 10/10 process and the export downloads.",
    ], numbered=True)

    D.h2("53. What to Check When Accuracy Looks Wrong")
    D.bullets([
        ("Is the server running the code you think?", "/api/health reports the pipeline version. A server on stale code is a classic false alarm."),
        ("Is the cache serving old results?", "If a change had no effect, this is the first suspect. Bump PIPELINE_VERSION."),
        ("Is the roster loaded?", "roster_loaded false makes every page look wrong in the same way."),
        ("Are you comparing like with like?", "The fast and full harnesses produce different absolute numbers by design."),
        ("Did the denominator move?", "More matched pages can lower a percentage while improving the system."),
        ("Is the ground truth trustworthy?", "9.2% of the client's records contradict each other; run tools/truth_conflicts.py before blaming the extractor."),
    ])

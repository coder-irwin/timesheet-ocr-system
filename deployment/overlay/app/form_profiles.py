"""Template profiles — one anchor set per form family.

WHY THIS EXISTS
---------------
Measured at scale: **56% of pages failed because their summary labels were not
found at all.** Not misread -- absent. Those pages are not the AARVI ENCON form
the original anchor set was written for; they are Samsung sheets, KBR weekly
sheets, and other client-specific layouts.

That was the single largest source of lost accuracy, larger than handwriting,
warping, and OCR quality combined. Fixing it is not a research problem: each
layout is a dictionary of labels.

DESIGN
------
A *profile* declares:
  * how to recognise the layout   (signature strings that appear on it)
  * where its header fields are   (label patterns)
  * where its summary totals are  (label patterns + how to read them)

Detection is by scoring the page's OCR text against each profile's signature and
taking the best match. This is deliberately simple and inspectable -- adding
template #7 means appending a dict, not retraining anything.

TERMS
-----
profile     the description of one form layout
signature   strings that reliably appear on that layout and nowhere else
anchor      a printed label used as a reference point to find a value
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .aarvi_form import Anchor


@dataclass(frozen=True)
class FormProfile:
    key: str
    label: str
    # Strings that identify this layout. Scored against all page text.
    signature: tuple[str, ...]
    header_anchors: tuple[Anchor, ...]
    summary_anchors: tuple[Anchor, ...]
    column_anchors: dict[str, tuple[str, ...]]
    # Some layouts pack several numbers in one cell ("30|21", "0|0|4").
    split_fields: dict[str, tuple[str, ...]] = field(default_factory=dict)
    notes: str = ""


# ---------------------------------------------------------------------------
# 1. AARVI ENCON -- the dominant family (IOCL, ADANI, SAFEARTH, and most others)
# ---------------------------------------------------------------------------

AARVI_HEADER = (
    Anchor("month_year", ("MONTH & YEAR", "MONTH AND YEAR", "MONTH YEAR")),
    # D-082. Label variants found on pages that produced no name at all.
    # Added as PHRASES rather than by lowering MATCH_THRESHOLD, because the
    # near misses sit right beside the labels that must never bind here:
    #   'Name of Employee/Consultant:-Parag Pillai'   65 -> 82   wanted
    #   'SUPERVISOR NAME :'                           64 -> 64   must not
    #   'Project Name : Solarium Green Energy'        64 -> 64   must not
    #   'CLIENT NAME :'                               58 -> 62   must not
    # At a threshold of 80 only the wanted one crosses. Dropping the threshold
    # to catch it instead would have bound the SUPERVISOR's name as the
    # employee on every sheet that names one -- they sit four points apart.
    #
    # "NAME OF RESOURCE" was tried and REMOVED: on the Solarium sheets it is a
    # TABLE COLUMN HEADER on a multi-employee grid, not a header label, and
    # matching it produced 'Company Project Name : Solarium Gr' as the
    # employee. A label that names a column is not a label that names a person.
    Anchor("employee_name", ("EMPLOYEE NAME", "SERVICE PERSON NAME",
                             "SERVICE PERSON", "NAME OF EMPLOYEE",
                             "NAME OF CONSULTANT", "EMPLOYEE CONSULTANT")),
    Anchor("designation", ("DESIGNATION",)),
    Anchor("employee_code", ("EMPLOYEE CODE", "SERVICE PERSON CODE", "E CODE",
                             "EMP CODE")),
    Anchor("client", ("CLIENT",)),
    Anchor("project", ("PROJECT",)),
    Anchor("location", ("LOCATION",)),
    Anchor("supervisor", ("SUPERVISOR NAME", "SUPERVISOR")),
)

AARVI_SUMMARY = (
    Anchor("total_present_days", ("P (TOTAL PRESENT DAYS)", "TOTAL PRESENT DAYS",
                                  "P TOTAL PRESENT"), numeric=True),
    Anchor("total_man_hours", ("TOTAL MAN HOURS", "TOTAL MANHOURS"), numeric=True),
    Anchor("total_ot_hours", ("TOTAL OT HOURS", "TOTAL O.T. HOURS"), numeric=True),
    Anchor("total_absent_days", ("A (TOTAL ABSENT DAYS)", "TOTAL ABSENT DAYS"),
           numeric=True),
    Anchor("total_leave_days", ("LEAVES (TOTAL LEAVES)", "TOTAL LEAVES"),
           numeric=True),
    Anchor("total_weekly_off", ("W/O (TOTAL WEEKLY OFF)", "TOTAL WEEKLY OFF",
                                "WO TOTAL WEEKLY"), numeric=True),
    Anchor("total_public_holiday", ("P.H. (TOTAL PUBLIC HOLIDAY)",
                                    "TOTAL PUBLIC HOLIDAY"), numeric=True),
    Anchor("total_comp_off", ("C/O (TOTAL COMPENSATORY OFF)",
                              "TOTAL COMPENSATORY OFF"), numeric=True),
)

AARVI_COLUMNS = {
    "date": ("DATE",),
    "in_time": ("TIME IN",),
    "out_time": ("TIME OUT",),
    "normal_hours": ("NORMAL WORKING HOURS", "NORMAL WORKING", "NORMAL HRS"),
    "ot_hours": ("OVER TIME HOURS", "OVER TIME"),
    "total_hours": ("TOTAL HOURS",),
    "remarks": ("REMARKS", "REMARK"),
}


# ---------------------------------------------------------------------------
# 2. Samsung E&A -- system-generated, "NAME [CODE]", totals in a Total row
# ---------------------------------------------------------------------------
# Observed layout:
#   ASHOK VARMA [30000001]
#   Calendar Days | Total Working    30 | 21
#   Worked | Off Days                17 | 4
#   ABS | LWP | LEA                  0 | 0 | 4
#   Total row:  Normal 136 | Extra 55 | Total 191 | Punch 202.24

SAMSUNG_HEADER = (
    Anchor("period", ("EMPLOYMENT FROM", "TIMESHEET AGENCY MANPOWER")),
)

SAMSUNG_SUMMARY = (
    Anchor("calendar_working", ("CALENDAR DAYS TOTAL WORKING",
                                "CALENDAR DAYS", "TOTAL WORKING")),
    Anchor("worked_offdays", ("WORKED OFF DAYS", "WORKED OFF")),
    Anchor("abs_lwp_lea", ("ABS LWP LEA", "ABS | LWP | LEA")),
)

SAMSUNG_COLUMNS = {
    "date": ("DATE-DAY", "DATE DAY", "DATE"),
    "in_time": ("PUNCH IN",),
    "out_time": ("PUNCH OUT",),
    "normal_hours": ("NORMAL HRS", "NORMAL HRS."),
    "ot_hours": ("EXTRA HRS", "EXTRA HRS."),
    "total_hours": ("TOTAL HRS", "TOTAL HRS."),
    "remarks": ("PROJECT CATEGORY", "PROJECT/ CATEGORY"),
}

# "30|21" -> two fields. Reading these is what makes the Samsung layout
# checkable at all, since it has no "Total Present Days" label.
SAMSUNG_SPLITS = {
    "calendar_working": ("period_days", "total_present_days"),
    "worked_offdays": ("worked_days", "total_weekly_off"),
    "abs_lwp_lea": ("total_absent_days", "total_lwp", "total_leave_days"),
}


# ---------------------------------------------------------------------------
# 3. KBR -- weekly project/task sheet, label and value in one box
# ---------------------------------------------------------------------------

KBR_HEADER = (
    Anchor("employee_code", ("EMPLOYEE ID",)),
    Anchor("employee_name", ("EMPLOYEE NAME",)),
    Anchor("period", ("WEEK END DATE",)),
    Anchor("project", ("RESPONSIBILITY CENTRE",)),
)

KBR_SUMMARY = (
    Anchor("total_hours", ("TOTAL",), numeric=True),
)

KBR_COLUMNS = {
    "project": ("PROJECT",),
    "task": ("TASK",),
    "total_hours": ("TOTAL",),
    "remarks": ("STATUS",),
}


PROFILES: tuple[FormProfile, ...] = (
    FormProfile(
        key="aarvi",
        label="AARVI ENCON attendance sheet (monthly / fortnightly)",
        signature=("AARVI ENCON", "ATTENDANCE SHEET", "TOTAL MAN HOURS",
                   "CLIENT'S APPROVAL", "TIME IN", "TIME OUT"),
        header_anchors=AARVI_HEADER,
        summary_anchors=AARVI_SUMMARY,
        column_anchors=AARVI_COLUMNS,
        notes="Dominant family. Handwritten and typed variants both occur.",
    ),
    FormProfile(
        key="samsung",
        label="Samsung E&A agency-manpower timesheet",
        signature=("SAMSUNG", "TIMESHEET (AGENCY MANPOWER)", "PUNCH IN",
                   "PUNCH OUT", "DAILY SIGNATURE", "CALENDAR DAYS"),
        header_anchors=SAMSUNG_HEADER,
        summary_anchors=SAMSUNG_SUMMARY,
        column_anchors=SAMSUNG_COLUMNS,
        split_fields=SAMSUNG_SPLITS,
        notes="System-generated. Identity is 'NAME [CODE]' with no label.",
    ),
    FormProfile(
        key="kbr",
        label="KBR weekly project timesheet",
        signature=("KBR", "WEEK END DATE", "RESPONSIBILITY CENTRE",
                   "DAILY HOURS", "UPLIFT", "COST TYPE"),
        header_anchors=KBR_HEADER,
        summary_anchors=KBR_SUMMARY,
        column_anchors=KBR_COLUMNS,
        notes="Weekly, not monthly. Rows are project/task, columns are days.",
    ),
)

DEFAULT_PROFILE = PROFILES[0]


def detect(all_text: str) -> tuple[FormProfile, float]:
    """Pick the profile whose signature best matches the page text.

    Scoring is a simple hit count normalised by signature length -- readable,
    debuggable, and good enough because the signatures are distinctive
    (a Samsung sheet never says "AARVI ENCON").
    """
    hay = " ".join(all_text.upper().split())
    best, best_score = DEFAULT_PROFILE, 0.0
    for p in PROFILES:
        hits = sum(1 for s in p.signature if s.upper() in hay)
        score = hits / len(p.signature)
        if score > best_score:
            best, best_score = p, score
    return best, best_score


def get(key: str | None) -> FormProfile:
    for p in PROFILES:
        if p.key == key:
            return p
    return DEFAULT_PROFILE

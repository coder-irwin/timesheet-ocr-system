"""Anchor-based field extraction for the AARVI ENCON timesheet family.

WHY ANCHORS AND NOT GRID COORDINATES
------------------------------------
The obvious approach is "the employee name lives at pixel (250, 180)". That
breaks the moment a page is photographed at a slightly different angle,
distance or crop -- which is every page, because these are phone captures.

The obvious fix is to detect the printed table grid and use cell indices. We
built that (see ocr_engine.detect_grid) and measured it: it succeeds on flat
scans and **fails on curved pages**, because a straight morphological kernel
cannot match a curved rule. On SAFEARTH01 it found 52 rows but only 2 columns.

So the primary strategy is anchors. Every one of these forms carries the *same
printed labels* -- "EMPLOYEE NAME", "TIME IN", "P (Total Present Days)". Those
labels are printed, so OCR reads them with high confidence even when the
handwritten values beside them are marginal. We locate a label, then take the
value from the region to its right (or below, for column headers).

This is robust to rotation, scale, crop and curl, because it only relies on
*local* relative position -- the value is beside its label no matter how the
page is warped globally.

Grid detection is kept as a secondary signal for the day rows, where anchors
don't exist (there is no printed label for "row 14").

TERMS
-----
anchor      A piece of printed text whose position we trust, used as a
            reference point to find nearby values.
fuzzy match Comparing strings by similarity rather than exact equality, so
            "EMPL0YEE NAME" (OCR misread) still matches "EMPLOYEE NAME".
band        A horizontal strip of the page, used to collect everything on the
            same visual line as an anchor.
"""
from __future__ import annotations

import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz

from .ocr_engine import TextBox


# ---------------------------------------------------------------------------
# Anchor definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Anchor:
    """A printed label we look for, and where its value sits relative to it."""
    field: str
    patterns: tuple[str, ...]
    direction: str = "right"       # right | below
    max_gap_x: float = 0.55        # as a fraction of page width
    numeric: bool = False


HEADER_ANCHORS: tuple[Anchor, ...] = (
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
                             "EMP CODE", "EMPLOYEE ID")),
    Anchor("client", ("CLIENT",)),
    Anchor("project", ("PROJECT",)),
    Anchor("location", ("LOCATION",)),
    Anchor("supervisor", ("SUPERVISOR NAME",)),
)

# The summary block. These are the invoice-critical numbers -- every one of
# them participates in a checksum in validate.py.
SUMMARY_ANCHORS: tuple[Anchor, ...] = (
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

# Column headers of the day grid. Used to learn each column's x-range from the
# page itself, rather than assuming fixed positions.
COLUMN_ANCHORS: dict[str, tuple[str, ...]] = {
    "date": ("DATE",),
    "in_time": ("TIME IN", "PUNCH IN"),
    "out_time": ("TIME OUT", "PUNCH OUT"),
    "normal_hours": ("NORMAL WORKING HOURS", "NORMAL WORKING", "NORMAL HRS",
                     "NORMAL"),
    "ot_hours": ("OVER TIME HOURS", "OVER TIME", "EXTRA HRS", "OVERTIME"),
    "total_hours": ("TOTAL HOURS", "TOTAL HRS"),
    "remarks": ("REMARKS", "REMARK"),
}

# Fields whose VALUE legitimately contains a label word, so the first value box
# must not be mistaken for the next label. "Safety Supervisor" scores 81 against
# the "SUPERVISOR NAME" label; "Site Engineer" would score similarly against an
# engineering label. Names and dates have no such overlap, and relaxing the stop
# for them measured worse (period_label started swallowing the neighbouring
# pair, which changed calendar reconciliation and cost day-status accuracy).
_TITLE_LIKE_FIELDS = frozenset({"designation"})

MATCH_THRESHOLD = 80        # rapidfuzz ratio, 0..100 -- to FIND a label
# Behind a switch so both states stay runnable and the effect is attributable.
STRIP_PERIOD_FROM_NAME = True
STRIP_DESIGNATION_FROM_NAME = True
# Fuzzy gate for weekday/annotation words ('SUNDAY' written across a row).
#
# Swept, not guessed. Real failures drove it: two rows annotated 'Swday.' and
# 'Sudny' -- single-letter DELETIONS, which score 72.7 against SUNDAY and so
# fell through the old gate of 82, reporting a marked weekly off as a worked
# day.
#
#   thresh   68     70     72  |  74     76  |  78     80     82  |  84
#   day      825    825    825 |  819    819 |  820    820    820 |  816
#
# 68-72 is a flat plateau, not a spike, so the value is not fitted to noise;
# 72 is its top and admits the 72.7 deletions. Five pages change, four up and
# one down by a single day, net +5 -- spread across five different files
# rather than resting on one page.
MERGED_CELL_SPANS_ROWS = False  # D-096: MEASURED WORSE (93.8 -> 89.7). OFF.
# Swept on the page this was found on: 0.5 -> 28/30, 0.4 / 0.3 / 0.2 -> 30/30.
# Flat below 0.4, so the value is not fitted to that page; 0.4 is the most
# conservative setting that wins, which keeps a tall stray box from being
# shared into a row it merely clips.
MERGED_CELL_MIN_OVERLAP = 0.4
MERGED_CELL_MIN_HEIGHT = 1.5
ANNOT_FUZZ_THRESHOLD = 72
FURNITURE_THRESHOLD = 92    # higher bar to DISCARD a box as a label



# D-093. The anchor sets in use are THREAD-LOCAL, not global.
#
# extract() used to assign the module globals for a non-AARVI page and restore
# them in a finally. The app runs its extraction workers as THREADS
# (app/main.py starts threading.Thread per worker, TS_WORKERS=2 in
# production), so two pages in flight could and did share one set:
#
#   thread A (samsung)  sets HEADER_ANCHORS = samsung + aarvi
#   thread B (aarvi)    never sets them -- it READS whatever is there
#                       and binds its header with Samsung's labels
#   thread A finishes   restores them WHILE B is still mid-extraction
#
# The failure is intermittent, depends on which two layouts collide, and is
# invisible to every harness in this project because all of them are
# single-threaded. Thread-local state removes the sharing without touching a
# single function signature, so the extraction logic that produces the
# measured accuracy is untouched.
_LOCAL = threading.local()


def _header_anchors() -> tuple:
    return getattr(_LOCAL, "header", None) or HEADER_ANCHORS


def _summary_anchors() -> tuple:
    return getattr(_LOCAL, "summary", None) or SUMMARY_ANCHORS


def _column_anchors() -> dict:
    return getattr(_LOCAL, "column", None) or COLUMN_ANCHORS


def _norm(s: str) -> str:
    """Normalise for fuzzy comparison, folding the digit/letter confusions OCR
    makes constantly (O/0, I/1) so they don't defeat the match."""
    s = s.upper()
    s = s.replace("0", "O").replace("1", "I").replace("5", "S")
    return re.sub(r"[^A-Z ]", " ", s).strip()


def _matches(text: str, patterns: tuple[str, ...]) -> int:
    """Score how well an OCR box matches a label.

    We deliberately do NOT use fuzz.partial_ratio here. partial_ratio finds the
    best-aligning substring, so "EMPLOYEE CODE" scores ~100 against
    "EMPLOYEE NAME" on the shared word "EMPLOYEE" -- which caused every
    employee_code lookup to bind to the name label instead. Measured on
    ADANI02: employee_code came back None despite being clearly on the page.

    token_set_ratio compares the whole token sets, so a shared prefix word is
    not enough on its own to win. We also require the candidate to be a
    comparable length to the pattern, which stops a short fragment from
    matching a long label.
    """
    t = _norm(text)
    if not t:
        return 0

    # If the box is "LABEL: VALUE", score the LABEL part as well.
    #
    # Without this, an inline box like "EMPLOYEE NAME: SAWRABH RAJ SAWRABH RAJ"
    # scores ~30 against "EMPLOYEE NAME": the strings differ hugely in length,
    # so both token_sort_ratio and the length guard punish it -- and the anchor
    # is never found at all. Measured: this was why KBR's employee_name and
    # week_end_date came back empty even though OCR read them perfectly.
    candidates = [t]
    if ":" in text or "：" in text:
        head = re.split(r"[:：]", text, 1)[0]
        head_n = _norm(head)
        if len(head_n) >= 3:
            candidates.append(head_n)

    best = 0
    for p in patterns:
        pn = _norm(p)
        if not pn:
            continue
        # token_sort_ratio, NOT token_set_ratio.
        #
        # token_set_ratio treats a subset as a perfect match, which bound
        # "Total Man Hours" to the day-grid column header "TOTAL HOURS"
        # (measured: it did this on 92% of pages, so the row-sum checksum --
        # the core of the whole product -- could not run). token_sort_ratio
        # compares the full sorted token strings, so a missing word costs score.
        #
        # It also still fixes the earlier EMPLOYEE CODE / EMPLOYEE NAME
        # confusion, since those differ in their final token.
        for cand in candidates:
            ratio = int(fuzz.token_sort_ratio(cand, pn))
            # Length guard: a short fragment should not claim a long label.
            len_ratio = min(len(cand), len(pn)) / max(len(cand), len(pn))
            if len_ratio < 0.45:
                ratio = int(ratio * 0.6)
            best = max(best, ratio)
    return best


def find_anchor(boxes: list[TextBox], patterns: tuple[str, ...],
                y_min: float | None = None,
                y_max: float | None = None) -> TextBox | None:
    """Best-scoring box for a label, optionally restricted to a vertical band.

    The band matters. On this form family the summary labels always sit BELOW
    the day grid, and the grid's own column headers use overlapping words
    ("Total Hours" vs "Total Man Hours"). Constraining the search to the region
    where a label can legitimately appear removes a whole class of
    cross-binding that no amount of string-similarity tuning fixes reliably.
    """
    best, best_score = None, MATCH_THRESHOLD - 1
    for b in boxes:
        if len(_norm(b.text)) < 3:
            continue
        if y_min is not None and b.cy < y_min:
            continue
        if y_max is not None and b.cy > y_max:
            continue
        s = _matches(b.text, patterns)
        if s > best_score:
            best, best_score = b, s
    return best


def value_right_of(anchor: TextBox, boxes: list[TextBox], page_w: int,
                   max_gap_x: float = 0.55,
                   nearest_line: bool = False) -> list[TextBox]:
    """Boxes on the same horizontal band, to the right of the anchor.

    'Same band' is defined by vertical overlap with the anchor rather than a
    fixed pixel tolerance, so it adapts to font size and to page scale.
    """
    out = []
    a_h = max(1, anchor.y1 - anchor.y0)
    a_cy = (anchor.y0 + anchor.y1) / 2
    for b in boxes:
        if b is anchor or b.x0 < anchor.x1 - a_h * 0.2:
            continue
        # The box's CENTRE must sit within the anchor's line, not merely
        # overlap it.
        #
        # Overlap alone is too permissive for handwriting: values are written
        # large and slanted, so a name written on line 2 overlaps the label on
        # line 1 by well over a third of its height. Measured effect -- the
        # employee_name field came back as 'Shiv Shankan Apsinl -2026',
        # swallowing the month/year value from the row above.
        #
        # Requiring the centre to land inside the band keeps each value bound
        # to its own row while still tolerating a lot of vertical drift.
        if abs(b.cy - a_cy) > a_h * 0.75:
            continue
        if (b.x0 - anchor.x1) > page_w * max_gap_x:
            continue
        out.append(b)
    # Left-to-right, but when two candidates share a column the one whose
    # centre is nearest the anchor's line wins. A two-line label is tall, its
    # 0.75h window reaches into the row above, and a pure x-sort then returned
    # the previous row's value: GRSE01 read W/O=2 PH=8 where the sheet says 8
    # and 2 (decision log D-019). Column tolerance is one anchor height.
    # Header fields are READ left to right and concatenated, so their order
    # must stay pure x -- re-ordering by vertical distance pulled a same-line
    # designation into the name on VSPL p1 ('Mahesh Mohanty Safety
    # Officer') and the page fell out of matching. Summary cells are single
    # numbers, and there the value nearest the label's own line is the value:
    # a two-line label's window reaches the row above and below, and on
    # GRSE01 pure x returned the neighbour's number (W/O=2 PH=8 for 8 and 2)
    # and a grid cell for Leaves ('08:30', 20px off-line, vs '2', 7px off).
    if nearest_line and SUMMARY_NEAREST_LINE:
        return sorted(out, key=lambda b: (abs(b.cy - a_cy), b.x0))
    return sorted(out, key=lambda b: b.x0)


_MONTH_WORDS = ("JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
                "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER",
                "DECEMBER")
_YEARISH_RE = re.compile(r"^(?:19|20)\d{2}$|^\d{1,4}$")


def strip_period_from_name(value: str | None) -> str | None:
    """Remove a month/year that bled into the employee-name field.

    The geometric band filter in `value_right_of` catches most of this, but
    not all: measured on the evaluation corpus, 8 pages still emerged with
    names like 'JITENDNA SINGH APRIL-2026', 'APRTL.2026 VIVEK KOMAR' and a
    page whose entire name was 'APRIL-2026'. Those are wrong in the delivered
    output -- a reviewer sees a month where an employee should be -- and they
    also fail to match the roster, so the employee is never identified.

    Deliberately conservative: month-looking words are stripped ONLY when the
    value also carries a year token. Contamination always arrives as a pair
    ('APRIL-2026', 'JUNE -202'), whereas a bare name that happens to resemble
    a month ('MAYA') carries no year and is left completely alone.
    """
    if not value:
        return value
    raw = str(value).strip()

    # The year may be glued to the month inside a single token ('APRIL-2026',
    # 'APRTL.2026'), so search the whole string rather than testing tokens.
    if not re.search(r"(?:19|20)\d{2}", raw):
        return raw or None

    keep = []
    for tok in re.split(r"\s+", raw):
        core = re.sub(r"[^A-Za-z0-9]", "", tok)
        if not core:
            continue
        if core.isdigit():                        # 2026, 26, a clipped '202'
            continue
        # Split into its leading letters and trailing digits so a glued
        # month-year is judged on its word part: 'APRTL2026' -> 'APRTL'.
        m = re.match(r"^([A-Za-z]+)(\d*)$", core)
        if m and len(m.group(1)) >= 3:
            word = m.group(1).upper()
            if max(fuzz.ratio(word, mn) for mn in _MONTH_WORDS) >= 75:
                continue                          # APRIL, APRTL, APSIL, JULV
        keep.append(tok)
    out = " ".join(keep).strip(" -.,:")
    return out or None


# Job-title words that get written into, or read into, the name field. Kept as
# a small hand-checked list of HEAD words rather than the full 445-entry
# designation vocabulary: matching whole designations against a name is what
# risks deleting a real surname, whereas these lead a title and never a person.
_TITLE_HEADS = (
    "DOCUMENT", "SAFETY", "SITE", "PROJECT", "QUALITY", "ELECTRICAL",
    "MECHANICAL", "CIVIL", "INSTRUMENT", "PIPING", "WELDING", "STORE",
    "SECURITY", "JUNIOR", "SENIOR", "ASSISTANT", "DEPUTY", "CHIEF",
    "SUPERVISOR", "ENGINEER", "OFFICER", "INSPECTOR", "TECHNICIAN",
    "OPERATOR", "MANAGER", "CONTROLLER", "CONTROL", "FOREMAN", "FITTER",
    "HELPER", "INCHARGE", "COORDINATOR", "EXECUTIVE", "TRAINEE",
)


def strip_designation_from_name(value: str | None) -> str | None:
    """Remove a job title that led the employee-name field.

    Measured on HO pages, which sit under different form layouts:

        'RAMESH CHANDRALER SHAHANWAJ KHAN'   -> SHAHANWAJ KHAN
        'RAMESH CHANDRA'                     -> nothing; it is a title only
        'SAFETY OFFICER MAHESH MOHANTY'      -> MAHESH MOHANTY

    Same failure class as the month bleeding into the name: the value is wrong
    in the delivered output AND stops the roster ever identifying the person.

    Conservative by construction. Only a title-word PREFIX is removed -- the
    scan stops at the first word that is not a title word, so a real surname
    following the title is never touched, and a name that merely happens to
    contain such a word later ('RAJESH FOREMAN') keeps it. If nothing but
    title words remain, the field is not a person and becomes None.
    """
    if not value:
        return value
    toks = [t for t in re.split(r"\s+", str(value).strip()) if t]
    i = 0
    while i < len(toks):
        core = re.sub(r"[^A-Za-z]", "", toks[i]).upper()
        if core and core in _TITLE_HEADS:
            i += 1
            continue
        break
    if i == 0:
        return str(value).strip() or None
    out = " ".join(toks[i:]).strip(" -.,:")
    return out or None


def _clean_name(v: str | None) -> str | None:
    """Both name-contamination repairs, each behind its own switch."""
    if STRIP_PERIOD_FROM_NAME:
        v = strip_period_from_name(v)
    if STRIP_DESIGNATION_FROM_NAME:
        v = strip_designation_from_name(v)
    return v


_NUM_RE = re.compile(r"-?\d+(?:[.:]\d+)?")

# "EMPLOYEE ID: 20000001" -- label and value inside ONE OCR box.
_INLINE_RE = re.compile(r"^\s*(?P<label>[^:]{3,40}?)\s*[:：]\s*(?P<value>.+)$")
# "ASHOK VARMA [30000001]" -- name and code with no label at all.
_BRACKET_ID_RE = re.compile(r"^\s*(?P<name>[A-Za-z][A-Za-z .'-]{3,60}?)\s*"
                            r"[\[(]\s*(?P<code>[A-Za-z0-9\-/]{3,20})\s*[\])]\s*$")


def inline_value(box: TextBox, patterns: tuple[str, ...]) -> str | None:
    """Extract the value when the label and value share one OCR box.

    Many layouts render "EMPLOYEE ID: 20000001" as a single text run, so the
    "value is to the right of the label" strategy finds nothing at all. Measured:
    this alone was the entire reason KBR02 and SAMS01 scored 0% -- the values
    were read perfectly by OCR, we just never looked inside the label box.

    Returns the text after the colon when the part BEFORE the colon is the
    label we were looking for.
    """
    m = _INLINE_RE.match(box.text)
    if not m:
        return None
    if _matches(m.group("label"), patterns) < MATCH_THRESHOLD:
        return None
    val = m.group("value").strip(" :.-")
    return val or None


def find_bracket_identity(boxes: list[TextBox]) -> tuple[str | None, str | None]:
    """Recover 'NAME [CODE]' where the form carries no printed label.

    Scans the upper part of the page and takes the first plausible match; the
    employee block is always near the top on these layouts.
    """
    if not boxes:
        return None, None
    page_bottom = max(b.y1 for b in boxes) or 1
    for b in sorted(boxes, key=lambda x: x.y0):
        if b.cy > page_bottom * 0.30:
            break
        m = _BRACKET_ID_RE.match(b.text)
        if m:
            code = m.group("code")
            # Require the code to contain a digit -- otherwise a parenthetical
            # like "Store Keeper (Senior)" would be mistaken for an ID.
            if any(c.isdigit() for c in code):
                return m.group("name").strip(), code
    return None, None


def _first_number(texts: list[str]) -> str | None:
    for t in texts:
        m = _NUM_RE.search(t.replace(",", ""))
        if m:
            return m.group(0)
    return None


@dataclass
class Extracted:
    value: str | None
    conf: float
    source: str = "anchor"        # anchor | grid | none
    anchor_text: str | None = None


# Text that is printed ON the form but is never a value: the vendor's own
# letterhead, section captions, and any box that is itself a label. Without
# this filter the 2-D assignment happily hands "ATTENDANCE SHEET" to
# employee_code, because it is the nearest unclaimed box below that label.
_FURNITURE = (
    "AARVI ENCON", "ATTENDANCE SHEET", "CLIENT'S APPROVAL", "CHECKED BY",
    "APPROVER", "SIGNATURE", "STAMP", "REMARKS", "TIMESHEET",
    "MARATHON", "INNOVA", "NEXTGEN", "PENINSULA", "LOWER PAREL", "MUMBAI",
    "EMPLOYMENT FROM", "AGENCY MANPOWER",
)


def _is_form_furniture(b: TextBox) -> bool:
    t = _norm(b.text)
    if len(t) < 3:
        return True
    for f in _FURNITURE:
        if _norm(f) in t or t in _norm(f):
            return True
    # A box that is itself one of our labels is never a value.
    #
    # This must be STRICTER than anchor matching, not equal to it. Measured
    # bug: the designation VALUE "SAFETY SUPERVISOR" scored 81 against the
    # "SUPERVISOR" label pattern and was silently discarded as furniture --
    # destroying the designation on most IOCL pages. A near-miss should be
    # treated as a value; only a near-exact label match is furniture.
    for a in _header_anchors() + _summary_anchors():
        if _matches(b.text, a.patterns) >= FURNITURE_THRESHOLD:
            return True
    return False


def _nearest_anchor_filter(anchor: TextBox, candidates: list[TextBox],
                           all_anchors: list[TextBox]) -> list[TextBox]:
    """Keep only the candidate boxes for which THIS anchor is the closest one.

    Why this is necessary, measured on IOCL30:

        MONTH & YEAR:   label cy=197   value 'Apsinl -2026'  cy=218   (d=21)
        EMPLOYEE NAME:  label cy=232   value 'Shiv Shankan'  cy=252   (d=20)

    Handwritten values sit ~20 px below their own label, but the form's rows
    are only ~35 px apart. So the month's value lands within tolerance of BOTH
    the month label and the name label, and a simple distance threshold assigns
    it to both -- producing 'Shiv Shankan Apsinl -2026'.

    No threshold can fix this, because the value genuinely is close to two
    labels. What distinguishes them is that it is CLOSER to its own. So we make
    the labels compete: a value belongs to whichever anchor is nearest.
    """
    if not all_anchors:
        return candidates
    a_cy = (anchor.y0 + anchor.y1) / 2
    kept = []
    for b in candidates:
        best_anchor, best_d = None, None
        for other in all_anchors:
            # Only labels to the LEFT of the value can own it.
            if other.x1 > b.x0 + 5:
                continue
            o_cy = (other.y0 + other.y1) / 2
            o_h = max(1, other.y1 - other.y0)
            # A value sits AT or BELOW its own label -- handwriting drops into
            # the cell, it never floats above the label. Ignoring that gives
            # the wrong owner: on IOCL30 'Apsinl -2026' (cy=218) is nearer the
            # EMPLOYEE NAME label (cy=232, d=14) than its own MONTH & YEAR
            # label (cy=197, d=21), so a pure nearest-neighbour rule shifted
            # every value down one row.
            if o_cy > b.cy + o_h * 0.5:
                continue
            d = b.cy - o_cy
            if best_d is None or d < best_d:
                best_anchor, best_d = other, d
        if best_anchor is None or abs(a_cy - (best_anchor.y0 + best_anchor.y1) / 2) < 1:
            kept.append(b)
    return kept


def extract_header(boxes: list[TextBox], page_w: int,
                   page_h: int = 0,
                   handwritten: bool = False) -> dict[str, Extracted]:
    # Header labels live in the top band; restricting the search stops them
    # binding to look-alike words further down the page.
    ymax = page_h * 0.35 if page_h else None
    # Resolve every header label first, so they can compete for values.
    found: dict[str, TextBox] = {}
    for a in _header_anchors():
        anc = find_anchor(boxes, a.patterns, y_max=ymax)
        if anc is not None:
            found[a.field] = anc
    # D-054: a bare "Name: X" / "Code: X" inline box (GSPL, GIGL "Attendance
    # Sheet" forms). The fuzzy anchor cannot match a one-word label without
    # also matching "Client Name" / "Supervisor Name", so the label part is
    # compared EXACTLY. Without this every GSPL page fell through to the
    # header VLM at ~45 s a page for a name OCR had already read.
    if BARE_INLINE_LABELS:
        for field, exact in _BARE_LABELS.items():
            if field in found:
                continue
            for b in boxes:
                if ymax is not None and b.cy > ymax:
                    continue
                m = _INLINE_RE.match(b.text or "")
                if m and _norm(m.group("label")).strip() in exact \
                        and m.group("value").strip(" :.-"):
                    found[field] = b
                    break
    all_anchors = list(found.values())

    # Globally assign value boxes to labels in 2-D. A per-label distance
    # threshold cannot separate rows that are 35px apart when handwriting sits
    # 20px low -- every value matches two labels and both claim it.
    # Global 2-D assignment is applied ONLY to handwritten pages.
    #
    # Measured both ways: it lifts handwritten accuracy 60% -> 70% by stopping
    # the field bleed, but costs printed pages 86% -> 76%, because on typed
    # forms values sit neatly on their label's line and the simpler band rule
    # is already correct -- while the global solver's one-value-one-owner
    # constraint occasionally starves a legitimate second field.
    #
    # The bleed is a handwriting problem, so the fix is applied where the
    # problem is.
    owned: dict[str, list[TextBox]] = {}
    if handwritten:
        # NOTE: ordinal (sequence) matching was implemented in
        # app/ordinal_match.py and MEASURED here, then reverted: 82.1% -> 79.5%,
        # handwritten 70% -> 60%. It is the right idea for a uniformly shifted
        # block, but its value-column detection pulled in grid column headers
        # ('NORMAL' was assigned to employee_code), and its 1:1 alignment check
        # passed on the wrong rows. It needs a reliable value-column boundary
        # before it can be trusted -- see docs/06.
        from .assignment import assign as assign_2d
        value_pool = [b for b in boxes
                      if (page_h == 0 or b.cy <= (ymax or page_h))
                      and b not in all_anchors
                      and not _is_form_furniture(b)]
        owned = assign_2d(found, value_pool)

    out: dict[str, Extracted] = {}
    for a in _header_anchors():
        anc = found.get(a.field)
        if anc is None:
            out[a.field] = Extracted(None, 0.0, "none")
            continue
        # Label and value may share one OCR box -- check inside it first.
        inline = inline_value(anc, a.patterns)
        if not inline and BARE_INLINE_LABELS and a.field in _BARE_LABELS:
            _m = _INLINE_RE.match(anc.text or "")
            if _m and _norm(_m.group("label")).strip() in _BARE_LABELS[a.field]:
                inline = _m.group("value").strip(" :.-") or None
        if inline:
            out[a.field] = Extracted(inline, anc.conf, "inline", anc.text)
            continue
        vals = (owned.get(a.field) or []) if handwritten \
            else value_right_of(anc, boxes, page_w, a.max_gap_x)
        # NOTE: an earlier 1-D attempt (_nearest_anchor_filter) was
        # implemented and MEASURED here, and made accuracy worse: 78.8% -> 66.7%.
        # Two variants were tried -- nearest-label, and nearest-label-at-or-above.
        # Both fixed the IOCL30 handwritten bleed but broke the side-by-side
        # label pairs ("MONTH & YEAR: v | CLIENT: v"), where the left column's
        # label competes with the right column's value. Correct assignment needs
        # x-distance as well as y, i.e. a proper 2-D assignment problem.
        # Left un-applied deliberately; see docs/06-accuracy-improvements.md.
        # Stop at the next label: header rows pack two label/value pairs side
        # by side ("EMPLOYEE NAME | <value> | CLIENT | <value>"), so we must not
        # swallow the neighbouring pair's label and value.
        #
        # The stop test uses FURNITURE_THRESHOLD, not MATCH_THRESHOLD.
        #
        # This is the same asymmetry documented at _is_form_furniture(): the bar
        # to FIND a label may be 80, but the bar to DISCARD a value as a label
        # must be higher, because job titles legitimately contain label words.
        # FURNITURE_THRESHOLD was introduced for exactly this bug and then
        # applied in only one of the two places that needed it -- this loop kept
        # comparing at 80, and
        #     _matches('Safety Supervisor', ('SUPERVISOR NAME',)) == 81
        # so the designation's own value tripped the break on the first box,
        # `trimmed` stayed empty, and the field was set to None. Measured: this
        # alone blanked the designation on 4 of the 6 pages where it came back
        # empty, on pages where the value had been located correctly.
        # Applying FURNITURE_THRESHOLD to EVERY box was measured and was a net
        # loss: designation 15/24 -> 18/23, but overall 78.4% -> 76.6%, because
        # a permissive stop lets other fields swallow the neighbouring pair's
        # label and value, and one page stopped matching its Excel row at all.
        #
        # The first box is different in kind from the rest. A header row reads
        # "LABEL value LABEL value", so the box immediately to the right of our
        # own anchor IS our value, by construction -- it cannot be the next
        # label. Only from the second box onward is the strict stop right.
        trimmed: list[TextBox] = []
        for b in vals:
            bar = (FURNITURE_THRESHOLD
                   if (not trimmed and a.field in _TITLE_LIKE_FIELDS)
                   else MATCH_THRESHOLD)
            if any(_matches(b.text, x.patterns) >= bar
                   for x in _header_anchors() if x.field != a.field):
                break
            trimmed.append(b)
        if not trimmed:
            out[a.field] = Extracted(None, 0.0, "none", anc.text)
            continue
        text = " ".join(b.text for b in trimmed).strip(" :.-")
        conf = min(b.conf for b in trimmed)
        out[a.field] = Extracted(text or None, conf, "anchor", anc.text)
    return out


def summary_band_start(boxes: list[TextBox], page_h: int) -> float:
    """Find where the summary block begins.

    Anchored on the most distinctive summary label ("P (Total Present Days)"),
    which is unique on the page and reads reliably because it is printed. Every
    other summary label sits on or below its line. Falls back to the bottom 35%
    of the page if that label can't be found.
    """
    for pats in (("P (TOTAL PRESENT DAYS)", "TOTAL PRESENT DAYS"),
                 ("LEAVES (TOTAL LEAVES)", "TOTAL LEAVES"),
                 ("A (TOTAL ABSENT DAYS)", "TOTAL ABSENT DAYS")):
        anc = find_anchor(boxes, pats, y_min=page_h * 0.40)
        if anc is not None:
            return anc.y0 - (anc.y1 - anc.y0) * 2.0
    return page_h * 0.65


# D-046: when NO summary label exists on the page (GSPL "Attendance Sheet",
# Siemens service sheets, ...), summary_band_start() falls back to 65% of the
# page height, and that fallback was being used as the rule-band bound. On
# s26 (50-page sample) the grid's last four rows sat at 65-70% of the page
# and were cut -- 12-Apr..15-Apr dropped with nothing to flag them. The
# physically meaningful bound on such a page is the bottom of the last
# date-like cell in the date column, plus one row pitch.
GRID_BOTTOM_FROM_DATES = True
CLEAN_RULES_BEAT_LADDER = True    # D-047
CLEAN_RULES_GATE = "strict"         # "strict" | "mismatch_only"
EXPECT_FROM = "calendar_first"      # "dates_first" | "calendar_first"
ZERO_HOURS_WEEKEND_IS_OFF = True  # D-048
HEADER_RULE_TOLERANT = True       # D-049
HEADER_FROM_DATES = True          # D-050
BARE_INLINE_LABELS = True         # D-054
_BARE_LABELS = {"employee_name": ("NAME", "EMP NAME"), "employee_code": ("CODE", "EMP CODE")}
DATE_BOTTOM_CAPS_GRID = False     # D-051: withdrawn (guard -1/-12, s08 silent 1->4)
_DATE_LIKE_LOOSE = re.compile(r"^\s*\d{1,2}\s*[-/.]\s*(?:\d{1,2}|[A-Za-z]{3,9})(?:\s*[-/.]\s*\d{2,4})?(?:\s*\(?\s*[A-Za-z]{3,9}\s*\)?)?\s*$")
_DATE_LIKE = re.compile(r"^\s*\d{1,2}\s*[-/.]\s*(?:\d{1,2}|[A-Za-z]{3,9})\s*[-/.]?\s*\d{0,4}\s*$")


def date_column_bottom(boxes: list[TextBox], page_w: int,
                       page_h: int) -> float | None:
    """y just below the lowest date-like cell in the left part of the page."""
    dates = [b for b in boxes
             if b.cx < page_w * 0.30 and b.cy > page_h * 0.15
             and _DATE_LIKE_LOOSE.match(b.text or "")]
    if len(dates) < 8:
        return None
    ys = sorted(b.cy for b in dates)
    pitches = sorted(b - a for a, b in zip(ys, ys[1:]) if b - a > 2)
    pitch = pitches[len(pitches) // 2] if pitches else 0.0
    return max(b.y1 for b in dates) + pitch * 0.6


def grid_bottom(boxes: list[TextBox], page_h: int) -> float | None:
    """The day grid's true lower edge: the TOP of the first summary label.

    Distinct from summary_band_start(), which subtracts a two-label-height
    safety pad. That pad is right for its own consumer -- extract_summary uses
    it as a y_min and must not miss a slightly-high label -- and disastrous as
    a grid bound: two label-heights is two grid rows on these forms, so the
    ladder was being truncated above days 29-31 on almost every page.

    Measured (787 day comparisons), sweeping the pad used as the band bound:
        pad 2.0 (summary_band_start)   80.4%
        pad 1.0                        81.8%
        pad 0.5                        82.7%
        pad 0.0  (this function)       87.0%
        pad -0.3                       87.2%
    The 57-of-83 trailing-day losses (days 29/30/31 absent) were this. Zero
    pad is taken: it is the physically meaningful boundary, and the extra 0.2
    points from cutting INTO the label is not worth rows that contain summary
    text.
    """
    for pats in (("P (TOTAL PRESENT DAYS)", "TOTAL PRESENT DAYS"),
                 ("LEAVES (TOTAL LEAVES)", "TOTAL LEAVES"),
                 ("A (TOTAL ABSENT DAYS)", "TOTAL ABSENT DAYS")):
        anc = find_anchor(boxes, pats, y_min=page_h * 0.40)
        if anc is not None:
            return float(anc.y0)
    return None


def extract_summary(boxes: list[TextBox], page_w: int,
                    page_h: int = 0) -> dict[str, Extracted]:
    # Restrict to the summary band so grid column headers cannot win the match.
    band = summary_band_start(boxes, page_h) if page_h else None
    out: dict[str, Extracted] = {}
    for a in _summary_anchors():
        anc = find_anchor(boxes, a.patterns, y_min=band)
        if anc is None:
            out[a.field] = Extracted(None, 0.0, "none")
            continue
        inline = inline_value(anc, a.patterns)
        if inline:
            out[a.field] = Extracted(_first_number([inline]), anc.conf,
                                     "inline", anc.text)
            continue
        vals = value_right_of(anc, boxes, page_w, a.max_gap_x,
                              nearest_line=True)
        # The NEXT field's label ("Leaves (Total Leaves)") sits on the same
        # line to the right of this field's value. Sorted by nearest line it
        # comes first, and stopping at it collected nothing: P read as None
        # on 6 of 7 hand-checked pages while '31', '28', '30 days' sat in
        # plain view. So: find the nearest other-anchor label, keep only
        # candidates LEFT of it, and read the first number among those.
        if SUMMARY_BOUND_BY_NEXT_LABEL:
            others = [b for b in vals
                      if any(_matches(b.text, x.patterns) >= MATCH_THRESHOLD
                             for x in _summary_anchors() if x.field != a.field)]
            x_limit = min((b.x0 for b in others), default=float("inf"))
            trimmed = [b for b in vals if b not in others and b.x1 <= x_limit + 2]
        else:
            trimmed = []
            for b in vals:
                if any(_matches(b.text, x.patterns) >= MATCH_THRESHOLD
                       for x in _summary_anchors() if x.field != a.field):
                    break
                trimmed.append(b)
        num = _first_number([b.text for b in trimmed])
        conf = min((b.conf for b in trimmed), default=0.0)
        out[a.field] = Extracted(num, conf, "anchor", anc.text)
    return out


def learn_columns(boxes: list[TextBox],
                  page_w: int | None = None) -> dict[str, tuple[float, float]]:
    """Learn each grid column's x-range from its printed header.

    Reading the geometry off the page beats hard-coding it: the same logical
    column sits at a different x on every capture, and some clients' forms
    omit columns entirely.
    """
    cols: dict[str, tuple[float, float]] = {}
    # Column headers live on ONE line: the header band. Searching the whole
    # page let a summary label ("Total Man Hours", bottom-left) fuzzy-match
    # the TOTAL HOURS column header, which planted a column at x 67..266 --
    # on top of the date column -- and swallowed every date cell (Siemens
    # sheet, D-038). Anchor the band on the DATE header, then learn the
    # other headers only from boxes on that line. Flag COLUMN_HEADERS_IN_BAND.
    pool = boxes
    if COLUMN_HEADERS_IN_BAND:
        d_anc = find_anchor(boxes, _column_anchors()["date"])
        if d_anc is not None:
            h = max(8.0, d_anc.y1 - d_anc.y0)
            # +-6 row-heights: stacked three-line headers stay in; a summary
            # label 1,100px below the grid cannot.
            band = [b for b in boxes if abs(b.cy - d_anc.cy) <= h * 6.0]
            if len(band) >= 3:
                # Stacked header lines ("TOTAL" over "HOURS", "TIME" over
                # "OUT") come from OCR as separate one-word boxes and match
                # nothing; the column is then INFERRED and can land on the
                # signature block (ADN903, D-040). Merge boxes that overlap
                # in x and sit on adjacent lines into one synthetic header
                # box, top to bottom, and offer both forms to the matcher.
                merged = []
                used = set()
                col = sorted(band, key=lambda b: (b.x0, b.cy))
                for i, a in enumerate(col):
                    if i in used:
                        continue
                    grp = [a]
                    for j in range(i + 1, len(col)):
                        c = col[j]
                        if j in used:
                            continue
                        ov = min(a.x1, c.x1) - max(a.x0, c.x0)
                        # Overlap in x and within ~two lines in y, in EITHER
                        # direction: sorted by x0, "HOURS" (634) precedes
                        # "TOTAL" (636) and a top-to-bottom guard here dropped
                        # the pair. Order is fixed by the cy sort below.
                        if ov >= 0.5 * min(a.x1 - a.x0, c.x1 - c.x0) and \
                                abs(c.cy - grp[-1].cy) <= h * 2.2:
                            grp.append(c); used.add(j)
                    if len(grp) >= 2:
                        grp.sort(key=lambda b: b.cy)
                        try:
                            merged.append(TextBox(
                                text=" ".join(str(b.text).strip() for b in grp),
                                conf=min(float(b.conf) for b in grp),
                                x0=min(b.x0 for b in grp), y0=min(b.y0 for b in grp),
                                x1=max(b.x1 for b in grp), y1=max(b.y1 for b in grp)))
                        except TypeError:
                            pass
                pool = band + merged
    for fieldname, pats in _column_anchors().items():
        anc = find_anchor(pool, pats)
        if anc is not None:
            # Widen slightly: values are often written wider than the header.
            pad = (anc.x1 - anc.x0) * 0.35
            cols[fieldname] = (anc.x0 - pad, anc.x1 + pad)

    # Fallback for the date column specifically.
    #
    # On handwritten forms the printed "Date" header is short and frequently
    # misread ("Dale", "Dote"), so the fuzzy anchor misses it -- and without a
    # date column NO day rows are emitted at all, which silently drops the
    # entire grid. Measured on IOCL30: 0 of 30 rows recovered.
    #
    # The date is always the leftmost column of this form family, so when the
    # header match fails we derive the column from the left edge of the other
    # columns we DID find. Losing the header is recoverable; losing the grid
    # is not.
    if "date" not in cols and cols:
        leftmost = min(x0 for x0, _ in cols.values())
        left_edge = min((b.x0 for b in boxes), default=0)
        # Scale-free thresholds.
        #
        # These were absolute pixels (20 and 5), tuned when every page was
        # normalised to a 1600px long edge. Landscape sheets are now rendered
        # at 2600 because their cells are otherwise unreadable, and at that
        # width a "20 pixel" gap means something quite different -- the rule
        # silently changes behaviour with the input size, which is exactly
        # what stops the pipeline generalising to a new capture.
        #
        # Expressed as a fraction of page width, the same rule holds at any
        # resolution. 20/1600 preserves the measured behaviour on the pages
        # it was tuned against.
        w = float(page_w or 1600)
        min_gap = w * 0.0125
        pad = w * 0.003
        if leftmost - left_edge > min_gap:
            cols["date"] = (left_edge - pad, leftmost - pad)
    # The date column is the LEFTMOST column on every form seen, and its
    # printed header ("DATE") is often centred in a column wider than the
    # header box: on a Siemens sheet the header spanned x 189..240 while the
    # left-aligned dates ran 109..203, so the learned bounds missed every
    # date, no anchors were read, positional numbering ran, and one merged
    # row shifted the month. Extend the learned date column's LEFT bound to
    # the leftmost text below the header (D-038). Flag DATE_COL_TO_LEFT_EDGE.
    if DATE_COL_TO_LEFT_EDGE and "date" in cols:
        hdr_y = max((b.cy for b in boxes if find_anchor([b], _column_anchors()["date"]) is not None), default=None)
        body_x0 = [b.x0 for b in boxes if hdr_y is not None and b.cy > hdr_y + 4]
        if body_x0:
            left = min(body_x0)
            d0, d1 = cols["date"]
            if left < d0:
                cols["date"] = (max(0.0, left - (d1 - d0) * 0.1), d1)
    return cols


def fit_ladder(found: list[int], lo_n: int = 26, hi_n: int = 31,
               tol: float = 0.25, min_align: float = 0.82) -> list[int] | None:
    """Fit a uniform row ladder across the detected rules, using the month.

    regularise_rules() estimates the pitch from the SMALLEST gaps, which is
    correct when rules are missing (a missed rule can only widen a gap). It is
    wrong when rules are SPURIOUS -- dense handwriting and doubled lines add
    extra detections, and then the smallest gaps are the noise. Measured on a
    JSPL page: gaps ran 23,23,22,23,23,14,11,12,10,13,10,20,24,... so the
    smallest-gap estimate returned a pitch of 13 against a true pitch of 23,
    and would have built a 55-row ladder for a 30-row grid.

    The robust constraint is one we already have: a month grid holds 28-31
    rows. So instead of estimating the pitch from the noise, try every
    plausible row count, lay a ladder of that many rungs across the span, and
    keep the one the detections agree with best. Spurious rules simply fail to
    align and are outvoted; missing rules cost nothing.
    """
    if len(found) < 8:
        return None
    span = found[-1] - found[0]
    if span <= 0:
        return None

    best: tuple[float, int] | None = None
    for n in range(lo_n, hi_n + 1):
        pitch = span / n
        if pitch <= 4:
            continue
        aligned = sum(
            1 for r in found
            if abs((r - found[0]) / pitch - round((r - found[0]) / pitch)) <= tol)
        # Slight penalty for more rungs: a denser ladder aligns more detections
        # by chance alone, so it must earn the extra rows.
        score = aligned / len(found) - 0.004 * n
        if best is None or score > best[0]:
            best = (score, n)
    if best is None:
        return None

    score, n = best
    if score + 0.004 * n < min_align:
        return None
    pitch = span / n
    return [int(round(found[0] + i * pitch)) for i in range(n + 1)]


def regularise_rules(found: list[int],
                     tol: float = 0.28,
                     min_hit: float = 0.75) -> list[int] | None:
    """Rebuild the complete rule ladder from a partially-detected one.

    A rejected page is usually not an irregular page. Page 11's in-band rules
    were:

        488 535 556 603 670 693 715 737 759 805 826 848 893
        gaps:  47 21 47 67 23 22 22 22 46 21 22 45

    Those gaps are 1x, 2x and 3x of a ~22 px pitch. The grid is perfectly
    regular; the detector simply missed some rules where the printed line was
    faint or crossed by handwriting. Judged on raw gap variance the page scores
    CV 0.45 and gets thrown away, losing a grid we could have reconstructed
    exactly.

    So: estimate the base pitch from the *smallest* gaps (a missed rule can
    only ever make a gap larger, never smaller), then lay a ladder from the
    first detected rule to the last and keep it only if the detections
    genuinely sit on it.

    Returns None when the detections do not fit a single pitch, which is the
    real "irregular page" case -- long runs of handwriting mistaken for rules.
    """
    if len(found) < 6:
        return None
    gaps = sorted(b - a for a, b in zip(found, found[1:]) if b - a > 4)
    if len(gaps) < 5:
        return None

    # Base pitch from the lower half of the gaps: unmissed neighbours.
    import statistics
    pitch = statistics.median(gaps[:max(3, len(gaps) // 2)])
    if pitch <= 4:
        return None

    span = found[-1] - found[0]
    n_steps = int(round(span / pitch))
    if not (10 <= n_steps <= 60):
        return None
    pitch = span / n_steps                    # refit exactly across the span

    ladder = [int(round(found[0] + i * pitch)) for i in range(n_steps + 1)]

    # Every detected rule must sit near a ladder rung, or the pitch is wrong.
    hits = 0
    for r in found:
        k = round((r - found[0]) / pitch)
        if abs(r - (found[0] + k * pitch)) <= tol * pitch:
            hits += 1
    if hits / len(found) < min_hit:
        return None
    return ladder


def rule_bands(rules: list[int], header_y: float,
               footer_y: float | None,
               max_cv: float = 0.30,
               min_rules: int = 20,
               repair: bool = True,
               expected_rows: int | None = None) -> list[int] | None:
    """Row boundaries taken from the form's PRINTED horizontal rules.

    Every other row-finder in this file infers boundaries from where the *ink*
    is. The rules are where the boundaries actually are, and they give two
    things ink clustering cannot:

      1. two rows whose handwriting merged into one cluster still occupy two
         separate bands
      2. a BLANK row still occupies a band, so it keeps its place in the day
         numbering instead of shifting every later day up by one

    Returns None when the rules are not trustworthy, because they are not
    always there. Measured across 12 pages: 5 pages had a clean regular grid
    (pitch CV 0.02-0.21), 2 had none detected at all, and the rest were noisy
    (CV up to 1.06 -- long runs of handwriting matching the kernel). Rather
    than degrade those pages, we hand them back to the ink clusterer.
    """
    if not rules:
        return None
    lo, hi = header_y, (footer_y if footer_y else float("inf"))
    # The rule AT the footer bound is the grid's own bottom edge; a strict
    # upper bound dropped it and the last day row fell outside the final
    # band (mv02: day 31 at y=1152 under a last band ending at 1142 with the
    # bottom rule at 1168). Flag FOOTER_RULE_INCLUSIVE (D-044).
    inband = sorted(r for r in rules
                    if lo < r and (r <= hi if FOOTER_RULE_INCLUSIVE else r < hi))
    if HEADER_RULE_TOLERANT and inband:
        # D-049: the "DATE" header text box is padded a few px below the
        # printed rule that closes the header, so lo (= the anchor's y1) sits
        # just UNDER the grid's top rule and that rule was excluded; row 1
        # then fell above the first band and was dropped (s49: rule 405,
        # header_y 410, row 1 at 411-435). Admit one rule within a third of
        # a pitch above the bound -- it is the grid's own top edge.
        _g = [b - a for a, b in zip(inband, inband[1:])]
        _pitch = sorted(_g)[len(_g) // 2] if _g else 0
        _above = [r for r in rules if lo - 0.34 * _pitch < r <= lo]
        if _pitch and _above:
            inband = sorted([max(_above)] + inband)
        # Same at the footer: the summary label's text box starts a few px
        # ABOVE the printed rule that closes the grid (s17: label y0 1273,
        # rule 1275), so the grid's own bottom rule fell outside the bound
        # and the last day row with it.
        if _pitch and hi != float("inf"):
            _below = [r for r in rules if hi < r < hi + 0.34 * _pitch]
            if _below and (not inband or _below[0] - inband[-1] > 0.5 * _pitch):
                inband = sorted(inband + [min(_below)])

    # Collapse hairline duplicates: a thick printed rule is often detected
    # twice, which would otherwise create a sliver band holding no ink.
    dedup: list[int] = []
    for r in inband:
        if not dedup or r - dedup[-1] > 6:
            dedup.append(r)
    if len(dedup) < min_rules:
        # Too few rules to band directly -- but a partial ladder can still be
        # completed if what WAS found sits on one pitch.
        return regularise_rules(dedup) if repair else None

    # A month cannot have more than 31 day rows, so 32 rungs is the hard
    # ceiling. More detections than that means spurious rules are carving real
    # rows into slivers -- and such a set can still pass the CV test (one page
    # passed at CV 0.249 with 34 rungs for a 30-row grid). When that happens
    # the raw detections are not an option: either a ladder explains them or
    # the page goes back to the ink clusterer.
    over_dense = len(dedup) - 1 > 31

    # D-047: when the printed rules are CLEAN -- a calendar-sized count, no
    # gap far from the median -- they ARE the grid, and a uniform ladder is a
    # worse model of them. s17/s06 (50-page sample): the real pitch drifts
    # 28.7 -> 33.5 px down the page (scanner/roller stretch), the 31-rung
    # ladder fitted over that span gains a phantom rung near day 21, and
    # every later row slid one day -- two SILENT wrong rows per page. The
    # ladder stays for noisy or sparse detections, which is what it was for.
    if CLEAN_RULES_BEAT_LADDER and len(dedup) >= 8:
        _g = [b - a for a, b in zip(dedup, dedup[1:])]
        _med = sorted(_g)[len(_g) // 2]
        # A detection closer than half a pitch to its neighbour is a doubled
        # or spurious line (s06: 542, 557, 564, 580 around a merged W/OFF
        # cell on a 22 px pitch -- two sliver bands, every later day slid).
        # Keep whichever of the pair sits nearer to prev + pitch.
        _clean = [dedup[0]]
        for r in dedup[1:]:
            if r - _clean[-1] < 0.5 * _med:
                _prev = _clean[-2] if len(_clean) > 1 else None
                if _prev is not None and abs(r - _prev - _med) < abs(_clean[-1] - _prev - _med):
                    _clean[-1] = r
                continue
            _clean.append(r)
        _g = [b - a for a, b in zip(_clean, _clean[1:])]
        # The count must agree with what the page says it holds (the date
        # column's own row count, else the calendar). s28: a diagonal
        # strike-through added rules 487/509/527/554 that survived the gap
        # test and gave 31 bands for a 30-row grid -- three silent slides.
        # No expectation available -> not clean; the ladder decides.
        _count_ok = (28 <= len(_clean) - 1 <= 31 if expected_rows is None
                     else len(_clean) - 1 == expected_rows) \
            if CLEAN_RULES_GATE == "mismatch_only" else \
            (expected_rows is not None and len(_clean) - 1 == expected_rows)
        if (_med > 4 and _count_ok
                and all(0.65 * _med <= g <= 1.45 * _med for g in _g)):
            return _clean

    if repair:
        # Try the month-constrained ladder FIRST, not only as a rescue.
        #
        # The CV test only asks "are the gaps consistent?", and a set of rules
        # that includes spurious detections can still pass it while carving
        # real rows into slivers -- one page passed at CV 0.249 and produced 33
        # bands for a 30-row grid, with day numbers duplicating as a result.
        # A ladder the detections vote for is a better grid than the raw
        # detections, whether they were noisy or merely sparse.
        ladder = fit_ladder(dedup)
        if ladder is None and over_dense:
            # Relax the agreement bar rather than fall back to a row count the
            # calendar says is impossible.
            ladder = fit_ladder(dedup, min_align=0.55)
        if ladder:
            return ladder
    if over_dense:
        return None

    gaps = [b - a for a, b in zip(dedup, dedup[1:])]
    mean = sum(gaps) / len(gaps)
    if mean <= 0:
        return None
    import statistics
    if statistics.pstdev(gaps) / mean <= max_cv:
        return dedup
    # Irregular by raw variance. That is usually MISSING rules rather than
    # spurious ones, so try to reconstruct before discarding the page.
    return regularise_rules(dedup) if repair else None


def rows_from_bands(boxes: list[TextBox],
                    bands: list[int]) -> list[list[TextBox]]:
    """Drop each box into the band its vertical centre falls in.

    Boxes above the first rule or below the last are ignored: those bounds are
    the printed top and bottom of the grid, so anything outside is header or
    summary text, not a day row.
    """
    from bisect import bisect_right

    buckets: dict[int, list[TextBox]] = {}
    for b in boxes:
        i = bisect_right(bands, b.cy) - 1
        if 0 <= i < len(bands) - 1:
            buckets.setdefault(i, []).append(b)

        # D-096. A MERGED cell belongs to every row it covers.
        #
        # "Weekly Off" is routinely printed once across the Saturday and
        # Sunday rows as a single merged cell. Bucketing by the box's centre
        # gave it to one of the two rows and left the other blank, so the
        # sheet lost a day it states plainly. Measured by hand on an HO
        # sample: 26 of 30 on one page, with all four errors this one cause,
        # and 17 such cells across 7 of 50 pages.
        #
        # Only a box that genuinely STRADDLES a boundary is shared, and only
        # into bands it covers by at least half their height -- a tall piece
        # of ink clipping the next row by a few pixels is not a merged cell.
        # Numbers are excluded: a date or an hours figure never spans rows,
        # and duplicating one would corrupt a column rather than complete it.
        if not MERGED_CELL_SPANS_ROWS:
            continue
        txt = str(getattr(b, "text", "")).strip()
        if not txt or any(ch.isdigit() for ch in txt):
            continue
        for j in range(len(bands) - 1):
            if j == i:
                continue
            lo, hi = bands[j], bands[j + 1]
            band_h = max(hi - lo, 1)
            # The box must be TALL ENOUGH TO BE A MERGED CELL in the first
            # place. Without this the rule shared ordinary single-row
            # annotations into their neighbours and the guard harness fell
            # 93.8% -> 89.0%. A merged cell covering two rows is about twice
            # a band high; a normal annotation is about one.
            if (b.y1 - b.y0) < MERGED_CELL_MIN_HEIGHT * band_h:
                continue
            overlap = min(b.y1, hi) - max(b.y0, lo)
            if overlap > 0 and overlap >= MERGED_CELL_MIN_OVERLAP * band_h:
                buckets.setdefault(j, []).append(b)
    # Emit EVERY band, including empty ones. An empty band is a real blank row
    # on the form and must hold its position, otherwise the days after it all
    # shift up by one -- the silent misalignment this function exists to fix.
    rows = [sorted(buckets.get(i, []), key=lambda b: b.x0)
            for i in range(len(bands) - 1)]
    return rows


# The physical left-to-right order of the day grid. Fixed by the printed form,
# so it holds even when a header is unreadable.
COLUMN_ORDER = ("date", "in_time", "out_time", "normal_hours",
                "ot_hours", "total_hours", "remarks")

_TOKEN_RE = re.compile(r"\S+")

# A clock reading, however OCR mangled the separator ('9:00Am', '9100 Am',
# '91100Am', '6.00 PM'). Used to split a box that merged two cells with no
# space between them, where whitespace tokenisation finds only one token.
_TIME_TOK_RE = re.compile(r"\d{1,2}\s*[:.!|,]?\s*\d{2}\s*[APap]?\.?\s*[Mm]?")


def _sub_tokens(text: str) -> list[tuple[int, int, str]]:
    """Split a cell's text into placeable pieces, as (start, end, text).

    Clock readings first: '9:00Am6:00pm' is a single whitespace token but two
    values, and splitting on whitespace alone leaves it unplaceable. Falls back
    to whitespace tokens for everything else.
    """
    times = [(m.start(), m.end(), m.group().strip())
             for m in _TIME_TOK_RE.finditer(text) if m.group().strip()]
    if len(times) >= 2:
        return times
    return [(m.start(), m.end(), m.group()) for m in _TOKEN_RE.finditer(text)]


def _assign_box(b: TextBox,
                columns: dict[str, tuple[float, float]]
                ) -> list[tuple[str, str, float]]:
    """Place one OCR box into one or more columns.

    The simple rule -- "the column containing the box's centre" -- fails on a
    box that spans two cells. OCR merges neighbouring cells routinely when the
    handwriting touches the rule between them:

        '9:00Am6:00pm'   x 257..471   in_time ends at 355, normal starts at 455

    That box's centre (364) lies in NO column, so both the clock-in and the
    clock-out were thrown away and the row read as empty. Requiring the centre
    to land in a cell is the same class of mistake as requiring a readable date.

    So: if the box straddles a boundary and holds more than one token, split
    the text and place each token by its own estimated position, interpolating
    across the box's width by character offset. A single-token box still falls
    back to nearest-column-by-centre rather than being dropped.
    """
    def col_at(x: float) -> str | None:
        for k, (x0, x1) in columns.items():
            if x0 <= x <= x1:
                return k
        return None

    text = b.text or ""
    width = max(1.0, b.x1 - b.x0)

    # Does the box straddle a column boundary? Checked BEFORE the centre rule:
    # a merged '9:00Am6:00pm' has its centre inside one of the two columns it
    # spans, so a centre-first test would hand both values to that one column
    # and leave the other empty -- which is what emptied the TIME OUT column.
    spanned = [k for k, (x0, x1) in columns.items()
               if min(b.x1, x1) - max(b.x0, x0) > 0.25 * (x1 - x0)]
    toks = _sub_tokens(text) if len(spanned) > 1 else []
    if len(toks) > 1 and text:
        placed: dict[str, list[str]] = {}
        for start, end, tok in toks:
            mid_frac = (start + end) / 2 / len(text)
            k = col_at(b.x0 + mid_frac * width)
            if k:
                placed.setdefault(k, []).append(tok)
        if len(placed) > 1:
            return [(k, " ".join(v), b.conf) for k, v in placed.items()]

    hits = [k for k, (x0, x1) in columns.items() if x0 <= b.cx <= x1]
    if hits:
        return [(hits[0], b.text, b.conf)]

    # Single token in a gap: give it to the nearest column instead of losing it.
    if columns:
        k = min(columns, key=lambda c: min(abs(b.cx - columns[c][0]),
                                           abs(b.cx - columns[c][1])))
        x0, x1 = columns[k]
        if min(abs(b.cx - x0), abs(b.cx - x1)) <= 0.6 * (x1 - x0):
            return [(k, b.text, b.conf)]
    return []


def infer_missing_columns(cols: dict[str, tuple[float, float]],
                          min_gap: float = 18.0) -> dict[str, tuple[float, float]]:
    """Fill in a column whose printed header was unreadable.

    A column is only learned if its header matched. That is fragile in exactly
    the wrong place: on a real page the "TIME OUT" header came back from OCR as
    'TME UT', which scores 42 against the pattern (threshold 80), so the column
    was never learned -- and every "6:00 PM" in the grid then fell into the
    dead space between in_time and normal_hours and was silently dropped. The
    whole TIME OUT column was blank in the output while the values sat plainly
    in the OCR. Measured: out_time is missing on 10% of pages, in_time on 6%.

    But the column ORDER is a property of the printed form, not of the ink. If
    the neighbours either side were found, the missing column is the gap
    between them. Same argument as the row ladder: reconstruct from the form's
    known geometry rather than discard.

    Guarded two ways, because some layouts genuinely omit a column (a form with
    no in/out pair must not have one invented):
      - the gap must be wide enough to hold a value
      - the gap must be a plausible column width next to the ones we did read
    """
    known = dict(cols)
    if len(known) < 2:
        return cols
    widths = [x1 - x0 for x0, x1 in known.values()]
    widths.sort()
    median_w = widths[len(widths) // 2]

    order = list(COLUMN_ORDER)
    i = 0
    while i < len(order):
        if order[i] in known:
            i += 1
            continue
        # A run of consecutive missing columns shares one gap between them.
        j = i
        while j < len(order) and order[j] not in known:
            j += 1
        left = next((order[k] for k in range(i - 1, -1, -1) if order[k] in known), None)
        right = next((order[k] for k in range(j, len(order)) if order[k] in known), None)
        if left and right:
            x0, x1 = known[left][1], known[right][0]
            span, count = x1 - x0, j - i
            if span >= min_gap * count:
                each = span / count
                # A gap far wider or narrower than a real column is not a
                # column -- it is the signature block, or nothing at all.
                if 0.35 * median_w <= each <= 2.5 * median_w:
                    # A missing column sits immediately right of its left
                    # neighbour at a normal width. Stretching it across the
                    # whole gap put an inferred TOTAL HOURS over the employee
                    # signature column on ADANI forms, and the scribbles
                    # became hours (D-040). Cap at 1.2x the median width.
                    if INFER_COL_CAP_WIDTH:
                        each = min(each, 1.2 * median_w)
                    for n, k in enumerate(order[i:j]):
                        cols[k] = (x0 + n * each, x0 + (n + 1) * each)
        i = j
    return cols


def extract_day_rows(boxes: list[TextBox], columns: dict[str, tuple[float, float]],
                     header_y: float,
                     footer_y: float | None = None,
                     bands: list[int] | None = None,
                     raw_rules: list[int] | None = None,
                     handwritten: bool = False) -> list[dict[str, Any]]:
    """Reconstruct the day grid from boxes below the column headers.

    Rows come from `bands` (boundaries derived from the form's printed rules by
    rule_bands) when the caller supplies them, and from vertical clustering of
    the ink otherwise. Each box is then assigned to whichever learned column
    its horizontal centre falls in.
    """
    from .ocr_engine import cluster_rows

    # The day grid is bounded BELOW by the summary block. Without this bound
    # the summary rows ("P (Total Present Days)", "Total Man Hours", ...) are
    # clustered as day rows: measured 37 "day" rows on a 30-day page, which
    # pushed it past the sequential-assignment ceiling so the page fell back to
    # unreliable dates and recovered only 16 days.
    body = [b for b in boxes if b.cy > header_y
            and (footer_y is None or b.cy < footer_y)]

    # Cluster using the grid's ROW PITCH, not box height.
    #
    # cluster_rows defaults to a tolerance derived from median box height. On
    # handwritten pages the writing is tall relative to the row spacing, so
    # that tolerance merges adjacent rows: measured 12 clusters recovered from
    # a 29-row grid, which alone accounted for ~30% of all day-status errors.
    #
    # The grid spans a known vertical range and holds ~28-31 rows, so the pitch
    # is (span / expected_rows). That is a property of the printed form rather
    # than of the ink, so it does not degrade with messy handwriting.
    if bands:
        # The bands already carry the grid's top and bottom, so re-bound the
        # body to them; anything outside is header or summary text.
        body = [b for b in boxes if bands[0] <= b.cy <= bands[-1]]
        # A band that holds TWO date cells is one band too few. rule_bands
        # fits a regular ladder to the printed rules and, when the fitted
        # pitch drifts from the real one (Siemens sheet: fitted 32px, real
        # 27.5px), a ladder step swallows two rows -- 30 rows for 31 dates,
        # the anchors split 25-to-5 on offset, and every day after the merge
        # is numbered one low. A printed rule lying between two dates is a
        # row boundary whatever the ladder says: insert it and re-bucket.
        # Flag SPLIT_TWO_DATE_BANDS (D-038).
        # Print only: on ink the date parser's junk still slips a gate now
        # and then (IOCLMS p10 lost a row). A typed sheet is where merged
        # bands actually occur.
        if SPLIT_TWO_DATE_BANDS and raw_rules and not handwritten:
            dcol = columns.get("date")
            if dcol:
                date_cells = sorted((b for b in body
                                     if dcol[0] <= b.cx <= dcol[1]
                                     and _date_components(str(b.text))),
                                    key=lambda b: b.cy)
                from bisect import bisect_right as _br
                # Evidence gates, because on handwriting the date parser
                # reads ink fragments as "dates" and a permissive split
                # over-segmented the grid (guard 856 -> 809). Print passes
                # all three; ink fails at least one: the two cells must
                # parse to CONSECUTIVE day numbers, both read at >= 0.85,
                # and a real printed rule must lie between them. No
                # midpoint fallback.
                dp = infer_day_position([str(b.text) for b in date_cells])
                extra = []
                for a, c in zip(date_cells, date_cells[1:]):
                    ia, ic = _br(bands, a.cy) - 1, _br(bands, c.cy) - 1
                    if ia != ic:
                        continue
                    da = normalise_day({"date": str(a.text)}, dp)
                    dc = normalise_day({"date": str(c.text)}, dp)
                    if da is None or dc is None or dc != da + 1:
                        continue
                    if min(float(getattr(a, "conf", 0)), float(getattr(c, "conf", 0))) < 0.85:
                        continue
                    between = [r for r in raw_rules if a.cy < r < c.cy]
                    if between:
                        extra.append(between[0])
                if extra:
                    bands = sorted(set(bands) | set(extra))
        rows = rows_from_bands(body, bands)
        keep_empty = True
    else:
        rows = cluster_rows(body, tol_frac=0.6)
        keep_empty = False
        if body and len(rows) < 24:
            span = max(b.cy for b in body) - min(b.cy for b in body)
            if span > 0:
                pitch = span / 29.0      # ~30 day rows per month grid
                rows = cluster_by_pitch(body, pitch)

    # NOTE: split_merged_rows() was built to fix cumulative day-shift from
    # two physical rows landing in one cluster, and MEASURED: day accuracy
    # 60.2% -> 57.3% at the 20-page mark. It only recovered 27 -> 29 rows and
    # did NOT fix the alignment it targeted (the Sunday stayed on day 3
    # instead of day 5). Kept in the file, unused, pending a better row-
    # boundary signal than "two time tokens far apart".

    out: list[dict[str, Any]] = []
    for r in rows:
        rec: dict[str, Any] = {}
        confs: dict[str, float] = {}
        for b in r:
            for fieldname, text, conf in _assign_box(b, columns):
                prev = rec.get(fieldname)
                rec[fieldname] = f"{prev} {text}".strip() if prev else text
                confs[fieldname] = min(confs.get(fieldname, 1.0), conf)
        # Keep the WHOLE row's text, including boxes that fell between the
        # learned column ranges. Annotations like "SUNDAY" or "ABSENT" are
        # written ACROSS the row, so their box centre often lands in a gap
        # between columns and the text was being discarded entirely --
        # measured as the top status error (W->P, 11 occurrences).
        rec["_row_text"] = " ".join(b.text for b in r)
        # When rows came from printed rules, an empty band is a genuine blank
        # row and MUST be kept as a placeholder. Dropping it is exactly the
        # bug that shifts every later day by one. It carries no status, so it
        # costs nothing but its position -- which is the whole point.
        if keep_empty:
            rec["_conf"] = confs
            if not r:
                rec["_blank"] = True
            out.append(rec)
            continue
        if not any(k for k in rec if not k.startswith("_")):
            continue
        # A day row must carry SOMETHING in a data column.
        #
        # We deliberately no longer require a readable DATE. Rows whose
        # handwritten date was illegible still have perfectly good in/out and
        # hours cells, and discarding them was the single largest source of
        # error in the whole product: 35.1% of day-status comparisons failed
        # purely because the row had been dropped -- more than misreads and
        # empty statuses combined. The day number is recovered from row order
        # instead (see infer_days_by_position).
        if not any(str(rec.get(k) or "").strip()
                   for k in ("date", "in_time", "out_time", "normal_hours",
                             "total_hours", "remarks")):
            continue
        rec["_conf"] = confs
        out.append(rec)
    return out


DAY_RE = re.compile(r"^\s*(\d{1,2})")
_DATE_PARTS_RE = re.compile(r"(\d{1,4})")


def _date_components(text: str) -> list[int]:
    """Pull the numeric components out of whatever date format was used."""
    return [int(x) for x in _DATE_PARTS_RE.findall(str(text))[:3]]


def infer_day_position(date_texts: list[str]) -> int:
    """Work out WHICH numeric component of the date is the day-of-month.

    We cannot assume a format. Real pages in this corpus use at least:
        01.04.2026   DD.MM.YYYY   (ADANI)
        06/21/2026   MM/DD/YYYY   (SAFEARTH)
        0|4|26       DD|M|YY      (IOCL, handwritten)
    Guessing wrong silently collapses every row onto the same day -- which is
    exactly what happened before this function existed: all 30 SAFEARTH rows
    parsed as "day 6" because 06 is the month there.

    The robust signal is not the format, it's the *behaviour down the column*:
    the day component increments from row to row, while month and year stay
    constant (or change at most once, when a period straddles two months).
    So we pick the position with the most distinct values.
    """
    cols: dict[int, list[int]] = {0: [], 1: [], 2: []}
    for t in date_texts:
        parts = _date_components(t)
        for i in range(min(3, len(parts))):
            cols[i].append(parts[i])

    best_pos, best_distinct = 0, -1
    for pos, vals in cols.items():
        if len(vals) < 3:
            continue
        # A day component must be a plausible day and must vary a lot.
        plausible = [v for v in vals if 1 <= v <= 31]
        if len(plausible) < len(vals) * 0.7:
            continue
        distinct = len(set(vals))
        if distinct > best_distinct:
            best_pos, best_distinct = pos, distinct
    return best_pos



_TIME_TOK = re.compile(r"\d{1,2}\s*[:.]?\s*\d{2}")


def split_merged_rows(rows: list[list[TextBox]],
                      columns: dict[str, tuple[float, float]]
                      ) -> list[list[TextBox]]:
    """Split a cluster that actually contains TWO physical grid rows.

    Verified against the scan of IOCLMS APR 2026 p001: the cluster for "day 2"
    held in_time='8: 8:', out_time='19100 19', normal_hours='00 08' -- two rows'
    worth of ink in one band. Every such merge shifts EVERY LATER DAY by one,
    which is why the Sunday annotation landed on day 3 instead of day 5.

    A cluster is split when its time column holds two separate time tokens in
    two distinct boxes: we cut on the vertical midpoint between them.
    """
    out: list[list[TextBox]] = []
    for r in rows:
        tcol = columns.get("in_time") or columns.get("out_time")
        if not tcol or len(r) < 4:
            out.append(r)
            continue
        x0, x1 = tcol
        times = sorted([b for b in r if x0 <= b.cx <= x1
                        and _TIME_TOK.search(b.text)], key=lambda b: b.cy)
        if len(times) < 2:
            out.append(r)
            continue
        # Two time readings far enough apart vertically = two rows.
        gap = times[-1].cy - times[0].cy
        h = max(1.0, sum(b.y1 - b.y0 for b in r) / len(r))
        if gap < h * 0.55:
            out.append(r)
            continue
        cut = (times[0].cy + times[-1].cy) / 2.0
        top = [b for b in r if b.cy <= cut]
        bot = [b for b in r if b.cy > cut]
        if top and bot:
            out.append(sorted(top, key=lambda b: b.x0))
            out.append(sorted(bot, key=lambda b: b.x0))
        else:
            out.append(r)
    return out


def cluster_by_pitch(boxes: list[TextBox], pitch: float) -> list[list[TextBox]]:
    """Group boxes into rows using a fixed row pitch.

    Each box is assigned to the row band its centre falls in, where bands are
    `pitch` apart starting at the topmost box. Unlike gap-based clustering this
    cannot merge two rows just because their ink is tall -- the band boundaries
    come from the form's geometry, not from the writing.
    """
    if not boxes or pitch <= 0:
        return []
    top = min(b.cy for b in boxes)
    buckets: dict[int, list[TextBox]] = {}
    for b in boxes:
        idx = int((b.cy - top) / pitch + 0.5)
        buckets.setdefault(idx, []).append(b)
    rows = [buckets[k] for k in sorted(buckets)]
    for r in rows:
        r.sort(key=lambda b: b.x0)
    return rows


# Anchor-consensus bar (decision log D-010/D-011). Swept on the IOCL fast set:
# the surface is flat across ANCHOR_MIN_FRAC in 0.5..0.9 and across a
# step-by-one variant; the ONLY setting that leaves the handwritten guard at
# its baseline (853/934) is unanimity. Below 1.0 a handwritten page whose
# merged dates agree "almost" wins the vote with the wrong offset (IOCLMS MAY
# p3: -8). Unanimity makes the rule inert on ink and live on print, which is
# the intent. Whether 1.0 is too brittle for a typed sheet with ONE misread
# date is measured on the corpus-faithful set (frozen_v2), not assumed.
ANCHOR_MIN_FRAC = 0.5
ANCHOR_RIVAL_CAP = False
ANCHOR_AGREE = 0.7   # D-051: swept 1.0/0.9/0.8/0.7/0.6/0.5 -> v2 1282/1286/1286/1300/1291/1291, guard 876 down to 0.7, 867 at 0.6

# Bare SAT/SUN in a value cell => W (decision log D-013). Flag so it can be A/B'd.
WEEKDAY_WORD_OFF = True

# Summary values: nearest the label's line, not first in x (D-019). Flag for A/B.
SUMMARY_NEAREST_LINE = True

# Summary value candidates are bounded by the next field's label, not cut at it (D-037).
SUMMARY_BOUND_BY_NEXT_LABEL = True

# Comp-off through OCR damage (D-022). Flag for A/B.
COMPOFF_FUZZY = True

# Exact annotation words beat the fuzzy matcher when present (D-044).
EXACT_ANNOTATION_FIRST = True

# Learned date column extends left to the grid's left edge (D-038).
DATE_COL_TO_LEFT_EDGE = True

# Column headers learned only from the header band (D-038).
COLUMN_HEADERS_IN_BAND = False

# A band holding two date cells is split on the printed rule between them (D-038).
SPLIT_TWO_DATE_BANDS = True

# The rule at the footer bound belongs to the grid (D-044).
FOOTER_RULE_INCLUSIVE = True

# An inferred column is capped at 1.2x median width beside its left neighbour (D-040).
INFER_COL_CAP_WIDTH = True

# '2026' in an hours cell is a year, not hours (D-027).
YEAR_IS_NOT_HOURS = False

def infer_days_by_position(day_rows: list[dict[str, Any]],
                           day_pos: int = 0,
                           trust_anchors: bool = True) -> dict[int, int]:
    """Map row-index -> day-number, filling gaps from sequence.

    Strategy:
      1. Read whatever dates are legible; these are the anchors.
      2. Fit `day = row_index + offset` using the most common offset among the
         anchors. Day grids are strictly sequential, so one offset explains the
         whole page.
      3. Assign every row from that fit -- including rows whose date was
         unreadable, which is the whole point.

    Anchors that disagree with the majority offset are ignored rather than
    trusted, since a misread date ("13" for "18") should not drag the fit.

    Falls back to per-row parsing when there are too few anchors to fit
    confidently, so a genuinely irregular page degrades rather than gets
    fabricated numbers.
    """
    anchors: dict[int, int] = {}
    for i, r in enumerate(day_rows):
        d = normalise_day(r, day_pos)
        if d is not None and 1 <= d <= 31:
            anchors[i] = d

    # STRONGEST SIGNAL: if we recovered close to a full month of rows, the
    # grid is complete and strictly sequential, so row position IS the day.
    #
    # This beats reading the dates, because adjacent handwritten dates
    # frequently land in the same OCR row band and merge ('021426 01426'),
    # so several rows parse to the SAME day number and collapse into one.
    # Measured: 27 usable rows collapsed to 12 distinct days that way, which
    # was the largest single source of day-status error in the product.
    n = len(day_rows)

    # ANCHOR CONSENSUS comes first. The positional branch below was adopted on
    # handwritten IOCL grids, where adjacent dates merge into one OCR box and
    # 27 rows yield 14 scattered day numbers. On a TYPED sheet the opposite
    # holds: 30 rows carry 30 legible dates that all agree on one offset --
    # and the positional branch discarded them and numbered from a spurious
    # header band instead, sliding every status one row late (ADN900: 5:W read
    # as day 6). Measured across the frozen set, 43% of all day errors were
    # this one-row slide. When the ink is that unanimous, the ink is right.
    # A leading band with no date maps to day 0 and drops out on its own.
    if trust_anchors and len(anchors) >= max(12, ANCHOR_MIN_FRAC * n):
        offs = Counter(d - i for i, d in anchors.items())
        off, votes = offs.most_common(1)[0]
        # D-051: below unanimity, the dissenters must be NOISE (scattered
        # misreads, each with its own offset), not a second consistent run.
        # A 25-Apr..24-May sheet has 6 April dates on one offset and 24 May
        # dates on another; the May majority would push the April rows off
        # the calendar (s42: 6 rows lost, 6 silent). Row ordinals are right
        # there, and the positional branch below gives exactly that.
        rival = offs.most_common(2)[1][1] if len(offs) > 1 else 0
        # The majority offset must also keep EVERY row on the calendar: a
        # cross-month sheet's minority run is at the top and would be pushed
        # to day <= 0. (Variant with a rival-size cap instead measured v2
        # 1286 vs 1300 -- it also rejected the phantom-band pages this
        # branch exists for.)
        # Only ANCHORED rows count: a leading band with no date legitimately
        # maps to day 0 and drops out (measured: requiring every row on the
        # calendar collapsed the branch, guard 876 -> 868, v2 -> 1246).
        on_calendar = all(1 <= i + off <= 31 for i in anchors)
        rival_ok = (rival <= max(2, 0.1 * len(anchors))) if ANCHOR_RIVAL_CAP else True
        if votes >= ANCHOR_AGREE * len(anchors) and on_calendar and rival_ok:
            return {i: i + off for i in range(n) if 1 <= i + off <= 31}

    if 27 <= n <= 32:
        # Trust POSITION over the ink, deliberately.
        #
        # An earlier version cross-checked position against the parsed dates
        # and fell back when they disagreed. Measured, that check never passed:
        # the dates on a handwritten grid are so unreliable (adjacent rows'
        # dates merge into one OCR box) that 27 clean rows produced only 14
        # distinct day numbers -- scattered, e.g. [2, 8, 12, 13, 16, ...].
        #
        # When we have very nearly a full month of rows, the grid is complete
        # and strictly sequential, so row order is a far better estimator than
        # a misread date. We record that the numbering was positional so the
        # reviewer can see it was inferred rather than read.
        return {i: i + 1 for i in range(n)}

    if len(anchors) < 3:
        return dict(anchors)

    offsets = Counter(d - i for i, d in anchors.items())
    offset, votes = offsets.most_common(1)[0]

    # Require the offset to explain a clear majority of the anchors. If the
    # rows are not actually sequential (a merged or reordered grid), we must
    # not invent day numbers.
    if votes < max(3, len(anchors) * 0.6):
        return dict(anchors)

    out: dict[int, int] = {}
    for i in range(len(day_rows)):
        d = i + offset
        if 1 <= d <= 31:
            out[i] = d
    # A legible date that agrees with the fit stays; one that disagrees is
    # overridden by the fit, which is more reliable than a single OCR read.
    return out


def normalise_day(rec: dict[str, Any], day_pos: int = 0) -> int | None:
    parts = _date_components(rec.get("date", ""))
    if len(parts) > day_pos:
        v = parts[day_pos]
        if 1 <= v <= 31:
            return v
    m = DAY_RE.match(str(rec.get("date", "")))
    return int(m.group(1)) if m else None


def extract(boxes: list[TextBox], page_w: int, page_h: int,
            profile=None, handwritten: bool = False,
            row_rules: list[int] | None = None,
            ink_footer: bool = True,
            full_header_bound: bool = False,
            infer_columns: bool = True,
            reconcile_days: bool = True,
            source_hint: str | None = None,
            trust_anchors: bool = True) -> dict[str, Any]:
    """Extract using the anchor set for the detected form layout.

    Measured: 56% of pages previously produced nothing because their labels
    belong to a different layout entirely (Samsung, KBR). Selecting the anchor
    set per page is therefore worth more than any OCR or heuristic improvement.
    """
    from . import form_profiles

    if profile is None:
        profile, _score = form_profiles.detect(" ".join(b.text for b in boxes))

    _h, _s, _c = HEADER_ANCHORS, SUMMARY_ANCHORS, COLUMN_ANCHORS
    try:
        # The AARVI anchors stay as the module default so existing callers and
        # tests behave identically; a non-AARVI page swaps them for its own --
        # on THIS THREAD only (D-093).
        if profile.key != "aarvi":
            _LOCAL.header = profile.header_anchors + _h
            _LOCAL.summary = profile.summary_anchors + _s
            _LOCAL.column = {**_c, **profile.column_anchors}
        rec = _extract_inner(boxes, page_w, page_h, handwritten, row_rules,
                             ink_footer, full_header_bound, infer_columns,
                             reconcile_days, source_hint,
                         trust_anchors=trust_anchors)
        rec["_profile"] = profile.key

        # Layouts that pack several numbers into one cell ("30 | 21") need the
        # compound expanded, otherwise they yield no usable totals at all.
        if profile.split_fields:
            from .split_fields import apply_splits
            rec["summary"] = apply_splits(rec.get("summary") or {},
                                          profile.split_fields)

        # Layouts whose totals live in an unlabelled "Total" ROW (Samsung, KBR)
        # are read by intersecting that row with the learned column geometry.
        if profile.key in ("samsung", "kbr"):
            from .split_fields import totals_row_values
            cols = learn_columns(boxes, page_w)
            row = totals_row_values(boxes, ("TOTAL",), cols)
            summ = rec.get("summary") or {}
            mapping = {"normal_hours": "total_man_hours",
                       "ot_hours": "total_ot_hours",
                       "total_hours": "total_hours"}
            for src, dst in mapping.items():
                if row.get(src) and not summ.get(dst):
                    summ[dst] = row[src]
            rec["summary"] = summ
        return rec
    finally:
        _LOCAL.header = _LOCAL.summary = _LOCAL.column = None


def _extract_inner(boxes: list[TextBox], page_w: int, page_h: int,
                   handwritten: bool = False,
                   row_rules: list[int] | None = None,
                   ink_footer: bool = True,
                   full_header_bound: bool = False,
                   infer_columns: bool = True,
                   reconcile_days: bool = True,
                   source_hint: str | None = None,
                   trust_anchors: bool = True) -> dict[str, Any]:
    """Full AARVI-family extraction. Returns the record plus per-field
    confidence, so validation can distinguish 'read confidently but wrong'
    from 'barely read at all'."""
    header = extract_header(boxes, page_w, page_h, handwritten)

    # Some layouts (e.g. Samsung) print "NAME [CODE]" with no label at all.
    if not header["employee_name"].value or not header["employee_code"].value:
        bname, bcode = find_bracket_identity(boxes)
        if bname and not header["employee_name"].value:
            header["employee_name"] = Extracted(bname, 0.9, "bracket")
        if bcode and not header["employee_code"].value:
            header["employee_code"] = Extracted(bcode, 0.9, "bracket")
    summary = extract_summary(boxes, page_w, page_h)
    columns = learn_columns(boxes, page_w)
    if infer_columns:
        columns = infer_missing_columns(columns)

    date_anc = find_anchor(boxes, _column_anchors()["date"])
    header_y = date_anc.y1 if date_anc else page_h * 0.25
    if HEADER_FROM_DATES and date_anc is None:
        # D-050: no "Date" header found (Samsung prints "Date-Day"), so the
        # 25% fallback cut rows 1-5 May on s09 and the rest of the page was
        # renumbered from the wrong row. The grid starts where the date
        # column starts: the topmost date-like cell that is part of the
        # regular run (its neighbour below is within 1.5 pitch).
        _dl = sorted((b for b in boxes if b.cx < page_w * 0.30
                      and _DATE_LIKE_LOOSE.match(b.text or "")),
                     key=lambda b: b.cy)
        if len(_dl) >= 8:
            _ys = [b.cy for b in _dl]
            _gaps = sorted(g for g in (b - a for a, b in zip(_ys, _ys[1:])) if g > 2)
            _pitch = _gaps[len(_gaps) // 2] if _gaps else 0
            for _i in range(len(_dl) - 1):
                if _pitch and _ys[_i + 1] - _ys[_i] <= 1.5 * _pitch:
                    # Only RAISE the bound: the fallback is kept unless it
                    # would cut real date rows (measured: replacing it
                    # outright cost guard 876 -> 851, v2 1282 -> 1248).
                    if _dl[_i].y0 < header_y:
                        header_y = _dl[_i].y0 - 0.15 * _pitch
                    break
    if full_header_bound:
        # The grid starts below ALL the column headers, not just below "Date".
        # Using the date anchor alone leaves headers that sit a few pixels
        # lower inside the body, where they are clustered into row 1: observed
        # as day 1 carrying normal_hours='HOURS' and ot_hours='HOURS'.
        heads = [find_anchor(boxes, p) for p in _column_anchors().values()]
        ys = [a.y1 for a in heads if a is not None]
        if ys:
            header_y = max(ys)
    # NOTE: bounding the day grid below by summary_band_start() was tried and
    # MEASURED: 51.5% -> 50.4%. It DID fix the pages that over-ran (p001/p002
    # went from 27/28 to a full 30 rows), but it cut genuine rows on others,
    # and the loss outweighed the gain. The summary band start is not a
    # reliable grid boundary on every layout. Left unbounded.
    # The rule-derived bands DO need a lower bound, unlike the ink clusterer:
    # the printed rules continue into the summary block, so without it the
    # summary rows become extra "days". That same bound was measured on the ink
    # path and HURT it (51.5% -> 50.4%, see the note above), so it must apply
    # only when the bands are actually accepted -- not merely when rules were
    # detected. Deciding here rather than inside extract_day_rows keeps the two
    # paths from contaminating each other: an early version passed footer_y
    # whenever any rule was found, and on a page whose 8 rules were rejected
    # the bound alone cut the grid from 30 day rows to 1.
    summary_y = summary_band_start(boxes, page_h)
    # The BANDS bound is grid_bottom, not summary_band_start: the latter's
    # two-label-height pad truncated the ladder above days 29-31 on nearly
    # every page (57 of 83 missing-day comparisons were trailing). See the
    # measurement at grid_bottom().
    _gb = grid_bottom(boxes, page_h)
    if _gb is None and GRID_BOTTOM_FROM_DATES and summary_y == page_h * 0.65:
        # No summary label on this page: the 65% fallback is not a grid
        # edge. Bound by the date column itself (D-046).
        _gb = date_column_bottom(boxes, page_w, page_h)
    if DATE_BOTTOM_CAPS_GRID:
        # D-051: the grid cannot extend more than a pitch below its last date
        # row. Samsung (s09) puts "Total Leave" 340 px below the last date,
        # with the totals block's own rules in between: 34 rules for 31 rows
        # -> over-dense -> a 38 px ladder over a 26 px grid -> every row
        # misassigned. Cap the bound at the date column's bottom.
        # Only when the rules between the bounds are OVER-DENSE (more than
        # 31 bands): capping every page cost guard 876 -> 864 (handwritten
        # last dates unreadable -> the cap cut real rows). The over-dense
        # page is going to a forced ladder anyway; the cap gives it its
        # real edge instead.
        _db = date_column_bottom(boxes, page_w, page_h)
        _hi = _gb if _gb is not None else summary_y
        _n_in = len([r for r in (row_rules or []) if header_y < r <= _hi])
        if _db is not None and _db < _hi and _n_in - 1 > 31:
            _gb = _db
    # What the page says it holds: the date column's regular run when it is
    # nearly complete, else the calendar month (D-047).
    _expected = None
    _dl = sorted((b for b in boxes if b.cx < page_w * 0.30 and b.cy > header_y
                  and _DATE_LIKE_LOOSE.match(b.text or "")), key=lambda b: b.cy)
    if EXPECT_FROM == "dates_first" and len(_dl) >= 26:
        _expected = len(_dl)
    else:
        try:
            from .reconcile import parse_period
            _pp = parse_period(header["month_year"].value)
            if _pp:
                import calendar as _cal
                _expected = _cal.monthrange(*_pp)[1]
        except Exception:                                       # noqa: BLE001
            _expected = None
        if _expected is None and len(_dl) >= 28:
            _expected = len(_dl)
    bands = rule_bands(row_rules or [], header_y, _gb or summary_y,
                       expected_rows=_expected)
    # `ink_footer` applies that same bound to the CLUSTERING path. It measured
    # worse once (51.5% -> 50.4%) and is off by default; it is a keyword rather
    # than a deleted branch so it can be re-measured now that the code around
    # it has changed, without editing the module between runs.
    day_rows = extract_day_rows(
        boxes, columns, header_y,
        footer_y=(summary_y if (ink_footer and not bands) else None),
        bands=bands, raw_rules=(row_rules or []), handwritten=handwritten)

    # Learn the date layout from the column as a whole before parsing any row.
    day_pos = infer_day_position([str(r.get("date", "")) for r in day_rows])

    # Recover day numbers for rows whose DATE could not be read.
    #
    # Measured: 35.1% of all day-status comparisons failed simply because the
    # row was dropped -- more than misreads and empty statuses combined. Rows
    # were discarded whenever the handwritten date was illegible, even though
    # every other cell on that row (in/out, hours) had been read fine.
    #
    # Day rows are strictly sequential, so a row's position in the grid tells
    # us its day even when the ink does not. We anchor on the rows we DID read
    # and interpolate the rest.
    day_numbers = infer_days_by_position(day_rows, day_pos,
                                         trust_anchors=trust_anchors)

    days = []
    for idx, r in enumerate(day_rows):
        day = day_numbers.get(idx)
        if day is None or not (1 <= day <= 31):
            continue
        days.append({
            "day": day,
            "in_time": r.get("in_time"),
            "out_time": r.get("out_time"),
            "normal_hours": r.get("normal_hours"),
            "ot_hours": r.get("ot_hours"),
            "total_hours": r.get("total_hours"),
            "remarks": r.get("remarks"),
            "status": _infer_status(r),
            "_conf": r.get("_conf", {}),
            # A bare weekday word in a value cell names its own day. Carried
            # so reconcile can snap the row to the calendar (GRSE01 prints
            # "SAT" one row below its Saturday; decision log D-022/D-025).
            "_weekday_word": _weekday_word(r),
        })

    rec_out = {
        "employee_name": _clean_name(header["employee_name"].value),
        "employee_code": header["employee_code"].value,
        "designation": header["designation"].value,
        "project": header["project"].value,
        "client": header["client"].value,
        "location": header["location"].value,
        "period_label": header["month_year"].value,
        "days": days,
        "summary": {k: v.value for k, v in summary.items()},
        "_confidence": {
            **{k: v.conf for k, v in header.items()},
            **{k: v.conf for k, v in summary.items()},
        },
        "_columns_found": sorted(columns),
        "_anchors_found": sorted(k for k, v in {**header, **summary}.items()
                                 if v.source == "anchor"),
    }

    # Last step: let the page repair itself from its own stated totals and the
    # calendar. Costs nothing, reads no pixels, and only fills rows we failed
    # to read at all -- see app/reconcile.py.
    if reconcile_days:
        from .reconcile import reconcile
        # The file's own name/folder is the last-resort period signal, used
        # only when the page itself yields no readable month. Carried on the
        # record so reconcile stays a pure record-in/record-out function.
        if source_hint:
            rec_out["_source_hint"] = source_hint
        rec_out = reconcile(rec_out)
    return rec_out


# Word-boundary anchored. The previous patterns were unanchored, and two of
# them matched inside ordinary words:
#     H\.?O   matched "HO" inside "HOURS"   -> every "8:00 HOURS" row became H/W
#     W/?O    matched "WO" inside "WORKING"
# That single bug produced the symmetric P->W / W->P confusion that was the
# largest remaining source of day-status error (17 of 211 comparisons).
_ABSENT_RE = re.compile(r"\b(ABSENT|ABSANT|ABSENJ|A\.?B\.?)\b", re.I)
_LEAVE_RE = re.compile(r"\b(LEAVE|LEAVES|C\.?L|S\.?L|P\.?L)\b", re.I)
_HOLIDAY_RE = re.compile(r"\b(HOLIDAY|HOLI\s*DAY|PUBLIC\s*HOLIDAY|P\.?H\.?)\b", re.I)
_WEEKOFF_RE = re.compile(
    r"\b(SUNDAY|SUNDAY?S|WEEK\s*OFF|WEEKLY\s*OFF|W\s*/\s*O|WO)\b", re.I)
_COMPOFF_RE = re.compile(r"\b(C\s*/\s*O|COMP\s*OFF|COMPENSATORY)\b", re.I)



# Annotation words as OCR usually mangles them. Matched fuzzily because the
# exact spellings are rarely what comes back.
LONE_LETTER_STATUS = True

_ANNOT_WORDS = (
    ("SUNDAY", "W"), ("WEEKOFF", "W"), ("WEEKLYOFF", "W"),
    ("HOLIDAY", "H"), ("ABSENT", "A"), ("LEAVE", "L"),
    # 'Sunday' as OCR actually returns it from these scans:
    #   SUNDOY  the u/n confusion pair ('Suudoy', 'Sundoy' -- scores 83 here
    #           vs 67 against the correct spelling, below the 82 threshold)
    #   HOPUNS  'Sunday' written UPSIDE-DOWN across the row, which OCR reads
    #           as the 180-degree flip: S,U,N,D,A,Y rotated and reversed is
    #           ~'HOPUNS'. Real reads 'bopuns' and 'hopins' both score 83
    #           against it. Found on rows the day-grid eval showed as W->P.
    ("SUNDOY", "W"), ("HOPUNS", "W"),
)


# The abbreviated forms supervisors actually write, tolerant of how OCR mangles
# them. Measured on a JSPL page: 'W/OFF' and 'C/OFF' were written on four rows
# and NONE were recognised -- not by the fuzzy word matcher (which folds to
# 'WFF' and then rejects anything under 5 characters) nor by _WEEKOFF_RE (whose
# \bWO\b cannot match inside 'w110ff'). Those rows were reported as worked days.
#
# The middle character class absorbs the usual substitutions for '/': OCR reads
# the stroke as 1, l, |, - or nothing at all, and reads O as 0.
_SHORT_OFF_RE = re.compile(r"\b([WC])\s*[/\\\-1lI|_]{0,3}\s*[O0]\s*F\s*F?\b", re.I)
_SHORT_PH_RE = re.compile(r"\b[PB]\s*[/.\-]?\s*H\b", re.I)


def _short_annotation(text: str) -> str | None:
    """Match the abbreviated non-working markers: W/OFF, C/OFF, P.H."""
    t = str(text or "")
    m = _SHORT_OFF_RE.search(t)
    if m:
        return "W" if m.group(1).upper() == "W" else "C"
    if _SHORT_PH_RE.search(t):
        return "H"
    return None


def _fuzzy_annotation(text: str) -> str | None:
    """Match a mangled annotation word to its status code."""
    t = re.sub(r"[^A-Z]", "", str(text or "").upper())
    if len(t) < 5:
        return None
    for word, code in _ANNOT_WORDS:
        n = len(word)
        # Slide over the string AND vary the window length.
        #
        # A fixed window drags in neighbouring letters and sinks the score.
        # Measured: the row text stripped to 'SINDAYMU' (the date cell read as
        # 'mu126'), and a fixed n+1 window scored 'SINDAYM' vs 'SUNDAY' below
        # threshold -- so a clearly-marked Sunday was reported as a worked day.
        for size in (n - 1, n, n + 1):
            if size < 4:
                continue
            for i in range(0, max(1, len(t) - size + 1)):
                window = t[i:i + size]
                if len(window) < size:
                    break
                if fuzz.ratio(window, word) >= ANNOT_FUZZ_THRESHOLD:
                    return code
    return None


def _positive_hours(v: Any) -> bool:
    """True only for a genuinely worked amount.

    The old check accepted any digit, so a row reading "0" counted as present.
    """
    if v is None:
        return False
    s = str(v).strip()
    if not s:
        return False
    # A YEAR is not hours. On ADANI02 the comp-off annotation's date fragment
    # ('2026') lands in the hours cell and was read as 2,026 worked hours,
    # which made a comp-off row Present. Any 4-digit value in 1900..2100
    # with no separator is a year, whatever cell it sits in (D-027).
    if YEAR_IS_NOT_HOURS and re.fullmatch(r"\s*(19|20)\d{2}\s*", s):
        return False
    m = re.search(r"\d+(?:[.:]\d+)?", s.replace(",", ""))
    if not m:
        return False
    txt = m.group(0)
    try:
        val = float(txt.replace(":", "."))
    except ValueError:
        return False
    return val > 0


_WEEKDAY_WORDS = {"MON": 0, "MONDAY": 0, "TUE": 1, "TUES": 1, "TUESDAY": 1,
                  "WED": 2, "WEDNESDAY": 2, "THU": 3, "THUR": 3, "THURS": 3,
                  "THURSDAY": 3, "FRI": 4, "FRIDAY": 4, "SAT": 5,
                  "SATURDAY": 5, "SUN": 6, "SUNDAY": 6}


def _weekday_word(rec: dict[str, Any]) -> int | None:
    """0..6 if a VALUE cell holds a bare weekday word, else None.

    Value cells only -- never the date cell, which on some forms carries the
    weekday beside every date.
    """
    for k in ("in_time", "out_time", "normal_hours", "total_hours",
              "ot_hours", "remarks"):
        v = re.sub(r"[^A-Z]", "", str(rec.get(k) or "").upper())
        if v in _WEEKDAY_WORDS:
            return _WEEKDAY_WORDS[v]
    return None


STATUS_COLUMN = False  # D-098: see decision log before re-enabling
_STATUS_LETTERS = {"P": "P", "A": "A", "L": "L", "H": "H", "C": "C",
                   "W": "W", "S": "W", "O": "W"}
WORKED_BEATS_CALENDAR_REMARK = False  # D-097: MEASURED WORSE (93.8 -> 92.9). OFF.
_CALENDAR_WORD = re.compile(r"\b(weekend|week\s*off|weekly\s*off|holiday|"
                            r"sunday|saturday|w\s*/\s*o)\b", re.I)
_PERSON_WORD = re.compile(r"\b(leave|absent|sick|casual|comp\s*off|c\s*/\s*o)\b", re.I)
_CLOCK_PAIR = re.compile(r"\d{1,2}\s*[:.]\s*\d{2}")


def _has_clock_pair(rec: dict) -> bool:
    """True when the row records BOTH an in-time and an out-time.

    Deliberately strict: a single stray time is noise, two are a shift.
    """
    return bool(_CLOCK_PAIR.search(str(rec.get("in_time") or ""))
                and _CLOCK_PAIR.search(str(rec.get("out_time") or "")))


def _infer_status(rec: dict[str, Any]) -> str | None:
    """Derive P/A/L/W/H from what the row actually contains.

    The AARVI form has no status column -- presence is implied by whether the
    row carries hours, and non-working days are annotated across the row or in
    Remarks. Order matters: an explicit annotation always beats an inference
    from hours, because a row can carry both (e.g. "SUNDAY" written across a
    row that still shows a shift).
    """
    # D-097. A calendar remark describes the DAY; recorded clock times
    # describe what HAPPENED. On the ERP exports a Remark column reads
    # "Weekend" or "Holiday" on every Saturday, Sunday and public holiday,
    # including the ones the person actually worked -- the row carries
    # 7:29 AM, 5:35 PM and 10:06 total hours beside the word. Hand-graded:
    # 26 of 31 on one such page, with every error a worked day reported as
    # W or H.
    #
    # Only WEEKEND and HOLIDAY words are overridden, and only when the row
    # carries a real in-time AND out-time. LEAVE and ABSENT are untouched:
    # those describe the person, not the calendar, and a leave row with
    # stray times should stay leave.
    if WORKED_BEATS_CALENDAR_REMARK and _has_clock_pair(rec):
        _cal = " ".join(str(rec.get(k) or "") for k in ("remarks", "date"))
        if _CALENDAR_WORD.search(_cal) and not _PERSON_WORD.search(_cal):
            return "P"

    # D-098. A layout with a NAMED status column has already answered the
    # question this function otherwise infers. Read it rather than deduce it.
    # Only a bare single letter is taken -- anything longer is an annotation
    # and goes through the normal path below, which already handles
    # "WEEK OFF" and the rest.
    if STATUS_COLUMN and rec.get("status"):
        _v = re.sub(r"[^A-Za-z]", "", str(rec.get("status"))).upper()
        if len(_v) == 1 and _v in _STATUS_LETTERS:
            return _STATUS_LETTERS[_v]

    annotation = " ".join(str(rec.get(k) or "") for k in
                          ("remarks", "date", "in_time", "out_time",
                           "normal_hours", "total_hours"))
    # NOTE: including the whole row's text here (_row_text, including boxes
    # that fell between column ranges) was tried and MEASURED: 55.1% -> 53.3%.
    # It caught the intended "SUNDAY" annotations but also pulled in text from
    # adjacent rows, producing more false annotations than it fixed.

    # Fuzzy weekday check first: OCR mangles these constantly ("Sinday",
    # "Sumday", "Sundoy"), and an exact regex misses every variant. Measured
    # on a real page: 'Sinday' fell through to the hours check and the day was
    # reported as worked.
    # An annotation word that is PRESENT beats a fuzzy guess at a mangled
    # one. "Full day paid leave" contains LEAVE; the sliding-window matcher
    # ran first and answered W (the one silent wrong row in the manual
    # verification, mv03 day 19). Exact first, fuzzy for ink. Flag
    # EXACT_ANNOTATION_FIRST (D-044).
    if EXACT_ANNOTATION_FIRST:
        if _ABSENT_RE.search(annotation):
            return "A"
        if _HOLIDAY_RE.search(annotation):
            return "H"
        if _COMPOFF_RE.search(annotation):
            return "C"
        if _LEAVE_RE.search(annotation):
            return "L"
        if _WEEKOFF_RE.search(annotation):
            return "W"
    if _fuzzy_annotation(annotation):
        return _fuzzy_annotation(annotation)

    # Abbreviated markers ('W/OFF', 'C/OFF', 'P.H.'). Checked before the hours
    # inference below, because these are frequently written INTO the hours
    # column rather than Remarks -- so the row looks like it carries a value.
    short = _short_annotation(annotation)
    if short:
        return short

    # Comp-off, read through OCR damage. On ADANI02 the annotation is
    # "C/O against duty on 30/03/2026, 04/04/2026" written across the time
    # columns, and the regex above matched 3 of 23 such rows: OCR returns
    # 'C/0', 'COff Agaunst', 'CO)f', 'C. Off' -- or splits the phrase so the
    # row's cells hold only the referenced dates ('15.03. 2026', '24.03.
    # 2026'). Two signals, either sufficient, both gated on no positive
    # hours: a comp-off HEAD in any value cell, or >= 2 calendar dates across
    # the value cells with no clock reading (a worked day carries in/out; a
    # comp-off row carries the dates it was earned on). Flag COMPOFF_FUZZY.
    # Gate on NO CLOCK READING, not on no positive hours: _positive_hours
    # reads '15.03. 2026' as fifteen hours, so the hours gate blocked this
    # rule on precisely the rows it exists for, and the fall-through then
    # inferred P from the same "hours". A date is not hours. A worked day
    # carries a clock time; a comp-off row never does.
    _joined0 = " ".join(str(rec.get(k) or "") for k in
                        ("in_time", "out_time", "normal_hours",
                         "total_hours", "ot_hours", "remarks"))
    _has_clock0 = re.search(
        r"\b\d{1,2}\s*[:]\s*\d{2}\b|\b\d{1,2}\s*[.]\s*\d{2}\b(?!\s*[./-]?\s*20\d{2})",
        _joined0)
    if COMPOFF_FUZZY and not _has_clock0:
        cells = [str(rec.get(k) or "") for k in
                 ("in_time", "out_time", "normal_hours", "total_hours",
                  "ot_hours", "remarks")]
        joined = " ".join(cells)
        for c in cells:
            t = re.sub(r"[^A-Z0-9]", "", c.upper())
            if re.match(r"^C[O0](FF?)?[O0]?F?(AGA|AGU|GAU|F)", t) or \
                    re.match(r"^C[O0]FF", t):
                return "C"
        n_dates = len(re.findall(r"\b\d{1,2}\s*[./-]\s*\d{1,2}\s*[./-]\s*20\d{2}\b", joined))
        has_clock = re.search(r"\b\d{1,2}\s*[:.]\s*\d{2}\b(?!\s*[./-]\s*20\d{2})", joined)
        if n_dates >= 2 and not has_clock:
            return "C"

    # Explicit annotations first, most specific first.
    if _ABSENT_RE.search(annotation):
        return "A"
    if _HOLIDAY_RE.search(annotation):
        return "H"
    if _COMPOFF_RE.search(annotation):
        return "C"
    if _LEAVE_RE.search(annotation):
        return "L"
    if _WEEKOFF_RE.search(annotation):
        return "W"

    # A lone status letter filling an ENTIRE cell is the status, wherever the
    # column assignment happened to drop it -- but ONLY on a row with no work
    # evidence. Measured both ways: day 13 read 'A' at 0.998 confidence into
    # out_time on an otherwise-empty row (a real absence, previously scored
    # unread); while rows carrying '08:00-17:00' shifts also carry stray
    # letters ('A' from a clipped AM, 'h' from HRS) in the hours columns, and
    # treating those as statuses flipped three worked days to A/H. A full
    # shift outweighs a stray letter; a bare letter on a blank row IS the row.
    if LONE_LETTER_STATUS and not any(
            _positive_hours(rec.get(k)) for k in
            ("in_time", "out_time", "normal_hours", "total_hours")):
        for k in ("in_time", "out_time", "normal_hours", "total_hours",
                  "ot_hours", "remarks"):
            v = str(rec.get(k) or "").strip().upper().strip(".· ")
            if v in ("A", "P", "W", "L", "C", "H"):
                return v

    # A bare weekday word filling a VALUE cell is a weekly off. GRSE01 prints
    # "SAT" / "SUN" as a merged cell across the time columns, exactly where a
    # clock reading would sit; _WEEKOFF_RE matches "SUNDAY" and "W/O" but not
    # the bare abbreviation, so five weekly-off rows per page came out None.
    # Only VALUE fields are checked -- never the date field, because other
    # forms (Avaada01) print the weekday beside the date on every row, and a
    # worked Sunday there must stay P. Gated on no positive hours, like the
    # lone-letter rule above.
    if WEEKDAY_WORD_OFF and not any(
            _positive_hours(rec.get(k)) for k in
            ("in_time", "out_time", "normal_hours", "total_hours")):
        for k in ("in_time", "out_time", "normal_hours", "total_hours",
                  "ot_hours", "remarks"):
            v = re.sub(r"[^A-Z]", "", str(rec.get(k) or "").upper())
            if v in ("SAT", "SUN", "SATURDAY", "SUNDAY", "WO", "WOFF"):
                return "W"

    # D-048: a row whose hours cell is an EXPLICIT zero, with no clock reading
    # and no annotation, on a date the form itself labels Sat/Sun ("11-Jul
    # (Sat)" -- Samsung prints the weekday beside every date) is a weekly
    # off. s08/s09 (50-page sample): 7 and 7 such shaded rows per page came
    # out EMPTY (flagged), and the blank-Sunday rule could not help because
    # the "0" is ink. Only the date cell's OWN weekday is consulted, only
    # with a literal zero, only with no clock -- a worked Sunday keeps P.
    if ZERO_HOURS_WEEKEND_IS_OFF:
        _hrs = str(rec.get("normal_hours") or "").strip()
        _tot = str(rec.get("total_hours") or "").strip()
        _zero = (re.fullmatch(r"0+(?:[.:]0+)?", _hrs) is not None
                 and (not _tot or re.fullmatch(r"0+(?:[.:]0+)?", _tot)))
        _noclock = not any(_positive_hours(rec.get(k))
                           for k in ("in_time", "out_time"))
        if _zero and _noclock and re.search(
                r"\b(SAT|SUN)(?:URDAY|DAY)?\b", str(rec.get("date") or ""), re.I):
            return "W"

    # Otherwise infer from whether any work was recorded.
    if _positive_hours(rec.get("normal_hours")) or \
            _positive_hours(rec.get("total_hours")):
        return "P"
    # EITHER clock reading is enough. Requiring both cost real rows: on
    # handwritten grids one of the two times is frequently unreadable while
    # the other is perfectly clear, and such a row is unambiguously a worked
    # day -- nobody writes a clock time on a day off. Measured: status_empty
    # was 11.4% of all day comparisons.
    if _positive_hours(rec.get("in_time")) or \
            _positive_hours(rec.get("out_time")):
        return "P"
    return None

"""Validation engine.

This is the product. The extractor is unreliable and always will be -- open
handwriting OCR does not reach the accuracy this account needs. What makes the
system trustworthy is that a timesheet is *self-validating*: the day rows carry
an arithmetic relationship to the stated monthly summary, the day count is
fixed by the period, and the identity fields must exist in a known roster.

So we never claim to know a field is right. We claim to know when something is
wrong -- and that claim is defensible at ~100% for the arithmetically
inconsistent class, which is the class that freezes invoices.

Two design points that are load-bearing and easy to get wrong:

1.  The stated summary must be read in a pass that never saw the day grid
    (see config.INDEPENDENT_SUMMARY_PASS). If one pass produces both, the model
    tends to derive the total from the rows it just wrote, the checksum agrees
    with itself, and the whole validation premise silently collapses.

2.  Roster matching flags ambiguity instead of taking the nearest name. A
    confident match to the *wrong* employee is exactly the invoice-freezing
    error, so a near-tie between two candidates is an issue, not a match.
"""
from __future__ import annotations

import calendar

from dataclasses import dataclass, asdict
from typing import Any, Iterable

from . import config
from .templates_spec import (
    STATUS_LEAVE,
    STATUS_NONWORKING,
    STATUS_PRESENT,
    STATUS_VALUES,
    TemplateSpec,
)

BLOCK = "block"   # cannot export until resolved
WARN = "warn"     # surface for review, exportable


@dataclass
class Issue:
    code: str
    severity: str
    message: str
    field: str | None = None      # dotted path, e.g. "summary.total_ot_hours"
    day: int | None = None        # 1-based day number when row-scoped
    expected: Any = None
    found: Any = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _num(v: Any) -> float | None:
    """Tolerant numeric coercion. Handwriting OCR emits '8.0', '8', '8 ', '-',
    '' and None for the same cell; none of those should crash validation."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "--", "NA", "N/A", "nil", "NIL"):
        return None
    # '8:30' style durations occasionally appear in the hours columns
    if ":" in s:
        try:
            h, m = s.split(":", 1)
            return float(int(h) + int(m) / 60.0)
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _sum(values: Iterable[Any]) -> float:
    """Sum the PLAUSIBLE per-day hour values only.

    Summing raw reads lets one misread cell ('1120' where the ink says 11.20,
    '51181' from smeared digits) drive the total to nonsense -- a real page
    reported 'day rows sum to 162553.9 OT hours'. No single day can exceed 24
    hours, so anything above that is an OCR artefact, not evidence; it is
    excluded here and caught separately by the per-day bounds check, which
    flags the actual offending row instead of poisoning the page total.
    """
    return round(sum(v for v in (_num(x) for x in values)
                     if v is not None and 0 <= v <= 24), 4)


def _close(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= config.HOURS_TOLERANCE


def _close_sum(stated: float | None, computed: float | None) -> bool:
    """Comparison for MONTHLY sums of handwritten per-day cells.

    A fixed 0.01-hour tolerance is right for a single value but wrong for a
    sum of ~30 hand-read cells: at 216 stated hours it flags a 1.2-hour drift
    (0.6%) as a blocking error, which buries the real signal. Reading noise
    accumulates with the number of cells; the tolerance must scale with the
    quantity. 2% of the stated total still catches every genuine defect this
    corpus has shown (missing days, a 42-hour cell, transposed digits are all
    >>2%) without flagging sub-1% accumulation drift on every page.
    """
    if stated is None or computed is None:
        return False
    return abs(stated - computed) <= max(config.HOURS_TOLERANCE,
                                         config.SUM_TOLERANCE_FRACTION
                                         * abs(stated))


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------

def _check_day_sequence(days: list[dict], spec: TemplateSpec) -> list[Issue]:
    issues: list[Issue] = []
    nums = [ _num(d.get("day")) for d in days ]
    seen: dict[int, int] = {}
    for idx, n in enumerate(nums):
        if n is None:
            issues.append(Issue("day_unreadable", BLOCK,
                                f"Row {idx + 1}: the day number could not be read.",
                                field=f"days[{idx}].day"))
            continue
        i = int(n)
        if i in seen:
            issues.append(Issue("day_duplicate", BLOCK,
                                f"Day {i} appears twice (rows {seen[i] + 1} and "
                                f"{idx + 1}). One of them is wrong.",
                                day=i))
        seen[i] = idx

    # A short or long grid usually means a row was missed or the wrong template
    # was picked -- both are silent killers, so this blocks.
    if days and len(days) not in range(spec.period_days - 3, spec.period_days + 2):
        issues.append(Issue(
            "row_count_mismatch", BLOCK,
            f"Found {len(days)} day rows, but this sheet covers "
            f"{spec.period_days} days. A row was probably missed.",
            expected=spec.period_days, found=len(days)))
    return issues


def _check_day_bounds(days: list[dict], spec: TemplateSpec) -> list[Issue]:
    issues: list[Issue] = []
    for idx, d in enumerate(days):
        day_no = _num(d.get("day"))
        day_i = int(day_no) if day_no is not None else None

        status = (d.get("status") or "").strip().upper()
        if status and status not in STATUS_VALUES:
            issues.append(Issue("status_unknown", WARN,
                                f"Day {day_i}: '{status}' is not a known status. Use one of "
                                f"{', '.join(STATUS_VALUES)}.",
                                field=f"days[{idx}].status", day=day_i,
                                found=status))

        nh = _num(d.get("normal_hours"))
        # Two bounds, two severities. Above NORMAL_HOURS_MAX_PER_DAY (12) is
        # unusual and worth a look; above 24 is physically impossible and
        # must be fixed. A Haldia sheet writes the day's TOTAL hours (15:07)
        # in this column and every worked row was blocked, which buried the
        # two rows on that page that were actually wrong (D-039).
        if nh is not None and (nh < 0 or nh > 24):
            issues.append(Issue("normal_hours_impossible", BLOCK,
                                f"Day {day_i}: {nh} hours is not possible in one day.",
                                field=f"days[{idx}].normal_hours", day=day_i,
                                found=nh))
        elif nh is not None and nh > config.NORMAL_HOURS_MAX_PER_DAY:
            issues.append(Issue("normal_hours_out_of_band", WARN,
                                f"Day {day_i}: {nh} hours is more than the usual "
                                f"{config.NORMAL_HOURS_MAX_PER_DAY}. Please check.",
                                field=f"days[{idx}].normal_hours", day=day_i,
                                found=nh))

        if spec.has_ot:
            ot = _num(d.get("ot_hours"))
            if ot is not None and (ot < 0 or ot > config.OT_HOURS_MAX_PER_DAY):
                issues.append(Issue("ot_out_of_band", BLOCK,
                                    f"Day {day_i}: {ot} overtime hours is more than the "
                                    f"allowed {config.OT_HOURS_MAX_PER_DAY}.",
                                    field=f"days[{idx}].ot_hours", day=day_i,
                                    found=ot))

        # A present day with zero hours, or a non-working day carrying hours,
        # is the classic misread-status / misread-hours pair.
        if status in STATUS_PRESENT and nh is not None and nh == 0:
            issues.append(Issue("present_but_zero_hours", WARN,
                                f"Day {day_i}: marked present but no hours are recorded.",
                                day=day_i))
        if status in STATUS_NONWORKING and nh:
            issues.append(Issue("nonworking_with_hours", WARN,
                                f"Day {day_i}: marked '{status}' (a day off) but has "
                                f"{nh} hours written against it.",
                                day=day_i, found=nh))
    return issues


UNCOMPUTABLE_IS_NOT_FAILED = True      # D-075


def _rows_carry_hours(days: list[dict]) -> bool:
    """True if ANY day row has an hours figure to add up."""
    for d in days:
        for k in ("normal_hours", "ot_hours", "total_hours"):
            if _num(d.get(k)) is not None:
                return True
    return False


def _check_row_sum_vs_summary(days: list[dict], summary: dict,
                              spec: TemplateSpec) -> list[Issue]:
    """The primary checksum. Only meaningful because the summary was read
    independently of the grid -- see module docstring.

    D-075. A check that could not be COMPUTED is not a check that FAILED, and
    the two must not produce the same severity. Measured on 150 corpus pages
    whose every day matched the client's own records and which were blocked
    anyway: 31 were blocked because we could not read the totals box, and 28
    because a stated total was compared against day rows carrying no hours at
    all -- a sum over a column that was never extracted. Nothing on those
    pages contradicted anything. They were blocked because the system failed
    to read something and then reported its own failure as the sheet's fault.

    That matters commercially, not just tidily: 3 pages in 303 passed clean,
    so a reviewer is handed everything and learns to click through -- which is
    how a page that genuinely IS wrong gets clicked through too.

    BLOCK is now reserved for "the numbers on this sheet disagree with each
    other". "We could not read it" is a WARN: the page still reaches a human,
    but as something to look at rather than something to fix.
    """
    issues: list[Issue] = []

    computed_normal = _sum(d.get("normal_hours") for d in days)
    stated_normal = _num(summary.get("total_normal_hours"))

    # No row on the sheet carries an hours figure -- this layout records
    # attendance only. Summing a column that does not exist yields 0, and
    # comparing a stated 170 against that 0 reports a 170-hour discrepancy
    # that exists nowhere but in the arithmetic.
    no_row_hours = UNCOMPUTABLE_IS_NOT_FAILED and not _rows_carry_hours(days)
    if no_row_hours:
        if stated_normal is not None or _num(summary.get("total_ot_hours")) is not None:
            issues.append(Issue(
                "hours_not_read_from_rows", WARN,
                "This sheet states a total number of hours, but no hours could be "
                "read from the individual day rows, so the two could not be "
                "checked against each other.",
                field="summary.total_normal_hours"))
        else:
            issues.append(Issue(
                "hours_not_verified", WARN,
                "The hours on this sheet could not be checked against a stated "
                "total, so the day rows have not been verified by arithmetic.",
                field="summary.total_normal_hours"))
        return issues

    if stated_normal is None:
        issues.append(Issue("summary_normal_missing",
                            WARN if UNCOMPUTABLE_IS_NOT_FAILED else BLOCK,
                            "The 'Total hours' box on the sheet is blank or unreadable, so "
                            "the day rows cannot be checked against it. Please fill it in.",
                            field="summary.total_normal_hours"))
    elif not _close_sum(stated_normal, computed_normal):
        issues.append(Issue(
            "normal_hours_sum_mismatch", BLOCK,
            f"The day rows add up to {computed_normal} hours, but the sheet says "
            f"{stated_normal} (a difference of {round(computed_normal - stated_normal, 2)}).",
            field="summary.total_normal_hours",
            expected=computed_normal, found=stated_normal))

    if spec.has_ot:
        computed_ot = _sum(d.get("ot_hours") for d in days)
        stated_ot = _num(summary.get("total_ot_hours"))
        # D-075. Checked against the paper: the Garden Reach layout has no
        # overtime box at all. Its totals block reads "Total Man Hours 153"
        # and, on the next line, "Total Hours 153" -- and the extractor maps
        # that second box to the overtime field, because on the standard AARVI
        # layout that row position IS the overtime total. The sheet is
        # perfectly consistent (18 worked days x 8:30 = 153); we invent the
        # overtime figure and then report the rows for disagreeing with it.
        #
        # The real repair belongs in the totals reader, which should match on
        # the printed label rather than the row position. Until it does, an
        # overtime total identical to the hours total, on a sheet where no row
        # records any overtime, is not a figure anyone wrote down.
        if (UNCOMPUTABLE_IS_NOT_FAILED and stated_ot is not None
                and stated_normal is not None and stated_ot == stated_normal
                and computed_ot == 0):
            issues.append(Issue(
                "ot_total_duplicates_hours_total", WARN,
                f"No separate overtime total could be read from this sheet — the "
                f"figure found ({stated_ot}) is the same as the total hours, and no "
                f"day row records any overtime. Overtime was therefore not checked.",
                field="summary.total_ot_hours"))
        elif stated_ot is None:
            issues.append(Issue("summary_ot_missing", WARN,
                                "The 'Total overtime' box on the sheet could not be read.",
                                field="summary.total_ot_hours"))
        elif not _close_sum(stated_ot, computed_ot):
            issues.append(Issue(
                "ot_sum_mismatch", BLOCK,
                f"The day rows add up to {computed_ot} overtime hours, but the sheet says "
                f"{stated_ot} (a difference of {round(computed_ot - stated_ot, 2)}).",
                field="summary.total_ot_hours",
                expected=computed_ot, found=stated_ot))
    return issues


def _check_day_count(days: list[dict], summary: dict,
                     spec: TemplateSpec) -> list[Issue]:
    issues: list[Issue] = []
    statuses = [(d.get("status") or "").strip().upper() for d in days]
    present = sum(1 for s in statuses if s in STATUS_PRESENT)
    leave = sum(1 for s in statuses if s in STATUS_LEAVE)

    stated_present = _num(summary.get("total_present_days"))
    if stated_present is not None and abs(present - stated_present) > 0:
        issues.append(Issue(
            "present_days_mismatch", BLOCK,
            f"Counted {present} present days in the rows, but the sheet says "
            f"{int(stated_present)}.",
            field="summary.total_present_days",
            expected=present, found=stated_present))

    if spec.has_leave_column:
        stated_leave = _num(summary.get("total_leave_days"))
        if stated_leave is not None and abs(leave - stated_leave) > 0:
            issues.append(Issue(
                "leave_days_mismatch", BLOCK,
                f"Counted {leave} leave days in the rows, but the sheet says "
                f"{int(stated_leave)}.",
                field="summary.total_leave_days",
                expected=leave, found=stated_leave))

    # Mandays is the invoice quantity -- if it disagrees with present days the
    # invoice is wrong by construction.
    mandays = _num(summary.get("mandays"))
    if mandays is not None and stated_present is not None and \
            not _close(mandays, stated_present):
        issues.append(Issue(
            "mandays_vs_present_mismatch", WARN,
            f"Mandays ({mandays}) is not the same as present days "
            f"({int(stated_present)}). Confirm which one is correct.",
            field="summary.mandays",
            expected=stated_present, found=mandays))

    man_hours = _num(summary.get("man_hours"))
    computed_normal = _sum(d.get("normal_hours") for d in days)
    # D-075: same reasoning as _check_row_sum_vs_summary. With no hours on any
    # row there is nothing to compare the stated total against, and reporting
    # the whole stated total as a discrepancy is an arithmetic artefact. The
    # single "hours not read from the rows" warning already covers it.
    if UNCOMPUTABLE_IS_NOT_FAILED and not _rows_carry_hours(days):
        man_hours = None
    if man_hours is not None and not _close_sum(man_hours, computed_normal):
        # Some sites define man-hours as normal+OT; report rather than assume.
        computed_with_ot = computed_normal + _sum(d.get("ot_hours") for d in days)
        if not _close_sum(man_hours, computed_with_ot):
            issues.append(Issue(
                "man_hours_mismatch", BLOCK,
                f"Total hours on the sheet ({man_hours}) matches neither the hours "
                f"added up from the rows ({computed_normal}) nor hours plus overtime "
                f"({computed_with_ot}).",
                field="summary.man_hours",
                expected=computed_normal, found=man_hours))
    return issues


WEEKOFF_WEEKDAY_SPREAD = 3      # D-083: distinct weekdays before we call it drift


def _check_weekoff_weekday(days: list[dict], period_label) -> list[Issue]:
    """Do the weekly-offs land on the SAME weekday each week?

    D-083. Counts cannot detect a permutation: a page with the right number of
    P, L and W reconciles perfectly with its own totals even when the rows have
    slipped against the dates. For a long time that was taken to mean placement
    could not be checked at all.

    It can, from a source neither the sheet nor the OCR controls -- the
    calendar. A site's rest day is a WEEKDAY, not a date. Whatever the
    convention, weekly-offs cluster on one or two weekdays; when the rows drift,
    they scatter across the week. Measured:

        a page with a one-row drift      W on Wed, Fri, Fri, Sat, Sat, Sun x3
                                         -> 4 distinct weekdays, 1 of 8 on a
                                            weekend
        seven correctly-read pages       Saturday + Sunday only, 4/4 5/5 8/8
                                            10/10 on a weekend

    Counting DISTINCT WEEKDAYS rather than weekend-ness keeps this
    convention-agnostic: a site whose rest day is Friday scores one weekday and
    passes, exactly as it should. Only scatter is suspicious.
    """
    if not period_label:
        return []
    try:
        from .reconcile import parse_period
        per = parse_period(period_label)
    except Exception:                                           # noqa: BLE001
        return []
    if not per:
        return []
    year, month = per
    last = calendar.monthrange(year, month)[1]
    offs = []
    for d in days:
        if (d.get("status") or "").strip().upper() != "W":
            continue
        dn = _num(d.get("day"))
        if dn is None or not 1 <= int(dn) <= last:
            continue
        offs.append(int(dn))
    if len(offs) < WEEKOFF_WEEKDAY_SPREAD:
        return []
    spread = {calendar.weekday(year, month, d) for d in offs}
    if len(spread) < WEEKOFF_WEEKDAY_SPREAD:
        return []
    names = ", ".join(calendar.day_name[w] for w in sorted(spread))
    return [Issue(
        "weekoff_weekday_scattered", BLOCK,
        f"The weekly offs on this sheet fall on {len(spread)} different days of "
        f"the week ({names}). A rest day does not move about like that, so the "
        f"rows have probably slipped against the dates — please check this page "
        f"against the paper.",
        field="days")]


def _check_in_out_consistency(days: list[dict], spec: TemplateSpec) -> list[Issue]:
    if not spec.has_in_out:
        return []
    issues: list[Issue] = []
    for idx, d in enumerate(days):
        day_no = _num(d.get("day"))
        day_i = int(day_no) if day_no is not None else None
        t_in, t_out = _parse_clock(d.get("in_time")), _parse_clock(d.get("out_time"))
        nh = _num(d.get("normal_hours"))
        if t_in is None or t_out is None or nh is None:
            continue
        span = t_out - t_in
        if span < 0:            # overnight shift
            span += 24.0
        ot = _num(d.get("ot_hours")) or 0.0
        # Allow an hour of unpaid break either way before flagging.
        if abs(span - (nh + ot)) > 1.5:
            issues.append(Issue(
                "in_out_vs_hours_mismatch", WARN,
                f"Day {day_i}: in-time to out-time is {round(span, 2)} hours, but "
                f"{nh} hours plus {ot} overtime are written. One of them is probably wrong.",
                day=day_i, expected=round(span, 2), found=nh + ot))
    return issues


def _parse_clock(v: Any) -> float | None:
    if v is None:
        return None
    s = str(v).strip().lower().replace(".", ":")
    if not s or s in ("-", "--"):
        return None
    pm = "pm" in s
    am = "am" in s
    s = s.replace("am", "").replace("pm", "").strip()
    if ":" not in s:
        if not s.isdigit():
            return None
        s = s.zfill(4)
        s = f"{s[:2]}:{s[2:]}" if len(s) == 4 else s
    try:
        h_str, m_str = s.split(":", 1)
        h, m = int(h_str), int(m_str[:2])
    except ValueError:
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    if pm and h < 12:
        h += 12
    if am and h == 12:
        h = 0
    return h + m / 60.0


def _check_identity(record: dict, roster, ) -> list[Issue]:
    """Roster match. Deliberately flags near-ties rather than resolving them."""
    issues: list[Issue] = []
    name = (record.get("employee_name") or "").strip()
    code = (record.get("employee_code") or "").strip()

    if not name and not code:
        # D-084. 292 of 1,218 corpus pages reach here, and the layouts behind
        # them are not all timesheets: one is an "Aarvi Encon Leave Record
        # Part-B", one a statutory FORM D register, several are multi-employee
        # grids. A reviewer told only that the name could not be read has to
        # open the scan to find out which. Quoting what the page actually says
        # at the top answers that without opening anything.
        #
        # A keyword detector for document kinds was tried first and dropped:
        # only one of six of those pages carries a heading clean enough to
        # match on, so it would have helped a sixth of them while adding a rule
        # that could mislabel a real timesheet. Showing the text works on every
        # page and claims nothing.
        head = (record.get("page_heading") or "").strip()
        extra = f' The top of the page reads: "{head[:70]}".' if len(head) >= 6 else ""
        issues.append(Issue("identity_missing", BLOCK,
                            "Neither the employee name nor the code could be read, so this "
                            "page cannot be matched to a person." + extra,
                            field="employee_name"))
        return issues

    if roster is None or roster.empty:
        issues.append(Issue("roster_absent", WARN,
                            "No employee list has been uploaded, so the name and code "
                            "could not be verified.",
                            field="employee_code"))
        return issues

    match = roster.match(name=name, code=code)
    if match.status == "exact_code":
        if match.name_score is not None and match.name_score < config.ROSTER_MIN_SCORE:
            issues.append(Issue(
                "identity_name_code_conflict", BLOCK,
                f"Code '{code}' belongs to '{match.roster_name}' in the employee "
                f"list, but the sheet says '{name}'. One of the two is wrong.",
                field="employee_name",
                expected=match.roster_name, found=name))
    elif match.status == "ambiguous":
        issues.append(Issue(
            "identity_ambiguous", BLOCK,
            f"'{name}' could be more than one person in the employee list "
            f"({', '.join(match.candidates)}). Please pick the right one.",
            field="employee_name", found=name))
    elif match.status == "none":
        issues.append(Issue(
            "identity_not_in_roster", BLOCK,
            f"Neither the name '{name}' nor the code '{code}' is in the "
            f"employee list.",
            field="employee_code", found=code or name))
    return issues


def _check_pass_disagreement(disagreements: dict[str, Any] | None) -> list[Issue]:
    """Dual-pass consensus. This is our uncertainty signal -- see config."""
    if not disagreements:
        return []
    issues: list[Issue] = []
    for path, val in disagreements.items():
        # Only entries shaped like a disagreement pair are ours.
        #
        # The page's whole analysis blob (route, profile, n_boxes, ...) is
        # stored in the same DB column and was being handed to this function
        # verbatim on every reviewer save, where unpacking `('needs_escalation')`
        # into (a, b) raised ValueError -- a 500 on EVERY correction, which made
        # the entire review step unusable while extraction looked healthy.
        if not (isinstance(val, (tuple, list)) and len(val) == 2):
            continue
        a, b = val
        issues.append(Issue(
            "pass_disagreement", WARN,
            f"The two extraction passes disagree on this value "
            f"({a!r} vs {b!r}). Treat as unverified.",
            field=path, expected=a, found=b))
    return issues


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def validate(record: dict, spec: TemplateSpec, roster=None,
             disagreements: dict | None = None) -> list[dict]:
    """Run every rule. Returns issues ordered most-severe first."""
    days = record.get("days") or []
    summary = record.get("summary") or {}

    issues: list[Issue] = []
    issues += _check_identity(record, roster)
    issues += _check_day_sequence(days, spec)
    issues += _check_day_bounds(days, spec)
    issues += _check_row_sum_vs_summary(days, summary, spec)
    issues += _check_day_count(days, summary, spec)
    issues += _check_in_out_consistency(days, spec)
    issues += _check_weekoff_weekday(days, record.get("period_start"))
    issues += _check_pass_disagreement(disagreements)

    # D-083. "hours_not_verified" says nothing on this page was confirmed by
    # arithmetic, and on most sheets that is simply untrue: the hours total is
    # the rarest of the summary figures, while the present / leave / weekly-off
    # counts are stated far more often and DO reconcile. Measured on 26
    # perfectly-read pages: 12 carried an hours total, 22 carried a present-day
    # count, and on 20 of them that count reconciled exactly.
    #
    # Keeping the warning in that case made the page review_optional, so only
    # ONE page in 278 passed clean -- the system had become honest and useless
    # at the same time. A reviewer handed everything learns to click through
    # everything, which is the failure this engine exists to prevent.
    #
    # The earlier refusal to trust counts came from two pages that reconciled
    # and still disagreed with the client's records. Both were then read off
    # the paper by eye (D-083): the sheet says "Leave", our output says L, and
    # the client's spreadsheet says A. We were right and the records were
    # wrong, so those pages were never evidence that counts cannot be trusted.
    if UNCOMPUTABLE_IS_NOT_FAILED:
        codes = {i.code for i in issues}
        verified = [
            name for name, key, bad in (
                ("present days", "total_present_days", "present_days_mismatch"),
                ("leave days", "total_leave_days", "leave_days_mismatch"),
            )
            if _num(summary.get(key)) is not None and bad not in codes
        ]
        if verified and "hours_not_verified" in codes:
            issues = [i for i in issues if i.code != "hours_not_verified"]

    # Collapse repeats of the same per-day WARNING into one line. A page
    # whose out-time column reads badly fires the identical in/out warning on
    # 15 rows -- honest, but a wall of duplicates buries the one blocking
    # issue among them, which is the "reviewing takes as long as doing it"
    # failure this engine exists to prevent. Five or more of the same code
    # become a single warning naming the days; blockers are never collapsed.
    by_code: dict[str, list[Issue]] = {}
    for i in issues:
        if i.severity == WARN and i.day is not None:
            by_code.setdefault(i.code, []).append(i)
    for code, group in by_code.items():
        if len(group) >= 5:
            days_list = ", ".join(str(i.day) for i in group)
            first = group[0]
            keep = Issue(code, WARN,
                         f"{len(group)} rows raise the same check "
                         f"(days {days_list}) — first instance: "
                         f"{first.message}",
                         field=first.field)
            issues = [i for i in issues if i not in group]
            issues.append(keep)

    order = {BLOCK: 0, WARN: 1}
    issues.sort(key=lambda i: (order.get(i.severity, 9), i.day or 0, i.code))
    return [i.to_dict() for i in issues]


def status_for(issues: list[dict]) -> str:
    if any(i["severity"] == BLOCK for i in issues):
        return "needs_review"
    if issues:
        return "review_optional"
    return "clean"

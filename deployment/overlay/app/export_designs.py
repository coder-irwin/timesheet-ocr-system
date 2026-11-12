"""Six Excel export designs.

The client's real output template is still unknown, so rather than guess once,
we ship six genuinely different presentations of the SAME extracted data and
let them pick. Each is optimised for a different consumer:

    1. timesheet      the full labour attendance sheet -- every day row with
                      in/out times, hours, OT and remarks, plus the summary
                      block, laid out like the paper form
    2. invoice        finance -- one row per employee, only billable quantities
    3. attendance     HR/site -- calendar grid, one column per day of the month
    4. audit          compliance -- every value with its confidence and issues
    5. payroll        payroll import -- flat, machine-readable, no formatting
    6. dashboard      management -- summary counts, exceptions, per-client rollup

DESIGN RULES APPLIED TO ALL FIVE
--------------------------------
* Nothing is invented. Every cell traces to an extracted value or is blank.
* A row that still carries a blocking issue is tinted, in every design, so a
  sheet leaving this system can never *look* clean when it isn't -- and the
  tint survives copy-paste into the client's own workbook.
* Frozen header rows and sized columns, because these get read on laptops.

TERMS
-----
freeze panes   keeps the header visible while scrolling
conditional
tint           background colour used to mark rows needing attention
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import config

# ---------------------------------------------------------------------------
# Shared styling
# ---------------------------------------------------------------------------

NAVY = "1F3864"
SLATE = "44546A"
GREEN = "2E7D32"
AMBER = "FFF2CC"
RED = "F8CBAD"
GREY = "F2F2F2"
WHITE = "FFFFFF"

H_FONT = Font(color=WHITE, bold=True, size=10)
TITLE_FONT = Font(bold=True, size=14, color=NAVY)
SUB_FONT = Font(size=9, italic=True, color="808080")
THIN = Side(style="thin", color="D0D0D0")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def _blocking(page: dict) -> bool:
    return any(i.get("severity") == "block" for i in (page.get("issues") or []))


def _flagged(page: dict) -> bool:
    return bool(page.get("issues"))


def _tint(page: dict) -> str | None:
    if _blocking(page):
        return RED
    if _flagged(page):
        return AMBER
    return None


def _header(ws, columns, row: int = 1, fill: str = NAVY) -> None:
    for i, (_, label) in enumerate(columns, start=1):
        c = ws.cell(row=row, column=i, value=label)
        c.fill = PatternFill("solid", fgColor=fill)
        c.font = H_FONT
        c.alignment = Alignment(horizontal="center", vertical="center",
                                wrap_text=True)
        c.border = BORDER
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def _autosize(ws, columns, max_w: int = 34) -> None:
    for i, (_key, label) in enumerate(columns, start=1):
        width = max(len(str(label)) + 2, 10)
        for row in ws.iter_rows(min_col=i, max_col=i, min_row=2):
            v = row[0].value
            if v is not None:
                width = max(width, min(len(str(v)) + 2, max_w))
        ws.column_dimensions[get_column_letter(i)].width = width


def _summary_of(page: dict) -> dict:
    return (page.get("record") or {}).get("summary") or {}


def _verified_designation(rec: dict) -> str | None:
    """The designation, only if the closed vocabulary confirmed it.

    The pipeline records `_original_designation` whenever the 444-title
    vocabulary recognised the read (even when the read was already exact).
    A read the vocabulary declined ('1ds h', a name glued to a title) is raw
    OCR junk: it stays visible in the Timesheet Detail, the Audit sheet and
    the review UI, but has no place on a finance deliverable, where a wrong
    title printed confidently is worse than a blank one.
    """
    if "_original_designation" in rec:
        return rec.get("designation")
    return None


def _rec_of(page: dict) -> dict:
    return page.get("record") or {}


# ---------------------------------------------------------------------------
# Design 1 -- INVOICE
# ---------------------------------------------------------------------------

INVOICE_COLS = [
    ("employee_code", "Emp Code"),
    ("employee_name", "Employee Name"),
    ("designation", "Designation"),
    ("client", "Client"),
    ("project", "Project"),
    ("period_label", "Period"),
    ("total_present_days", "Present Days"),
    ("total_man_hours", "Man Hours"),
    ("total_ot_hours", "OT Hours"),
    ("billable", "Billable Days"),
    ("verified", "Verified"),
]


def design_invoice(wb: Workbook, pages: list[dict]) -> None:
    """Finance view: only what gets billed, one row per employee-month.

    Deliberately narrow. A finance reviewer should not have to scroll past
    thirty day-columns to find the two numbers that drive the invoice.
    """
    ws = wb.create_sheet("Invoice")
    ws["A1"] = "TIMESHEET INVOICE SUMMARY"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = ("Rows tinted red carry an unresolved validation issue and "
                "should not be invoiced until reviewed.")
    ws["A2"].font = SUB_FONT
    _header(ws, INVOICE_COLS, row=4)

    r = 5
    for p in pages:
        rec, summ = _rec_of(p), _summary_of(p)
        vals = {
            **{k: rec.get(k) for k in ("employee_code", "employee_name",
                                       "client", "project", "period_label")},
            "designation": _verified_designation(rec),
            **{k: summ.get(k) for k in ("total_present_days", "total_man_hours",
                                        "total_ot_hours")},
            "billable": summ.get("total_present_days"),
            "verified": "NO -- review" if _blocking(p) else
                        ("check" if _flagged(p) else "yes"),
        }
        tint = _tint(p)
        for i, (key, _) in enumerate(INVOICE_COLS, start=1):
            c = ws.cell(row=r, column=i, value=vals.get(key))
            c.border = BORDER
            if tint:
                c.fill = PatternFill("solid", fgColor=tint)
        r += 1

    # Totals row -- the number finance actually wants.
    ws.cell(row=r + 1, column=6, value="TOTAL").font = Font(bold=True)
    for col, key in ((7, "total_present_days"), (8, "total_man_hours"),
                     (9, "total_ot_hours")):
        letter = get_column_letter(col)
        c = ws.cell(row=r + 1, column=col,
                    value=f"=SUM({letter}5:{letter}{r - 1})")
        c.font = Font(bold=True)
    _autosize(ws, INVOICE_COLS)


# ---------------------------------------------------------------------------
# Design 2 -- ATTENDANCE CALENDAR
# ---------------------------------------------------------------------------

def design_attendance(wb: Workbook, pages: list[dict]) -> None:
    """Site/HR view: a calendar grid, one column per day.

    This mirrors the shape the client's OWN spreadsheets already use (one row
    per employee, days as columns), so it drops into their existing workflow
    with no re-learning.
    """
    ws = wb.create_sheet("Attendance")
    ws["A1"] = "MONTHLY ATTENDANCE GRID"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = "P present · A absent · L leave · W weekly off · H holiday · ? unread"
    ws["A2"].font = SUB_FONT

    base = [("employee_code", "Code"), ("employee_name", "Employee Name")]
    days = [(f"d{i}", str(i)) for i in range(1, 32)]
    tail = [("present", "P"), ("absent", "A"), ("leave", "L"), ("off", "W/H")]
    cols = base + days + tail
    _header(ws, cols, row=4)

    from .reconcile import parse_period, infer_period_from_grid
    import calendar as _cal

    r = 5
    for p in pages:
        rec = _rec_of(p)
        by_day = {d.get("day"): d for d in (rec.get("days") or [])
                  if d.get("day")}
        period = parse_period(rec.get("period_label")) \
            or infer_period_from_grid(rec.get("period_label"),
                                      rec.get("days") or [])
        month_len = _cal.monthrange(*period)[1] if period else 31
        ws.cell(row=r, column=1, value=rec.get("employee_code")).border = BORDER
        ws.cell(row=r, column=2, value=rec.get("employee_name")).border = BORDER

        counts = {"P": 0, "A": 0, "L": 0, "OFF": 0}
        for i in range(1, 32):
            if i > month_len:      # printed-form furniture, not an unread day
                ws.cell(row=r, column=2 + i).border = BORDER
                continue
            d = by_day.get(i)
            st = (d or {}).get("status") or ("" if d is None else "?")
            c = ws.cell(row=r, column=2 + i, value=st)
            c.alignment = Alignment(horizontal="center")
            c.border = BORDER
            if st == "P":
                counts["P"] += 1
                c.fill = PatternFill("solid", fgColor="E8F5E9")
            elif st == "A":
                counts["A"] += 1
                c.fill = PatternFill("solid", fgColor=RED)
            elif st == "L":
                counts["L"] += 1
                c.fill = PatternFill("solid", fgColor=AMBER)
            elif st in ("W", "H"):
                counts["OFF"] += 1
                c.fill = PatternFill("solid", fgColor=GREY)
            elif st == "?":
                c.fill = PatternFill("solid", fgColor=AMBER)

        for off, key in enumerate(("P", "A", "L", "OFF")):
            c = ws.cell(row=r, column=34 + off, value=counts[key])
            c.font = Font(bold=True)
            c.border = BORDER
        r += 1

    for i in range(3, 34):
        ws.column_dimensions[get_column_letter(i)].width = 3.6
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 26


# ---------------------------------------------------------------------------
# Design 3 -- AUDIT TRAIL
# ---------------------------------------------------------------------------

AUDIT_COLS = [
    ("source_name", "Source File"),
    ("employee_name", "Employee"),
    ("field", "Field"),
    ("value", "Extracted Value"),
    ("confidence", "OCR Confidence"),
    ("route", "Read As"),
    ("issue", "Validation Issue"),
    ("severity", "Severity"),
]


def design_audit(wb: Workbook, pages: list[dict]) -> None:
    """Compliance view: every extracted value, its confidence, and its issues.

    The client is govt-adjacent. This sheet answers "where did this number come
    from and how sure were you" for each value, without needing the app.
    """
    ws = wb.create_sheet("Audit")
    ws["A1"] = "EXTRACTION AUDIT TRAIL"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = ("One row per extracted field. Confidence is the OCR engine's "
                "own score (0-1); blank means the value was derived, not read.")
    ws["A2"].font = SUB_FONT
    _header(ws, AUDIT_COLS, row=4, fill=SLATE)

    r = 5
    for p in pages:
        rec, summ = _rec_of(p), _summary_of(p)
        conf = rec.get("_confidence") or {}
        route = (p.get("disagreements") or {}).get("route") or ""
        issues_by_field: dict[str, list] = {}
        for i in (p.get("issues") or []):
            issues_by_field.setdefault(i.get("field") or "", []).append(i)

        fields = [(k, rec.get(k)) for k in
                  ("employee_name", "employee_code", "designation", "client",
                   "project", "location", "period_label")]
        fields += [(k, v) for k, v in summ.items()]
        # Day rows: the post-OCR evaluation layer's verdict per day, so the
        # audit trail answers "how sure were you about the 14th" as well as
        # "about the name". Confidence here is the ROW score (app/rowconf),
        # not a raw OCR number; the reason sits in the issue column.
        day_rows = []
        for d in (rec.get("days") or []):
            flag = d.get("_review") or ""
            why = d.get("_review_why") or []
            day_rows.append((f"day_{d.get('day')}", d.get("status"),
                             d.get("_row_conf"), (why[0][:110] if why else ""),
                             {"must_fix": "block", "review": "warn"}.get(flag, "")))

        for key, val in fields:
            iss = issues_by_field.get(key) or []
            row_vals = {
                "source_name": p.get("source_name"),
                "employee_name": rec.get("employee_name"),
                "field": key, "value": val,
                "confidence": round(conf[key], 3) if isinstance(conf.get(key),
                                                               (int, float)) else None,
                "route": route,
                "issue": iss[0]["message"][:110] if iss else "",
                "severity": iss[0]["severity"] if iss else "",
            }
            for i, (k, _) in enumerate(AUDIT_COLS, start=1):
                c = ws.cell(row=r, column=i, value=row_vals.get(k))
                c.border = BORDER
                if iss and iss[0]["severity"] == "block":
                    c.fill = PatternFill("solid", fgColor=RED)
                elif iss:
                    c.fill = PatternFill("solid", fgColor=AMBER)
            r += 1
        for key, val, rconf, why, sev in day_rows:
            row_vals = {
                "source_name": p.get("source_name"),
                "employee_name": rec.get("employee_name"),
                "field": key, "value": val,
                "confidence": rconf, "route": route,
                "issue": why, "severity": sev,
            }
            for i, (k, _) in enumerate(AUDIT_COLS, start=1):
                c = ws.cell(row=r, column=i, value=row_vals.get(k))
                c.border = BORDER
                if sev == "block":
                    c.fill = PatternFill("solid", fgColor=RED)
                elif sev == "warn":
                    c.fill = PatternFill("solid", fgColor=AMBER)
            r += 1
    _autosize(ws, AUDIT_COLS, max_w=60)


# ---------------------------------------------------------------------------
# Design 4 -- PAYROLL IMPORT
# ---------------------------------------------------------------------------

PAYROLL_COLS = [
    ("emp_code", "EMP_CODE"),
    ("emp_name", "EMP_NAME"),
    ("period", "PERIOD"),
    ("present_days", "PRESENT_DAYS"),
    ("absent_days", "ABSENT_DAYS"),
    ("leave_days", "LEAVE_DAYS"),
    ("weekly_off", "WEEKLY_OFF"),
    ("holidays", "HOLIDAYS"),
    ("comp_off", "COMP_OFF"),
    ("normal_hours", "NORMAL_HRS"),
    ("ot_hours", "OT_HRS"),
    ("status", "STATUS"),
    ("counts_from", "COUNTS_FROM"),
]


def design_payroll(wb: Workbook, pages: list[dict]) -> None:
    """Machine-readable import file.

    No merged cells, no title rows, no colour-as-meaning -- a payroll system
    parsing this must not have to skip decoration. Status is a plain word so a
    downstream filter can reject unverified rows programmatically.
    """
    ws = wb.create_sheet("Payroll_Import")
    _header(ws, PAYROLL_COLS, row=1, fill=SLATE)
    r = 2
    for p in pages:
        rec, summ = _rec_of(p), _summary_of(p)
        # Sheets that print no totals box (the shared multi-employee grids)
        # carry counts worked out from the day rows instead. Which one was
        # used is stated in COUNTS_FROM so nobody mistakes a count for a
        # figure the site wrote down.
        counted = rec.get("_counted") or {}
        stated = any(summ.get(k) for k in
                     ("total_present_days", "total_absent_days", "total_leave_days",
                      "total_weekly_off", "total_public_holiday", "total_comp_off"))
        src = summ if stated else counted
        vals = {
            "emp_code": rec.get("employee_code"),
            "emp_name": rec.get("employee_name"),
            "period": rec.get("period_label"),
            "present_days": src.get("total_present_days"),
            "absent_days": src.get("total_absent_days"),
            "leave_days": src.get("total_leave_days"),
            "weekly_off": src.get("total_weekly_off"),
            "holidays": src.get("total_public_holiday"),
            "comp_off": src.get("total_comp_off"),
            "counts_from": "sheet totals" if stated else
                           ("day rows (sheet has no totals box)" if counted else ""),
            "normal_hours": summ.get("total_man_hours"),
            "ot_hours": summ.get("total_ot_hours"),
            "status": "HOLD" if _blocking(p) else
                      ("REVIEW" if _flagged(p) else "OK"),
        }
        for i, (k, _) in enumerate(PAYROLL_COLS, start=1):
            ws.cell(row=r, column=i, value=vals.get(k))
        r += 1
    _autosize(ws, PAYROLL_COLS)


# ---------------------------------------------------------------------------
# Design 5 -- MANAGEMENT DASHBOARD
# ---------------------------------------------------------------------------

def design_dashboard(wb: Workbook, pages: list[dict]) -> None:
    """Management view: what needs attention, and where.

    Answers three questions in one screen: how much came in, how much is
    clean, and which sites are generating the problems.
    """
    ws = wb.create_sheet("Dashboard")
    ws["A1"] = "TIMESHEET PROCESSING DASHBOARD"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = f"Generated {time.strftime('%d %b %Y %H:%M')}"
    ws["A2"].font = SUB_FONT

    total = len(pages)
    blocking = sum(1 for p in pages if _blocking(p))
    flagged = sum(1 for p in pages if _flagged(p) and not _blocking(p))
    clean = total - blocking - flagged
    cached = sum(1 for p in pages if p.get("from_cache"))

    tiles = [
        ("Pages processed", total, NAVY),
        ("Clean -- ready to invoice", clean, GREEN),
        ("Needs review", flagged, "B7791F"),
        ("Blocked -- do not invoice", blocking, "C0392B"),
        ("Served from cache (no re-processing)", cached, SLATE),
    ]
    r = 4
    for label, value, colour in tiles:
        a = ws.cell(row=r, column=1, value=label)
        a.font = Font(bold=True, size=10)
        b = ws.cell(row=r, column=2, value=value)
        b.font = Font(bold=True, size=16, color=colour)
        b.alignment = Alignment(horizontal="center")
        r += 1

    # Per-client rollup -- where the problems concentrate.
    r += 2
    ws.cell(row=r, column=1, value="BY SOURCE FILE").font = Font(bold=True, size=11)
    r += 1
    cols = [("src", "Source"), ("n", "Pages"), ("blk", "Blocked"),
            ("warn", "Review"), ("ok", "Clean")]
    for i, (_, lab) in enumerate(cols, start=1):
        c = ws.cell(row=r, column=i, value=lab)
        c.fill = PatternFill("solid", fgColor=NAVY)
        c.font = H_FONT
    r += 1

    by_src: dict[str, list] = {}
    for p in pages:
        by_src.setdefault(p.get("source_name") or "?", []).append(p)
    for src, ps in sorted(by_src.items()):
        blk = sum(1 for x in ps if _blocking(x))
        wrn = sum(1 for x in ps if _flagged(x) and not _blocking(x))
        ws.cell(row=r, column=1, value=src)
        ws.cell(row=r, column=2, value=len(ps))
        ws.cell(row=r, column=3, value=blk)
        ws.cell(row=r, column=4, value=wrn)
        ws.cell(row=r, column=5, value=len(ps) - blk - wrn)
        r += 1

    # Top recurring issues -- tells them what to fix at source.
    r += 2
    ws.cell(row=r, column=1, value="MOST COMMON ISSUES").font = Font(bold=True, size=11)
    r += 1
    counts: dict[str, int] = {}
    for p in pages:
        for i in (p.get("issues") or []):
            counts[i.get("code", "?")] = counts.get(i.get("code", "?"), 0) + 1
    for code, n in sorted(counts.items(), key=lambda x: -x[1])[:12]:
        ws.cell(row=r, column=1, value=code)
        ws.cell(row=r, column=2, value=n)
        r += 1

    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 12
    for col in "CDE":
        ws.column_dimensions[col].width = 11


# ---------------------------------------------------------------------------
# Design 6 -- FULL TIMESHEET DETAIL
# ---------------------------------------------------------------------------

TS_DAY_COLS = [
    ("day", "Day"), ("weekday", "Weekday"), ("status", "Status"),
    ("in_time", "Time In"), ("out_time", "Time Out"),
    ("normal_hours", "Normal Hrs"), ("ot_hours", "OT Hrs"),
    ("total_hours", "Total Hrs"), ("remarks", "Remarks"),
]

_TS_SUMMARY_ROWS = [
    ("total_present_days", "Total Present Days (P)"),
    ("total_weekly_off", "Total Weekly Off (W/O)"),
    ("total_public_holiday", "Total Public Holiday (P.H)"),
    ("total_absent_days", "Total Absent Days (A)"),
    ("total_leave_days", "Total Leaves (L)"),
    ("total_comp_off", "Total Comp. Off (C/O)"),
    ("total_man_hours", "Total Normal Hours"),
    ("total_ot_hours", "Total Over Time Hours"),
]

_WD_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def design_timesheet(wb: Workbook, pages: list[dict]) -> None:
    """The complete labour attendance sheet, one block per employee.

    This is the export that answers "show me everything the page said":
    the full header (who / where / which month), every day row with its
    in/out times, hours, OT and remarks, and the sheet's own summary
    totals -- laid out the way the paper form is, so the client can hold
    the scan and the Excel side by side and compare line by line.

    Values the system inferred (rather than read) are italicised and say
    so in the remarks; nothing is silently invented.
    """
    from .reconcile import parse_period, weekday_of

    ws = wb.create_sheet("Timesheet Detail")
    ws["A1"] = "LABOUR ATTENDANCE TIMESHEET — FULL DETAIL"
    ws["A1"].font = TITLE_FONT
    ws["A2"] = ("One block per employee. Grey rows are weekly offs/holidays, "
                "red are absences. Italic values were inferred from the "
                "sheet's own totals, not read from the grid.")
    ws["A2"].font = SUB_FONT

    r = 4
    for p in pages:
        rec, summ = _rec_of(p), _summary_of(p)
        period = parse_period(rec.get("period_label"))

        # --- employee header block ---------------------------------------
        c = ws.cell(row=r, column=1,
                    value=(rec.get("employee_name") or p.get("source_name")
                           or "UNKNOWN"))
        c.font = Font(bold=True, size=12, color=NAVY)
        status = ("NEEDS CORRECTION" if _blocking(p)
                  else "CHECK WARNINGS" if _flagged(p) else "ALL CHECKS PASSED")
        sc = ws.cell(row=r, column=8, value=status)
        sc.font = Font(bold=True, size=10,
                       color=("C0392B" if _blocking(p)
                              else "B7791F" if _flagged(p) else GREEN))
        r += 1
        head_pairs = [
            ("Emp. Code", rec.get("employee_code")),
            ("Designation", rec.get("designation")),
            ("Period", rec.get("period_label")),
            ("Client", rec.get("client")),
            ("Project / Site", rec.get("project") or rec.get("location")),
            ("Source file", p.get("source_name")),
        ]
        for label, val in head_pairs:
            if val in (None, ""):
                continue
            ws.cell(row=r, column=1, value=label).font = Font(
                bold=True, size=9, color="6A7280")
            ws.cell(row=r, column=2, value=val)
            r += 1
        r += 1

        # --- day table -----------------------------------------------------
        _header(ws, TS_DAY_COLS, row=r, fill=SLATE)
        ws.freeze_panes = None          # per-block tables cannot freeze
        r += 1
        for d in (rec.get("days") or []):
            st = (d.get("status") or "").upper()
            wd = (weekday_of(period[0], period[1], d.get("day") or 0)
                  if period else None)
            inferred = d.get("_inferred")
            vals = {
                "day": d.get("day"),
                "weekday": _WD_NAMES[wd] if wd is not None else "",
                "status": d.get("status"),
                "in_time": d.get("in_time"), "out_time": d.get("out_time"),
                "normal_hours": d.get("normal_hours"),
                "ot_hours": d.get("ot_hours"),
                "total_hours": d.get("total_hours"),
                "remarks": (d.get("remarks") or "") +
                           (" [inferred from sheet totals]" if inferred else ""),
            }
            fill = (GREY if st in ("W", "H", "C")
                    else RED if st == "A"
                    else AMBER if st == "L" else None)
            for i, (k, _) in enumerate(TS_DAY_COLS, start=1):
                cell = ws.cell(row=r, column=i, value=vals.get(k))
                cell.border = BORDER
                if i <= 3:
                    cell.alignment = Alignment(horizontal="center")
                if fill:
                    cell.fill = PatternFill("solid", fgColor=fill)
                if inferred:
                    cell.font = Font(italic=True, color=SLATE)
            r += 1

        # --- summary block, exactly as the sheet states it -----------------
        r += 1
        ws.cell(row=r, column=1, value="SUMMARY (as stated on the sheet)"
                ).font = Font(bold=True, size=10)
        r += 1
        for key, label in _TS_SUMMARY_ROWS:
            val = summ.get(key)
            if val in (None, ""):
                continue
            ws.cell(row=r, column=1, value=label).font = Font(size=9)
            vc = ws.cell(row=r, column=3, value=val)
            vc.font = Font(bold=True)
            vc.alignment = Alignment(horizontal="center")
            r += 1

        # --- open issues ----------------------------------------------------
        open_issues = p.get("issues") or []
        if open_issues:
            r += 1
            ws.cell(row=r, column=1,
                    value="CHECKS RAISED").font = Font(bold=True, size=10)
            r += 1
            for i in open_issues:
                c = ws.cell(row=r, column=1, value=f"• {i.get('message')}")
                c.font = Font(size=9, color=("C0392B"
                              if i.get("severity") == "block" else "B7791F"))
                r += 1
        r += 2   # gap before the next employee

    widths = {1: 24, 2: 9, 3: 8, 4: 11, 5: 11, 6: 11, 7: 9, 8: 20, 9: 34}
    for col, w in widths.items():
        ws.column_dimensions[get_column_letter(col)].width = w


# ---------------------------------------------------------------------------

DESIGNS: dict[str, tuple[str, Callable[[Workbook, list[dict]], None]]] = {
    "timesheet": ("Timesheet detail (the full sheet)", design_timesheet),
    "invoice": ("Invoice summary (finance)", design_invoice),
    "attendance": ("Attendance calendar (site/HR)", design_attendance),
    "audit": ("Audit trail (compliance)", design_audit),
    "payroll": ("Payroll import (machine-readable)", design_payroll),
    "dashboard": ("Management dashboard", design_dashboard),
}


def export(pages: list[dict], batch_name: str, design: str = "all",
           out_dir: Path | None = None) -> Path:
    """Write one design, or all five in a single workbook for comparison."""
    out_dir = out_dir or config.EXPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_"
                   for ch in batch_name).strip() or "batch"
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = out_dir / f"{safe}_{design}_{stamp}.xlsx"

    wb = Workbook()
    wb.remove(wb.active)
    chosen = DESIGNS if design == "all" else {design: DESIGNS[design]}
    for _key, (_label, fn) in chosen.items():
        fn(wb, pages)
    wb.save(dest)
    return dest

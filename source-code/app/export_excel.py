"""Excel export.

The client types into an existing Excel file today; that file's exact shape is
the real contract and we do not have it yet. So this writes a defensible
default layout and keeps the column order in one list at the top -- when the
client's actual template arrives, that list plus the header row is the only
thing that changes.

Three sheets, deliberately:
  Timesheets  - one row per employee-month, the invoice-facing numbers
  Daily       - one row per employee-day, for anyone who needs to audit a total
  Exceptions  - every unresolved issue, so nothing is silently exported clean
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import config
from .templates_spec import get as get_template

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(color="FFFFFF", bold=True)
FLAG_FILL = PatternFill("solid", fgColor="FFF2CC")
BLOCK_FILL = PatternFill("solid", fgColor="F8CBAD")

SUMMARY_COLUMNS = [
    ("source_name", "Source File"),
    ("employee_code", "Employee Code"),
    ("employee_name", "Employee Name"),
    ("project", "Project"),
    ("period_start", "Period From"),
    ("period_end", "Period To"),
    ("total_present_days", "Present Days"),
    ("total_leave_days", "Leave Days"),
    ("total_normal_hours", "Normal Hours"),
    ("total_ot_hours", "OT Hours"),
    ("mandays", "Mandays"),
    ("man_hours", "Man-Hours"),
    ("status", "Status"),
    ("issue_count", "Open Issues"),
]

DAILY_COLUMNS = [
    ("employee_code", "Employee Code"),
    ("employee_name", "Employee Name"),
    ("day", "Day"),
    ("status", "Status"),
    ("in_time", "In"),
    ("out_time", "Out"),
    ("normal_hours", "Normal Hrs"),
    ("ot_hours", "OT Hrs"),
]

EXCEPTION_COLUMNS = [
    ("source_name", "Source File"),
    ("employee_code", "Employee Code"),
    ("employee_name", "Employee Name"),
    ("severity", "Severity"),
    ("code", "Rule"),
    ("day", "Day"),
    ("field", "Field"),
    ("message", "Issue"),
]


def _style_header(ws, columns) -> None:
    for i, (_, label) in enumerate(columns, start=1):
        c = ws.cell(row=1, column=i, value=label)
        c.fill, c.font = HEADER_FILL, HEADER_FONT
        c.alignment = Alignment(horizontal="center", vertical="center")
    ws.freeze_panes = "A2"


def _autosize(ws, columns) -> None:
    for i, (key, label) in enumerate(columns, start=1):
        width = max(len(label) + 2, 12)
        for row in ws.iter_rows(min_col=i, max_col=i, min_row=2):
            v = row[0].value
            if v is not None:
                width = max(width, min(len(str(v)) + 2, 40))
        ws.column_dimensions[get_column_letter(i)].width = width


def export_batch(pages: list[dict], batch_name: str,
                 out_dir: Path | None = None) -> Path:
    out_dir = out_dir or config.EXPORT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in batch_name).strip()
    dest = out_dir / f"{safe or 'batch'}_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"

    wb = Workbook()
    ws = wb.active
    ws.title = "Timesheets"
    _style_header(ws, SUMMARY_COLUMNS)

    ws_daily = wb.create_sheet("Daily")
    _style_header(ws_daily, DAILY_COLUMNS)

    ws_exc = wb.create_sheet("Exceptions")
    _style_header(ws_exc, EXCEPTION_COLUMNS)

    r, rd, re_ = 2, 2, 2
    for page in pages:
        rec = page.get("record") or {}
        summary = rec.get("summary") or {}
        issues = page.get("issues") or []
        blocking = [i for i in issues if i.get("severity") == "block"]

        flat: dict[str, Any] = {
            "source_name": page.get("source_name"),
            "employee_code": rec.get("employee_code"),
            "employee_name": rec.get("employee_name"),
            "project": rec.get("project"),
            "period_start": rec.get("period_start"),
            "period_end": rec.get("period_end"),
            "status": page.get("status"),
            "issue_count": len(issues),
            **{k: summary.get(k) for k in (
                "total_present_days", "total_leave_days", "total_normal_hours",
                "total_ot_hours", "mandays", "man_hours")},
        }
        for i, (key, _) in enumerate(SUMMARY_COLUMNS, start=1):
            cell = ws.cell(row=r, column=i, value=flat.get(key))
            # An exported row that still carries a blocking issue is tinted, so
            # a spreadsheet that leaves this system can never look clean when
            # it isn't. Colour survives copy-paste into the client's own file.
            if blocking:
                cell.fill = BLOCK_FILL
            elif issues:
                cell.fill = FLAG_FILL
        r += 1

        for d in rec.get("days") or []:
            row = {"employee_code": rec.get("employee_code"),
                   "employee_name": rec.get("employee_name"), **d}
            for i, (key, _) in enumerate(DAILY_COLUMNS, start=1):
                ws_daily.cell(row=rd, column=i, value=row.get(key))
            rd += 1

        for iss in issues:
            row = {"source_name": page.get("source_name"),
                   "employee_code": rec.get("employee_code"),
                   "employee_name": rec.get("employee_name"), **iss}
            for i, (key, _) in enumerate(EXCEPTION_COLUMNS, start=1):
                cell = ws_exc.cell(row=re_, column=i, value=row.get(key))
                if iss.get("severity") == "block":
                    cell.fill = BLOCK_FILL
            re_ += 1

    for sheet, cols in ((ws, SUMMARY_COLUMNS), (ws_daily, DAILY_COLUMNS),
                        (ws_exc, EXCEPTION_COLUMNS)):
        _autosize(sheet, cols)

    wb.save(dest)
    return dest

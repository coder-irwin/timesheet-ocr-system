"""Hand-read ground truth for the benchmark pages.

Every value below was read off the rendered page by eye. This is small but it
is *real* -- which matters more than size, because the whole point is to
measure engines against what is actually on the paper.

We deliberately record the INVOICE-CRITICAL fields rather than every character
on the page. Character-level accuracy (CER) is the usual OCR metric, but it is
the wrong one here: getting 99% of characters right while misreading
"Total OT Hours" is a failed page, and getting the employee's designation
slightly wrong costs nothing. The client's exposure is concentrated in about a
dozen numbers per page, so those are what we score.
"""
from __future__ import annotations

GROUND_TRUTH: dict[str, dict[str, str]] = {
    # Handwritten AARVI form. The hard case.
    "IOCL30_Indian_Oil_Corpor_p1.png": {
        "_kind": "handwritten",
        "employee_name": "Lokesh Khurana",
        "employee_code": "54788",
        "designation": "Safety Supervisor",
        "month_year": "April-2026",
        "client": "IOCL MR",
        "present_days": "25",
        "total_man_hours": "200",
        "total_ot_hours": "23",
        "weekly_off": "04",
        "public_holiday": "01",
    },
    # Same AARVI form, typed and printed.
    "ADANI02__ADANI_INFRA__IN_p1.png": {
        "_kind": "printed",
        "employee_name": "SATISH SAXENA",
        "employee_code": "9100955164",
        "designation": "Store Keeper",
        "month_year": "April-2026",
        "client": "M/s.ADANI (Infra) India Ltd.",
        "project": "MPL",
        "location": "POCKET-3",
        "present_days": "26",
        "leaves": "0",
        "weekly_off": "4",
        "comp_off": "2",
    },
    # Samsung system-generated timesheet, different layout entirely.
    "SAMS01_Samsung_Engineeri_p1.png": {
        "_kind": "printed",
        "employee_name": "ASHOK VARMA",
        "employee_code": "34218437",
        "period": "01-Apr-2026 : 30-Apr-2026",
        "total_normal_hours": "136",
        "total_extra_hours": "55",
        "total_hours": "191",
        "calendar_days": "30",
        "total_working": "21",
    },
    # Warped phone-scanner capture, 21st-to-20th period.
    "SAFEARTH01___Safearth_Re_p1.png": {
        "_kind": "printed_warped",
        "employee_name": "ANIL LAL RATHORE",
        "employee_code": "SAFE900",
        "month_year": "June - July 26",
        "location": "Kadapa, Andhra Pradesh",
        "present_days": "25",
        "weekly_off": "05",
        "leaves": "00",
        "total_ot_hours": "0.0",
    },
    # KBR weekly timesheet -- a genuinely different template.
    "KBR02_Kellog_Brown___Roo_p1.png": {
        "_kind": "printed",
        "employee_name": "SAWRABH RAJ SAWRABH RAJ",
        "employee_code": "20029990",
        "week_end_date": "03-Jul-26",
        "total_hours": "40.00",
    },
}


def critical_fields(page: str) -> dict[str, str]:
    return {k: v for k, v in GROUND_TRUTH.get(page, {}).items()
            if not k.startswith("_")}

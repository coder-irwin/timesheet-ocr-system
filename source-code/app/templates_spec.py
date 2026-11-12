"""Per-template field schemas.

15 templates is a schema problem, not a training problem -- nothing here is
learned or fine-tuned. Each template declares its period length and which
optional columns exist; the extraction prompt and the validation rules are both
generated from that declaration, so adding template #16 is a dict entry.

Add new templates at the bottom. `hints` are literal strings the classifier
looks for and are also injected into the extraction prompt as orientation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TemplateSpec:
    key: str
    label: str
    period_days: int                 # 15 or 30/31 -- drives the day-count rule
    has_in_out: bool = True          # day-wise in/out clock times present
    has_ot: bool = True
    has_allowance: bool = False
    allowance_labels: tuple[str, ...] = ()
    has_leave_column: bool = True
    hints: tuple[str, ...] = ()      # substrings that identify this template
    notes: str = ""

    def day_fields(self) -> list[str]:
        f = ["day", "status"]
        if self.has_in_out:
            f += ["in_time", "out_time"]
        f += ["normal_hours"]
        if self.has_ot:
            f += ["ot_hours"]
        if self.has_allowance:
            f += list(self.allowance_labels)
        return f

    def summary_fields(self) -> list[str]:
        f = ["total_normal_hours", "mandays", "man_hours"]
        if self.has_ot:
            f.append("total_ot_hours")
        if self.has_leave_column:
            f.append("total_leave_days")
        f.append("total_present_days")
        if self.has_allowance:
            f += [f"total_{a}" for a in self.allowance_labels]
        return f


# Status vocabulary is fixed across templates so validation can reason about it.
# P=present, A=absent, L=leave, W=weekly off, H=holiday.
STATUS_VALUES = ("P", "A", "L", "W", "H")
STATUS_PRESENT = ("P",)
STATUS_LEAVE = ("L",)
STATUS_NONWORKING = ("W", "H")

TEMPLATES: dict[str, TemplateSpec] = {
    "t30_std": TemplateSpec(
        key="t30_std",
        label="Standard monthly (30/31 day, in/out + OT)",
        period_days=31,
        hints=("monthly attendance", "in time", "out time", "o.t."),
        notes="Most common variant across sites.",
    ),
    "t30_no_inout": TemplateSpec(
        key="t30_no_inout",
        label="Monthly, hours only (no in/out clock columns)",
        period_days=31,
        has_in_out=False,
        hints=("normal hours", "total hours"),
    ),
    "t15_fortnight": TemplateSpec(
        key="t15_fortnight",
        label="Fortnightly (15 day cycle)",
        period_days=15,
        hints=("fortnight", "15 days", "1st half", "2nd half"),
        notes="Two per month per employee; period_start distinguishes halves.",
    ),
    "t30_allowance": TemplateSpec(
        key="t30_allowance",
        label="Monthly with allowance columns",
        period_days=31,
        has_allowance=True,
        allowance_labels=("night_allowance", "site_allowance"),
        hints=("night allowance", "site allowance", "n.a.", "conveyance"),
    ),
}

DEFAULT_TEMPLATE = "t30_std"


def get(key: str | None) -> TemplateSpec:
    return TEMPLATES.get(key or DEFAULT_TEMPLATE, TEMPLATES[DEFAULT_TEMPLATE])


def classifier_menu() -> str:
    """Rendered into the classifier prompt."""
    lines = []
    for t in TEMPLATES.values():
        bits = [f"{t.period_days}-day period"]
        bits.append("has in/out times" if t.has_in_out else "no in/out times")
        if t.has_ot:
            bits.append("has OT column")
        if t.has_allowance:
            bits.append("has allowance columns (" + ", ".join(t.allowance_labels) + ")")
        lines.append(f'- "{t.key}": {t.label}. {"; ".join(bits)}.')
    return "\n".join(lines)


def json_shape(spec: TemplateSpec) -> dict[str, Any]:
    """The JSON shape we ask the model for, used in the prompt and to validate
    the parsed structure before anything downstream touches it."""
    day = {f: None for f in spec.day_fields()}
    return {
        "employee_name": None,
        "employee_code": None,
        "project": None,
        "period_start": None,
        "period_end": None,
        "days": [day],
        "summary": {f: None for f in spec.summary_fields()},
    }

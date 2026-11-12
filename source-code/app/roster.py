"""Employee master roster matching.

The single biggest accuracy lever available. Handwritten names are the hardest
field for any OCR, but they are drawn from a closed set of ~3,000 known people
-- so we do not need to *read* the name correctly, only to identify which
roster entry it is.

The rule that matters: a near-tie between two candidates is reported as
ambiguous rather than resolved to the nearest one. Silently attributing a page
to the wrong employee is the exact failure that freezes a 50-person invoice for
months, and it is far worse than asking a reviewer to click a name.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process

from . import config


@dataclass
class Match:
    status: str                 # exact_code | strong_name | ambiguous | none
    roster_code: str | None = None
    roster_name: str | None = None
    name_score: float | None = None
    candidates: list[str] = field(default_factory=list)


def _norm_code(s: Any) -> str:
    """Codes are typed by hand and photographed; strip the noise that carries
    no information so 'EMP-0421 ' and 'emp0421' collide as intended."""
    return "".join(ch for ch in str(s or "").upper() if ch.isalnum())


def _norm_name(s: Any) -> str:
    return " ".join(str(s or "").upper().split())


class Roster:
    """Loaded from a CSV with at least `employee_code` and `employee_name`
    columns; any other columns are carried through to the export untouched."""

    def __init__(self, rows: list[dict[str, str]] | None = None):
        self.rows = rows or []
        self._by_code: dict[str, dict] = {}
        self._names: list[str] = []
        self._name_to_row: dict[str, dict] = {}
        for r in self.rows:
            code = _norm_code(r.get("employee_code"))
            name = _norm_name(r.get("employee_name"))
            if code:
                self._by_code[code] = r
            if name:
                self._names.append(name)
                self._name_to_row.setdefault(name, r)

    @property
    def empty(self) -> bool:
        return not self.rows

    def __len__(self) -> int:
        return len(self.rows)

    @classmethod
    def from_csv(cls, path: str | Path) -> "Roster":
        p = Path(path)
        if not p.exists():
            return cls([])
        # utf-8-sig: rosters come out of Excel and carry a BOM more often than not.
        with p.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            rows = [{(k or "").strip().lower().replace(" ", "_"): (v or "").strip()
                     for k, v in row.items()} for row in reader]
        return cls(rows)

    def match(self, name: str = "", code: str = "") -> Match:
        ncode, nname = _norm_code(code), _norm_name(name)

        # 1. Exact code hit is authoritative. We still score the name against it
        #    so a code/name conflict surfaces instead of passing silently.
        if ncode and ncode in self._by_code:
            row = self._by_code[ncode]
            score = (fuzz.token_sort_ratio(nname, _norm_name(row.get("employee_name")))
                     if nname else None)
            return Match("exact_code", row.get("employee_code"),
                         row.get("employee_name"), score)

        if not nname or not self._names:
            return Match("none")

        # 2. Fall back to the name. Take the top few so we can measure the
        #    margin -- that margin is what separates a match from a guess.
        #    The margin must be measured against the nearest DIFFERENT name:
        #    the same person legitimately appears in the roster more than once
        #    (one row per client), and two rows both reading 'Yogesh Raman'
        #    are not an ambiguity about who this is -- only about which code,
        #    and a name match never supplies a code anyway.
        top = process.extract(nname, self._names, scorer=fuzz.token_sort_ratio,
                              limit=5)
        if not top:
            return Match("none")

        best_name, best_score, _ = top[0]
        if best_score < config.ROSTER_MIN_SCORE:
            return Match("none", candidates=[t[0] for t in top])

        rival = next((t for t in top[1:]
                      if _norm_name(t[0]) != _norm_name(best_name)), None)
        if rival is not None:
            if best_score - rival[1] < config.ROSTER_MIN_MARGIN:
                return Match("ambiguous", candidates=[t[0] for t in top[:2]],
                             name_score=best_score)

        row = self._name_to_row[best_name]
        return Match("strong_name", row.get("employee_code"),
                     row.get("employee_name"), best_score)

    def suggest(self, name: str, limit: int = 5) -> list[dict[str, Any]]:
        """Candidate list for the review UI dropdown."""
        if not self._names:
            return []
        hits = process.extract(_norm_name(name), self._names,
                               scorer=fuzz.token_sort_ratio, limit=limit * 2)
        out, seen = [], set()
        for n, score, _ in hits:
            row = self._name_to_row[n]
            display = row.get("employee_name")
            if _norm_name(display) in seen:      # one row per client -> dupes
                continue
            seen.add(_norm_name(display))
            out.append({
                "employee_code": row.get("employee_code"),
                "employee_name": display,
                "score": round(score, 1),
            })
            if len(out) >= limit:
                break
        return out

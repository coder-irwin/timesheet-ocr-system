"""Live state + log for a long corpus run, so it can be watched while it runs.

A full accuracy pass over the corpus is 1,218 pages and takes hours. Without
this, the only way to know what it is doing is to wait for it to finish, and
the only thing you learn at the end is one number. This records, per page, what
was read and whether it was right, and keeps a small JSON file up to date that
a dashboard can poll.

Two deliberate choices:

* The rate is measured over a sliding window of at least 15 minutes, never over
  the last page. Page times vary by an order of magnitude -- a clean typed sheet
  is seconds, a hard handwritten header with the VLM is a minute or two -- so a
  short window produces an ETA that swings wildly and is worse than no ETA.
* Everything is flushed on every page. A run that dies at hour four must leave
  behind everything it learned up to hour four.
"""
from __future__ import annotations

import json
import time
from collections import Counter, deque
from pathlib import Path

BASE = Path(__file__).parent.parent
STATE = BASE / "data" / "corpus_run_state.json"
RUNLOG = BASE / "data" / "corpus_run.log"

WINDOW_MIN = 15.0          # shortest history before the rate is called measured
WINDOW_MAX = 45.0


class RunState:
    def __init__(self, total_pages: int, label: str, pipeline_version: str,
                 resumed: int = 0) -> None:
        self.total = max(total_pages, 1)
        self.label = label
        self.version = pipeline_version
        self.started = time.time()
        self.resumed = resumed
        self.n = 0
        self.hist: deque[tuple[float, int]] = deque(maxlen=600)
        self.days_ok = 0
        self.days_cmp = 0
        self.name_ok = 0
        self.name_cmp = 0
        self.matched = 0
        self.escaped = 0        # wrong day on a page we called clean
        self.flagged_bad = 0    # wrong day on a page we did flag
        self.reasons: Counter[str] = Counter()
        self.per_ds: dict[str, Counter] = {}
        self.errors: list[dict] = []
        self.recent: deque[str] = deque(maxlen=40)
        RUNLOG.parent.mkdir(parents=True, exist_ok=True)
        self.log = RUNLOG.open("a", buffering=1)
        self._say(f"===== RUN START {label} · pipeline {pipeline_version} · "
                  f"{total_pages} pages ({resumed} already scored) =====")

    # ------------------------------------------------------------------
    def _say(self, line: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log.write(f"{stamp} {line}\n")
        self.recent.append(f"{stamp} {line}")

    def page(self, res: dict, secs: float | None = None, from_ckpt: bool = False) -> None:
        """Record one scored page and refresh the state file."""
        self.n += 1
        ds = res.get("dataset", "?")
        d = self.per_ds.setdefault(ds, Counter())
        d["pages"] += 1

        if not res.get("matched"):
            why = res.get("reason", "unmatched")
            self.reasons[why] += 1
            d["unmatched"] += 1
            if why in ("page_error", "pdf_error"):
                self.errors.append({"pdf": res.get("pdf"), "page": res.get("page"),
                                    "reason": why})
            if not from_ckpt:
                self._say(f"  {ds:8} {str(res.get('pdf'))[-52:]} p{res.get('page')} "
                          f"-> no truth match ({why})"
                          + (f"  read name {res.get('extracted_name')!r}"
                             if res.get("extracted_name") else ""))
        else:
            self.matched += 1
            d["matched"] += 1
            ok, cmp_ = res.get("days_ok", 0), res.get("days_cmp", 0)
            self.days_ok += ok
            self.days_cmp += cmp_
            d["days_ok"] += ok
            d["days_cmp"] += cmp_
            self.name_cmp += 1
            self.name_ok += bool(res.get("name_ok"))
            d["name_ok"] += bool(res.get("name_ok"))
            wrong = cmp_ - ok
            if wrong:
                if res.get("flagged"):
                    self.flagged_bad += 1
                    d["flagged_bad"] += 1
                else:
                    # The metric that matters: a wrong day on a page nobody was
                    # asked to check.
                    self.escaped += 1
                    d["escaped"] += 1
            if not from_ckpt:
                mark = "ok " if not wrong else ("FLAGGED" if res.get("flagged") else "ESCAPED")
                self._say(f"  {ds:8} {str(res.get('pdf'))[-52:]} p{res.get('page')} "
                          f"-> {ok}/{cmp_} days  {mark}  "
                          f"name={'y' if res.get('name_ok') else 'n'}  "
                          f"status={res.get('page_status')}"
                          + (f"  {secs:.1f}s" if secs else ""))
        self.flush()

    # ------------------------------------------------------------------
    def rate(self) -> tuple[float, str]:
        """Pages per minute over the longest window up to 45 minutes."""
        now = time.time()
        if not self.hist or now - self.hist[-1][0] >= 20:
            self.hist.append((now, self.n))
        win = [s for s in self.hist
               if WINDOW_MIN * 60 <= now - s[0] <= WINDOW_MAX * 60]
        base = win[0] if win else (self.hist[0] if self.hist else None)
        if base and self.n > base[1] and now - base[0] > 60:
            mins = (now - base[0]) / 60.0
            tag = "measured" if mins >= WINDOW_MIN else f"early ({int(mins)} min)"
            return (self.n - base[1]) / mins, tag
        return 0.0, "warming up"

    def flush(self) -> None:
        r, tag = self.rate()
        left = max(self.total - self.resumed - self.n, 0)
        eta = (left / r) if r > 0 else None
        acc = 100.0 * self.days_ok / self.days_cmp if self.days_cmp else None
        state = {
            "label": self.label,
            "pipeline": self.version,
            "started": self.started,
            "updated": time.time(),
            "total_pages": self.total,
            "resumed": self.resumed,
            "done": self.n + self.resumed,
            "left": left,
            "pct": round(100.0 * (self.n + self.resumed) / self.total, 2),
            "rate_per_min": round(r, 2),
            "rate_quality": tag,
            "eta_minutes": None if eta is None else round(eta, 1),
            "elapsed_minutes": round((time.time() - self.started) / 60.0, 1),
            "accuracy": {
                "day_status_pct": None if acc is None else round(acc, 2),
                "days_ok": self.days_ok,
                "days_compared": self.days_cmp,
                "name_pct": (round(100.0 * self.name_ok / self.name_cmp, 2)
                             if self.name_cmp else None),
                "name_ok": self.name_ok,
                "name_compared": self.name_cmp,
            },
            "safety": {
                "pages_with_a_wrong_day_that_were_flagged": self.flagged_bad,
                "pages_with_a_wrong_day_NOT_flagged": self.escaped,
                "caught_pct": (round(100.0 * self.flagged_bad /
                                     (self.flagged_bad + self.escaped), 2)
                               if (self.flagged_bad + self.escaped) else None),
            },
            "matched_pages": self.matched,
            "unmatched_reasons": dict(self.reasons.most_common()),
            "per_dataset": {k: dict(v) for k, v in self.per_ds.items()},
            "errors": self.errors[-25:],
            "recent_log": list(self.recent),
        }
        tmp = STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1))
        tmp.replace(STATE)          # atomic: the dashboard never sees half a file

    def done(self) -> None:
        self._say(f"===== RUN END · {self.n} pages scored this session · "
                  f"day status {self.days_ok}/{self.days_cmp} · "
                  f"not-flagged wrong pages {self.escaped} =====")
        self.flush()
        self.log.close()

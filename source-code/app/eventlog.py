"""A plain-language activity feed for the UI.

Why not just show the server log
--------------------------------
The uvicorn/RapidOCR log is written for whoever is debugging the machine. The
person watching a demo wants to know what the system is *doing to their
paperwork*: which page it is on, what it found, and why a page got flagged.
Those are different audiences, so this is a different stream -- short, ordered,
and written in the words the client uses ("read 30 day rows", not
"cluster_by_pitch n=30").

Kept in memory on purpose. It is a live view, not a record; the durable record
is the audit trail in SQLite, which is what a compliance question needs.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Literal

Level = Literal["info", "good", "warn", "bad", "step"]

_MAX = 600                      # a few full batches; older lines fall off
_lock = threading.Lock()
_events: deque[dict[str, Any]] = deque(maxlen=_MAX)
_seq = 0


def emit(message: str, level: Level = "info",
         page_id: int | None = None, detail: str | None = None) -> None:
    """Record one line. Safe to call from any worker thread."""
    global _seq
    with _lock:
        _seq += 1
        _events.append({
            "seq": _seq,
            "t": time.time(),
            "level": level,
            "message": message,
            "page_id": page_id,
            "detail": detail,
        })


def since(after: int = 0, limit: int = 200) -> list[dict[str, Any]]:
    """Everything newer than `after`, oldest first.

    The client passes back the last sequence number it saw, so a poll returns
    only what is new -- no duplicates, no re-rendering the whole feed.
    """
    with _lock:
        out = [e for e in _events if e["seq"] > after]
    return out[-limit:]


def latest_seq() -> int:
    with _lock:
        return _seq


def clear() -> None:
    global _seq
    with _lock:
        _events.clear()
        _seq = 0

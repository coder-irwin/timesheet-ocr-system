"""SQLite persistence + audit log.

SQLite rather than Postgres because the whole product must run on a 16GB
Windows laptop with no infrastructure -- a DB server is an installation step,
a support burden, and a thing that can fail during a demo. At 3,000 pages a
month this workload is nowhere near SQLite's limits.

The audit log is a hard requirement, not a nice-to-have: the client is
govt-adjacent and will be asked who changed which number and when.
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS batch (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    created_at    REAL NOT NULL,
    note          TEXT
);

CREATE TABLE IF NOT EXISTS page (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id       INTEGER NOT NULL REFERENCES batch(id) ON DELETE CASCADE,
    source_name    TEXT NOT NULL,
    image_path     TEXT NOT NULL,
    page_hash      TEXT NOT NULL,
    template_key   TEXT,
    status         TEXT NOT NULL DEFAULT 'pending',
    record_json    TEXT,
    issues_json    TEXT,
    disagree_json  TEXT,
    meta_json      TEXT,
    from_cache     INTEGER NOT NULL DEFAULT 0,
    extract_ms     INTEGER,
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL
);

-- Same page uploaded twice must resolve to the same extraction, never a
-- second inference run.
CREATE INDEX IF NOT EXISTS idx_page_hash   ON page(page_hash);
CREATE INDEX IF NOT EXISTS idx_page_batch  ON page(batch_id);
CREATE INDEX IF NOT EXISTS idx_page_status ON page(status);

CREATE TABLE IF NOT EXISTS audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    page_id     INTEGER REFERENCES page(id) ON DELETE CASCADE,
    ts          REAL NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    field       TEXT,
    old_value   TEXT,
    new_value   TEXT,
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_page ON audit(page_id);

-- One person checks a page at a time. A lock is claimed on open, renewed
-- while the page is on screen, released on save / leave, and expires after
-- LOCK_TTL_S of silence so a closed laptop never freezes a page.
CREATE TABLE IF NOT EXISTS page_lock (
    page_id     INTEGER PRIMARY KEY REFERENCES page(id) ON DELETE CASCADE,
    actor       TEXT NOT NULL,
    since       REAL NOT NULL,
    heartbeat   REAL NOT NULL
);
"""

LOCK_TTL_S = 300.0


def lock_status(page_id: int) -> dict | None:
    """Who holds the page now, or None if free / expired."""
    with db() as conn:
        row = conn.execute("SELECT * FROM page_lock WHERE page_id = ?", (page_id,)).fetchone()
    if not row:
        return None
    if time.time() - row["heartbeat"] > LOCK_TTL_S:
        return None
    return dict(row)


def acquire_lock(page_id: int, actor: str) -> dict:
    """Claim the page for `actor`. Returns {"ok": True} or {"ok": False, "held_by": name, "since": ts}."""
    now = time.time()
    with db() as conn:
        row = conn.execute("SELECT * FROM page_lock WHERE page_id = ?", (page_id,)).fetchone()
        if row and row["actor"] != actor and now - row["heartbeat"] <= LOCK_TTL_S:
            return {"ok": False, "held_by": row["actor"], "since": row["since"]}
        conn.execute("INSERT INTO page_lock (page_id, actor, since, heartbeat) VALUES (?,?,?,?) "
                     "ON CONFLICT(page_id) DO UPDATE SET actor=excluded.actor, "
                     "since=CASE WHEN page_lock.actor=excluded.actor THEN page_lock.since ELSE excluded.since END, "
                     "heartbeat=excluded.heartbeat",
                     (page_id, actor, now, now))
    return {"ok": True, "held_by": actor, "since": now}


def release_lock(page_id: int, actor: str) -> None:
    with db() as conn:
        conn.execute("DELETE FROM page_lock WHERE page_id = ? AND actor = ?", (page_id, actor))


def locks_for(page_ids: list[int]) -> dict[int, str]:
    """page_id -> holder, for every live lock among the given pages."""
    if not page_ids:
        return {}
    cutoff = time.time() - LOCK_TTL_S
    q = ",".join("?" * len(page_ids))
    with db() as conn:
        rows = conn.execute(f"SELECT page_id, actor FROM page_lock WHERE heartbeat > ? AND page_id IN ({q})",
                            [cutoff, *page_ids]).fetchall()
    return {r["page_id"]: r["actor"] for r in rows}



def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL lets the UI read while a batch is still being written.
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init() -> None:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.executescript(SCHEMA)


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------

def create_batch(name: str, note: str = "") -> int:
    with db() as conn:
        cur = conn.execute(
            "INSERT INTO batch (name, created_at, note) VALUES (?, ?, ?)",
            (name, time.time(), note))
        return int(cur.lastrowid)


def list_batches() -> list[dict]:
    with db() as conn:
        rows = conn.execute("""
            SELECT b.id, b.name, b.created_at, b.note,
                   COUNT(p.id)                                        AS pages,
                   SUM(p.status = 'needs_review')                     AS needs_review,
                   SUM(p.status = 'clean')                            AS clean,
                   SUM(p.status = 'review_optional')                  AS review_optional,
                   SUM(p.status = 'corrected')                        AS corrected,
                   SUM(p.status IN ('pending','processing'))          AS pending,
                   SUM(p.status = 'error')                            AS errored,
                   SUM(p.from_cache)                                  AS from_cache
            FROM batch b LEFT JOIN page p ON p.batch_id = b.id
            GROUP BY b.id ORDER BY b.created_at DESC
        """).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def add_page(batch_id: int, source_name: str, image_path: str,
             page_hash: str, meta: dict | None = None) -> int:
    now = time.time()
    with db() as conn:
        cur = conn.execute("""
            INSERT INTO page (batch_id, source_name, image_path, page_hash,
                              meta_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (batch_id, source_name, image_path, page_hash,
             json.dumps(meta or {}), now, now))
        return int(cur.lastrowid)


def set_page_result(page_id: int, *, template_key: str, status: str,
                    record: dict, issues: list, disagreements: dict,
                    from_cache: bool, extract_ms: int) -> None:
    with db() as conn:
        conn.execute("""
            UPDATE page SET template_key = ?, status = ?, record_json = ?,
                            issues_json = ?, disagree_json = ?, from_cache = ?,
                            extract_ms = ?, updated_at = ?
            WHERE id = ?""",
            (template_key, status, json.dumps(record, ensure_ascii=False,
                                              default=str),
             json.dumps(issues, ensure_ascii=False, default=str),
             # Stores whatever diagnostic blob the pipeline produced (OCR
             # confidence profile, route, anchors found). Serialised as-is:
             # an earlier version coerced each value with list(), which
             # crashed on the integer fields and lost every successfully
             # extracted page at the persistence step.
             json.dumps(disagreements or {}, ensure_ascii=False, default=str),
             1 if from_cache else 0, extract_ms, time.time(), page_id))


def set_page_status(page_id: int, status: str) -> None:
    with db() as conn:
        conn.execute("UPDATE page SET status = ?, updated_at = ? WHERE id = ?",
                     (status, time.time(), page_id))


def get_page(page_id: int) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM page WHERE id = ?", (page_id,)).fetchone()
    return _hydrate(row) if row else None


def list_pages(batch_id: int | None = None,
               status: str | None = None) -> list[dict]:
    q = ["SELECT * FROM page WHERE 1=1"]
    args: list[Any] = []
    if batch_id is not None:
        q.append("AND batch_id = ?")
        args.append(batch_id)
    if status:
        if status == "flagged":
            # The review queue: only pages that actually need a human.
            q.append("AND status IN ('needs_review','review_optional','error')")
        else:
            q.append("AND status = ?")
            args.append(status)
    q.append("ORDER BY id ASC")
    with db() as conn:
        rows = conn.execute(" ".join(q), args).fetchall()
    return [_hydrate(r) for r in rows]


def find_by_hash(page_hash: str, exclude_page_id: int | None = None) -> dict | None:
    """Previous extraction of the identical page, from any batch."""
    with db() as conn:
        if exclude_page_id:
            row = conn.execute(
                "SELECT * FROM page WHERE page_hash = ? AND id != ? "
                "AND record_json IS NOT NULL ORDER BY id DESC LIMIT 1",
                (page_hash, exclude_page_id)).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM page WHERE page_hash = ? AND record_json IS NOT NULL "
                "ORDER BY id DESC LIMIT 1", (page_hash,)).fetchone()
    return _hydrate(row) if row else None


def update_record(page_id: int, record: dict, issues: list, status: str) -> None:
    with db() as conn:
        conn.execute("""
            UPDATE page SET record_json = ?, issues_json = ?, status = ?,
                            updated_at = ? WHERE id = ?""",
            (json.dumps(record, ensure_ascii=False),
             json.dumps(issues, ensure_ascii=False), status,
             time.time(), page_id))


def _hydrate(row: sqlite3.Row) -> dict:
    d = dict(row)
    for src, dest in (("record_json", "record"), ("issues_json", "issues"),
                      ("disagree_json", "disagreements"), ("meta_json", "meta")):
        raw = d.pop(src, None)
        try:
            d[dest] = json.loads(raw) if raw else ({} if dest != "issues" else [])
        except json.JSONDecodeError:
            d[dest] = {} if dest != "issues" else []
    return d


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

def audit(page_id: int | None, actor: str, action: str, field: str | None = None,
          old: Any = None, new: Any = None, detail: str = "") -> None:
    with db() as conn:
        conn.execute("""
            INSERT INTO audit (page_id, ts, actor, action, field, old_value,
                               new_value, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (page_id, time.time(), actor, action, field,
             None if old is None else str(old),
             None if new is None else str(new), detail))


def audit_trail(page_id: int) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM audit WHERE page_id = ? ORDER BY ts ASC",
            (page_id,)).fetchall()
    return [dict(r) for r in rows]


def audit_all(limit: int = 500) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT a.*, p.source_name FROM audit a "
            "LEFT JOIN page p ON p.id = a.page_id "
            "ORDER BY a.ts DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]

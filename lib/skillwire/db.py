"""SQLite storage at ~/.claude/skillwire/skillwire.db."""
from __future__ import annotations

import sqlite3
import time

from . import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,
    session_id  TEXT,
    event       TEXT    NOT NULL,     -- hook event name
    skill       TEXT,                 -- NULL for prompt rows
    outcome     TEXT    NOT NULL,     -- prompt | routed | loaded | failed | denied | redirected
    module      TEXT,                 -- which module decided (denied/redirected/routed)
    redirect_to TEXT,
    detail      TEXT,
    duration_ms INTEGER,
    variant     TEXT,                 -- active A/B description variant, if any
    prompt_hash TEXT,
    prompt      TEXT,                 -- only when telemetry.store_prompts is true
    cwd         TEXT
);
CREATE INDEX IF NOT EXISTS events_session ON events(session_id);
CREATE INDEX IF NOT EXISTS events_skill_ts ON events(skill, ts);
CREATE TABLE IF NOT EXISTS ab_rotations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    skill       TEXT NOT NULL,
    variant     TEXT NOT NULL,
    description TEXT NOT NULL,
    started_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ab_skill ON ab_rotations(skill, started_at);
"""

EVENT_COLUMNS = ("ts", "session_id", "event", "skill", "outcome", "module", "redirect_to",
                 "detail", "duration_ms", "variant", "prompt_hash", "prompt", "cwd")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(paths.db_path()), timeout=2.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def insert_event(conn: sqlite3.Connection, **row) -> None:
    row.setdefault("ts", time.time())
    unknown = set(row) - set(EVENT_COLUMNS)
    if unknown:
        raise ValueError(f"unknown event columns: {unknown}")
    cols = ", ".join(row)
    conn.execute(f"INSERT INTO events ({cols}) VALUES ({', '.join('?' * len(row))})", tuple(row.values()))
    conn.commit()


def last_prompt_hash(conn: sqlite3.Connection, session_id: str) -> str | None:
    r = conn.execute(
        "SELECT prompt_hash FROM events WHERE session_id=? AND outcome='prompt' ORDER BY ts DESC, id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    return r["prompt_hash"] if r else None


def loaded_in_session(conn: sqlite3.Connection, session_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT skill FROM events WHERE session_id=? AND outcome='loaded'", (session_id,)
    ).fetchall()
    return {r["skill"] for r in rows}


def active_variant(conn: sqlite3.Connection, skill: str) -> str | None:
    r = conn.execute(
        "SELECT variant FROM ab_rotations WHERE skill=? ORDER BY started_at DESC, id DESC LIMIT 1", (skill,)
    ).fetchone()
    return r["variant"] if r else None

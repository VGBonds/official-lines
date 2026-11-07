"""SQLite storage. One file, no server. Back it up by copying the file.

Tables
------
sources     health of each source (mirrors sources.yaml + last fetch result)
statements  one official item: url, title, date, text (private, for analysis), LLM extraction
events      a group of statements about the same incident/issue, plus its analysis
llm_calls   every LLM call with tokens and cost (the budget guard reads this)
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id            TEXT PRIMARY KEY,
    actor         TEXT NOT NULL,
    kind          TEXT NOT NULL,
    name          TEXT NOT NULL,
    url           TEXT,
    last_run_at   TEXT,
    last_ok_at    TEXT,
    last_error    TEXT,
    last_found    INTEGER DEFAULT 0,
    last_new      INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS statements (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id     TEXT NOT NULL REFERENCES sources(id),
    actor         TEXT NOT NULL,
    kind          TEXT NOT NULL,
    url           TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    published_at  TEXT,              -- ISO date-time (UTC) or NULL if unknown
    fetched_at    TEXT NOT NULL,
    text          TEXT,              -- full text, private: used for analysis, never published
    extraction    TEXT,              -- JSON from the extraction step
    extracted_at  TEXT,
    relevant      INTEGER,           -- 1 = substantive statement, 0 = noise (job ads, notices...)
    domain        TEXT,              -- politics | economics | both | other
    event_id      INTEGER REFERENCES events(id),
    grouped_at    TEXT
);
CREATE INDEX IF NOT EXISTS idx_statements_event ON statements(event_id);
CREATE INDEX IF NOT EXISTS idx_statements_published ON statements(published_at);

CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    slug          TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL,
    summary       TEXT,
    domain        TEXT,
    created_at    TEXT NOT NULL,
    first_seen    TEXT,
    last_seen     TEXT,
    featured      INTEGER DEFAULT 0, -- editor's pick (shown first, preferred by the weekly brief)
    analysis      TEXT,              -- JSON: LLM analysis + computed metrics
    analysed_at   TEXT,
    analysed_statement_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS llm_calls (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    at            TEXT NOT NULL,
    purpose       TEXT NOT NULL,
    model         TEXT NOT NULL,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    cost_usd      REAL
);
"""


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection):
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def loads(value: str | None):
    return json.loads(value) if value else None


def dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)

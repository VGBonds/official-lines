"""SQLite storage. One file, no server. Back it up by copying the file.

Tables
------
sources     health of each source (mirrors sources.yaml + last fetch result)
statements  one official item: url, title, date, text (private, for analysis), LLM extraction
parts       one issue within a statement (a press briefing has many, most statements one);
            parts, not whole statements, are grouped into events
events      a group of parts about the same development, plus its analysis
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
    domain        TEXT               -- politics | economics | both | other
);
CREATE INDEX IF NOT EXISTS idx_statements_published ON statements(published_at);

CREATE TABLE IF NOT EXISTS parts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id  INTEGER NOT NULL REFERENCES statements(id) ON DELETE CASCADE,
    idx           INTEGER NOT NULL,  -- order within the statement, from 0
    issue         TEXT NOT NULL,
    summary       TEXT,
    data          TEXT,              -- JSON: topics, places, claims, key_terms
    text_start    INTEGER,           -- where the passage sits in statements.text
    text_end      INTEGER,           --   (NULL if we could not locate it)
    event_id      INTEGER REFERENCES events(id),
    grouped_at    TEXT,
    UNIQUE (statement_id, idx)
);
CREATE INDEX IF NOT EXISTS idx_parts_event ON parts(event_id);

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
    analysed_statement_count INTEGER DEFAULT 0  -- number of parts at the last analysis
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
    _migrate(conn)
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    return conn


SCHEMA_VERSION = 2


def _migrate(conn: sqlite3.Connection) -> None:
    """Version 1 grouped whole statements (statements.event_id). Version 2 groups parts.
    Upgrading keeps all collected statements and the cost ledger, and clears what the new
    steps redo: extraction, events and analyses. The next run re-extracts everything."""
    columns = {r[1] for r in conn.execute("PRAGMA table_info(statements)")}
    if "event_id" not in columns:
        return
    conn.executescript("""
        PRAGMA foreign_keys=OFF;
        BEGIN;
        DROP INDEX IF EXISTS idx_statements_event;
        CREATE TABLE statements_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL REFERENCES sources(id), actor TEXT NOT NULL,
            kind TEXT NOT NULL, url TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
            published_at TEXT, fetched_at TEXT NOT NULL, text TEXT, extraction TEXT,
            extracted_at TEXT, relevant INTEGER, domain TEXT);
        INSERT INTO statements_v2 (id, source_id, actor, kind, url, title, published_at,
                                   fetched_at, text)
            SELECT id, source_id, actor, kind, url, title, published_at, fetched_at, text
            FROM statements;
        DROP TABLE statements;
        ALTER TABLE statements_v2 RENAME TO statements;
        DELETE FROM events;
        COMMIT;
        PRAGMA foreign_keys=ON;
    """)


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

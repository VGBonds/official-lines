"""Step 2: group relevant statements into events.

The cheap model sees the list of open events (active in the last OPEN_DAYS) and a batch of
new statements, and assigns each statement to an existing event or a new one.
"""

import logging
import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

import anthropic

from parallax.catalog import Catalog
from parallax.db import loads, now_iso, transaction
from parallax.llm import prompts
from parallax.llm.client import LLM, LLMError
from parallax.llm.schemas import Grouping

log = logging.getLogger(__name__)

BATCH_SIZE = 25
OPEN_DAYS = 21
MAX_OPEN_EVENTS = 150


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].rstrip("-")


def group_pending(conn: sqlite3.Connection, catalog: Catalog, llm: LLM, model: str) -> int:
    pending = conn.execute(
        """SELECT * FROM statements WHERE relevant = 1 AND event_id IS NULL
           ORDER BY COALESCE(published_at, fetched_at)"""
    ).fetchall()
    grouped = 0
    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start:start + BATCH_SIZE]
        open_events = _open_events(conn)
        user = prompts.GROUP_USER.format(
            events="\n".join(f"E{e['id']}: {e['title']} -- {e['summary']}" for e in open_events)
            or "(none yet)",
            statements="\n".join(_describe(s, catalog) for s in batch),
        )
        try:
            grouping = llm.structured(purpose="group", model=model, system=prompts.GROUP_SYSTEM,
                                      user=user, schema=Grouping, max_tokens=8000, effort="low")
        except (LLMError, anthropic.APIError) as e:
            log.warning("grouping batch failed: %s", e)
            continue
        grouped += apply_grouping(conn, batch, grouping, {e["id"] for e in open_events})
    return grouped


def _open_events(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    since = (datetime.now(UTC) - timedelta(days=OPEN_DAYS)).isoformat()
    return conn.execute(
        "SELECT id, title, summary FROM events WHERE last_seen >= ? OR last_seen IS NULL"
        " ORDER BY last_seen DESC LIMIT ?",
        (since, MAX_OPEN_EVENTS),
    ).fetchall()


def _describe(s: sqlite3.Row, catalog: Catalog) -> str:
    ex = loads(s["extraction"]) or {}
    return (f"[{s['id']}] {catalog.actor(s['actor']).name} ({s['kind']}), "
            f"{(s['published_at'] or s['fetched_at'])[:10]}: {s['title']}\n"
            f"    issue: {ex.get('issue', '')}\n    summary: {ex.get('summary', '')}")


def apply_grouping(conn: sqlite3.Connection, batch: list[sqlite3.Row], grouping: Grouping,
                   open_ids: set[int]) -> int:
    """Write the model's answer to the database. Anything malformed or missing gets its own
    new event, so no statement is lost."""
    now = now_iso()
    new_meta = {n.key: n for n in grouping.new_events}
    created: dict[str, int] = {}
    by_id = {s["id"]: s for s in batch}
    assigned: dict[int, int] = {}

    with transaction(conn):
        def create(title: str, summary: str, domain: str | None) -> int:
            cur = conn.execute(
                "INSERT INTO events (slug, title, summary, domain, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (f"tmp-{uuid.uuid4().hex}", title, summary, domain, now),
            )
            event_id = cur.lastrowid
            conn.execute("UPDATE events SET slug=? WHERE id=?",
                         (f"{slugify(title) or 'event'}-{event_id}", event_id))
            return event_id

        for a in grouping.assignments:
            s = by_id.get(a.statement_id)
            if s is None or s["id"] in assigned:
                continue
            target = a.event.strip()
            if re.fullmatch(r"E\d+", target) and int(target[1:]) in open_ids:
                assigned[s["id"]] = int(target[1:])
            elif target in new_meta:
                if target not in created:
                    meta = new_meta[target]
                    created[target] = create(meta.title, meta.summary, s["domain"])
                assigned[s["id"]] = created[target]

        for s in batch:  # the model skipped it: give it an event of its own
            if s["id"] not in assigned:
                ex = loads(s["extraction"]) or {}
                assigned[s["id"]] = create(ex.get("issue") or s["title"],
                                           ex.get("summary", ""), s["domain"])

        for statement_id, event_id in assigned.items():
            conn.execute("UPDATE statements SET event_id=?, grouped_at=? WHERE id=?",
                         (event_id, now, statement_id))
        refresh_event_dates(conn, set(assigned.values()))
    return len(assigned)


def refresh_event_dates(conn: sqlite3.Connection, event_ids: set[int]) -> None:
    for event_id in event_ids:
        conn.execute(
            """UPDATE events SET
                 first_seen = (SELECT MIN(COALESCE(published_at, fetched_at)) FROM statements
                               WHERE event_id = events.id),
                 last_seen  = (SELECT MAX(COALESCE(published_at, fetched_at)) FROM statements
                               WHERE event_id = events.id)
               WHERE id = ?""",
            (event_id,),
        )

"""Step 2: group the parts of relevant statements into events.

The cheap model sees the list of open events (active in the last OPEN_DAYS) and a batch of
new parts (one issue each, see extract.py), and assigns each part to an existing event or
a new one. A merge pass then looks at all open events side by side and folds duplicates
together (the same development filed twice, typically once per actor, because the parts
were in different batches).

Statements older than GROUP_WINDOW_DAYS are archived but not grouped.
"""

import logging
import re
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

import anthropic

from official_lines.catalog import Catalog
from official_lines.db import now_iso, transaction
from official_lines.llm import prompts
from official_lines.llm.client import LLM, LLMError
from official_lines.llm.schemas import Grouping, Merges

log = logging.getLogger(__name__)

BATCH_SIZE = 25
OPEN_DAYS = 21
MAX_OPEN_EVENTS = 400
GROUP_WINDOW_DAYS = 30

# A part together with the statement it comes from.
PART_COLUMNS = """p.*, s.actor, s.kind, s.url, s.title, s.published_at, s.fetched_at, s.domain,
    s.text, COALESCE(s.published_at, s.fetched_at) AS date,
    (SELECT COUNT(*) FROM parts q WHERE q.statement_id = p.statement_id) AS n_parts"""


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].rstrip("-")


def group_pending(conn: sqlite3.Connection, catalog: Catalog, llm: LLM, model: str) -> int:
    since = (datetime.now(UTC) - timedelta(days=GROUP_WINDOW_DAYS)).isoformat()
    pending = conn.execute(
        f"""SELECT {PART_COLUMNS} FROM parts p JOIN statements s ON s.id = p.statement_id
            WHERE s.relevant = 1 AND p.event_id IS NULL
              AND COALESCE(s.published_at, s.fetched_at) >= ?
            ORDER BY COALESCE(s.published_at, s.fetched_at), p.statement_id, p.idx""",
        (since,),
    ).fetchall()
    grouped = 0
    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start:start + BATCH_SIZE]
        open_events = _open_events(conn)
        user = prompts.GROUP_USER.format(
            events="\n".join(f"E{e['id']}: {e['title']} [{e['actors']}]" for e in open_events)
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
        """SELECT e.id, e.title, e.summary, e.first_seen, e.last_seen,
                  group_concat(DISTINCT s.actor) AS actors
           FROM events e LEFT JOIN parts p ON p.event_id = e.id
                LEFT JOIN statements s ON s.id = p.statement_id
           WHERE e.last_seen >= ? OR e.last_seen IS NULL
           GROUP BY e.id ORDER BY e.last_seen DESC LIMIT ?""",
        (since, MAX_OPEN_EVENTS),
    ).fetchall()


def merge_duplicates(conn: sqlite3.Connection, llm: LLM, model: str) -> int:
    """One call over all open events: fold duplicates of the same development together."""
    events = _open_events(conn)
    if len(events) < 2:
        return 0
    user = prompts.MERGE_USER.format(events="\n".join(
        f"{e['id']} | {(e['first_seen'] or '')[:10]}..{(e['last_seen'] or '')[:10]} | "
        f"{e['actors']} | {e['title']} -- {e['summary'] or ''}" for e in events))
    try:
        merges = llm.structured(purpose="merge", model=model, system=prompts.MERGE_SYSTEM,
                                user=user, schema=Merges, max_tokens=8000, effort="low")
    except (LLMError, anthropic.APIError) as e:
        log.warning("merge pass failed: %s", e)
        return 0
    return apply_merges(conn, merges, {e["id"] for e in events})


def apply_merges(conn: sqlite3.Connection, merges: Merges, valid_ids: set[int]) -> int:
    folded = 0
    gone: set[int] = set()
    with transaction(conn):
        for m in merges.merges:
            if m.keep not in valid_ids or m.keep in gone:
                continue
            for other in m.merge:
                if other == m.keep or other not in valid_ids or other in gone:
                    continue
                conn.execute("UPDATE parts SET event_id=? WHERE event_id=?", (m.keep, other))
                conn.execute("UPDATE events SET featured = MAX(featured, (SELECT featured FROM"
                             " events WHERE id=?)) WHERE id=?", (other, m.keep))
                conn.execute("DELETE FROM events WHERE id=?", (other,))
                gone.add(other)
                folded += 1
            refresh_event_dates(conn, {m.keep})
    return folded


def _describe(p: sqlite3.Row, catalog: Catalog) -> str:
    of = f" (passage {p['idx'] + 1} of {p['n_parts']})" if p["n_parts"] > 1 else ""
    return (f"[{p['id']}] {catalog.actor(p['actor']).name} ({p['kind']}), "
            f"{p['date'][:10]}: {p['title']}{of}\n"
            f"    issue: {p['issue']}\n    summary: {p['summary'] or ''}")


def apply_grouping(conn: sqlite3.Connection, batch: list[sqlite3.Row], grouping: Grouping,
                   open_ids: set[int]) -> int:
    """Write the model's answer to the database. Anything malformed or missing gets its own
    new event, so no part is lost."""
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
            s = by_id.get(a.part_id)
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
                assigned[s["id"]] = create(s["issue"] or s["title"], s["summary"] or "",
                                           s["domain"])

        for part_id, event_id in assigned.items():
            conn.execute("UPDATE parts SET event_id=?, grouped_at=? WHERE id=?",
                         (event_id, now, part_id))
        refresh_event_dates(conn, set(assigned.values()))
    return len(assigned)


def refresh_event_dates(conn: sqlite3.Connection, event_ids: set[int]) -> None:
    for event_id in event_ids:
        conn.execute(
            """UPDATE events SET
                 first_seen = (SELECT MIN(COALESCE(s.published_at, s.fetched_at))
                               FROM parts p JOIN statements s ON s.id = p.statement_id
                               WHERE p.event_id = events.id),
                 last_seen  = (SELECT MAX(COALESCE(s.published_at, s.fetched_at))
                               FROM parts p JOIN statements s ON s.id = p.statement_id
                               WHERE p.event_id = events.id)
               WHERE id = ?""",
            (event_id,),
        )

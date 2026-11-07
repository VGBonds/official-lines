"""Step 3: compare what different actors said about one event.

Only events where at least MIN_ACTORS different actors spoke are analysed, at most once a
day each, and at most `max_per_day` analyses a day in total. This keeps cost predictable.
"""

import logging
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

import anthropic

from parallax.catalog import Catalog
from parallax.db import dumps, loads, now_iso, transaction
from parallax.llm import prompts
from parallax.llm.client import LLM, LLMError
from parallax.llm.schemas import EventAnalysis
from parallax.pipeline import metrics

log = logging.getLogger(__name__)

MIN_ACTORS = 2
MAX_STATEMENTS_PER_ACTOR = 3
TEXT_EXCERPT_CHARS = 3000
REANALYSE_AFTER_HOURS = 20
SILENCE_LOOKBACK_DAYS = 60
SILENCE_MIN_STATEMENTS = 2


def analyses_today(conn: sqlite3.Connection) -> int:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return conn.execute(
        "SELECT COUNT(*) FROM llm_calls WHERE purpose='analyze' AND substr(at, 1, 10)=?",
        (today,),
    ).fetchone()[0]


def events_due(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    cutoff = (datetime.now(UTC) - timedelta(hours=REANALYSE_AFTER_HOURS)).isoformat()
    return conn.execute(
        """SELECT e.*, COUNT(DISTINCT s.actor) AS actors, COUNT(s.id) AS n
           FROM events e JOIN statements s ON s.event_id = e.id
           GROUP BY e.id
           HAVING actors >= ? AND n > e.analysed_statement_count
              AND (e.analysed_at IS NULL OR e.analysed_at < ?)
           ORDER BY e.featured DESC, actors DESC, e.last_seen DESC LIMIT ?""",
        (MIN_ACTORS, cutoff, limit),
    ).fetchall()


def analyze_due(conn: sqlite3.Connection, catalog: Catalog, llm: LLM, model: str,
                max_per_day: int, only_slug: str | None = None) -> int:
    if only_slug:
        events = conn.execute("SELECT * FROM events WHERE slug=?", (only_slug,)).fetchall()
    else:
        remaining = max_per_day - analyses_today(conn)
        if remaining <= 0:
            log.info("daily analysis cap reached (%d)", max_per_day)
            return 0
        events = events_due(conn, remaining)
    done = 0
    for event in events:
        try:
            analyze_event(conn, catalog, llm, model, event)
            done += 1
        except (LLMError, anthropic.APIError) as e:
            log.warning("analysis failed for %s: %s", event["slug"], e)
    return done


def select_statements(conn: sqlite3.Connection, event_id: int) -> list[sqlite3.Row]:
    rows = conn.execute(
        "SELECT * FROM statements WHERE event_id=? ORDER BY COALESCE(published_at, fetched_at)"
        " DESC", (event_id,),
    ).fetchall()
    per_actor: Counter = Counter()
    kept = []
    for r in rows:  # newest first, a few per actor so no single voice dominates the input
        if per_actor[r["actor"]] < MAX_STATEMENTS_PER_ACTOR:
            per_actor[r["actor"]] += 1
            kept.append(r)
    return list(reversed(kept))


def analyze_event(conn: sqlite3.Connection, catalog: Catalog, llm: LLM, model: str,
                  event: sqlite3.Row) -> dict:
    statements = select_statements(conn, event["id"])
    user = prompts.ANALYZE_USER.format(
        title=event["title"], statements="\n\n".join(_describe(s, catalog) for s in statements))
    result = llm.structured(purpose="analyze", model=model, system=prompts.ANALYZE_SYSTEM,
                            user=user, schema=EventAnalysis, max_tokens=16000, effort="medium")
    analysis = result.model_dump()

    texts: dict[str, str] = defaultdict(str)
    for s in statements:
        texts[s["actor"]] += " " + (s["text"] or "")
    computed = metrics.compute(analysis, texts, pair_history(conn, exclude_event=event["id"]))
    computed["silent"] = silent_actors(conn, event["id"], statements)

    payload = {"llm": analysis, "metrics": computed, "model": model,
               "statement_ids": [s["id"] for s in statements]}
    total = conn.execute("SELECT COUNT(*) FROM statements WHERE event_id=?",
                         (event["id"],)).fetchone()[0]
    with transaction(conn):
        conn.execute(
            "UPDATE events SET analysis=?, analysed_at=?, analysed_statement_count=?,"
            " title=?, summary=? WHERE id=?",
            (dumps(payload), now_iso(), total, result.title, result.summary, event["id"]),
        )
    return payload


def _describe(s: sqlite3.Row, catalog: Catalog) -> str:
    ex = loads(s["extraction"]) or {}
    claims = "\n".join(f"      - {c['text']} [quote: \"{c['quote']}\"]"
                       for c in ex.get("claims", []))
    terms = ", ".join(f"'{t['term']}' = {t['refers_to']}" for t in ex.get("key_terms", []))
    return (
        f"--- statement_id={s['id']} actor={s['actor']} "
        f"({catalog.actor(s['actor']).name}, {s['kind']}) "
        f"date={(s['published_at'] or s['fetched_at'])[:10]}\n"
        f"title: {s['title']}\n"
        f"extracted claims:\n{claims}\n"
        f"key terms: {terms}\n"
        f"text excerpt:\n{(s['text'] or '')[:TEXT_EXCERPT_CHARS]}"
    )


def pair_history(conn: sqlite3.Connection, exclude_event: int) -> dict[str, list[float]]:
    """Agreement scores of every actor pair over earlier analysed events (the baseline)."""
    history: dict[str, list[float]] = defaultdict(list)
    for row in conn.execute(
        "SELECT analysis FROM events WHERE analysis IS NOT NULL AND id != ?", (exclude_event,)
    ):
        for key, v in (loads(row[0])["metrics"].get("pairs") or {}).items():
            history[key].append(v["score"])
    return history


def silent_actors(conn: sqlite3.Connection, event_id: int,
                  statements: list[sqlite3.Row]) -> list[dict]:
    """Actors that spoke repeatedly on this event's topics lately, but not on this event."""
    topics = Counter(t for s in statements
                     for t in (loads(s["extraction"]) or {}).get("topics", []))
    main_topics = {t for t, _ in topics.most_common(3)}
    if not main_topics:
        return []
    present = {s["actor"] for s in statements}
    since = (datetime.now(UTC) - timedelta(days=SILENCE_LOOKBACK_DAYS)).isoformat()
    counts: Counter = Counter()
    for row in conn.execute(
        "SELECT actor, extraction FROM statements WHERE relevant=1 AND event_id != ?"
        " AND COALESCE(published_at, fetched_at) >= ?", (event_id, since),
    ):
        if row["actor"] not in present and main_topics & set(
                (loads(row["extraction"]) or {}).get("topics", [])):
            counts[row["actor"]] += 1
    return [{"actor": a, "recent_statements_on_topic": n}
            for a, n in counts.most_common() if n >= SILENCE_MIN_STATEMENTS]

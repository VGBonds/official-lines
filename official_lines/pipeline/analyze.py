"""Step 3: compare what different actors said about one event.

The input is the parts (one issue each) filed under the event: for each, the extracted
claims and the passage of the original text it comes from.

Only events where at least MIN_ACTORS different actors spoke are analysed, at most once a
day each, and at most `max_per_day` analyses a day in total. This keeps cost predictable.
"""

import logging
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

import anthropic

from official_lines.catalog import Catalog
from official_lines.db import dumps, loads, now_iso, transaction
from official_lines.llm import prompts
from official_lines.llm.client import LLM, LLMError
from official_lines.llm.schemas import EventAnalysis
from official_lines.pipeline import metrics
from official_lines.pipeline.events import PART_COLUMNS

log = logging.getLogger(__name__)

MIN_ACTORS = 2
MAX_PARTS_PER_ACTOR = 3
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
        """SELECT e.*, COUNT(DISTINCT s.actor) AS actors, COUNT(p.id) AS n
           FROM events e JOIN parts p ON p.event_id = e.id
                JOIN statements s ON s.id = p.statement_id
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


def select_parts(conn: sqlite3.Connection, event_id: int) -> list[sqlite3.Row]:
    rows = conn.execute(
        f"""SELECT {PART_COLUMNS} FROM parts p JOIN statements s ON s.id = p.statement_id
            WHERE p.event_id=? ORDER BY date DESC""", (event_id,),
    ).fetchall()
    per_actor: Counter = Counter()
    kept = []
    for r in rows:  # newest first, a few per actor so no single voice dominates the input
        if per_actor[r["actor"]] < MAX_PARTS_PER_ACTOR:
            per_actor[r["actor"]] += 1
            kept.append(r)
    return list(reversed(kept))


def analyze_event(conn: sqlite3.Connection, catalog: Catalog, llm: LLM, model: str,
                  event: sqlite3.Row) -> dict:
    parts = select_parts(conn, event["id"])
    user = prompts.ANALYZE_USER.format(
        title=event["title"], statements="\n\n".join(_describe(p, catalog) for p in parts))
    result = llm.structured(purpose="analyze", model=model, system=prompts.ANALYZE_SYSTEM,
                            user=user, schema=EventAnalysis, max_tokens=16000, effort="medium")
    analysis = result.model_dump()

    texts: dict[str, str] = defaultdict(str)
    for p in parts:
        texts[p["actor"]] += " " + passage(p)
    computed = metrics.compute(analysis, texts, pair_history(conn, exclude_event=event["id"]))
    computed["silent"] = silent_actors(conn, event["id"], parts)

    payload = {"llm": analysis, "metrics": computed, "model": model,
               "part_ids": [p["id"] for p in parts]}
    total = conn.execute("SELECT COUNT(*) FROM parts WHERE event_id=?",
                         (event["id"],)).fetchone()[0]
    with transaction(conn):
        conn.execute(
            "UPDATE events SET analysis=?, analysed_at=?, analysed_statement_count=?,"
            " title=?, summary=? WHERE id=?",
            (dumps(payload), now_iso(), total, result.title, result.summary, event["id"]),
        )
    return payload


def passage(p: sqlite3.Row) -> str:
    """The part's own passage of the original text ('' if it could not be located)."""
    if p["text_start"] is None:
        return ""
    return (p["text"] or "")[p["text_start"]:p["text_end"]]


def _describe(p: sqlite3.Row, catalog: Catalog) -> str:
    data = loads(p["data"]) or {}
    claims = "\n".join(f"      - {c['text']} [quote: \"{c['quote']}\"]"
                       for c in data.get("claims", []))
    terms = ", ".join(f"'{t['term']}' = {t['refers_to']}" for t in data.get("key_terms", []))
    of = f" (passage {p['idx'] + 1} of {p['n_parts']} in a multi-issue statement)" \
        if p["n_parts"] > 1 else ""
    return (
        f"--- statement_id={p['statement_id']} actor={p['actor']} "
        f"({catalog.actor(p['actor']).name}, {p['kind']}) "
        f"date={p['date'][:10]}\n"
        f"title: {p['title']}{of}\n"
        f"issue: {p['issue']}\n"
        f"extracted claims:\n{claims}\n"
        f"key terms: {terms}\n"
        f"text excerpt:\n{passage(p)[:TEXT_EXCERPT_CHARS] or '(not located; use the claims)'}"
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
                  parts: list[sqlite3.Row]) -> list[dict]:
    """Actors that spoke repeatedly on this event's topics lately, but not on this event."""
    topics = Counter(t for p in parts for t in (loads(p["data"]) or {}).get("topics", []))
    main_topics = {t for t, _ in topics.most_common(3)}
    if not main_topics:
        return []
    present = {p["actor"] for p in parts}
    since = (datetime.now(UTC) - timedelta(days=SILENCE_LOOKBACK_DAYS)).isoformat()
    seen: dict[str, set[int]] = defaultdict(set)  # actor -> statements on these topics
    for row in conn.execute(
        """SELECT s.actor, p.statement_id, p.data
           FROM parts p JOIN statements s ON s.id = p.statement_id
           WHERE s.relevant=1 AND p.event_id IS NOT ?
             AND COALESCE(s.published_at, s.fetched_at) >= ?""", (event_id, since),
    ):
        if row["actor"] not in present and main_topics & set(
                (loads(row["data"]) or {}).get("topics", [])):
            seen[row["actor"]].add(row["statement_id"])
    counts = Counter({a: len(ids) for a, ids in seen.items()})
    return [{"actor": a, "recent_statements_on_topic": n}
            for a, n in counts.most_common() if n >= SILENCE_MIN_STATEMENTS]

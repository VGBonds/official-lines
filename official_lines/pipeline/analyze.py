"""Step 3: compare what different actors said about one event.

Two queues, each with its own daily allowance (`max_per_day`):
- updates: events compared before, that another actor has since joined. They are compared
  again on the next run, so a comparison never stays without an actor we already have.
- new comparisons: events where at least MIN_ACTORS actors spoke, or where the same actors
  added statements (then at most once every REANALYSE_AFTER_HOURS).

The input is the parts (one issue each) filed under the event: for each, the extracted
claims and the passage of the original text it comes from.

A text that several actors publish (a joint statement, a verbatim republication) goes into
the comparison once, as one joint voice ("joint:CA+FR+GB") with its publishers named, so
that one text never counts as several agreeing actors. Detection is plain text comparison
(wording.same_text_groups), no AI.

`compare()` is the comparison itself and does not touch the database, so the golden set
(golden.py) can run it on stored inputs. `analyze_event()` loads the parts, calls it and
stores the result.

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
from official_lines.pipeline import metrics, wording
from official_lines.pipeline.events import PART_COLUMNS

log = logging.getLogger(__name__)

MIN_ACTORS = 2
MAX_PARTS_PER_ACTOR = 3
TEXT_EXCERPT_CHARS = 3000
REANALYSE_AFTER_HOURS = 20
SILENCE_LOOKBACK_DAYS = 60
SILENCE_MIN_STATEMENTS = 2
JOINT_PREFIX = "joint:"


def analyses_today(conn: sqlite3.Connection, purpose: str = "analyze") -> int:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    return conn.execute(
        "SELECT COUNT(*) FROM llm_calls WHERE purpose=? AND substr(at, 1, 10)=?",
        (purpose, today),
    ).fetchone()[0]


def analysed_actors(conn: sqlite3.Connection, analysis: dict) -> set[str]:
    """Actors whose statements went into a stored comparison."""
    if "actors" in analysis:
        return set(analysis["actors"])
    ids = analysis.get("part_ids") or []  # comparisons made before "actors" was stored
    return {r[0] for r in conn.execute(
        f"SELECT DISTINCT s.actor FROM parts p JOIN statements s ON s.id = p.statement_id"
        f" WHERE p.id IN ({','.join('?' * len(ids))})", ids)} if ids else set()


def late_actors(conn: sqlite3.Connection, event_id: int, analysis: dict | None) -> list[str]:
    """Actors in the event now that were not in its last comparison."""
    if not analysis:
        return []
    current = [r[0] for r in conn.execute(
        """SELECT s.actor FROM parts p JOIN statements s ON s.id = p.statement_id
           WHERE p.event_id=? GROUP BY s.actor ORDER BY MIN(COALESCE(s.published_at,
           s.fetched_at))""", (event_id,))]
    seen = analysed_actors(conn, analysis)
    return [a for a in current if a not in seen]


def updates_due(conn: sqlite3.Connection, limit: int) -> list[sqlite3.Row]:
    rows = conn.execute(
        """SELECT e.*, COUNT(DISTINCT s.actor) AS actors FROM events e
           JOIN parts p ON p.event_id = e.id JOIN statements s ON s.id = p.statement_id
           WHERE e.analysis IS NOT NULL GROUP BY e.id
           ORDER BY e.featured DESC, actors DESC, e.last_seen DESC"""
    ).fetchall()
    return [r for r in rows if late_actors(conn, r["id"], loads(r["analysis"]))][:limit]


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
        return _run(conn, catalog, llm, model, events, "analyze")
    done = 0
    # Updates first: an updated event's analysed_at becomes now, so it is not due again below.
    for purpose, find in (("update", updates_due), ("analyze", events_due)):
        remaining = max_per_day - analyses_today(conn, purpose)
        if remaining <= 0:
            log.info("daily cap reached for %s (%d)", purpose, max_per_day)
            continue
        done += _run(conn, catalog, llm, model, find(conn, remaining), purpose)
    return done


def _run(conn, catalog, llm, model, events, purpose: str) -> int:
    done = 0
    for event in events:
        try:
            analyze_event(conn, catalog, llm, model, event, purpose)
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


def passage(p: sqlite3.Row) -> str:
    """The part's own passage of the original text ('' if it could not be located)."""
    if p["text_start"] is None:
        return ""
    return (p["text"] or "")[p["text_start"]:p["text_end"]]


def part_record(p: sqlite3.Row) -> dict:
    """What the comparison needs from a part, as plain data (also the golden-set format)."""
    data = loads(p["data"]) or {}
    return {"statement_id": p["statement_id"], "idx": p["idx"], "actor": p["actor"],
            "kind": p["kind"], "date": (p["date"] or "")[:10], "title": p["title"],
            "issue": p["issue"],
            "claims": data.get("claims", []), "key_terms": data.get("key_terms", []),
            "of_several": p["n_parts"] > 1, "passage": passage(p)}


def joint_voices(parts: list[dict]) -> dict[str, dict]:
    """Texts that several actors published: joint voice id -> members and part indexes.
    Compared per statement (its parts in this event joined), because extraction may split
    one publisher's copy of a joint text into several parts and another's not."""
    by_statement: dict[int, list[int]] = defaultdict(list)
    for i, p in sorted(enumerate(parts), key=lambda ip: ip[1].get("idx", 0)):
        by_statement[p["statement_id"]].append(i)  # in the order the passages have in the text
    texts = {sid: " ".join(parts[i]["passage"] for i in idx) for sid, idx in by_statement.items()}
    voices: dict[str, dict] = {}
    for group in wording.same_text_groups(texts):
        indexes = sorted(i for sid in group for i in by_statement[sid])
        members = sorted({parts[i]["actor"] for i in indexes})
        if len(members) < 2:
            continue
        vid = JOINT_PREFIX + "+".join(members)
        voices.setdefault(vid, {"members": members, "parts": []})["parts"] += indexes
    return voices


def compare(catalog: Catalog, llm: LLM, model: str, title: str, parts: list[dict],
            history: dict[str, list[float]], purpose: str = "analyze") -> dict:
    """The comparison of one event: the model's stance table plus the computed metrics.
    `parts` are part_record() dicts; `history` the pair baseline (pair_history())."""
    voices = joint_voices(parts)
    joint_of = {i: vid for vid, v in voices.items() for i in v["parts"]}
    blocks, shown = [], set()
    for i, p in enumerate(parts):
        vid = joint_of.get(i)
        if vid is None:
            blocks.append(_describe(p, catalog))
        elif vid not in shown:
            shown.add(vid)
            blocks.append(_describe_joint(vid, [parts[j] for j in voices[vid]["parts"]],
                                          catalog))
    user = prompts.ANALYZE_USER.format(title=title, statements="\n\n".join(blocks))
    result = llm.structured(purpose=purpose, model=model, system=prompts.ANALYZE_SYSTEM,
                            user=user, schema=EventAnalysis, max_tokens=16000, effort="medium")
    analysis = result.model_dump()

    texts: dict[str, str] = defaultdict(str)
    for p in parts:
        texts[p["actor"]] += " " + p["passage"]
    members = {vid: v["members"] for vid, v in voices.items()}
    computed = metrics.compute(analysis, texts, history, voices=members)
    return {"llm": analysis, "metrics": computed, "model": model,
            "voices": {vid: {"members": v["members"],
                             "statement_ids": sorted({parts[i]["statement_id"]
                                                      for i in v["parts"]})}
                       for vid, v in voices.items()},
            "actors": sorted({p["actor"] for p in parts})}


def analyze_event(conn: sqlite3.Connection, catalog: Catalog, llm: LLM, model: str,
                  event: sqlite3.Row, purpose: str = "analyze") -> dict:
    rows = select_parts(conn, event["id"])
    payload = compare(catalog, llm, model, event["title"], [part_record(r) for r in rows],
                      pair_history(conn, exclude_event=event["id"]), purpose)
    payload["metrics"]["silent"] = silent_actors(conn, event["id"], rows)
    payload["part_ids"] = [r["id"] for r in rows]
    total = conn.execute("SELECT COUNT(*) FROM parts WHERE event_id=?",
                         (event["id"],)).fetchone()[0]
    with transaction(conn):
        conn.execute(
            "UPDATE events SET analysis=?, analysed_at=?, analysed_statement_count=?,"
            " title=?, summary=? WHERE id=?",
            (dumps(payload), now_iso(), total, payload["llm"]["title"],
             payload["llm"]["summary"], event["id"]),
        )
    return payload


def _claims(p: dict) -> str:
    claims = "\n".join(f"      - {c['text']} [quote: \"{c['quote']}\"]" for c in p["claims"])
    terms = ", ".join(f"'{t['term']}' = {t['refers_to']}" for t in p["key_terms"])
    excerpt = p["passage"][:TEXT_EXCERPT_CHARS] or "(not located; use the claims)"
    return (f"issue: {p['issue']}\nextracted claims:\n{claims}\nkey terms: {terms}\n"
            f"text excerpt:\n{excerpt}")


def _describe(p: dict, catalog: Catalog) -> str:
    of = " (one passage of a multi-issue statement)" if p["of_several"] else ""
    return (f"--- statement_id={p['statement_id']} actor={p['actor']} "
            f"({catalog.actor(p['actor']).name}, {p['kind']}) date={p['date']}\n"
            f"title: {p['title']}{of}\n{_claims(p)}")


def _describe_joint(vid: str, group: list[dict], catalog: Catalog) -> str:
    """One joint text, shown once with its publishers. The longest version stands for all."""
    rep = max(group, key=lambda p: len(p["passage"]))
    names = ", ".join(catalog.actor(a).name for a in sorted({p["actor"] for p in group}))
    published = "; ".join(f"{catalog.actor(p['actor']).name} {p['date']}: {p['title']}"
                          for p in group)
    return (f"--- statement_id={rep['statement_id']} actor={vid}\n"
            f"ONE JOINT TEXT published by {names}. Treat it as a single voice and use exactly"
            f" the actor id '{vid}' for it.\npublished as: {published}\n{_claims(rep)}")


def pair_history(conn: sqlite3.Connection, exclude_event: int) -> dict[str, list[float]]:
    """Agreement scores of every actor pair over earlier analysed events (the baseline).
    Co-publishers of one text are left out: that is shared wording, not a measurement."""
    history: dict[str, list[float]] = defaultdict(list)
    for row in conn.execute(
        "SELECT analysis FROM events WHERE analysis IS NOT NULL AND id != ?", (exclude_event,)
    ):
        pairs = loads(row[0])["metrics"].get("pairs") or {}
        for key, v in metrics.measured(pairs).items():
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

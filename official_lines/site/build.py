"""Generate the public website as plain static HTML files.

The site shows titles, dates, links to the original, our own neutral summaries and short
quotes (max ~30 words). It never republishes the full text of a statement.
"""

import shutil
import sqlite3
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from itertools import combinations
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

from official_lines.catalog import Catalog, on_map
from official_lines.config import PROJECT_ROOT
from official_lines.db import loads
from official_lines.pipeline import metrics, wording
from official_lines.pipeline.analyze import late_actors
from official_lines.pipeline.events import PART_COLUMNS

HERE = Path(__file__).parent
INDEX_DAYS = 45
ACTOR_DAYS = 90
WORDING_SHOWN = 200
STANCE_SYMBOL = {"asserts": "●", "qualifies": "◐", "denies": "○"}


def build_site(conn: sqlite3.Connection, catalog: Catalog, out: Path, site_url: str,
               briefs_dir: Path) -> int:
    env = Environment(loader=FileSystemLoader(HERE / "templates"),
                      autoescape=select_autoescape(["html"]))
    env.globals.update(site_url=site_url, actors=catalog.actors,
                       built_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
                       stance_symbol=STANCE_SYMBOL)
    env.filters["date"] = lambda v: (v or "")[:10]
    env.filters["names"] = lambda ids: _and([catalog.actor(a).name for a in ids])

    if out.exists():
        shutil.rmtree(out)
    (out / "event").mkdir(parents=True)
    (out / "actor").mkdir()
    (out / "briefs").mkdir()
    shutil.copytree(HERE / "static", out / "static")

    passages = shared_passages(conn)
    events = load_events(conn, catalog, passages)
    pages = 0
    for e in events:
        _write(out / "event" / f"{e['slug']}.html",
               env.get_template("event.html").render(e=e, root=".."))
        pages += 1

    since = (datetime.now(UTC) - timedelta(days=INDEX_DAYS)).isoformat()
    recent = [e for e in events if (e["last_seen"] or "") >= since]
    activity = Counter(a for e in recent for a in e["map_iso"])
    _write(out / "index.html", env.get_template("index.html").render(
        events=recent, activity=dict(activity), root=".",
        actor_options=sorted(((a, catalog.actor(a).name)
                              for a in {x for e in recent for x in e["countries"] + e["orgs"]}),
                             key=lambda o: o[1])))

    for actor_id, actor in catalog.actors.items():
        statements = actor_statements(conn, actor_id)
        _write(out / "actor" / f"{actor.page}.html", env.get_template("actor.html").render(
            actor=actor, statements=statements,
            sources=[s for s in catalog.sources if s.actor == actor_id], root=".."))
        pages += 1

    _write(out / "wording.html", env.get_template("wording.html").render(
        **wording_page(conn, passages), root="."))
    _write(out / "coverage.html", env.get_template("coverage.html").render(
        rows=coverage(conn, catalog), root="."))
    method = markdown.markdown((PROJECT_ROOT / "docs" / "methodology.md").read_text(),
                               extensions=["tables"])
    _write(out / "method.html", env.get_template("page.html").render(
        title="Method", body=method, root="."))

    briefs = []
    for path in sorted(briefs_dir.glob("*.md"), reverse=True) if briefs_dir.exists() else []:
        html = markdown.markdown(path.read_text(), extensions=["tables"])
        _write(out / "briefs" / f"{path.stem}.html", env.get_template("page.html").render(
            title=path.stem, body=html, root=".."))
        briefs.append(path.stem)
    _write(out / "briefs.html", env.get_template("briefs.html").render(briefs=briefs, root="."))
    return pages + 5 + len(briefs)


def _write(path: Path, html: str) -> None:
    path.write_text(html, encoding="utf-8")


def load_events(conn: sqlite3.Connection, catalog: Catalog,
                passages: list[dict] | None = None) -> list[dict]:
    passages_of: dict[int, list[tuple[dict, dict]]] = defaultdict(list)
    for p in passages or []:
        for o in p["occurrences"]:
            passages_of[o["statement_id"]].append((p, o))
    by_event: dict[int, list[dict]] = defaultdict(list)
    for p in conn.execute(
        f"SELECT {PART_COLUMNS} FROM parts p JOIN statements s ON s.id = p.statement_id"
        " WHERE p.event_id IS NOT NULL ORDER BY date, p.idx"
    ):
        by_event[p["event_id"]].append({
            "id": p["statement_id"], "actor": p["actor"], "kind": p["kind"], "url": p["url"],
            "title": p["title"], "date": p["date"], "summary": p["summary"] or "",
            "claims": (loads(p["data"]) or {}).get("claims", []),
            "of_several": p["n_parts"] > 1,
            "span": (p["text_start"], p["text_end"]),
        })

    events = []
    for row in conn.execute("SELECT * FROM events ORDER BY featured DESC, last_seen DESC"):
        statements = by_event.get(row["id"], [])
        if not statements:
            continue
        actor_ids = list(dict.fromkeys(s["actor"] for s in statements))
        e = dict(row)
        e["statements"] = statements
        e["statement_count"] = len({s["id"] for s in statements})
        e["by_actor"] = {a: [s for s in statements if s["actor"] == a] for a in actor_ids}
        e["countries"] = [a for a in actor_ids if catalog.actor(a).is_country]
        e["orgs"] = [a for a in actor_ids if not catalog.actor(a).is_country]
        e["map_iso"] = sorted({catalog.actor(s["actor"]).iso_numeric for s in statements
                               if on_map(catalog.actor(s["actor"]), s["kind"])})
        e["analysis"] = refresh_labels(loads(row["analysis"]))
        e["voice_names"] = voice_names(catalog, e["analysis"])
        e["background"] = (e["analysis"] or {}).get("llm", {}).get("background", "")
        e["late_actors"] = late_actors(conn, row["id"], e["analysis"])
        e["late_names"] = _and([catalog.actor(a).name for a in e["late_actors"]])
        e["shared_wording"] = event_wording(statements, passages_of)
        if e["analysis"]:
            e["matrix"] = stance_matrix(e["analysis"], actor_ids)
        events.append(e)
    return events


def event_wording(statements: list[dict],
                  passages_of: dict[int, list[tuple[dict, dict]]]) -> list[dict]:
    """Shared passages that sit inside this event's parts, one line per set of actors."""
    found: dict[int, tuple[dict, set[str]]] = {}
    for s in statements:
        for p, o in passages_of.get(s["id"], []):
            if wording.in_span(o, *s["span"]):
                found.setdefault(id(p), (p, set()))[1].add(s["actor"])
    return wording.group_by_actors(
        [{**p, "actors": sorted(actors)} for p, actors in found.values() if len(actors) >= 2])


def refresh_labels(analysis: dict | None) -> dict | None:
    """Recompute shared floor / uncontested majority / contested from the stored stance table
    and filter the terminology, so comparisons stored under older definitions follow the
    current ones."""
    if analysis:
        prop_ids = [p["id"] for p in analysis["llm"]["propositions"]]
        analysis["metrics"].update(
            metrics.agreement_labels(analysis["metrics"]["stance_table"], prop_ids))
        analysis["llm"]["terminology"] = metrics.contrasting_terms(
            analysis["llm"].get("terminology", []))
    return analysis


def _and(names: list[str]) -> str:
    return " and ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " and " + names[-1]


def voice_names(catalog: Catalog, analysis: dict | None) -> dict[str, str]:
    """Display names for every column the stance table can have: actors and joint voices."""
    names = {a: actor.name for a, actor in catalog.actors.items()}
    for vid, v in ((analysis or {}).get("voices") or {}).items():
        names[vid] = _and([catalog.actor(a).name for a in v["members"]]) + " (joint text)"
    return names


def stance_matrix(analysis: dict, actor_ids: list[str]) -> dict:
    """Rows = propositions, columns = voices that took any stance (an actor, or one joint
    text published by several actors); cells = stance + quote."""
    table = analysis["metrics"]["stance_table"]
    voices = analysis.get("voices") or {}
    known = set(actor_ids) | set(voices)
    cells: dict[tuple[str, str], dict] = {}
    for p in analysis["llm"]["positions"]:
        if p["actor"] in known:
            cells.setdefault((p["proposition_id"], p["actor"]), p)
    for vid, v in voices.items():  # a publisher's own column inherits the joint text's quotes
        for a in v["members"]:
            for (pid, who), p in list(cells.items()):
                if who == vid:
                    cells.setdefault((pid, a), p)

    def first_member(v: str) -> int:  # columns follow the order actors first spoke in
        members = voices[v]["members"] if v in voices else [v]
        return min((actor_ids.index(a) for a in members if a in actor_ids),
                   default=len(actor_ids))

    columns = sorted((v for v in table if table[v] and v in known), key=first_member)
    rows = []
    for prop in analysis["llm"]["propositions"]:
        rows.append({
            "prop": prop,
            "floor": prop["id"] in analysis["metrics"]["shared_floor"],
            "majority": prop["id"] in analysis["metrics"]["uncontested_majority"],
            "contested": prop["id"] in analysis["metrics"]["contested"],
            "cells": [
                {"stance": table.get(a, {}).get(prop["id"]),
                 "quote": cells.get((prop["id"], a), {}).get("quote", "")}
                for a in columns
            ],
        })
    return {"columns": columns, "rows": rows}


def actor_statements(conn: sqlite3.Connection, actor_id: str) -> list[dict]:
    since = (datetime.now(UTC) - timedelta(days=ACTOR_DAYS)).isoformat()
    rows = conn.execute(
        """SELECT * FROM statements
           WHERE actor = ? AND COALESCE(published_at, fetched_at) >= ?
           ORDER BY COALESCE(published_at, fetched_at) DESC LIMIT 200""",
        (actor_id, since),
    ).fetchall()
    events: dict[int, list[dict]] = defaultdict(list)  # a briefing can feed several events
    for r in conn.execute(
        """SELECT DISTINCT p.statement_id, e.slug, e.title FROM parts p
           JOIN events e ON e.id = p.event_id JOIN statements s ON s.id = p.statement_id
           WHERE s.actor = ? ORDER BY p.statement_id, p.idx""", (actor_id,),
    ):
        events[r["statement_id"]].append({"slug": r["slug"], "title": r["title"]})
    return [{**dict(r), "summary": (loads(r["extraction"]) or {}).get("summary", ""),
             "events": events.get(r["id"], [])} for r in rows]


def shared_passages(conn: sqlite3.Connection) -> list[dict]:
    """Passages shared across actors, over recent statements and every statement in an event."""
    since = (datetime.now(UTC) - timedelta(days=ACTOR_DAYS)).isoformat()
    rows = conn.execute(
        """SELECT id, actor, text FROM statements
           WHERE text IS NOT NULL AND relevant = 1
             AND (COALESCE(published_at, fetched_at) >= ?
                  OR id IN (SELECT statement_id FROM parts WHERE event_id IS NOT NULL))""",
        (since,),
    ).fetchall()
    return wording.find_passages([dict(r) for r in rows])


def wording_page(conn: sqlite3.Connection, passages: list[dict]) -> dict:
    """Pairs of actors by number of shared passages, and the passages with where they appear."""
    pairs: dict[tuple[str, str], dict] = {}
    for p in passages:
        for x, y in combinations(p["occurrences"], 2):
            if x["actor"] != y["actor"]:
                pair = tuple(sorted((x["actor"], y["actor"])))
                row = pairs.setdefault(pair, {"pair": pair, "statements": set(),
                                              "passages": set(), "longest": 0})
                row["statements"].add(frozenset((x["statement_id"], y["statement_id"])))
                row["passages"].add(id(p))
                row["longest"] = max(row["longest"], p["words"])
    for row in pairs.values():
        row["statements"], row["passages"] = len(row["statements"]), len(row["passages"])
    meta = {r["id"]: dict(r) for r in conn.execute(
        "SELECT id, actor, url, title, COALESCE(published_at, fetched_at) AS date"
        " FROM statements WHERE text IS NOT NULL")}
    spans: dict[int, list[dict]] = defaultdict(list)
    for r in conn.execute(
        """SELECT p.statement_id, p.text_start, p.text_end, e.slug, e.title FROM parts p
           JOIN events e ON e.id = p.event_id"""
    ):
        spans[r["statement_id"]].append(dict(r))
    shown = passages[:WORDING_SHOWN]  # longest first
    rows = []
    for p in shown:
        occurrences = []
        for o in p["occurrences"]:
            events = [{"slug": s["slug"], "title": s["title"]} for s in spans[o["statement_id"]]
                      if wording.in_span(o, s["text_start"], s["text_end"])]
            occurrences.append({**meta[o["statement_id"]], "events": events})
        rows.append({**p, "occurrences": sorted(occurrences, key=lambda o: o["date"] or "")})
    return {"pairs": sorted(pairs.values(), key=lambda r: (-r["longest"], -r["statements"])),
            "passages": rows, "total": len(passages), "days": ACTOR_DAYS}


def coverage(conn: sqlite3.Connection, catalog: Catalog) -> list[dict]:
    health = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM sources")}
    counts = dict(conn.execute("SELECT source_id, COUNT(*) FROM statements GROUP BY source_id"))
    rows = []
    for s in catalog.sources:
        h = health.get(s.id, {})
        rows.append({"source": s, "statements": counts.get(s.id, 0),
                     "last_ok_at": h.get("last_ok_at"), "last_error": h.get("last_error")})
    return rows

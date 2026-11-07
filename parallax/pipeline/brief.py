"""The weekly brief: a Markdown draft for the newsletter, written by the stronger model.

You (the editor) review and edit the draft, then paste it into Substack. Featured events
(`parallax feature <slug>`) are always included; the rest are ranked by how many actors
spoke and how contested the event is.
"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from parallax.catalog import Catalog
from parallax.db import loads
from parallax.llm import prompts
from parallax.llm.client import LLM

MAX_EVENTS = 6


def pick_events(conn: sqlite3.Connection, days: int) -> list[sqlite3.Row]:
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT e.*, COUNT(DISTINCT s.actor) AS actors FROM events e
           JOIN statements s ON s.event_id = e.id
           WHERE e.analysis IS NOT NULL AND e.last_seen >= ? GROUP BY e.id""",
        (since,),
    ).fetchall()

    def score(e):
        m = loads(e["analysis"])["metrics"]
        notable = len(m["unusual_alignment"]) + len(m["shared_wording"]) + len(m["silent"])
        return (e["featured"], e["actors"] + 2 * len(m["contested"]) + notable)

    return sorted(rows, key=score, reverse=True)[:MAX_EVENTS]


def write_brief(conn: sqlite3.Connection, catalog: Catalog, llm: LLM, model: str,
                site_url: str, out_dir: Path, days: int = 7) -> Path | None:
    events = pick_events(conn, days)
    if not events:
        return None
    material = []
    for e in events:
        a = loads(e["analysis"])
        material.append({
            "title": e["title"],
            "url": f"{site_url}/event/{e['slug']}.html",
            "actors": sorted({p["actor"] for p in a["llm"]["positions"]}),
            "analysis": a["llm"],
            "metrics": {k: v for k, v in a["metrics"].items() if k != "stance_table"},
        })
    text = llm.text(
        purpose="brief", model=model, system=prompts.BRIEF_SYSTEM,
        user="Events of the week (JSON):\n" + json.dumps(
            {"actor_names": {k: v.name for k, v in catalog.actors.items()}, "events": material},
            ensure_ascii=False, indent=1),
        max_tokens=16000, effort="medium",
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"brief-{datetime.now(UTC):%Y-%m-%d}.md"
    path.write_text(text)
    return path

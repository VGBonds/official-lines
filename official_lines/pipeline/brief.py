"""The weekly brief: a Markdown draft for the newsletter, written by the stronger model.

You (the editor) review and edit the draft, then paste it into Substack. Featured events
(`official-lines feature <slug>`) are always included; the rest are ranked by how many actors
spoke and how contested the event is.
"""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from official_lines.catalog import Catalog
from official_lines.db import loads
from official_lines.llm import prompts
from official_lines.llm.client import LLM
from official_lines.site.build import refresh_labels, voice_names

MAX_EVENTS = 6


def pick_events(conn: sqlite3.Connection, days: int) -> list[sqlite3.Row]:
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """SELECT e.*, COUNT(DISTINCT s.actor) AS actors FROM events e
           JOIN parts p ON p.event_id = e.id JOIN statements s ON s.id = p.statement_id
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
    material, names = [], {}
    for e in events:
        a = refresh_labels(loads(e["analysis"]))
        names.update(voice_names(catalog, a))  # actors, plus any joint text's publishers
        material.append({
            "title": e["title"],
            "url": f"{site_url}/event/{e['slug']}.html",
            "actors": a.get("actors") or sorted({p["actor"] for p in a["llm"]["positions"]}),
            "joint_texts": a.get("voices") or {},
            "analysis": a["llm"],
            "metrics": {k: v for k, v in a["metrics"].items() if k != "stance_table"},
        })
    text = llm.text(
        purpose="brief", model=model, system=prompts.BRIEF_SYSTEM,
        user="Events of the week (JSON):\n" + json.dumps(
            {"actor_names": names, "events": material}, ensure_ascii=False, indent=1),
        max_tokens=16000, effort="medium",
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"brief-{datetime.now(UTC):%Y-%m-%d}.md"
    path.write_text(text)
    return path

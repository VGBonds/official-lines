"""Step 1: read each new statement once with the cheap model and store structured content."""

import logging
import sqlite3

import anthropic

from parallax.catalog import Catalog
from parallax.db import dumps, now_iso, transaction
from parallax.llm import prompts
from parallax.llm.client import LLM, LLMError
from parallax.llm.schemas import StatementExtraction

log = logging.getLogger(__name__)

MAX_TEXT_CHARS = 8000  # ~2k tokens; the opening of an official statement carries its line


def extract_pending(conn: sqlite3.Connection, catalog: Catalog, llm: LLM, model: str,
                    limit: int) -> int:
    rows = conn.execute(
        """SELECT s.*, src.name AS source_name FROM statements s
           JOIN sources src ON src.id = s.source_id
           WHERE s.extracted_at IS NULL
           ORDER BY COALESCE(s.published_at, s.fetched_at) DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    done = 0
    for row in rows:
        user = prompts.EXTRACT_USER.format(
            source_name=row["source_name"],
            actor_name=catalog.actor(row["actor"]).name,
            kind=row["kind"],
            published=row["published_at"] or "unknown",
            url=row["url"],
            title=row["title"],
            text=(row["text"] or "(no text available, title only)")[:MAX_TEXT_CHARS],
        )
        try:
            result = llm.structured(purpose="extract", model=model,
                                    system=prompts.EXTRACT_SYSTEM, user=user,
                                    schema=StatementExtraction, max_tokens=4000, effort="low")
        except (LLMError, anthropic.APIError) as e:
            log.warning("extract failed for statement %s: %s", row["id"], e)
            continue
        with transaction(conn):
            conn.execute(
                "UPDATE statements SET extraction=?, extracted_at=?, relevant=?, domain=?"
                " WHERE id=?",
                (dumps(result.model_dump()), now_iso(), int(result.relevant), result.domain,
                 row["id"]),
            )
        done += 1
    return done

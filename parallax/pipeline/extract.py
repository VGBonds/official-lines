"""Step 1: read each new statement once with the cheap model and store structured content.

A statement is split into parts, one per issue. Most statements have one part; a press
briefing has one per question. For each part we also find where its passage sits in the
original text, so that the comparison step reads the right passage and not the whole
briefing.
"""

import logging
import re
import sqlite3

import anthropic

from parallax.catalog import Catalog
from parallax.db import dumps, now_iso, transaction
from parallax.llm import prompts
from parallax.llm.client import LLM, LLMError
from parallax.llm.schemas import IssuePart, StatementExtraction

log = logging.getLogger(__name__)

MAX_TEXT_CHARS = 30000  # ~7.5k tokens: long enough for a full press briefing


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
        text = (row["text"] or "")[:MAX_TEXT_CHARS]
        user = prompts.EXTRACT_USER.format(
            source_name=row["source_name"],
            actor_name=catalog.actor(row["actor"]).name,
            kind=row["kind"],
            published=row["published_at"] or "unknown",
            url=row["url"],
            title=row["title"],
            text=text or "(no text available, title only)",
        )
        try:
            result = llm.structured(purpose="extract", model=model,
                                    system=prompts.EXTRACT_SYSTEM, user=user,
                                    schema=StatementExtraction, max_tokens=16000, effort="low")
        except (LLMError, anthropic.APIError) as e:
            log.warning("extract failed for statement %s: %s", row["id"], e)
            continue
        save_extraction(conn, row["id"], text, result)
        done += 1
    return done


def save_extraction(conn: sqlite3.Connection, statement_id: int, text: str,
                    result: StatementExtraction) -> None:
    parts = result.parts if result.relevant else []
    spans = locate_parts(text, parts)
    with transaction(conn):
        conn.execute(
            "UPDATE statements SET extraction=?, extracted_at=?, relevant=?, domain=?"
            " WHERE id=?",
            (dumps({"summary": result.summary}), now_iso(), int(result.relevant and bool(parts)),
             result.domain, statement_id),
        )
        conn.execute("DELETE FROM parts WHERE statement_id=?", (statement_id,))
        for idx, (part, (start, end)) in enumerate(zip(parts, spans, strict=True)):
            data = part.model_dump(include={"topics", "places", "claims", "key_terms"})
            conn.execute(
                "INSERT INTO parts (statement_id, idx, issue, summary, data, text_start,"
                " text_end) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (statement_id, idx, part.issue, part.summary, dumps(data), start, end),
            )


def locate_parts(text: str, parts: list[IssuePart]) -> list[tuple[int | None, int | None]]:
    """Find where each part's passage starts in the text: at its verbatim opening words, or
    failing that at its first quote. A passage ends where the next located one starts.
    A single part is the whole text."""
    if len(parts) <= 1:
        return [(0, len(text))] * len(parts)
    starts = [_start(text, p) for p in parts]
    found = sorted(s for s in starts if s is not None)
    return [(s, next((f for f in found if f > s), len(text))) if s is not None else (None, None)
            for s in starts]


def _start(text: str, part: IssuePart) -> int | None:
    for snippet in [part.opening, *(c.quote for c in part.claims)]:
        if (i := _find(text, snippet)) is not None:
            return i
    return None


def _find(text: str, snippet: str) -> int | None:
    """Position of a snippet in the text, ignoring case, whitespace and punctuation drift."""
    words = re.findall(r"\w+", snippet)[:12]
    if len(words) < 3:
        return None
    match = re.search(r"\W+".join(map(re.escape, words)), text, flags=re.I)
    return match.start() if match else None

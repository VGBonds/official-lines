"""One collection pass over the catalog.

For each enabled source: read the feed or listing page, keep links we have not seen,
fetch each new statement page, extract its text, store it. A failing source never stops
the pass; its error is recorded in the `sources` table and shown on the coverage page.
"""

import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx

from official_lines.catalog import Catalog, Source
from official_lines.collect.http import Blocked, PoliteClient
from official_lines.collect.parsers import Item, parse_article, parse_feed, parse_listing
from official_lines.db import now_iso, transaction

log = logging.getLogger(__name__)

FULL_TEXT_CHARS = 1500  # feed text shorter than this is treated as a teaser: fetch the page


@dataclass
class SourceResult:
    source_id: str
    found: int = 0
    new: int = 0
    error: str | None = None


def sync_sources(conn: sqlite3.Connection, catalog: Catalog) -> None:
    with transaction(conn):
        for s in catalog.sources:
            conn.execute(
                """INSERT INTO sources (id, actor, kind, name, url) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET actor=excluded.actor, kind=excluded.kind,
                   name=excluded.name, url=excluded.url""",
                (s.id, s.actor, s.kind, s.name, s.url),
            )


def collect(
    conn: sqlite3.Connection,
    catalog: Catalog,
    client: PoliteClient,
    max_new_per_source: int,
    only: str | None = None,
) -> list[SourceResult]:
    sync_sources(conn, catalog)
    sources = [s for s in catalog.enabled_sources() if only in (None, s.id)]
    known = {row[0] for row in conn.execute("SELECT url FROM statements")}

    # Sources are fetched in parallel (different hosts); writes happen here, on one thread.
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [
            pool.submit(_fetch_source, s, client, known, max_new_per_source) for s in sources
        ]
        results = []
        for source, future in zip(sources, futures, strict=True):
            result, rows = future.result()
            _store(conn, source, result, rows)
            results.append(result)
            log.info("%-28s found=%-3d new=%-3d %s", source.id, result.found, result.new,
                     result.error or "")
    return results


def _fetch_source(source: Source, client: PoliteClient, known: set[str], max_new: int):
    result = SourceResult(source.id)
    rows = []
    try:
        items = _list_items(source, client)
        result.found = len(items)
        for item in [i for i in items if i.url not in known][:max_new]:
            row = _fetch_statement(source, item, client)
            if row:
                rows.append(row)
        result.new = len(rows)
    except (httpx.HTTPError, Blocked) as e:
        result.error = f"{type(e).__name__}: {e}"[:300]
    except Exception as e:  # noqa: BLE001 - one broken source must not stop the run
        log.exception("unexpected error in %s", source.id)
        result.error = f"{type(e).__name__}: {e}"[:300]
    return result, rows


def _list_items(source: Source, client: PoliteClient) -> list[Item]:
    response = client.get(source.url)
    if source.method == "rss":
        return parse_feed(response.content)
    return parse_listing(response.text, str(response.url), source.link_selector,
                         source.link_pattern)


def _fetch_statement(source: Source, item: Item, client: PoliteClient) -> dict | None:
    title, published, text = item.title, item.published_at, item.feed_text
    if not text or len(text) < FULL_TEXT_CHARS:
        try:
            page = client.get(item.url)
        except (httpx.HTTPError, Blocked) as e:
            # Page blocked or down: keep what the feed/listing gave us (at least the title),
            # so the site still records that this actor spoke.
            log.warning("%s: cannot fetch %s (%s)", source.id, item.url, str(e).splitlines()[0])
            page = None
        if page is not None:
            article = parse_article(page.text, item.url)
            title = title or article.title
            published = published or article.published_at
            if article.text and len(article.text) > len(text or ""):
                text = article.text
    if not title:
        return None
    return {
        "source_id": source.id, "actor": source.actor, "kind": source.kind, "url": item.url,
        "title": title.strip(), "published_at": published, "text": text,
    }


def _store(conn: sqlite3.Connection, source: Source, result: SourceResult, rows: list[dict]):
    now = now_iso()
    with transaction(conn):
        for r in rows:
            conn.execute(
                """INSERT OR IGNORE INTO statements
                   (source_id, actor, kind, url, title, published_at, fetched_at, text)
                   VALUES (:source_id, :actor, :kind, :url, :title, :published_at, :now, :text)""",
                {**r, "now": now},
            )
        conn.execute(
            """UPDATE sources SET last_run_at=?, last_error=?, last_found=?, last_new=?,
               last_ok_at = CASE WHEN ? IS NULL THEN ? ELSE last_ok_at END WHERE id=?""",
            (now, result.error, result.found, result.new, result.error, now, source.id),
        )

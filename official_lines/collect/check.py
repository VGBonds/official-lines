"""Check whether a source can be read, without storing anything.

Runs the same steps as a collection pass (robots.txt, the polite client, the feed or
listing parser, the article extractor) on one source and reports what it found: the list
page's answer, how many statement links it gives, and how much text the first statement
pages yield. Used to decide which candidate sources to enable. Run it on the server: some
sites answer a laptop but refuse data-centre addresses.
"""

from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from official_lines.catalog import Catalog, Source
from official_lines.collect.http import Blocked, PoliteClient
from official_lines.collect.parsers import parse_article, parse_feed, parse_listing

GOOD_TEXT_CHARS = 500  # a statement page with less text is probably a stub or a JS shell
SUGGESTIONS = 12


@dataclass
class Sample:
    url: str
    title: str | None
    published_at: str | None
    text_chars: int
    error: str | None = None


@dataclass
class CheckResult:
    source_id: str
    verdict: str  # ok, needs_pattern, thin_text, no_links, blocked, robots, not_found, error
    detail: str = ""
    links: int = 0
    samples: list[Sample] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)  # link candidates for a pattern


def check_source(source: Source, client: PoliteClient, samples: int = 2,
                 catalog: Catalog | None = None) -> CheckResult:
    result = CheckResult(source.id, "error")
    if source.method == "unsc_records":
        return _check_records(source, client, catalog, result, samples)
    try:
        response = client.get(source.url)
    except Blocked as e:
        return _set(result, "robots", str(e))
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        verdict = "not_found" if code in (404, 410) else "blocked"
        return _set(result, verdict, f"HTTP {code} from {e.request.url}")
    except httpx.HTTPError as e:
        return _set(result, "blocked", f"{type(e).__name__}: no answer (timeout or refused)")

    if source.method == "rss":
        items = parse_feed(response.content)
    else:
        selector = source.link_selector or "a[href]"
        items = parse_listing(response.text, str(response.url), selector, source.link_pattern)
        if not source.link_pattern:
            result.suggestions = _suggest(source, [i.url for i in items])
    result.links = len(items)
    if not items:
        what = "not a feed, or an empty one" if source.method == "rss" else \
            f"no links in {len(response.content) // 1024} KB of HTML (built by JavaScript?)"
        return _set(result, "no_links", what)

    for item in items[:samples]:
        result.samples.append(_sample(item, client))
    best = max(s.text_chars for s in result.samples)
    if source.method == "html" and not source.link_pattern:
        return _set(result, "needs_pattern",
                    "the page answers; pick the statement links from the suggestions")
    if best < GOOD_TEXT_CHARS:
        return _set(result, "thin_text", f"statement pages give at most {best} characters")
    return _set(result, "ok", f"{len(items)} links, statement text up to {best} characters")


def _check_records(source: Source, client: PoliteClient, catalog: Catalog | None,
                   result: CheckResult, samples: int = 2) -> CheckResult:
    """The meetings table, then the newest record old enough to be published: how many
    delegations it yields, or why it cannot be fetched (usually robots.txt)."""
    from official_lines.collect import unsc
    try:
        meetings = unsc.parse_meetings(client.get(source.url).text)
    except Blocked as e:
        return _set(result, "robots", str(e))
    except httpx.HTTPError as e:
        return _set(result, "blocked", f"{type(e).__name__}: the meetings table did not answer")
    result.links = len(meetings)
    if not meetings:
        return _set(result, "no_links", "no meetings in the table (layout changed?)")
    due = unsc.due_meetings(meetings, set())
    if not due:
        return _set(result, "ok", f"{len(meetings)} meetings listed, none due yet")
    meeting = due[0]
    url = unsc.record_url(meeting.symbol)
    try:
        data = unsc.fetch_record(meeting.symbol, client)
    except Blocked as e:
        return _set(result, "robots", f"{len(meetings)} meetings listed; {e}")
    except httpx.HTTPError as e:
        return _set(result, "blocked", f"{len(meetings)} meetings listed; record: {e}")
    if data is None:
        return _set(result, "thin_text", f"{len(meetings)} meetings listed; {meeting.symbol} "
                    f"({meeting.date[:10]}) is not published yet at {url}")
    turns, missed = unsc.split_turns(unsc.pdf_text(data), catalog)
    for t in turns[:samples]:
        result.samples.append(Sample(url, f"{t.actor}: {t.text[:60]}", meeting.date, len(t.text)))
    kept = sorted({t.actor for t in turns})
    return _set(result, "ok", f"{len(meetings)} meetings listed; {meeting.symbol} on "
                f"'{meeting.topic}' gives {len(kept)} actors ({', '.join(kept)}); "
                f"not in the catalog: {', '.join(sorted(missed)) or 'none'}")


def _set(result: CheckResult, verdict: str, detail: str) -> CheckResult:
    result.verdict, result.detail = verdict, detail
    return result


def _sample(item, client: PoliteClient) -> Sample:
    text = item.feed_text or ""
    title, published = item.title, item.published_at
    try:
        article = parse_article(client.get(item.url).text, item.url)
    except (httpx.HTTPError, Blocked) as e:
        return Sample(item.url, title, published, len(text), str(e).splitlines()[0][:120])
    if article.text and len(article.text) > len(text):
        text = article.text
    return Sample(item.url, title or article.title, published or article.published_at,
                  len(text))


def _suggest(source: Source, urls: list[str]) -> list[str]:
    """Links on the listing page's own site with a deeper path: likely statement pages."""
    host = urlparse(source.url).netloc.removeprefix("www.")
    deep = [u for u in urls if urlparse(u).netloc.removeprefix("www.") == host
            and len([p for p in urlparse(u).path.split("/") if p]) >= 2]
    return sorted(deep, key=len, reverse=True)[:SUGGESTIONS]


def format_result(r: CheckResult) -> str:
    lines = [f"{r.verdict.upper():14} {r.source_id}: {r.detail}"]
    for s in r.samples:
        state = f"ERROR {s.error}" if s.error else f"{s.text_chars} chars"
        lines.append(f"    sample: {state} | {(s.published_at or '-')[:10]} | "
                     f"{(s.title or '-')[:70]}\n            {s.url}")
    for u in r.suggestions:
        lines.append(f"    link: {u}")
    return "\n".join(lines)

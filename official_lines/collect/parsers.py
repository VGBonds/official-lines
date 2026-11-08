"""Turn raw feeds, listing pages and article pages into plain Python data."""

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit

import feedparser
import trafilatura
from bs4 import BeautifulSoup

TRACKING_PARAMS = re.compile(r"^(utm_|fbclid|gclid|mc_)")
# Text of bot-check / "please enable JavaScript" pages: not a statement, do not store it.
PLACEHOLDER_PAGE = re.compile(
    r"enable javascript|javascript is disabled|just a moment|access denied|are you a robot"
    r"|checking your browser", re.I)


@dataclass
class Item:
    """One candidate statement, before we have fetched its page."""

    url: str
    title: str | None = None
    published_at: str | None = None
    feed_text: str | None = None  # some feeds carry the whole text


@dataclass
class Article:
    title: str | None
    published_at: str | None
    text: str | None


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = "&".join(
        p for p in parts.query.split("&") if p and not TRACKING_PARAMS.match(p.split("=")[0])
    )
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, query, ""))


def to_iso(value) -> str | None:
    """Best effort: struct_time, RFC 822 string, or ISO string -> ISO UTC string."""
    if value is None:
        return None
    try:
        if isinstance(value, str):
            try:
                dt = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:  # time.struct_time from feedparser (already UTC)
            dt = datetime(*value[:6], tzinfo=UTC)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).replace(microsecond=0).isoformat()


def parse_feed(content: bytes) -> list[Item]:
    feed = feedparser.parse(content)
    items = []
    for entry in feed.entries:
        link = entry.get("link")
        if not link:
            continue
        date = entry.get("published_parsed") or entry.get("updated_parsed")
        raw = entry.content[0].get("value", "") if entry.get("content") else entry.get("summary")
        text = html_to_text(raw) if raw else None
        items.append(Item(normalize_url(link), entry.get("title"), to_iso(date), text))
    return items


def parse_listing(html: str, base_url: str, selector: str, pattern: str | None) -> list[Item]:
    soup = BeautifulSoup(html, "lxml")
    base_tag = soup.find("base", href=True)
    if base_tag:  # links are relative to <base href>, not to the page address
        base_url = urljoin(base_url, base_tag["href"])
    regex = re.compile(pattern) if pattern else None
    seen, items = set(), []
    for a in soup.select(selector):
        href = a.get("href")
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        url = normalize_url(urljoin(base_url, href))
        if url in seen or (regex and not regex.search(url)):
            continue
        seen.add(url)
        title = " ".join(a.get_text(" ", strip=True).split()) or None
        items.append(Item(url, title))
    return items


def parse_article(html: str, url: str) -> Article:
    data = trafilatura.bare_extraction(html, url=url, with_metadata=True, include_comments=False)
    if data is None:
        return Article(None, None, None)
    if not isinstance(data, dict):  # newer trafilatura returns a Document object
        data = data.as_dict()
    text = data.get("text")
    if text and len(text) < 1000 and PLACEHOLDER_PAGE.search(text):
        return Article(None, None, None)
    return Article(data.get("title"), to_iso(data.get("date")), text)


def html_to_text(html: str) -> str:
    return " ".join(BeautifulSoup(html, "lxml").get_text(" ").split())

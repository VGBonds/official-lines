"""Security Council verbatim records (document symbols S/PV.NNNN): one meeting, one
statement per speaking delegation.

The record is the United Nations' own transcript of what each delegation said, first-hand.
We read the Council's meetings table (the Dag Hammarskjöld Library's list for the year,
which gives the symbol, date and topic of every meeting), fetch each record not yet stored,
split it at the speaker lines and keep the delegations that are actors in our catalog.

Where the record comes from is one URL template with the symbol in it
(OFFICIAL_LINES_UN_RECORD_URL in .env). The default is the Official Document System's
symbol service, whose robots.txt asks bots to stay away: our client refuses it, as it
refuses any such site, and the source stays blocked until the owner has an address the UN
allows (the Dag Hammarskjöld Library grants API access on request). Nothing else in this
module depends on where the PDF comes from.

Kept: speakers with a country or organisation in parentheses that maps to a catalog actor,
and the Secretary-General (the UN's own voice). Not kept: the President (procedural, and
occasionally speaking for their own country without a country in the line), briefers without
a country (UN officials and civil society alike: the line does not tell them apart), and
delegations that are not catalog actors (logged with a count, so the owner can add them).
"""

import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO

from bs4 import BeautifulSoup

from official_lines.catalog import Catalog, Source
from official_lines.collect.http import PoliteClient

log = logging.getLogger(__name__)

METHOD = "unsc_records"
KIND = "un_record"
DEFAULT_RECORD_URL = "https://documents.un.org/api/symbol/access?s={symbol}&l=E&t=pdf"
PERMALINK = "https://docs.un.org/{symbol}"  # the UN's public link to a document
RECORD_DELAY_DAYS = 4    # a record is rarely published sooner than this after the meeting
MAX_MEETING_AGE_DAYS = 60
MIN_TURN_CHARS = 200     # shorter turns are procedural ("I thank the representative ...")

# How the records name our actors (UN usage) where it differs from the catalog's name.
UN_NAMES = {
    "United States of America": "US", "United States": "US",
    "United Kingdom of Great Britain and Northern Ireland": "GB", "United Kingdom": "GB",
    "Russian Federation": "RU", "Türkiye": "TR", "Turkey": "TR",
    "Iran (Islamic Republic of)": "IR", "Islamic Republic of Iran": "IR", "Iran": "IR",
    "Viet Nam": "VN", "Republic of Korea": None, "China": "CN",
    "European Union": "eu", "African Union": "au", "League of Arab States": "arab_league",
    "Organization of Islamic Cooperation": "oic", "Organisation of Islamic Cooperation": "oic",
    "Gulf Cooperation Council": "gcc", "Association of Southeast Asian Nations": "asean",
}

SPEAKER = re.compile(
    r"^(?P<who>(?:Mr|Mrs|Ms|Dr|Sir|Sheikh|Archbishop|Cardinal|Rabbi)\.?\s[^():]{1,60}?"
    r"|The President|The Secretary-General|The Deputy Secretary-General)"
    r"(?:\s\((?P<country>[^()]{2,70})\))?"
    r"(?:\s\((?:spoke|interpretation)[^()]*\))?\s*:\s(?P<rest>.*)$")
HEADER = re.compile(
    r"^\s*(S/PV\.\d+\b.*|.*\bS/PV\.\d+\s*|\d\d-\d{5}(\s\(E\))?(\s\d+/\d+)?|\*\d{7}\*|Provisional)\s*$")
NOTICE_START = "This record contains the text of speeches"
MEETING_START = re.compile(r"^\s*The meeting (was called to order|resumed) at")


@dataclass
class Meeting:
    symbol: str      # "S/PV.10123"
    date: str        # ISO date-time, UTC midnight
    topic: str
    press_release: str | None = None

    @property
    def number(self) -> str:
        return self.symbol.split(".")[-1]


@dataclass
class Turn:
    actor: str
    text: str


def record_url(symbol: str) -> str:
    template = os.environ.get("OFFICIAL_LINES_UN_RECORD_URL", DEFAULT_RECORD_URL)
    return template.format(symbol=symbol)


# --- the meetings table --------------------------------------------------------------------

def parse_meetings(html: str) -> list[Meeting]:
    """The library's meetings table: rows of symbol link, date, press release, topic,
    outcome; newest first. Rows without a symbol (the headings) are skipped."""
    meetings = []
    for tr in BeautifulSoup(html, "lxml").select("tr"):
        cells = tr.select("td")
        if len(cells) < 4:
            continue
        link = cells[0].find("a")
        symbol = (link.get_text(" ", strip=True) if link else cells[0].get_text(strip=True))
        if not re.fullmatch(r"S/PV\.\d+(\s*\(Resumption\s*\d+\))?", symbol):
            continue
        date = _meeting_date(cells[1].get_text(" ", strip=True))
        if date is None:
            continue
        press = cells[2].get_text(" ", strip=True) or None
        meetings.append(Meeting(symbol.replace(" ", ""), date,
                                cells[3].get_text(" ", strip=True), press))
    return meetings


def _meeting_date(text: str) -> str | None:
    m = re.search(r"(\d{1,2})\s+([A-Z][a-z]+)\s+(\d{4})", text)
    if not m:
        return None
    try:
        dt = datetime.strptime(" ".join(m.groups()), "%d %B %Y").replace(tzinfo=UTC)
    except ValueError:
        return None
    return dt.isoformat()


def due_meetings(meetings: list[Meeting], known_urls: set[str], now: datetime | None = None,
                 ) -> list[Meeting]:
    """Meetings old enough for a record to exist, young enough to matter, and not yet
    stored (a stored meeting has at least one statement under its permalink)."""
    now = now or datetime.now(UTC)
    oldest = (now - timedelta(days=MAX_MEETING_AGE_DAYS)).isoformat()
    newest = (now - timedelta(days=RECORD_DELAY_DAYS)).isoformat()
    stored = {u.split("#")[0] for u in known_urls if u.startswith("https://docs.un.org/")}
    return [m for m in meetings
            if oldest <= m.date <= newest and PERMALINK.format(symbol=m.symbol) not in stored]


# --- the record ---------------------------------------------------------------------------

def pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def clean_lines(text: str) -> list[str]:
    """The record's body: everything from the opening of the meeting, without the page
    headers ('S/PV.10123 The situation ... 18/03/2026', '26-03788 2/29')."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if MEETING_START.match(line)), 0)
    return [line.rstrip() for line in lines[start:] if not HEADER.match(line)]


def split_turns(text: str, catalog: Catalog) -> tuple[list[Turn], dict[str, int]]:
    """One Turn per speaker line, in order; lines of a turn are joined with spaces. Returns
    the turns of actors we keep and a count of the delegations we do not."""
    turns: list[Turn] = []
    skipped: dict[str, int] = {}
    current: tuple[str | None, list[str]] | None = None  # (actor or None, lines)

    def close():
        if current and current[0] and current[1]:
            turns.append(Turn(current[0], _join(current[1])))

    for line in clean_lines(text):
        m = SPEAKER.match(line)
        if m:
            close()
            actor = speaker_actor(m.group("who"), m.group("country"), catalog)
            if actor is None and m.group("country"):
                skipped[m.group("country")] = skipped.get(m.group("country"), 0) + 1
            current = (actor, [m.group("rest")])
        elif current is not None:
            current[1].append(line)
    close()
    return [t for t in turns if len(t.text) >= MIN_TURN_CHARS], skipped


def _join(lines: list[str]) -> str:
    paragraphs, buf = [], []
    for line in lines:
        if line.strip():
            buf.append(line.strip())
        elif buf:
            paragraphs.append(" ".join(buf))
            buf = []
    if buf:
        paragraphs.append(" ".join(buf))
    return "\n\n".join(paragraphs)


def speaker_actor(who: str, country: str | None, catalog: Catalog) -> str | None:
    if who.strip() == "The Secretary-General":
        return "un" if "un" in catalog.actors else None
    if not country:
        return None
    name = " ".join(country.split())
    if name in UN_NAMES:
        actor = UN_NAMES[name]
        return actor if actor in catalog.actors else None
    for actor_id, actor in catalog.actors.items():
        if actor.name.lower() == name.lower():
            return actor_id
    return None


def statements_for(meeting: Meeting, turns: list[Turn], source: Source,
                   catalog: Catalog) -> list[dict]:
    """One statement per actor and meeting; an actor that spoke twice (a right of reply) has
    its turns joined in order."""
    by_actor: dict[str, list[str]] = {}
    for t in turns:
        by_actor.setdefault(t.actor, []).append(t.text)
    rows = []
    date = meeting.date[:10]
    for actor, texts in by_actor.items():
        name = catalog.actor(actor).name
        topic = meeting.topic[0].lower() + meeting.topic[1:] if meeting.topic[:4] == "The " \
            else meeting.topic
        rows.append({
            "source_id": source.id, "actor": actor, "kind": KIND,
            "url": f"{PERMALINK.format(symbol=meeting.symbol)}#{actor}",
            "title": f"{name} at the Security Council on {topic} ({meeting.symbol}, "
                     f"{_pretty_date(date)})",
            "published_at": meeting.date, "text": "\n\n".join(texts), "page_missing": False,
        })
    return rows


def _pretty_date(iso_date: str) -> str:
    return datetime.fromisoformat(iso_date).strftime("%-d %B %Y")


# --- the collect pass -----------------------------------------------------------------------

def fetch_record(symbol: str, client: PoliteClient) -> bytes | None:
    """The record's PDF, or None when it is not published yet (the service answers a page
    instead of a PDF). Raises Blocked when robots.txt forbids the address, like any fetch."""
    response = client.get(record_url(symbol))
    if "pdf" not in response.headers.get("content-type", "") and \
            not response.content.startswith(b"%PDF"):
        return None
    return response.content


def collect_records(source: Source, client: PoliteClient, catalog: Catalog, known: set[str],
                    max_new: int) -> tuple[int, list[dict]]:
    """(meetings found, statement rows). Each due meeting costs one fetch; a record that is
    not published yet is simply tried again on a later pass."""
    meetings = parse_meetings(client.get(source.url).text)
    rows: list[dict] = []
    skipped: dict[str, int] = {}
    tried = 0
    for meeting in due_meetings(meetings, known):
        if tried >= max_new:
            break
        tried += 1
        data = fetch_record(meeting.symbol, client)
        if data is None:
            log.info("%s: %s not published yet", source.id, meeting.symbol)
            continue
        turns, missed = split_turns(pdf_text(data), catalog)
        for name, n in missed.items():
            skipped[name] = skipped.get(name, 0) + n
        rows.extend(statements_for(meeting, turns, source, catalog))
        log.info("%s: %s (%s): %d statements kept", source.id, meeting.symbol, meeting.date[:10],
                 len(rows))
    if skipped:
        log.info("%s: delegations not in the catalog: %s", source.id,
                 ", ".join(f"{k} ({v})" for k, v in sorted(skipped.items(), key=lambda kv: -kv[1])))
    return len(meetings), rows

"""Collection with a stand-in HTTP client: failed statement pages are retried later."""

from pathlib import Path

import httpx

from official_lines.collect.run import collect, pages_to_retry
from official_lines.db import now_iso

FIXTURES = Path(__file__).parent / "fixtures"
FEED = "https://www.gov.uk/fcdo.atom"
STRAIT = "https://example.gov/news/strait"
RATES = "https://example.gov/news/rates"
ARTICLE = ("<html><head><title>{title}</title></head><body><article><h1>{title}</h1>"
           + "".join(f"<p>Point {i}: the minister set out position number {i} of the government "
                     f"in some detail, covering aspect {i * 7} of the matter.</p>"
                     for i in range(30))
           + "</article></body></html>")


class Page:
    def __init__(self, url: str, body: bytes):
        self.url, self.content, self.text = url, body, body.decode()


class FakeClient:
    """Serves the fixture feed; pages listed in `down` fail with a connection error."""

    def __init__(self, down: set[str]):
        self.down = down
        self.requested: list[str] = []

    def get(self, url: str) -> Page:
        self.requested.append(url)
        if url in self.down:
            raise httpx.ConnectError("connection reset by peer")
        if url == FEED:
            return Page(url, (FIXTURES / "sample.rss").read_bytes())
        return Page(url, ARTICLE.format(title=url.rsplit("/", 1)[-1]).encode())


def _row(conn, url):
    return conn.execute("SELECT * FROM statements WHERE url=?", (url,)).fetchone()


def test_failed_page_is_kept_and_retried(conn, catalog):
    collect(conn, catalog, FakeClient(down={STRAIT}), max_new_per_source=15, only="gb-fcdo")
    stub, full = _row(conn, STRAIT), _row(conn, RATES)
    assert stub["text"] == "Short teaser." and stub["page_missing_since"]  # kept, marked
    assert len(full["text"]) > 1000 and full["page_missing_since"] is None
    conn.execute("UPDATE statements SET extracted_at=?, relevant=1 WHERE url=?",
                 (now_iso(), STRAIT))
    conn.commit()

    # Still down on the next pass: retried, nothing changes.
    client = FakeClient(down={STRAIT})
    [result] = collect(conn, catalog, client, max_new_per_source=15, only="gb-fcdo")
    assert (result.retried, result.recovered) == (1, 0)
    assert RATES not in client.requested  # complete statements are not fetched again

    # Back up: the full text replaces the teaser and the statement is read again.
    [result] = collect(conn, catalog, FakeClient(down=set()), max_new_per_source=15,
                       only="gb-fcdo")
    assert (result.retried, result.recovered) == (1, 1)
    healed = _row(conn, STRAIT)
    assert len(healed["text"]) > 1000 and healed["page_missing_since"] is None
    assert healed["extracted_at"] is None and healed["relevant"] is None


def test_retries_stop_after_retry_window(conn, catalog):
    collect(conn, catalog, FakeClient(down={STRAIT}), max_new_per_source=15, only="gb-fcdo")
    assert pages_to_retry(conn)["gb-fcdo"][0]["url"] == STRAIT
    conn.execute("UPDATE statements SET page_missing_since='2026-01-01T00:00:00+00:00'")
    assert pages_to_retry(conn) == {}

from pathlib import Path

import pytest

from parallax.catalog import Catalog, CatalogError, Source, load_catalog, on_map, validate
from parallax.collect.parsers import normalize_url, parse_feed, parse_listing, to_iso

FIXTURES = Path(__file__).parent / "fixtures"
REPO = Path(__file__).parent.parent


def test_fixture_catalog_loads(catalog):
    assert len(catalog.sources) == 5
    assert [s.id for s in catalog.enabled_sources()] == ["gb-fcdo", "us-fed", "cn-mfa", "io-imf"]


def test_real_catalog_is_valid():
    load_catalog(REPO / "sources")  # raises CatalogError if sources.yaml breaks a rule


def _with(catalog, **overrides):
    base = dict(id="x", actor="GB", kind="mfa", name="x", homepage="h", method="rss",
                url="https://www.gov.uk/x.atom")
    return Catalog(catalog.actors, [Source(**{**base, **overrides})])


@pytest.mark.parametrize("overrides, message", [
    ({"actor": "XX"}, "unknown actor"),
    ({"kind": "news"}, "kind must be"),
    ({"url": "https://tass.com/rss/v2.xml"}, "out of scope"),
    ({"method": "html"}, "link_selector"),
    ({"actor": "imf", "kind": "mfa"}, "organisations use kind"),
])
def test_validation_rejects(catalog, overrides, message):
    with pytest.raises(CatalogError, match=message):
        validate(_with(catalog, **overrides))


def test_map_rules(catalog):
    assert on_map(catalog.actor("GB"), "mfa")
    assert not on_map(catalog.actor("US"), "central_bank")  # central banks: off the map in v1
    assert not on_map(catalog.actor("imf"), "org")           # orgs never colour a country


def test_parse_feed():
    items = parse_feed((FIXTURES / "sample.rss").read_bytes())
    assert [i.title for i in items] == ["Statement on the strait", "Rate decision"]
    assert items[0].url == "https://example.gov/news/strait"  # tracking parameter removed
    assert items[0].published_at == "2026-11-03T10:00:00+00:00"
    assert items[1].published_at == "2026-11-04T13:00:00+00:00"  # converted to UTC


def test_parse_listing():
    html = (FIXTURES / "listing.html").read_text()
    items = parse_listing(html, "https://www.fmprc.gov.cn/eng/xw/", "ul.list a", r"/eng/xw/")
    assert [i.url for i in items] == [
        "https://www.fmprc.gov.cn/eng/xw/202611/t1.html",
        "https://www.fmprc.gov.cn/eng/xw/202611/t2.html",
    ]
    assert items[0].title == "Spokesperson's remarks on the strait"


def test_normalize_and_dates():
    assert normalize_url("HTTPS://Example.GOV/a?id=3&utm_medium=x#top") == "https://example.gov/a?id=3"
    assert to_iso("2026-11-05") == "2026-11-05T00:00:00+00:00"
    assert to_iso("not a date") is None


def test_placeholder_pages_are_not_statements():
    from parallax.collect.parsers import parse_article
    html = ("<html><head><title>x</title></head><body><p>JavaScript is disabled in your "
            "browser. Please enable JavaScript to proceed.</p></body></html>")
    assert parse_article(html, "https://example.org/a").text is None


def test_listing_respects_base_href():
    html = ('<html><head><base href="https://x.de/Web/EN/"></head>'
            '<body><a href="News/a.html">A</a></body></html>')
    items = parse_listing(html, "https://x.de/Web/EN/Home/home.html", "a", None)
    assert items[0].url == "https://x.de/Web/EN/News/a.html"

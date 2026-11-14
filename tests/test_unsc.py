"""Security Council verbatim records: one meeting, one statement per catalog delegation."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from official_lines.catalog import CatalogError, on_map, validate
from official_lines.collect import unsc
from official_lines.collect.run import collect
from official_lines.site.build import kind_label

FIXTURES = Path(__file__).parent / "fixtures"
RECORD = (FIXTURES / "spv_sample.txt").read_text()
TABLE = """<table>
<tr><th>Meeting Record</th><th>Date</th><th>Press</th><th>Topic</th><th>Outcome</th></tr>
<tr><td>Document links will work once published.</td></tr>
<tr><td><a href="https://docs.un.org/S/PV.99999">S/PV.99999</a></td><td>18 March 2026</td>
<td><a href="https://www.un.org/press/en/2026/sc1.doc.htm"> SC/1 </a></td>
<td>The situation in the strait</td><td></td></tr>
<tr><td><a href="https://docs.un.org/S/PV.99998">S/PV.99998</a></td><td>17 March 2026</td>
<td></td><td>Threats to international peace and security</td><td>S/RES/1 15-0-0</td></tr>
</table>"""


def source(catalog):
    return next(s for s in catalog.sources if s.method == "unsc_records")


def test_meetings_table_parses_newest_first():
    meetings = unsc.parse_meetings(TABLE)
    assert [m.symbol for m in meetings] == ["S/PV.99999", "S/PV.99998"]
    assert meetings[0].date == "2026-03-18T00:00:00+00:00"
    assert meetings[0].topic == "The situation in the strait"
    assert meetings[0].press_release == "SC/1"
    assert meetings[1].press_release is None


def test_due_meetings_respect_delay_age_and_known():
    meetings = unsc.parse_meetings(TABLE)
    now = datetime(2026, 3, 20, tzinfo=UTC)
    assert unsc.due_meetings(meetings, set(), now) == []  # both younger than the delay
    now = datetime(2026, 3, 25, tzinfo=UTC)
    assert [m.symbol for m in unsc.due_meetings(meetings, set(), now)] == ["S/PV.99999",
                                                                           "S/PV.99998"]
    known = {"https://docs.un.org/S/PV.99999#CN", "https://example.gov/x"}
    assert [m.symbol for m in unsc.due_meetings(meetings, known, now)] == ["S/PV.99998"]
    assert unsc.due_meetings(meetings, set(), datetime(2026, 6, 1, tzinfo=UTC)) == []  # too old


def test_record_is_split_per_catalog_delegation(catalog):
    turns, missed = unsc.split_turns(RECORD, catalog)
    assert [t.actor for t in turns] == ["CN", "GB", "un", "CN"]  # no President, no briefer
    assert missed == {"Ruritania": 1}
    china = turns[0].text
    assert china.startswith("A ship was stopped in the strait.")
    assert "constructive role" in china and "S/PV.99999" not in china and "2/9" not in china
    assert "(spoke in Chinese)" not in china

    meeting = unsc.parse_meetings(TABLE)[0]
    rows = unsc.statements_for(meeting, turns, source(catalog), catalog)
    assert [r["actor"] for r in rows] == ["CN", "GB", "un"]
    cn = rows[0]
    assert cn["url"] == "https://docs.un.org/S/PV.99999#CN" and cn["kind"] == "un_record"
    assert cn["title"] == ("China at the Security Council on the situation in the strait "
                           "(S/PV.99999, 18 March 2026)")
    assert cn["published_at"] == meeting.date
    assert "groundless" in cn["text"]
    assert cn["text"].index("A ship") < cn["text"].index("groundless")


def test_speaker_names_map_to_actors(catalog):
    assert unsc.speaker_actor("Mr. Nebenzia", "Russian Federation", catalog) == "RU"
    assert unsc.speaker_actor("Mr. X", "United Kingdom of Great Britain and Northern Ireland",
                              catalog) == "GB"
    assert unsc.speaker_actor("Mr. X", "Iran (Islamic Republic of)", catalog) == "IR"
    assert unsc.speaker_actor("Mr. X", "European Union", catalog) == "eu"
    assert unsc.speaker_actor("Mr. X", "Republic of Korea", catalog) is None
    assert unsc.speaker_actor("The President", None, catalog) is None
    assert unsc.speaker_actor("The Secretary-General", None, catalog) == "un"


def test_record_url_is_one_setting(monkeypatch):
    assert unsc.record_url("S/PV.1") == unsc.DEFAULT_RECORD_URL.format(symbol="S/PV.1")
    monkeypatch.setenv("OFFICIAL_LINES_UN_RECORD_URL", "https://allowed.example/{symbol}.pdf")
    assert unsc.record_url("S/PV.1") == "https://allowed.example/S/PV.1.pdf"


def minimal_pdf(text: str) -> bytes:
    """A one-page PDF with one line of text and a correct cross-reference table."""
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
            .encode())
    return out


def test_pdf_text_reads_a_pdf():
    assert "The meeting was called to order." in unsc.pdf_text(
        minimal_pdf("The meeting was called to order."))


class Page:
    def __init__(self, body: bytes, content_type: str):
        self.content, self.text = body, body.decode("latin-1")
        self.headers = {"content-type": content_type}


class RecordClient:
    """The meetings table, and a record for S/PV.99999 only (99998 is 'not published')."""

    def __init__(self):
        self.requested: list[str] = []

    def get(self, url: str) -> Page:
        self.requested.append(url)
        if "render_meeting" in url:
            return Page(TABLE.encode(), "text/html")
        if "S/PV.99999" in url:
            return Page(b"%PDF-fake", "application/pdf")
        return Page(b"<html>not yet</html>", "text/html")


def test_collect_stores_one_statement_per_delegation(conn, catalog, monkeypatch):
    monkeypatch.setattr(unsc, "pdf_text", lambda data: RECORD)
    monkeypatch.setattr(unsc, "datetime", _FixedDatetime)
    src = source(catalog)
    client = RecordClient()
    [result] = collect(conn, catalog, client, max_new_per_source=15, only=src.id)
    assert (result.found, result.new, result.error) == (2, 3, None)
    rows = conn.execute("SELECT actor, kind, url, published_at FROM statements"
                        " WHERE source_id=? ORDER BY url", (src.id,)).fetchall()
    assert [(r["actor"], r["kind"]) for r in rows] == [("CN", "un_record"), ("GB", "un_record"),
                                                       ("un", "un_record")]
    assert all(r["published_at"] == "2026-03-18T00:00:00+00:00" for r in rows)
    assert sum("S/PV.99999" in u for u in client.requested) == 1

    # The next pass fetches only the record that was not published (99999 is stored).
    client = RecordClient()
    [result] = collect(conn, catalog, client, max_new_per_source=15, only=src.id)
    assert (result.found, result.new) == (2, 0)
    assert not any("S/PV.99999" in u for u in client.requested)


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 3, 25, tzinfo=tz or UTC)


def test_catalog_rules_for_records(catalog):
    assert not on_map(catalog.actor("CN"), "un_record")  # a Council speech never colours the map
    assert kind_label("un_record") == "at the Security Council, verbatim record"
    assert kind_label("mfa") == "mfa"
    src = source(catalog)
    validate(catalog)
    broken = type(src)(**{**src.__dict__, "actor": "CN"})
    catalog.sources.append(broken)
    with pytest.raises(CatalogError):
        validate(catalog)
    catalog.sources.pop()

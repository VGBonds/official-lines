"""The whole chain on fake data: extract -> group -> analyze -> brief -> build site."""

import json

import pytest

from official_lines.collect.run import sync_sources
from official_lines.db import now_iso
from official_lines.llm.client import AnthropicLLM, BudgetExceeded
from official_lines.pipeline.analyze import analyze_due
from official_lines.pipeline.brief import write_brief
from official_lines.pipeline.events import group_pending
from official_lines.pipeline.extract import extract_pending
from official_lines.site.build import build_site
from tests.conftest import FakeLLM

RESTRAINT = "We call on all parties to exercise maximum restraint and avoid escalation now."
BRIEFING = ("Spokesperson's regular press conference. Q: On the strait. A: " + RESTRAINT
            + " Q: On trade talks. A: The talks were constructive and continue next week.")
STATEMENTS = [
    ("gb-fcdo", "GB", "mfa", "UK statement on the strait"),
    ("cn-mfa", "CN", "mfa", "Regular press conference"),
    ("us-fed", "US", "central_bank", "Fed remarks touching the strait"),
    ("io-imf", "imf", "org", "IMF on shipping disruption in the strait"),
    ("gb-fcdo", "GB", "mfa", "Vacancy: press officer"),
]


@pytest.fixture
def filled(conn, catalog):
    sync_sources(conn, catalog)
    for i, (src, actor, kind, title) in enumerate(STATEMENTS):
        conn.execute(
            "INSERT INTO statements (source_id, actor, kind, url, title, published_at,"
            " fetched_at, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (src, actor, kind, f"https://x/{i}", title, now_iso(), now_iso(),
             BRIEFING if actor == "CN" else RESTRAINT),
        )
    conn.commit()
    return conn


def test_full_pipeline(filled, catalog, tmp_path):
    llm = FakeLLM()
    assert extract_pending(filled, catalog, llm, "m", limit=100) == 5
    assert filled.execute("SELECT COUNT(*) FROM statements WHERE relevant=0").fetchone()[0] == 1

    # 4 relevant statements; the Chinese briefing has two parts, so 5 parts.
    assert group_pending(filled, catalog, llm, "m") == 5
    events = {e["title"]: e for e in filled.execute("SELECT * FROM events")}
    assert set(events) == {"Strait incident", "Trade talks"}
    strait = events["Strait incident"]
    assert strait["slug"] == f"strait-incident-{strait['id']}"
    actors = {r[0] for r in filled.execute(
        "SELECT s.actor FROM parts p JOIN statements s ON s.id = p.statement_id"
        " WHERE p.event_id=?", (strait["id"],))}
    assert actors == {"GB", "CN", "US", "imf"}  # China's briefing sits next to the others

    # Only the strait has 2+ actors; trade talks (China alone) is not compared.
    assert analyze_due(filled, catalog, llm, "m", max_per_day=5) == 1
    assert analyze_due(filled, catalog, llm, "m", max_per_day=5) == 0  # nothing new to compare


def test_daily_cap(filled, catalog):
    llm = FakeLLM()
    extract_pending(filled, catalog, llm, "m", limit=100)
    group_pending(filled, catalog, llm, "m")
    for _ in range(3):
        filled.execute("INSERT INTO llm_calls (at, purpose, model, input_tokens, output_tokens,"
                       " cost_usd) VALUES (?, 'analyze', 'm', 0, 0, 0)", (now_iso(),))
    assert analyze_due(filled, catalog, llm, "m", max_per_day=3) == 0


def test_analysis_and_site(filled, catalog, tmp_path):
    llm = FakeLLM()
    extract_pending(filled, catalog, llm, "m", limit=100)
    group_pending(filled, catalog, llm, "m")
    slug = filled.execute("SELECT slug FROM events WHERE title='Strait incident'").fetchone()[0]
    assert analyze_due(filled, catalog, llm, "m", max_per_day=5, only_slug=slug) == 1

    analysis = json.loads(filled.execute("SELECT analysis FROM events WHERE slug=?",
                                         (slug,)).fetchone()[0])
    m = analysis["metrics"]
    assert m["shared_floor"] == ["p1"] and m["contested"] == ["p2"]
    assert m["shared_wording"]  # identical texts across actors are flagged

    brief = write_brief(filled, catalog, llm, "m", "https://p.example", tmp_path / "briefs")
    assert brief.read_text().startswith("# Brief")

    out = tmp_path / "site"
    build_site(filled, catalog, out, "https://p.example", tmp_path / "briefs")
    page = (out / "event" / f"{slug}.html").read_text()
    # Foreign ministries colour the map; the Fed (central bank) and the IMF do not.
    assert "data-lit='[\"156\", \"826\"]'" in page
    assert "International Monetary Fund" in page
    assert "one of several topics in this statement" in page
    assert "A ship was stopped in the strait on 1 November." in page  # background
    assert "Shared wording:" in page and "identical passage of 13 words" in page
    assert "provocation" in page  # terminology with two actors and different words
    wording_page = (out / "wording.html").read_text()
    assert "We call on all parties to exercise maximum restraint" in wording_page
    assert f"event/{slug}.html" in wording_page
    assert 'data-ids=" ' in (out / "index.html").read_text()
    assert "A ship was stopped in the strait on 1 November." in (out / "index.html").read_text()
    china = (out / "actor" / "CN.html").read_text()
    assert "Strait incident" in china and "Trade talks" in china
    assert (out / "index.html").exists() and (out / "coverage.html").exists()
    assert "Bank of Russia" in (out / "coverage.html").read_text()  # disabled sources shown

    # The search index: every proposition with its stances and quotes, every claim once.
    index = json.loads((out / "search.json").read_text())
    p2 = next(p for p in index["props"] if p["e"] == slug and p["l"] == "contested")
    assert {(s["a"], s["s"]) for s in p2["stances"]} >= {("CN", "denies"), ("US", "asserts")}
    assert all(s["q"] and s["n"] for s in p2["stances"])
    claims = [c for c in index["claims"] if c["e"] == slug]
    assert claims and len({(c["a"], c["c"]) for c in claims}) == len(claims)
    assert claims[0]["sd"] and index["events"][slug]["t"] == "Strait incident"
    search = (out / "search.html").read_text()
    assert "static/search.js" in search and 'href="./search.html"' in page.replace("..", ".")


def test_budget_guard(conn):
    conn.execute("INSERT INTO llm_calls (at, purpose, model, input_tokens, output_tokens,"
                 " cost_usd) VALUES (?, 'x', 'm', 0, 0, 5.0)", (now_iso(),))
    llm = AnthropicLLM(conn, monthly_budget_usd=5.0, client=object())
    with pytest.raises(BudgetExceeded):
        llm.text(purpose="t", model="m", system="s", user="u", max_tokens=10, effort="low")


def test_merge_duplicates(filled, catalog):
    from official_lines.llm.schemas import Merge, Merges
    from official_lines.pipeline.events import apply_merges
    now = now_iso()
    ids = [filled.execute("INSERT INTO events (slug, title, created_at, last_seen) VALUES"
                          " (?, 'x', ?, ?)", (f"e{i}", now, now)).lastrowid for i in range(3)]
    extract_pending(filled, catalog, FakeLLM(), "m", limit=100)
    for actor, event_id in (("GB", ids[0]), ("CN", ids[1])):
        filled.execute("UPDATE parts SET event_id=? WHERE statement_id IN"
                       " (SELECT id FROM statements WHERE actor=?)", (event_id, actor))
    filled.execute("UPDATE events SET featured=1 WHERE id=?", (ids[1],))
    merges = Merges(merges=[Merge(keep=ids[0], merge=[ids[1], 9999, ids[0]])])
    assert apply_merges(filled, merges, set(ids)) == 1
    actors = {r[0] for r in filled.execute(
        "SELECT s.actor FROM parts p JOIN statements s ON s.id = p.statement_id"
        " WHERE p.event_id=?", (ids[0],))}
    assert actors == {"GB", "CN"}
    assert filled.execute("SELECT featured FROM events WHERE id=?", (ids[0],)).fetchone()[0] == 1
    assert filled.execute("SELECT COUNT(*) FROM events WHERE id=?", (ids[1],)).fetchone()[0] == 0


def test_locate_parts():
    from official_lines.pipeline.extract import locate_parts
    from tests.conftest import strait_part, trade_part
    spans = locate_parts(BRIEFING, [strait_part("Q: on the  strait"), trade_part()])
    first, second = (BRIEFING[a:b] for a, b in spans)
    assert first.startswith("Q: On the strait") and "maximum restraint" in first
    assert "trade" not in first and second.startswith("Q: On trade talks")
    # Opening not found: fall back to the claim's quote; nothing found at all: (None, None).
    assert locate_parts(BRIEFING, [strait_part("no such words here", "maximum restraint"),
                                   strait_part("missing too", "absent quote here")])[1] == \
        (None, None)
    assert locate_parts("anything", [trade_part()]) == [(0, 8)]


def test_migration_from_v1(tmp_path):
    import sqlite3

    from official_lines.db import connect
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE sources (id TEXT PRIMARY KEY, actor TEXT, kind TEXT, name TEXT);
        CREATE TABLE events (id INTEGER PRIMARY KEY, slug TEXT, title TEXT, created_at TEXT);
        CREATE TABLE statements (id INTEGER PRIMARY KEY, source_id TEXT, actor TEXT,
            kind TEXT, url TEXT UNIQUE, title TEXT, published_at TEXT, fetched_at TEXT,
            text TEXT, extraction TEXT, extracted_at TEXT, relevant INTEGER, domain TEXT,
            event_id INTEGER REFERENCES events(id), grouped_at TEXT);
        CREATE INDEX idx_statements_event ON statements(event_id);
        INSERT INTO sources VALUES ('s', 'GB', 'mfa', 'S');
        INSERT INTO events VALUES (1, 'e', 'E', '2026-11-01');
        INSERT INTO statements VALUES (7, 's', 'GB', 'mfa', 'https://x', 'T', NULL, '2026-11-01',
            'body', '{}', '2026-11-01', 1, 'politics', 1, '2026-11-01');
    """)
    old.commit()
    old.close()
    conn = connect(path)
    row = conn.execute("SELECT * FROM statements").fetchone()
    assert row["id"] == 7 and row["text"] == "body" and row["extracted_at"] is None
    assert "event_id" not in row.keys()
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    connect(path)  # a second connect is a no-op


def test_new_actor_triggers_update(filled, catalog, tmp_path):
    """A compared event that a new actor joins is compared again on the next run, even when
    the day's new comparisons are used up; until then the page says who is missing."""
    llm = FakeLLM()
    extract_pending(filled, catalog, llm, "m", limit=100)
    group_pending(filled, catalog, llm, "m")
    assert analyze_due(filled, catalog, llm, "m", max_per_day=5) == 1
    strait = filled.execute("SELECT id, slug FROM events WHERE title='Strait incident'").fetchone()

    # Russia speaks later; its passage lands in the already compared event.
    sid = filled.execute(
        "INSERT INTO statements (source_id, actor, kind, url, title, published_at, fetched_at,"
        " text, extracted_at, relevant) VALUES ('ru-cbr', 'RU', 'central_bank', 'https://x/ru',"
        " 'Russia on the strait', ?, ?, ?, ?, 1)", (now_iso(), now_iso(), RESTRAINT, now_iso()),
    ).lastrowid
    filled.execute("INSERT INTO parts (statement_id, idx, issue, summary, data, text_start,"
                   " text_end, event_id) VALUES (?, 0, 'Strait incident', 'Russia comments.',"
                   " '{}', 0, ?, ?)", (sid, len(RESTRAINT), strait["id"]))
    filled.commit()

    out = tmp_path / "site"
    build_site(filled, catalog, out, "https://p.example", tmp_path / "briefs")
    page = (out / "event" / f"{strait['slug']}.html").read_text()
    assert f"Statements from {catalog.actor('RU').name} arrived later" in page

    for _ in range(5):  # today's new comparisons are used up
        filled.execute("INSERT INTO llm_calls (at, purpose, model, input_tokens, output_tokens,"
                       " cost_usd) VALUES (?, 'analyze', 'm', 0, 0, 0)", (now_iso(),))
    assert analyze_due(filled, catalog, llm, "m", max_per_day=5) == 1
    assert llm.calls[-1] == "update"
    analysis = json.loads(filled.execute("SELECT analysis FROM events WHERE id=?",
                                         (strait["id"],)).fetchone()[0])
    assert "RU" in analysis["actors"]
    assert analyze_due(filled, catalog, llm, "m", max_per_day=5) == 0  # up to date now

    build_site(filled, catalog, out, "https://p.example", tmp_path / "briefs")
    assert "arrived later" not in (out / "event" / f"{strait['slug']}.html").read_text()


JOINT_TEXT = ("We, the foreign ministers, are concerned by the stopping of a ship in the strait "
              "and call on all parties to exercise restraint. " * 6)


def test_joint_text_is_one_voice(conn, catalog, tmp_path):
    """The UK and the US publish the same text; China answers. The table has two columns,
    the joint text counts once, and the UK-US pair is not a measured agreement."""
    sync_sources(conn, catalog)
    rows = [("gb-fcdo", "GB", "mfa", "Joint statement on the strait", JOINT_TEXT),
            ("us-fed", "US", "central_bank", "Joint statement on the strait",
             "Washington. " + JOINT_TEXT),
            ("cn-mfa", "CN", "mfa", "Remarks on the strait", RESTRAINT)]
    for i, (src, actor, kind, title, text) in enumerate(rows):
        conn.execute(
            "INSERT INTO statements (source_id, actor, kind, url, title, published_at,"
            " fetched_at, text) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (src, actor, kind, f"https://j/{i}", title, now_iso(), now_iso(), text))
    conn.commit()
    llm = FakeLLM()
    extract_pending(conn, catalog, llm, "m", limit=100)
    group_pending(conn, catalog, llm, "m")
    assert analyze_due(conn, catalog, llm, "m", max_per_day=5) == 1
    row = conn.execute("SELECT slug, analysis FROM events WHERE analysis IS NOT NULL").fetchone()
    a = json.loads(row["analysis"])
    assert list(a["voices"]) == ["joint:GB+US"]
    assert a["voices"]["joint:GB+US"]["members"] == ["GB", "US"]
    assert a["actors"] == ["CN", "GB", "US"]
    assert set(a["metrics"]["stance_table"]) == {"CN", "joint:GB+US"}
    assert a["metrics"]["pairs"]["GB|US"]["joint"] is True
    assert "joint" not in a["metrics"]["pairs"]["CN|GB"]
    assert a["metrics"]["contested"] == ["p2"]

    out = tmp_path / "site"
    build_site(conn, catalog, out, "https://p.example", tmp_path / "briefs")
    page = (out / "event" / f"{row['slug']}.html").read_text()
    assert "<th>United Kingdom and United States (joint text)</th>" in page
    matrix = page[page.index('<table class="matrix">'):page.index("</table>")]
    assert matrix.count("<th>") == 3  # proposition + two voices
    assert "published the same text" in page

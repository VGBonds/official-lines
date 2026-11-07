"""The whole chain on fake data: extract -> group -> analyze -> brief -> build site."""

import json

import pytest

from parallax.collect.run import sync_sources
from parallax.db import now_iso
from parallax.llm.client import AnthropicLLM, BudgetExceeded
from parallax.pipeline.analyze import analyze_due
from parallax.pipeline.brief import write_brief
from parallax.pipeline.events import group_pending
from parallax.pipeline.extract import extract_pending
from parallax.site.build import build_site
from tests.conftest import FakeLLM

STATEMENTS = [
    ("gb-fcdo", "GB", "mfa", "UK statement on the strait"),
    ("cn-mfa", "CN", "mfa", "Spokesperson on the strait"),
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
             "We call on all parties to exercise maximum restraint and avoid escalation now."),
        )
    conn.commit()
    return conn


def test_full_pipeline(filled, catalog, tmp_path):
    llm = FakeLLM()
    assert extract_pending(filled, catalog, llm, "m", limit=100) == 5
    assert filled.execute("SELECT COUNT(*) FROM statements WHERE relevant=0").fetchone()[0] == 1

    assert group_pending(filled, catalog, llm, "m") == 4
    events = filled.execute("SELECT * FROM events").fetchall()
    assert len(events) == 1 and events[0]["slug"] == f"strait-incident-{events[0]['id']}"

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
    slug = filled.execute("SELECT slug FROM events").fetchone()[0]
    assert analyze_due(filled, catalog, llm, "m", max_per_day=5, only_slug=slug) == 1

    analysis = json.loads(filled.execute("SELECT analysis FROM events").fetchone()[0])
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
    assert (out / "index.html").exists() and (out / "coverage.html").exists()
    assert "Bank of Russia" in (out / "coverage.html").read_text()  # disabled sources shown


def test_budget_guard(conn):
    conn.execute("INSERT INTO llm_calls (at, purpose, model, input_tokens, output_tokens,"
                 " cost_usd) VALUES (?, 'x', 'm', 0, 0, 5.0)", (now_iso(),))
    llm = AnthropicLLM(conn, monthly_budget_usd=5.0, client=object())
    with pytest.raises(BudgetExceeded):
        llm.text(purpose="t", model="m", system="s", user="u", max_tokens=10, effort="low")

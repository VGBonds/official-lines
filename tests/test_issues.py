"""Step 4: propositions of compared events filed under issues, and the issue pages."""

import json

from official_lines.db import now_iso
from official_lines.llm.schemas import IssueChoice, IssueMapping, NewIssue
from official_lines.pipeline import issues, metrics
from official_lines.pipeline.analyze import analyze_due
from official_lines.pipeline.events import group_pending
from official_lines.pipeline.extract import extract_pending
from official_lines.site.build import build_site
from tests.conftest import FakeLLM
from tests.test_pipeline import RESTRAINT, filled  # noqa: F401  (fixture)


def compared_strait(conn, catalog, llm):
    extract_pending(conn, catalog, llm, "m", limit=100)
    group_pending(conn, catalog, llm, "m")
    assert analyze_due(conn, catalog, llm, "m", max_per_day=5) == 1
    return conn.execute("SELECT * FROM events WHERE title='Strait incident'").fetchone()


def second_event(conn, title="Second strait incident"):
    """Another compared-to-be event with the same two actors, a week later."""
    now = now_iso()
    event_id = conn.execute(
        "INSERT INTO events (slug, title, created_at, first_seen, last_seen) VALUES"
        " (?, ?, ?, '2026-12-01T00:00:00+00:00', '2026-12-01T00:00:00+00:00')",
        (f"second-{now[:10]}", title, now)).lastrowid
    for i, (src, actor) in enumerate((("gb-fcdo", "GB"), ("cn-mfa", "CN"))):
        sid = conn.execute(
            "INSERT INTO statements (source_id, actor, kind, url, title, published_at,"
            " fetched_at, text, extracted_at, relevant) VALUES (?, ?, 'mfa', ?, ?, ?, ?, ?, ?, 1)",
            (src, actor, f"https://second/{i}", f"{actor} on the second incident",
             "2026-12-01T00:00:00+00:00", now, RESTRAINT, now)).lastrowid
        conn.execute("INSERT INTO parts (statement_id, idx, issue, summary, data, text_start,"
                     " text_end, event_id) VALUES (?, 0, 'Strait incident', 's', '{}', 0, ?, ?)",
                     (sid, len(RESTRAINT), event_id))
    conn.commit()
    return conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()


def filings(conn):
    return {(r[0], r[1]): r[2] for r in conn.execute(
        "SELECT m.event_id, m.proposition_id, i.title FROM issue_propositions m"
        " JOIN issues i ON i.id = m.issue_id")}


def test_filed_under_issues_across_events(filled, catalog, tmp_path):  # noqa: F811
    llm = FakeLLM()
    strait = compared_strait(filled, catalog, llm)
    assert [e["id"] for e in issues.events_due(filled)] == [strait["id"]]
    assert issues.map_due(filled, llm, "m") == 1
    assert llm.calls[-1] == "issues"
    assert filings(filled) == {(strait["id"], "p1"): "Ship stoppages in the strait",
                               (strait["id"], "p2"): "Maritime law in the strait"}
    slugs = [r[0] for r in filled.execute("SELECT slug FROM issues ORDER BY id")]
    assert slugs == ["ship-stoppages-in-the-strait-1", "maritime-law-in-the-strait-2"]
    assert issues.events_due(filled) == [] and issues.map_due(filled, llm, "m") == 0

    # A second event with the same propositions is filed under the SAME two issues.
    second = second_event(filled)
    assert analyze_due(filled, catalog, llm, "m", max_per_day=5, only_slug=second["slug"]) == 1
    assert issues.map_due(filled, llm, "m") == 1
    assert filled.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == 2
    assert len(filings(filled)) == 4

    # A re-comparison that keeps the propositions keeps the filing; one that rewords them
    # makes it stale: left out of the site until the next run files the event again.
    assert analyze_due(filled, catalog, llm, "m", max_per_day=5, only_slug=strait["slug"]) == 1
    assert issues.events_due(filled) == []
    analysis = json.loads(filled.execute("SELECT analysis FROM events WHERE id=?",
                                         (strait["id"],)).fetchone()[0])
    analysis["llm"]["propositions"][1]["text"] = "The stop was lawful."
    filled.execute("UPDATE events SET analysis=? WHERE id=?",
                   (json.dumps(analysis), strait["id"]))
    filled.commit()
    assert [e["id"] for e in issues.events_due(filled)] == [strait["id"]]
    out = tmp_path / "site"
    build_site(filled, catalog, out, "https://p.example", tmp_path / "briefs")
    page = (out / "issue" / "ship-stoppages-in-the-strait-1.html").read_text()
    assert second["slug"] in page and strait["slug"] not in page  # (the comparison retitles)
    assert issues.map_due(filled, llm, "m") == 1
    assert len(filings(filled)) == 4
    assert filings(filled)[(strait["id"], "p2")] == "Other questions"  # reworded: filed anew

    build_site(filled, catalog, out, "https://p.example", tmp_path / "briefs")
    index = (out / "issues.html").read_text()
    assert 'href="issue/ship-stoppages-in-the-strait-1.html"' in index
    assert "Maritime law in the strait" in index
    page = (out / "issue" / "ship-stoppages-in-the-strait-1.html").read_text()
    # One row per proposition and event, with the original wording and the event link.
    assert page.count("A ship was stopped.") == 2
    assert f'href="../event/{strait["slug"]}.html"' in page
    assert f'href="../event/{second["slug"]}.html"' in page
    assert "<th>China</th>" in page and "<th>United Kingdom</th>" in page
    assert 'title="“a ship was stopped”" tabindex="0">●</span>' in page and "shared floor" in page
    law = (out / "issue" / "maritime-law-in-the-strait-2.html").read_text()
    assert 'title="“a violation”" tabindex="0">●</span>' in law
    assert 'title="“no violation”" tabindex="0">○</span>' in law
    assert "contested" in law and "Stances per voice" in law
    event_page = (out / "event" / f"{strait['slug']}.html").read_text()
    assert 'href="../issue/ship-stoppages-in-the-strait-1.html"' in event_page
    assert "Issues</a>" in (out / "index.html").read_text()  # nav link


def test_mapping_guards(filled, catalog):  # noqa: F811
    llm = FakeLLM()
    strait = compared_strait(filled, catalog, llm)
    existing = issues.find_or_create_issue(filled, "Maritime law in the strait")
    filled.commit()
    props = issues.propositions_of(strait)
    mapping = IssueMapping(
        choices=[IssueChoice(proposition_id="p1", issue="I999"),      # not offered: skipped
                 IssueChoice(proposition_id="p1", issue="new:law"),   # first choice won
                 IssueChoice(proposition_id="p2", issue="new:law"),
                 IssueChoice(proposition_id="p9", issue="new:law")],  # unknown proposition
        new_issues=[NewIssue(key="new:law", title="maritime LAW in the strait")])
    assert issues.apply_mapping(filled, strait, props, mapping, {existing}) == 1
    assert filings(filled) == {(strait["id"], "p2"): "Maritime law in the strait"}  # reused
    assert filled.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == 1
    # An undeclared new key still files the proposition: the key becomes the title. A choice
    # spelled 'NEW: Host country' matches a declaration 'new:host-country'.
    undeclared = IssueMapping(choices=[IssueChoice(proposition_id="p1", issue="new:host-country"),
                                       IssueChoice(proposition_id="p2", issue=str(existing))],
                              new_issues=[])
    assert issues.apply_mapping(filled, strait, props, undeclared, {existing}) == 2
    assert filings(filled) == {(strait["id"], "p1"): "Host country",
                               (strait["id"], "p2"): "Maritime law in the strait"}
    spelled = IssueMapping(choices=[IssueChoice(proposition_id="p1", issue="NEW: Host Country"),
                                    IssueChoice(proposition_id="p2", issue=f"I{existing}")],
                           new_issues=[NewIssue(key="new:host-country", title="Host country")])
    assert issues.apply_mapping(filled, strait, props, spelled, {existing}) == 2
    assert filled.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == 2  # reused, not new


def test_remap_all_and_candidates(filled, catalog, monkeypatch):  # noqa: F811
    llm = FakeLLM()
    strait = compared_strait(filled, catalog, llm)
    issues.find_or_create_issue(filled, "Old issue nobody uses")
    filled.commit()
    assert issues.map_due(filled, llm, "m") == 1
    assert issues.drop_empty_issues(filled) == 1
    assert issues.remap_all(filled, llm, "m") == 1
    titles = {r[0] for r in filled.execute("SELECT title FROM issues")}
    assert titles == {"Ship stoppages in the strait", "Maritime law in the strait"}
    assert len(filings(filled)) == 2

    # Past the cap, only recently used issues and word matches are offered.
    monkeypatch.setattr(issues, "MAX_ISSUES_SHOWN", 1)
    filled.execute("INSERT INTO issues (slug, title, created_at) VALUES ('stale-9', 'Unrelated"
                   " question', ?)", (now_iso(),))
    filled.execute("INSERT INTO issues (slug, title, created_at) VALUES ('old-10', 'Old"
                   " maritime matters', ?)", (now_iso(),))
    filled.commit()
    offered = {r["title"] for r in issues.candidate_issues(filled, issues.propositions_of(
        filled.execute("SELECT * FROM events WHERE id=?", (strait["id"],)).fetchone()))}
    assert offered == {"Ship stoppages in the strait", "Maritime law in the strait",
                       "Old maritime matters"}  # 'maritime' matches a proposition word


def test_issue_counts():
    rows = [{"event_id": 1, "contested": True,
             "cells": {"US": {"stance": "asserts"}, "CN": {"stance": "denies"}}},
            {"event_id": 1, "contested": False, "cells": {"US": {"stance": "qualifies"}}},
            {"event_id": 2, "contested": False, "cells": {"US": {"stance": "asserts"}}}]
    counts = metrics.issue_counts(rows)
    assert counts["events"] == 2 and counts["propositions"] == 3 and counts["contested"] == 1
    assert counts["voices"]["US"] == {"asserts": 2, "qualifies": 1, "denies": 0, "events": 2}
    assert counts["voices"]["CN"] == {"asserts": 0, "qualifies": 0, "denies": 1, "events": 1}


def test_estimate_cost_is_small():
    # A month of filings at the current volume (12 comparisons a day, 6 propositions each)
    # with a few hundred issues on the list stays well under a dollar with Haiku.
    month = issues.estimate_cost(12 * 30, 300, 6, "claude-haiku-5-5")
    assert 0 < month < 0.5
    assert issues.estimate_cost(0, 0, 0, "claude-haiku-5-5") == 0


def test_issues_command(filled, catalog, monkeypatch, capsys):  # noqa: F811
    import argparse

    from official_lines import cli
    llm = FakeLLM()
    compared_strait(filled, catalog, llm)
    monkeypatch.setattr(cli, "_llm", lambda settings, conn: llm)
    settings = argparse.Namespace(extract_model="claude-haiku-5-5")
    cli.cmd_issues(argparse.Namespace(all=False), settings, catalog, filled)
    out = capsys.readouterr().out
    assert "1 compared events to file" in out and "estimated cost $0.00" in out
    assert "filed 1 of 1 events; 2 issues now" in out
    cli.cmd_issues(argparse.Namespace(all=False), settings, catalog, filled)
    assert "nothing to file" in capsys.readouterr().out
    cli.cmd_issues(argparse.Namespace(all=True), settings, catalog, filled)
    assert "filed 1 of 1 events; 2 issues now" in capsys.readouterr().out
    analysis = json.loads(filled.execute("SELECT analysis FROM events WHERE analysis IS NOT"
                                         " NULL").fetchone()[0])
    assert len(analysis["llm"]["propositions"]) == 2  # the comparison itself is untouched

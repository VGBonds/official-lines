import re
from pathlib import Path

import pytest

from official_lines.catalog import load_catalog
from official_lines.db import connect
from official_lines.llm.schemas import (
    Assignment,
    Claim,
    EventAnalysis,
    Framing,
    Grouping,
    IssuePart,
    KeyTerm,
    NewEvent,
    Position,
    Proposition,
    StatementExtraction,
    TermComparison,
    TermUsage,
)

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def catalog():
    return load_catalog(FIXTURES / "catalog")


@pytest.fixture
def conn(tmp_path):
    return connect(tmp_path / "test.db")


def strait_part(opening="", quote="a ship was stopped"):
    return IssuePart(
        issue="Strait incident", opening=opening,
        summary="The source comments on the strait incident.",
        topics=["shipping", "strait"], places=["Strait"],
        claims=[Claim(text="A ship was stopped.", quote=quote, type="fact")],
        key_terms=[KeyTerm(term="incident", refers_to="the stopping of a ship")],
    )


def trade_part():
    return IssuePart(
        issue="Trade talks", opening="Q: On trade talks.", summary="Talks will continue.",
        topics=["trade"], places=[],
        claims=[Claim(text="Talks were constructive.", quote="the talks were constructive",
                      type="position")],
        key_terms=[],
    )


class FakeLLM:
    """Stands in for the API. Parts are grouped by their issue; each actor gets a stance.
    A 'press conference' is split into two parts: the strait and trade talks."""

    def __init__(self):
        self.calls = []

    def structured(self, *, purpose, model, system, user, schema, max_tokens, effort):
        self.calls.append(purpose)
        if schema is StatementExtraction:
            relevant = "vacancy" not in user.lower()
            if "press conference" in user.lower():
                parts = [strait_part("Q: On the strait.", "maximum restraint"), trade_part()]
            else:
                parts = [strait_part()]
            return StatementExtraction(relevant=relevant, domain="politics",
                                       summary="The source comments.",
                                       parts=parts if relevant else [])
        if schema is Grouping:
            found = re.findall(r"^\[(\d+)\].*\n\s+issue: (.+)$", user, flags=re.M)
            keys = {issue: "new:" + issue.lower().replace(" ", "-") for _, issue in found}
            return Grouping(
                assignments=[Assignment(part_id=int(i), event=keys[issue]) for i, issue in found],
                new_events=[NewEvent(key=k, title=issue, summary=f"About the {issue.lower()}.")
                            for issue, k in keys.items()],
            )
        if schema is EventAnalysis:
            actors = sorted(set(re.findall(r"actor=(\w+)", user)))
            ids = {a: int(re.search(rf"statement_id=(\d+) actor={a}\b", user).group(1))
                   for a in actors}
            positions = [Position(actor=a, proposition_id="p1", stance="asserts",
                                  quote="a ship was stopped", statement_id=ids[a])
                         for a in actors]
            positions.append(Position(actor=actors[0], proposition_id="p2", stance="denies",
                                      quote="no violation", statement_id=ids[actors[0]]))
            positions += [Position(actor=a, proposition_id="p2", stance="asserts",
                                   quote="a violation", statement_id=ids[a]) for a in actors[1:]]
            return EventAnalysis(
                title="Strait incident", summary="Several actors commented.",
                background="A ship was stopped in the strait on 1 November.",
                propositions=[Proposition(id="p1", text="A ship was stopped."),
                              Proposition(id="p2", text="The stop violated maritime law.")],
                positions=positions,
                terminology=[TermComparison(concept="the stop", usages=[
                    TermUsage(actor=a, term="incident") for a in actors])],
                framing=[Framing(actor=a, frame="Emphasises navigation.") for a in actors],
            )
        raise AssertionError(f"unexpected schema {schema}")

    def text(self, *, purpose, model, system, user, max_tokens, effort):
        self.calls.append(purpose)
        return "# Brief\n\nDraft."

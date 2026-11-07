import re
from pathlib import Path

import pytest

from parallax.catalog import load_catalog
from parallax.db import connect
from parallax.llm.schemas import (
    Assignment,
    Claim,
    EventAnalysis,
    Framing,
    Grouping,
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


class FakeLLM:
    """Stands in for the API. Everything is put in one event; each actor gets a stance."""

    def __init__(self):
        self.calls = []

    def structured(self, *, purpose, model, system, user, schema, max_tokens, effort):
        self.calls.append(purpose)
        if schema is StatementExtraction:
            return StatementExtraction(
                relevant="vacancy" not in user.lower(), domain="politics",
                summary="The source comments on the strait incident.",
                issue="Strait incident", topics=["shipping", "strait"], places=["Strait"],
                claims=[Claim(text="A ship was stopped.", quote="a ship was stopped",
                              type="fact")],
                key_terms=[KeyTerm(term="incident", refers_to="the stopping of a ship")],
            )
        if schema is Grouping:
            ids = [int(i) for i in re.findall(r"^\[(\d+)\]", user, flags=re.M)]
            return Grouping(
                assignments=[Assignment(statement_id=i, event="new:strait") for i in ids],
                new_events=[NewEvent(key="new:strait", title="Strait incident",
                                     summary="A ship was stopped in the strait.")],
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

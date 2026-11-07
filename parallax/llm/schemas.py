"""The exact shapes the LLM must return. The API enforces these schemas (structured outputs).

Note what is NOT here: no truth, accuracy, bias or credibility field. Ever.
"""

from typing import Literal

from pydantic import BaseModel, Field

Domain = Literal["politics", "economics", "both", "other"]
Stance = Literal["asserts", "denies", "qualifies"]


# --- Step 1: one statement ------------------------------------------------------------------

class Claim(BaseModel):
    text: str = Field(description="Neutral paraphrase of one claim, in plain words.")
    quote: str = Field(description="Verbatim excerpt (max ~30 words) supporting the claim.")
    type: Literal["fact", "position", "demand", "commitment", "accusation", "denial"]


class KeyTerm(BaseModel):
    term: str = Field(description="The exact word or phrase the source uses.")
    refers_to: str = Field(description="Neutral description of what the term refers to.")


class StatementExtraction(BaseModel):
    relevant: bool = Field(
        description="True if this states a position, decision, assessment or account of events. "
        "False for routine notices, job offers, event calendars, data tables without commentary, "
        "routine consular travel-advice updates and ceremonial greetings without political content."
    )
    domain: Domain
    summary: str = Field(description="One or two neutral sentences: who says what about what.")
    issue: str = Field(
        description="Short noun phrase naming the specific incident or issue, e.g. "
        "'Fed November 2026 rate decision' or 'Strike on X port, 3 Nov 2026'."
    )
    topics: list[str] = Field(description="2-5 short lowercase topic tags.")
    places: list[str]
    claims: list[Claim] = Field(description="Up to 6 central claims.")
    key_terms: list[KeyTerm] = Field(
        description="Up to 5 loaded or distinctive terms the source uses for actors or events."
    )


# --- Step 2: grouping statements into events ---------------------------------------------------

class Assignment(BaseModel):
    statement_id: int
    event: str = Field(
        description="Either the id of an existing event (e.g. 'E12'), "
        "or a new key 'new:<short-key>'. Statements that share a new key form one new event."
    )


class NewEvent(BaseModel):
    key: str = Field(description="The 'new:<short-key>' used in assignments.")
    title: str = Field(description="Neutral, factual event title, no loaded terms.")
    summary: str = Field(description="One neutral sentence on what the event is.")


class Grouping(BaseModel):
    assignments: list[Assignment]
    new_events: list[NewEvent]


# --- Step 3: analysing one event ---------------------------------------------------------------

class Proposition(BaseModel):
    id: str = Field(description="p1, p2, ...")
    text: str = Field(description="A neutral proposition that sources can assert, deny or qualify.")


class Position(BaseModel):
    actor: str = Field(description="Actor id exactly as given in the input (e.g. 'CN', 'un').")
    proposition_id: str
    stance: Stance
    quote: str = Field(description="Verbatim excerpt (max ~30 words) showing the stance.")
    statement_id: int


class TermUsage(BaseModel):
    actor: str
    term: str


class TermComparison(BaseModel):
    concept: str = Field(description="Neutral label for the thing being named.")
    usages: list[TermUsage]


class Framing(BaseModel):
    actor: str
    frame: str = Field(description="One neutral sentence: what this actor emphasises or omits.")


class EventAnalysis(BaseModel):
    title: str = Field(description="Neutral, factual event title.")
    summary: str = Field(
        description="2-3 neutral sentences describing what the statements are about, "
        "attributing every contested point to who says it."
    )
    propositions: list[Proposition] = Field(description="3-10 propositions, most contested first.")
    positions: list[Position] = Field(
        description="Only where a source clearly asserts, denies or qualifies. Omit otherwise."
    )
    terminology: list[TermComparison] = Field(
        description="Concepts that different actors name differently. Empty if none."
    )
    framing: list[Framing]

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


class IssuePart(BaseModel):
    issue: str = Field(
        description="Short noun phrase naming the specific development this passage is about, "
        "e.g. 'Fed November 2026 rate decision' or 'Strike on X port, 3 Nov 2026'."
    )
    opening: str = Field(
        description="The first 6-12 words of the passage on this issue, copied exactly from the "
        "text, so that the passage can be found again."
    )
    summary: str = Field(description="One or two neutral sentences: who says what about what.")
    topics: list[str] = Field(description="2-5 short lowercase topic tags.")
    places: list[str]
    claims: list[Claim] = Field(description="Up to 6 central claims on this issue.")
    key_terms: list[KeyTerm] = Field(
        description="Up to 5 loaded or distinctive terms the source uses for actors or events."
    )


class StatementExtraction(BaseModel):
    relevant: bool = Field(
        description="True if this states a position, decision, assessment or account of events. "
        "False for routine notices, job offers, event calendars, data tables without commentary, "
        "routine consular travel-advice updates and ceremonial greetings without political content."
    )
    domain: Domain
    summary: str = Field(description="One or two neutral sentences on the whole statement.")
    parts: list[IssuePart] = Field(
        description="One part per distinct issue, in the order they appear. Most statements "
        "address one issue and have exactly one part. Press briefings, question-and-answer "
        "sessions and speeches that cover several issues get one part per issue (at most 15). "
        "Leave out purely procedural or ceremonial passages. Empty if not relevant."
    )


# --- Step 2: grouping statements into events ---------------------------------------------------

class Assignment(BaseModel):
    part_id: int
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


class Merge(BaseModel):
    keep: int = Field(description="Id of the event to keep.")
    merge: list[int] = Field(description="Ids of duplicate events to fold into it.")


class Merges(BaseModel):
    merges: list[Merge]


# --- Step 3: analysing one event ---------------------------------------------------------------

class Proposition(BaseModel):
    id: str = Field(description="p1, p2, ...")
    text: str = Field(description="A neutral proposition that sources can assert, deny or qualify.")


class Position(BaseModel):
    actor: str = Field(description="Actor id exactly as given in the input: 'CN', 'un', or a "
                       "joint voice such as 'joint:CA+FR+GB'.")
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
    background: str = Field(
        description="2-4 plain sentences for a newcomer: what happened, who, when, where. "
        "Only from the given statements; undisputed facts stated plainly, everything else "
        "attributed to its source."
    )
    summary: str = Field(
        description="2-3 neutral sentences on how the official lines relate, "
        "attributing every point to who says it."
    )
    propositions: list[Proposition] = Field(
        description="3-10 propositions phrased so that different sides can take a stance on "
        "the same one; most contested first."
    )
    positions: list[Position] = Field(
        description="Only where a source clearly asserts, denies or qualifies. Omit otherwise."
    )
    terminology: list[TermComparison] = Field(
        description="Concepts that two or more actors name with different words. "
        "Empty if none."
    )
    framing: list[Framing]


# --- Step 4: filing propositions under issues --------------------------------------------------

class IssueChoice(BaseModel):
    proposition_id: str
    issue: str = Field(
        description="Either the id of an existing issue (e.g. 'I12'), or a new key "
        "'new:<short-key>'. Propositions that share a new key go under one new issue."
    )


class NewIssue(BaseModel):
    key: str = Field(description="The 'new:<short-key>' used in choices.")
    title: str = Field(
        description="Short neutral noun phrase naming the question at issue, in nobody's "
        "wording, e.g. 'Sanctions on Iran' or 'Euro area interest rate path'."
    )


class IssueMapping(BaseModel):
    choices: list[IssueChoice] = Field(description="Exactly one choice per proposition.")
    new_issues: list[NewIssue]

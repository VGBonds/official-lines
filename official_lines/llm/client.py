"""Thin wrapper around the Anthropic API: structured output, cost ledger, budget guard.

Every call is logged in the `llm_calls` table. Before each call we add up this month's spend;
past OFFICIAL_LINES_MONTHLY_BUDGET_USD we refuse to call the API (BudgetExceeded).
"""

import sqlite3
from datetime import UTC, datetime
from typing import Protocol, TypeVar

import anthropic
from pydantic import BaseModel

from official_lines.config import PRICES_PER_MTOK
from official_lines.db import now_iso, transaction

T = TypeVar("T", bound=BaseModel)


class BudgetExceeded(RuntimeError):
    pass


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    """What the pipeline needs from a language model. Tests use a fake implementation."""

    def structured(self, *, purpose: str, model: str, system: str, user: str,
                   schema: type[T], max_tokens: int, effort: str) -> T: ...

    def text(self, *, purpose: str, model: str, system: str, user: str,
             max_tokens: int, effort: str) -> str: ...


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES_PER_MTOK.get(model, (5.0, 25.0))  # unknown model: assume pricey
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def month_spend(conn: sqlite3.Connection) -> float:
    month = datetime.now(UTC).strftime("%Y-%m")
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM llm_calls WHERE substr(at, 1, 7) = ?", (month,)
    ).fetchone()
    return row[0]


class AnthropicLLM:
    def __init__(self, conn: sqlite3.Connection, monthly_budget_usd: float,
                 client: anthropic.Anthropic | None = None):
        self.conn = conn
        self.budget = monthly_budget_usd
        self.client = client or anthropic.Anthropic(max_retries=4)

    def structured(self, *, purpose, model, system, user, schema, max_tokens, effort):
        self._check_budget()
        response = self.client.messages.parse(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=schema,
            output_config={"effort": effort},
        )
        self._record(purpose, model, response.usage)
        self._check_stop(response)
        if response.parsed_output is None:
            raise LLMError(f"{purpose}: no parsed output")
        return response.parsed_output

    def text(self, *, purpose, model, system, user, max_tokens, effort):
        self._check_budget()
        with self.client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort},
        ) as stream:
            response = stream.get_final_message()
        self._record(purpose, model, response.usage)
        self._check_stop(response)
        return "".join(b.text for b in response.content if b.type == "text")

    def _check_budget(self) -> None:
        spent = month_spend(self.conn)
        if spent >= self.budget:
            raise BudgetExceeded(
                f"Monthly LLM budget reached: ${spent:.2f} of ${self.budget:.2f}. "
                "Raise OFFICIAL_LINES_MONTHLY_BUDGET_USD or wait for next month."
            )

    def _check_stop(self, response) -> None:
        if response.stop_reason == "refusal":
            raise LLMError("model declined the request")
        if response.stop_reason == "max_tokens":
            raise LLMError("output hit max_tokens; raise the limit for this step")

    def _record(self, purpose: str, model: str, usage) -> None:
        tokens_in = (usage.input_tokens or 0) + (usage.cache_read_input_tokens or 0) + (
            usage.cache_creation_input_tokens or 0)
        tokens_out = usage.output_tokens or 0
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO llm_calls (at, purpose, model, input_tokens, output_tokens, cost_usd)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (now_iso(), purpose, model, tokens_in, tokens_out,
                 cost_usd(model, tokens_in, tokens_out)),
            )

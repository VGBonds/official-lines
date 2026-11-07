# Architecture

Small and boring on purpose: one Python package, one SQLite file, a static website. No web framework, no queue, no containers.

## Pipeline

```
collect ──► extract ──► group ──► analyze ──► build
  │            │           │          │          │
  HTTP      Haiku 5.5   Haiku 5.5  Sonnet 5.5   Jinja → site/*.html
  no AI     per         per batch  per event    + metrics (plain Python)
            statement   of 25      (2+ actors)
```

`parallax run` executes all five in order. Each step only processes what is new, so running it twice is harmless. If the AI budget is reached, the AI steps are skipped and collection and the site keep going.

## Code map

```
parallax/
  cli.py              commands (argparse); start reading here
  config.py           settings from .env, model prices
  catalog.py          loads + validates sources/actors.yaml and sources/sources.yaml
  db.py               SQLite schema and helpers
  collect/
    http.py           polite HTTP client: honest User-Agent, robots.txt, per-host pause
    parsers.py        RSS/Atom, listing pages (CSS selectors), article text (trafilatura)
    run.py            one collection pass; a failing source never stops the others
  llm/
    client.py         Anthropic API wrapper: structured output, cost ledger, budget guard
    schemas.py        the exact JSON shapes the AI must return (pydantic)
    prompts.py        every prompt; part of the published method
  pipeline/
    extract.py        step 1: summary, issue, claims + quotes, key terms per statement
    events.py         step 2: assign statements to events (or create new ones)
    analyze.py        step 3: propositions × actors stance table, silence
    metrics.py        agreement, shared floor, contested, unusual alignment, shared wording
    brief.py          weekly newsletter draft
  site/
    build.py          generates site/ from the database
    templates/        Jinja HTML templates
    static/           style.css, map.js (D3 world map from a CDN)
sources/              actors.yaml, sources.yaml
deploy/               server setup script, systemd timers, Caddy config, push.sh
tests/                offline tests; tests/conftest.py has the stand-in AI (FakeLLM)
```

## Database (`data/parallax.db`)

| Table | One row per | Key columns |
|---|---|---|
| `sources` | source in the catalog | last_ok_at, last_error, last_found, last_new |
| `statements` | official statement | url (unique), title, published_at, text (private), extraction (JSON), relevant, event_id |
| `events` | event | slug, title, summary, featured, analysis (JSON: AI output + metrics) |
| `llm_calls` | AI call | purpose, model, tokens, cost_usd |

Look inside with `sqlite3 data/parallax.db`, e.g. `SELECT actor, COUNT(*) FROM statements GROUP BY actor;`.

## Design choices, and why

- **Static site.** Nothing to hack, nothing to crash, served for free by Caddy, survives traffic spikes. Filtering and search on the front page run in the browser.
- **AI grouping instead of embeddings.** At a few hundred statements a day, asking a cheap model to assign statements to open events costs about $1 a month and avoids heavy machine-learning libraries on a small server.
- **Structured outputs.** The API guarantees the JSON shape (`llm/schemas.py`), so a malformed answer can't corrupt the database.
- **Metrics outside the AI.** The AI only records who says what, with quotes. Agreement scores and flags are plain arithmetic in `metrics.py`, readable and testable.
- **Swappable model.** The pipeline only depends on the small `LLM` protocol in `llm/client.py`. Tests use a fake; another vendor could be added the same way.
- **Two models.** The cheap one reads everything, the stronger one only compares events where at least two actors spoke, capped per day.

## Tests

`uv run pytest` runs offline tests: catalog rules, parsers, metrics, and the whole pipeline with the stand-in AI, including the rule that organisations and central banks never colour the map.

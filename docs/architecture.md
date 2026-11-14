# Architecture

Small and boring on purpose: one Python package, one SQLite file, a static website. No web framework, no queue, no containers.

## Pipeline

```
collect ──► extract ──► group ──► analyze ──► file ──► build
  │            │           │          │          │         │
  HTTP      Haiku 5.5   Haiku 5.5  Sonnet 5.5  Haiku 5.5  Jinja → site/*.html
  no AI     per         per batch  per event   per        + metrics (plain Python)
            statement   of 25      (2+ actors) compared
                        parts                  event
```

`official-lines run` executes all of them in order (`analyze` ends with the filing step). Each step only processes what is new, so running it twice is harmless. If the AI budget is reached, the AI steps are skipped and collection and the site keep going.

## Code map

```
official_lines/
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
    extract.py        step 1: split each statement into parts (one per issue), with
                      summary, claims + quotes, key terms; find each part's passage
    events.py         step 2: assign parts to events (or create new ones), merge duplicates
    analyze.py        step 3: propositions × actors stance table, silence; joint texts
                      (one text published by several actors) become one voice
    issues.py         step 4: file each proposition of a compared event under an issue
                      (chosen from the stored list or newly named by Haiku); nothing else
    golden.py         the golden set: hand-judged comparisons re-run after prompt changes
    metrics.py        agreement, shared floor, contested, unusual alignment, shared wording,
                      per-issue counts
    wording.py        identical passages across actors (event pages + Shared wording page)
    brief.py          weekly newsletter draft
  site/
    build.py          generates site/ from the database, including search.json (every
                      proposition with its stances, every claim) for the Positions page,
                      and the issue pages (one row per proposition and event)
    templates/        Jinja HTML templates
    static/           style.css, map.js (D3 world map from a CDN), search.js (the Positions
                      page: matching runs in the browser over search.json)
sources/              actors.yaml, sources.yaml
deploy/               server setup script, systemd timers, Caddy config, push.sh
tests/                offline tests; tests/conftest.py has the stand-in AI (FakeLLM)
```

## Database (`data/official-lines.db`)

| Table | One row per | Key columns |
|---|---|---|
| `sources` | source in the catalog | last_ok_at, last_error, last_found, last_new |
| `statements` | official statement | url (unique), title, published_at, text (private), extraction (JSON: overall summary), relevant, page_missing_since |
| `parts` | issue within a statement | statement_id, idx, issue, summary, data (JSON: claims, key terms, topics), text_start/text_end (its passage), event_id |
| `events` | event | slug, title, summary, featured, analysis (JSON: AI output + metrics) |
| `issues` | issue (a question propositions from different events are filed under) | slug, title |
| `issue_propositions` | proposition of a compared event | event_id, proposition_id (`p1`…, into events.analysis), issue_id, propositions_hash (fingerprint of the propositions filed; a re-comparison that rewords them makes it stale) |
| `llm_calls` | AI call | purpose, model, tokens, cost_usd |

Look inside with `sqlite3 data/official-lines.db`, e.g. `SELECT actor, COUNT(*) FROM statements GROUP BY actor;`.

The schema has a version number (`PRAGMA user_version`). `db.py` upgrades an older database on the next run; version 1 to 2 keeps every collected statement but redoes extraction, events and analyses; version 2 to 3 only adds a column; version 3 to 4 only adds the two issues tables (nothing is redone; the next run files every compared event).

## Design choices, and why

- **Each run reads only what is new.** A source's feed or listing shows its latest items; anything whose URL we don't have yet is fetched (at most 15 per source per run, the rest next run). We never crawl archives, so a source that is down for longer than its list reaches back loses those items for us. If one statement page fails, we keep the feed's title and summary, mark it `page_missing_since`, and retry that page on each run for 2 days; when it arrives, the full text replaces the stub and the AI reads the statement again.
- **Parts, not whole statements.** A foreign ministry's daily press briefing answers ten or more questions on unrelated issues. Filed as one item it could only join one event, and that ministry would be missing from every other comparison. So extraction splits each statement into one part per issue, and events collect parts. Most statements have exactly one part.

- **Static site.** Nothing to hack, nothing to crash, served for free by Caddy, survives traffic spikes. Filtering and search on the front page run in the browser.
- **Search is a lookup, not an answer.** The Positions page fetches `search.json` (built with the site; under 1 MB raw, about a fifth of that compressed, loaded on the first keystroke) and matches in the browser: every query word must occur, short words exactly, longer words on a light stem; stance words are dropped and a stance filter offered instead. No server, no model call, no relevance ranking: contested propositions first, then newest. Anything a model would add (an answer to "who is against X", a digest across events) sits on top of this, never instead of it, so a reader can always check the evidence set the digest was made from.
- **AI grouping instead of embeddings.** At a few hundred statements a day, asking a cheap model to assign statements to open events costs about $1 a month and avoids heavy machine-learning libraries on a small server.
- **Structured outputs.** The API guarantees the JSON shape (`llm/schemas.py`), so a malformed answer can't corrupt the database.
- **Metrics outside the AI.** The AI only records who says what, with quotes. Agreement scores and flags are plain arithmetic in `metrics.py`, readable and testable.
- **One text is one voice.** Before the comparison, `analyze.joint_voices` compares the parts' passages per statement (`wording.same_text_groups`): statements that are mostly the same text form a joint voice (`joint:CA+FR+GB`), which the model sees once and must use as one actor id. Labels (shared floor, majority, contested) count voices; pair agreements are per actor, with each publisher inheriting the joint text's stances, and pairs of co-publishers flagged `joint` and left out of the polar pair, the unusual-alignment flags and the history baseline. Without this, a G7 declaration reposted by five governments read as five agreeing actors. The model is kept to the ids it was given (`analyze.resolve_voices`): an entry under an invented id is dropped, and a joint id the model formed itself from known actors (`joint:GB+FI`) becomes one entry per member.
- **An issue is a grouping, and the wording stays visible.** Propositions are phrased per event, so a question cannot be followed across events by text search. The filing step (`issues.py`) has the cheap model do one thing: choose an existing issue or name a new one per proposition. Stances, quotes and wording are never touched, and the issue page shows the original wording on every row, so that a filing that treats two questions as one can be seen. Each filing records a fingerprint of the propositions it was made for; a re-comparison that rewords them makes the filing stale, so the event is filed again on the next run and the stale rows are left out of the site until then. Guards in `apply_mapping`: a choice must name an offered issue or a declared new key, a new title that already exists (ignoring case) reuses the existing issue, the first choice per proposition wins. Past 300 issues the model is shown the ones used in the last 90 days plus those sharing a word with the propositions, which keeps the call cheap as the list grows.
- **The comparison is separable from the database.** `analyze.compare()` takes plain part records and returns the analysis with metrics; `analyze_event()` only loads and stores. That is what lets the golden set run a comparison on stored inputs.
- **Swappable model.** The pipeline only depends on the small `LLM` protocol in `llm/client.py`. Tests use a fake; another vendor could be added the same way.
- **Two models.** The cheap one reads everything, the stronger one only compares events where at least two actors spoke, capped per day. When another actor joins an event after its comparison, the event is compared again on the next run (its own daily allowance), and until then its page says which actors are not in the table yet.

## Tests

`uv run pytest` runs offline tests: catalog rules, parsers, metrics, and the whole pipeline with the stand-in AI, including the rule that organisations and central banks never colour the map.

`uv run official-lines golden` runs the **golden set** (`tests/golden/*.json`): events judged by hand, stored with their exact comparison input, compared again with the real model and checked against coarse expectations (which actors form a joint voice, how many propositions are contested, which pairs must come out opposed or aligned, no mirror-image propositions). It costs a few cents per case. Run it after every change to `prompts.py` or `metrics.py`; add a case with `golden --export SLUG` and fill in its `expect` block (keys documented in `official_lines/pipeline/golden.py`).

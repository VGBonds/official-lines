# Parallax

**Same event, every official angle.**

Parallax collects what governments and international organisations *officially* say (heads of government, foreign and finance ministries, central banks, the UN, IMF, World Bank, WHO, EU, NATO, BRICS, African Union, ASEAN and others), groups their statements by event, and shows side by side where the official lines agree, where they contradict each other, and who stays silent.

It does not judge truth. It shows the positions so that readers can judge for themselves. Unusual agreement and unusual disagreement are both flagged.

## How it works, in one picture

```
 official feeds and          collect         extract           group            compare           build
 press pages (≈15 countries ───────────► statements ───────► claims, terms ──► events ────────► stance table ──► static
 + ≈15 organisations)        every 3 h    (SQLite)  Haiku    per statement     Haiku            Sonnet + maths    website
                                                                                                                  + weekly brief
```

Everything is Python. One small server, one SQLite file, a static website. Target running cost: **about $25–50 a month**.

## Quick start (on your laptop)

```bash
uv sync                      # install (once)
cp .env.example .env         # then paste your Anthropic API key into .env
uv run parallax collect      # fetch statements (no AI, free)
uv run parallax run          # full pipeline: collect, AI steps, build the site
uv run parallax serve        # open http://localhost:8000
```

New to all of this? Start with **[docs/getting-started.md](docs/getting-started.md)**.

## Documentation

| Guide | What it covers |
|---|---|
| [Getting started](docs/getting-started.md) | Installing the tools, the API key and spending limits, first run on your laptop |
| [Deployment](docs/deployment.md) | Putting it on a Hetzner server step by step, with a domain and HTTPS |
| [Operations](docs/operations.md) | Daily and weekly routine: the editor workflow, the newsletter, costs, backups, troubleshooting |
| [Sources](docs/sources.md) | The source catalog: format, adding or fixing a source, coverage gaps |
| [Architecture](docs/architecture.md) | How the code is organised, the database, each pipeline step |
| [Methodology](docs/methodology.md) | What we measure and how. Also published on the site as the "Method" page |
| [Roadmap](docs/roadmap.md) | What comes next, and the business plan |

## Commands

| Command | What it does |
|---|---|
| `uv run parallax sources` | List all sources and whether their last fetch worked |
| `uv run parallax collect` | Fetch new statements (`--source ID` for just one) |
| `uv run parallax extract` | AI step 1: read new statements |
| `uv run parallax group` | AI step 2: group statements into events |
| `uv run parallax analyze` | AI step 3: compare actors on events (`--event SLUG` for one) |
| `uv run parallax build` | Generate the website into `site/` |
| `uv run parallax run` | All of the above, in order (this is what the server runs every 3 hours) |
| `uv run parallax brief` | Draft the weekly newsletter into `data/briefs/` |
| `uv run parallax feature SLUG` | Mark an event as an editor's pick (`unfeature` to undo) |
| `uv run parallax costs` | AI spend this month, by step |
| `uv run parallax serve` | Preview the site locally |

## Ground rules (do not "improve" these away)

1. No truth, bias or credibility score, anywhere. We measure agreement and distance, never honesty.
2. Official first-hand speech only. No news agencies, broadcasters or newspapers, state-owned or not.
3. The site shows titles, links, our own summaries and quotes of at most ~30 words. Never full texts.
4. Organisations never colour the map, not even their host country. Central banks are off the map in v1.
5. Coverage gaps are shown, not hidden.

## Tests

```bash
uv run pytest        # offline tests (a stand-in replaces the AI)
uv run ruff check .  # style check
```

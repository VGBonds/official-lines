# Operations: the routine

Once deployed, Official Lines runs by itself every 3 hours. Your job as editor takes about an hour a week.

## Daily, 5 minutes (optional)

- Look at the site's front page. Anything badly grouped or summarised? Note it (see "Fixing mistakes" below).
- Look at the **Coverage** page. Red rows mean a source failed on its last run. One failure is normal (sites go down); a source failing for several days needs fixing ([sources.md](sources.md)).

## Weekly: the newsletter, about an hour

1. **Pick events.** Browse the week's compared events on the site. Mark the ones you want in the letter as editor's picks:
   ```bash
   uv run official-lines feature strait-incident-42
   ```
   (The slug is the last part of the event page's address.) Picks are shown first on the site and always included in the brief.
2. **Draft.**
   ```bash
   uv run official-lines brief            # covers the last 7 days
   ```
   This writes `data/briefs/brief-YYYY-MM-DD.md` and costs about $0.10–0.30.
3. **Edit.** Open the file and check every quote against the event page, cut what's weak, add your own framing paragraph if you like. Keep to the house rules: attribute every claim, no verdicts.
4. **Publish on the site:** `uv run official-lines build`. The brief appears under "Briefs".
5. **Publish on Substack:** open the brief's page on your site (Briefs), select the text, copy, and paste it into a new Substack post: headings, links and quotes keep their formatting. Add a title, preview, send.

If you run the brief on the server, fetch the draft to your laptop with:

```bash
scp official-lines@SERVER_IP:official-lines/data/briefs/brief-*.md .
```

Or simply run `official-lines brief` on your laptop after copying the database down (`scp official-lines@SERVER_IP:official-lines/data/official-lines.db data/`).

## Costs

```bash
uv run official-lines costs
```

shows this month's AI spend per step. Typical month:

| Step | Model | Volume | Cost |
|---|---|---|---|
| extract | Haiku 5.5 | ~300–600 statements/day | ~$5–10 |
| group | Haiku 5.5 | ~20–30 calls/day | ~$1 |
| analyze | Sonnet 5.5 | ≤ 12 events/day | ~$10–20 |
| brief | Sonnet 5.5 | 4/month | ~$1 |

Levers in `.env` if it gets too expensive:

- `OFFICIAL_LINES_MAX_ANALYSES_PER_DAY` (default 12): the biggest lever. It applies twice: up to 12 new comparisons a day, and up to 12 updates of events that another actor joined after their comparison (`update` in `official-lines costs`). Worst case about $0.70 a day.
- `OFFICIAL_LINES_MAX_EXTRACT_PER_RUN` (default 300).
- `OFFICIAL_LINES_ANALYZE_MODEL=claude-haiku-5-5`: much cheaper, noticeably weaker comparisons.
- `OFFICIAL_LINES_MONTHLY_BUDGET_USD`: the hard stop. Once reached, collection and the site keep working; only the AI steps pause until the 1st of next month.

The ledger counts cached input at full price, so the real bill is at or below what `costs` shows. The Anthropic Console's Usage page shows the exact bill.

## Fixing mistakes

The AI will sometimes group badly or misstate a stance. In v1 the fixes are manual:

- **Re-run a comparison** after more statements arrived: `uv run official-lines analyze --event SLUG`.
- **Two events that should be one, or a statement in the wrong event:** for now, fix it in the database with `sqlite3 data/official-lines.db` (e.g. `UPDATE parts SET event_id=12 WHERE statement_id=345;`; a press briefing has several parts, see `SELECT id, idx, issue FROM parts WHERE statement_id=345;`), then re-analyse. A small editor command for this is on the [roadmap](roadmap.md).
- **A systematic mistake** (the same kind of error again and again): the prompts in `official_lines/llm/prompts.py` are the place to fix it. Prompts are published methodology, so note changes in the Method page.

## Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| `AuthenticationError` | API key missing or wrong in `.env` | Check `ANTHROPIC_API_KEY`; make a new key if needed |
| "Monthly LLM budget reached" in the log | Budget guard hit | Expected. Raise `OFFICIAL_LINES_MONTHLY_BUDGET_USD` or wait |
| `credit balance is too low` | Prepaid credits used up | Buy credits in the Console |
| A source shows `HTTPStatusError: 403` | The site blocks automated reading | See [sources.md](sources.md); look for another official route |
| A source shows `Blocked: robots.txt` | The site asks bots not to read that page | Respect it; find another page or mark the source disabled |
| Site shows no events | Not enough data yet, or the AI steps did not run | `uv run official-lines costs` and the log; events need 2+ actors to be compared |
| Map is empty | Map data comes from a CDN; offline or blocked | Check the browser console |

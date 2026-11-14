# Improvement ideas

A trace of ideas and the discussion around them, so that decisions can be traced back later. The [roadmap](roadmap.md) holds what we have committed to; this page holds what we are considering. When an idea is picked up, move it to the roadmap and note the date here.

## First: observe, then evaluate (agreed 2026-11-08)

The site went live on 2026-11-08. Before building more, it runs for a few days unattended. Then we evaluate:

- **Budget:** cost per day and per step (`official-lines costs`). Do the caps (300 extractions per run, 12 comparisons per day) bite too early or too late?
- **Sources:** which fail repeatedly (`official-lines sources`), which deliver only titles, and whether the page retries recover text (`statements.page_missing_since`).
- **Coverage:** statements per actor, and the share of events where 2+ actors spoke, our core measure of whether there is anything to compare.
- **Quality:** a spot check of 5-10 comparisons and backgrounds. Is the grouping right, are the stances defensible, does the neutral language hold?

Only then do we decide which of the ideas below come first.

## Evaluation of 2026-11-13: the comparison rarely fires

Counted on the live site over 45 days: 1210 events, 39 with two or more actors, 2 with a contested proposition. Three causes, two of them fixed the same day:

1. **Joint texts counted as several agreeing actors.** The G7 declaration reposted by five publishers read as five actors asserting eight propositions, all "uncontested majority". Fixed: a text that several actors publish is one voice in the table (Method, "One text is one voice").
2. **Denials under-recorded.** On the Joshua Wong event China asserted that the sentence was a lawful application of the law and ten governments called the prosecutions unjust, yet no denial was recorded: one contested row of eight. Fixed in the prompt: a stance is checked for every actor and every proposition, incompatibility counts as denial, mirror-image propositions are merged. A golden set (`official-lines golden`) now guards both fixes.
3. **The counter-voices are missing.** In multi-actor events the UK, EU, France and China dominate; the US appears twice, Iran, India and Israel never. Open: see "More coverage" below, with priority for missing sides over volume. The UN's own meeting records (press.un.org) quote every delegation on one event and are the richest single "same event, many actors" source; whether a UN summary of a delegate counts as official first-hand speech is an editor's decision still to take.

Re-running the 39 compared events on the server with the fixes (2026-11-14) gave 7 events with a joint voice and 3 with a contested proposition (the Hong Kong sentencing went from 1 contested row to 5). The small rise is the honest result: most multi-actor events are still one side talking, and no fix invents a counter-voice that never published.

Also noted, not yet done: the front page lists every single-actor event (1.3 MB of HTML, growing); no RSS output, sitemap or analytics; the shared-wording page is dominated by boilerplate (letterhead phrases shared by Saudi Arabia and the OIC in 117 statement pairs); per-event propositions cannot be compared across events, which a fixed proposition bank per theme would allow (see "Group events into themes").

## Questions over the data (raised 2026-11-14)

The user's product idea: ask "who is against the sanctions on Iran" or "who is calling for more CO2 reductions", get the set of events that bear on it (deterministic, free), and behind a paywall an AI digest of that evidence set with references to the events.

- **Done 2026-11-14: the Positions page.** A deterministic lookup over every proposition (with stances and quotes) and every claim, in the browser, no model call (Method, "Finding who takes which stance"). It is the free, verifiable, indexable layer, and it shows what people actually ask for before anything is built on top.
- **The limit is coverage, not the model.** A question like the Iran one needs Tehran, Moscow and Beijing in the same table as Washington. Iran's foreign ministry, Russia's finance ministry and Saudi Arabia are still off; the voices we do read rarely land on the same event. Sources before paid features.
- **Done 2026-11-14: the issue layer.** Propositions are phrased per event, so the search finds words, not issues. Now a Haiku call right after each comparison files every proposition under an issue ("Sanctions on Iran", "Euro area interest rate path"), chosen from the stored list or newly named; `pipeline/issues.py`, Method "Issues". Each issue has a page with a running table, one row per proposition and event, voices as columns, and an index by number of events and contested rows. The risk stands: merging two different propositions into one issue manufactures agreement, so the original wording is on every row, the event page links each proposition to its issue, and no score is computed across events. **Cost:** one Haiku 5.5 call per comparison, about 1,500–7,000 input tokens (the issue list grows with the site; past 300 issues only recent and word-matching ones are shown) and under 300 output tokens: at 12 comparisons a day about $0.005–0.01 a day, so $0.15–0.30 a month at current volume (the ledger's `issues` line shows the real figure). The one-off backfill of the ~40 compared events on the server costs about $0.02. Open: an issue filter on the event index, issues in search.json, and whether the model splits too finely (one issue per event) or too coarsely; check the Issues index after a week.
- **Paid layer, when there is traffic.** An AI digest over an evidence set (a Sonnet call over ten events' tables costs roughly $0.10–0.15; every sentence anchored to an event, actor and quote, reusing the brief's material builder) is a reasonable paid feature but not the moat: a digest is easy to copy into any chatbot. What an analyst or journalist cannot rebuild is saved questions with alerts when a new actor takes a stance, CSV export of the tables, and an API. Put the paywall on those and on volume; keep one free digest a day as the demonstration.

## Directions (raised 2026-11-08)

Suggested order after the evaluation: **coverage → ranking → themes**, then economics and timelines. That goes from cheapest to most valuable without building on sand.

### 1. Highlight the controversial or consequential issues

Push the most contested and widely debated events up, or mark them.

- **Cheap:** we already compute what is needed: how many actors spoke, how many propositions are contested, the furthest-apart pair, unusual alignments and shared wording.
- **Caution:** "consequential" is a judgement. Make the ranking a **published formula** on the Method page (e.g. actors + 2 × contested points + notable patterns + heads of government speaking), so we never quietly decide what matters.

### 2. More coverage

Candidates: Turkey, Pakistan, Vietnam, Canada, Japan, Argentina, Kazakhstan, Egypt, Norway, Switzerland. (India's government sites currently block us.)

- **Likely easier**, with good English sites: Pakistan (the foreign ministry's weekly briefing is ideal for the per-issue split), Canada, Norway, Vietnam (foreign ministry briefings), Turkey (foreign ministry), Egypt, Kazakhstan. Japan is on the panel but thin.
- **Harder:** Switzerland publishes mostly in German and French, Argentina mostly in Spanish. Both clash with English-only.
- **New risk:** sites that refuse data-centre IP addresses (see [Sources](sources.md)). Probe every new source **from the server**, not only from a laptop.
- Aim for balance, not volume: a first source for an uncovered actor beats a fifth for a well-covered one.

### 3. Group events into themes

- Use a **fixed, published list of themes** (e.g. trade, security, human rights, climate, health, monetary policy) instead of letting the AI invent new ones each week. Stable themes make "everything on X over time" possible and keep the grouping inspectable.
- Each part already carries topic tags. A theme per event can come from the comparison step at almost no extra cost.

### 4. Statements beyond institutional press releases ("the MP said…", "at the conference the president said…")

- **Yes, through official records:** parliamentary records (UK Hansard, Bundestag minutes, other parliaments' transcripts), UN meeting records, and conference transcripts published by the organiser are official and in scope.
- **No, through media:** "Reuters reports the minister said…" is media coverage and outside our rule of official sources only.
- **Label separately:** an MP, especially from the opposition, is not the government's line. Parliament would need its own kind (e.g. `parliament`), shown apart from government positions and never coloured onto the map as the country's position.

### 5. Timelines and chains of events

- Link each event to the earlier events it follows up (e.g. sanctions → response → counter-measures), and show a timeline per theme or country.
- Best built after themes (3), which narrow down which events can be related.

### 6. Economics

- Official economic data (money supply, policy rates, inflation, growth, reserves) from **official data APIs**: central banks (Fed/FRED, ECB Data Portal), IMF, World Bank, national statistics offices. These are plain numbers: no AI, no AI cost.
- Combined with central bank statements, this is the "central bank view" on the roadmap, and the most promising piece for finance and risk readers, who are the most likely paying audience.

### 7. Country profile

Select a country and see all its events, its economic data, and how its positions correspond to others'. Agreed that this is still vaguely defined. It grows out of 3, 5 and 6, and the actor pages are where it would live. Define it once those exist.

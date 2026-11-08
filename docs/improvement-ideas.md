# Improvement ideas

A trace of ideas and the discussion around them, so that decisions can be traced back later. The [roadmap](roadmap.md) holds what we have committed to; this page holds what we are considering. When an idea is picked up, move it to the roadmap and note the date here.

## First: observe, then evaluate (agreed 2026-11-08)

The site went live on 2026-11-08. Before building more, it runs for a few days unattended. Then we evaluate:

- **Budget:** cost per day and per step (`official-lines costs`). Do the caps (300 extractions per run, 12 comparisons per day) bite too early or too late?
- **Sources:** which fail repeatedly (`official-lines sources`), which deliver only titles, and whether the page retries recover text (`statements.page_missing_since`).
- **Coverage:** statements per actor, and the share of events where 2+ actors spoke, our core measure of whether there is anything to compare.
- **Quality:** a spot check of 5-10 comparisons and backgrounds. Is the grouping right, are the stances defensible, does the neutral language hold?

Only then do we decide which of the ideas below come first.

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

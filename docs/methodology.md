# Method

Official Lines puts official statements about the same event side by side, so that you can see where governments and international organisations agree, where they part, and who stays silent. **We do not judge whether anything is true.** That is your call.

## What we read

Only **official, first-hand speech**:

- heads of state or government, foreign ministries, finance ministries, government press offices;
- central banks (collected, shown on events, but never coloured onto the map);
- international and regional organisations (UN, IMF, World Bank, WHO, BIS, EU, ECB, NATO, BRICS, SCO, African Union, ASEAN, Arab League, GCC, OIC).

We do **not** read news agencies (state-owned or not), broadcasters, newspapers, think tanks or social media. An organisation never colours the country hosting its headquarters.

One judgement call: a portal run by a government's own office that publishes that government's announcements counts as a government press office, even when it calls itself a newspaper. Today this applies to the Viet Nam Government Portal (run by the Government Office). The Coverage page names every source we read.

We read **English** versions only. Some governments say less, or say it differently, in English than in their own language. The [Coverage](coverage.html) page lists every source we read and every one we could not read (blocked, no English version, no machine-readable page). An actor that looks silent may simply be one we cannot read: check Coverage before drawing conclusions.

## How a statement becomes a comparison

1. **Collect.** Several times a day we read each source's feed or press page and store new statements. We keep the full text privately for analysis. The site shows only the title, the date, a link to the original, our own short summary and quotes of at most about 30 words.
2. **Extract.** An AI model (currently Claude Haiku) reads each statement once. A statement that covers several issues, such as a daily press briefing, is split into one part per issue; most statements have one. For each part it records a neutral summary, the specific issue, the central claims with verbatim quotes, and the distinctive terms used. Routine notices (vacancies, calendars) are marked as not relevant.
3. **Group into events.** The model assigns parts to **events**: one specific development such as an incident, decision or meeting, not a broad theme. An ongoing negotiation that actors comment on over a couple of weeks counts as one event. A second pass merges events that turn out to be the same development.
4. **Compare.** When at least two actors have spoken on an event, a stronger model (currently Claude Sonnet) lists the propositions that matter, phrased neutrally, and records for each actor whether its statements **assert** (●), **qualify** (◐) or **deny** (○) each one, always with a verbatim quote. Saying nothing is not a stance. Propositions are phrased so that both sides can take a stance on the same one; a source that clearly rejects a claim without repeating it (for example, calling criticism of a verdict "interference") is recorded as denying it, with the quote that shows this.
   Statements keep arriving after an event was compared. When a new actor joins, the event is compared again on the next run (within about 3 hours). Until then the event page names the actors whose statements are listed but not yet in the table, so a missing column never looks like an actor we left out.
   The same step lists **terminology**: concepts that two or more actors name with different words (for example "the war" and "the special military operation"). One actor varying its own wording is style, not a difference between official lines, and is left out.
   The same step writes a short **background** for readers new to the event. It may use only what the statements themselves say, never the model's own knowledge: facts that no source disputes are stated plainly, everything else is attributed ("according to ..."), and evaluative words and unattributed motives or causes are not allowed. Where actors use rival names for the same thing, the background describes it neutrally instead. A background built only from official statements is still only as complete as those statements: what no one mentions is missing.
5. **Measure.** Plain arithmetic, no AI, turns that table into the numbers below.

## Agreement labels

Each proposition in the stance table can carry one label. "The actors in the table" are the actors that took at least one stance in the comparison: the columns of the table on the event page.

| Label | Definition | Example with France, Germany, the UK, the US and China in the table |
|---|---|---|
| **Shared floor** | **Every** actor in the table asserts it. No silence, no qualification, no denial. | All five assert it. |
| **Uncontested majority** | **More than half** of the actors in the table assert it, **none** denies it, and the others are silent or qualify. | Four assert it, China says nothing about it. |
| **Contested** | At least one actor asserts it and at least one other denies it. | Four assert it, China denies it. |
| *(no label)* | Anything else, e.g. a claim made by one or two actors that nobody else addresses. | |

**Silence is not agreement.** An actor that says nothing on a proposition is shown as a blank cell and never counted as assenting. That is why a shared floor requires every actor to say it explicitly, and why it is rare when many actors speak. When it does occur, it is notable.

None of these labels says anything about truth. A shared floor is what the official lines do not fight about; it can still be wrong.

## The numbers

| Measure | Definition |
|---|---|
| Stance value | asserts = 1, qualifies = 0.5, denies = 0 |
| Agreement of two actors | Over the propositions both took a stance on: the average of 1 − \|difference in stance value\|. 1 = same line, 0 = opposite lines. |
| Furthest apart | The pair with the lowest agreement (below 0.5, over at least 2 shared propositions). |
| Unusual agreement / disagreement | A pair whose agreement on this event differs by 0.5 or more from its average over at least 3 earlier events. "Unusual" is relative to what we have recorded so far, nothing more. |
| Shared wording | Passages of 8 or more identical words in a row (ignoring case and punctuation) that two or more different actors publish: a joint statement, a quote of another actor, or common talking points. One actor repeating itself does not count. The event page shows one line per group of actors, with the passage length in words; the [Shared wording](wording.html) page lists every passage across events and who shares wording with whom. |
| Silence | Actors that made at least 2 statements on the same topics in the last 60 days, but none on this event. |

## Rules we give the AI

- Describe what sources say. Never judge truth, intent or legitimacy.
- Use neutral wording; attribute loaded terms ("X calls it …") instead of adopting them.
- Quotes must be verbatim. If something is unclear, leave it out.
- Treat every actor the same way, whatever its political system or alignment.

The exact prompts are public, in the project's source code (`official_lines/llm/prompts.py`).

## Known limits

- **AI errors.** Summaries and stance tables are machine-made and can be wrong. Every stance carries a quote and every statement links to its original: check them.
- **Uneven coverage.** We read some actors through four channels and others through one or none. See Coverage.
- **English only.** English versions are written for foreign audiences.
- **Model leanings.** Any AI model carries leanings from its training. We work against this with the rules above, verbatim quotes, and by publishing our prompts.
- **Event boundaries.** Deciding that two statements are about "the same event" is itself a judgement. We keep events narrow, except for ongoing negotiations, which we keep together so that the sides can be compared.
- **Briefing splits.** Splitting a press briefing into issues is done by the AI. When a passage is attributed to the wrong issue, an actor can appear in the wrong event; the link to the original lets you check.

# Method

Official Lines puts official statements about the same event side by side, so that you can see where governments and international organisations agree, where they part, and who stays silent. **We do not judge whether anything is true.** That is your call.

## What we read

Only **official, first-hand speech**:

- heads of state or government, foreign ministries, finance ministries, government press offices;
- central banks (collected, shown on events, but never coloured onto the map);
- international and regional organisations (UN, IMF, World Bank, WHO, BIS, EU, ECB, NATO, BRICS, SCO, African Union, ASEAN, Arab League, GCC, OIC).

We do **not** read news agencies (state-owned or not), broadcasters, newspapers, think tanks or social media. An organisation never colours the country hosting its headquarters.

One judgement call: a portal run by a government's own office that publishes that government's announcements counts as a government press office, even when it calls itself a newspaper. Today this applies to the Viet Nam Government Portal (run by the Government Office). The Coverage page names every source we read.

Security Council meetings are read from the United Nations' own verbatim records (document symbols S/PV.NNNN), the UN's transcript of each delegation's words: one statement per delegation we follow, shown as "at the Security Council, verbatim record" and never coloured onto the map as the government's line. Not kept: the President's turns, briefers without a country, and delegations outside our panel. The records appear five to ten days after a meeting. (At the time of writing this source waits for an address the UN allows bots to use; see Coverage.)

We read **English** versions only. Some governments say less, or say it differently, in English than in their own language. The [Coverage](coverage.html) page lists every source we read and every one we could not read (blocked, no English version, no machine-readable page). An actor that looks silent may simply be one we cannot read: check Coverage before drawing conclusions.

## How a statement becomes a comparison

1. **Collect.** Several times a day we read each source's feed or press page and store new statements. We keep the full text privately for analysis. The site shows only the title, the date, a link to the original, our own short summary and quotes of at most about 30 words.
2. **Extract.** An AI model (currently Claude Haiku) reads each statement once. A statement that covers several issues, such as a daily press briefing, is split into one part per issue; most statements have one. For each part it records a neutral summary, the specific issue, the central claims with verbatim quotes, and the distinctive terms used. Routine notices (vacancies, calendars) are marked as not relevant.
3. **Group into events.** The model assigns parts to **events**: one specific development such as an incident, decision or meeting, not a broad theme. An ongoing negotiation that actors comment on over a couple of weeks counts as one event. A second pass merges events that turn out to be the same development.
4. **Compare.** When at least two actors have spoken on an event, a stronger model (currently Claude Sonnet) lists the propositions that matter, phrased neutrally, and records for each actor whether its statements **assert** (●), **qualify** (◐) or **deny** (○) each one, always with a verbatim quote. Saying nothing is not a stance. Propositions are phrased so that both sides can take a stance on the same one; a source that clearly rejects a claim without repeating it (for example, calling criticism of a verdict "interference") is recorded as denying it, with the quote that shows this.
   **One text is one voice.** A text that several actors publish, such as a joint statement or a verbatim republication, goes into the comparison once, as a single column headed with its publishers ("France, Germany and United Kingdom (joint text)"). Four governments reposting one declaration are not four actors agreeing; they are one text with four signatures. A publisher that also speaks on its own gets a column of its own, which shows its own stances and, where it says nothing itself, those of the text it signed. Joint texts are found by plain text comparison: a statement of at least 60 words of which at least 60% also appears in another actor's statement (the rest is typically an intro line, spelling differences and page furniture).
   **Denial without repetition.** A source denies a proposition whenever its text is incompatible with it, even if it never repeats it: calling prosecutions "unjust" denies that the conviction was a lawful application of the law. Propositions are never written as mirror images of each other ("the verdict was lawful" and "the verdict was unjust"); the two sides take opposite stances on one proposition. A cell stays empty only when the actor's text does not bear on the proposition.
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
| Agreement of two actors | Over the propositions both took a stance on: the average of 1 − \|difference in stance value\|. 1 = same line, 0 = opposite lines. A publisher of a joint text takes that text's stances. Two publishers of the same text are not measured against each other: co-signing is recorded as shared wording, and such a pair is left out of "furthest apart", of the unusual-alignment flags and of the baseline. |
| Furthest apart | The pair with the lowest agreement (below 0.5, over at least 2 shared propositions). |
| Unusual agreement / disagreement | A pair whose agreement on this event differs by 0.5 or more from its average over at least 3 earlier events. "Unusual" is relative to what we have recorded so far, nothing more. |
| Joint text | A statement of at least 60 words of which at least 60% (in runs of 8 words) also appears in another actor's statement. Its publishers form one voice in the stance table. |
| Shared wording | Passages of 8 or more identical words in a row (ignoring case and punctuation) that two or more different actors publish: a joint statement, a quote of another actor, or common talking points. One actor repeating itself does not count. The event page shows one line per group of actors, with the passage length in words; the [Shared wording](wording.html) page lists every passage across events and who shares wording with whom. |
| Silence | Actors that made at least 2 statements on the same topics in the last 60 days, but none on this event. |

## Finding who takes which stance

The [Positions](search.html) page looks up a subject across every event: "sanctions iran", "emission reduction", "ceasefire". It is a lookup, not an answer. It does not interpret the question; it finds the propositions (from compared events) and the claims (from every statement) that contain the words, and lists who asserts, qualifies or denies each proposition, with the quote behind the stance. Every word must occur; words of three letters or fewer must match exactly, longer words match on their stem. Stance words such as "for" and "against" are ignored, because a stance depends on how the proposition is worded: "denies that the sanctions are justified" and "asserts that the sanctions should be lifted" are both ways of being against them. Filter by stance instead, and read the proposition before the stances. Propositions are phrased per event, so the same question can be worded differently in two events; the search finds words, not issues. Nothing is ranked by relevance: contested propositions first, then the newest, then claims.

## Issues

Propositions are phrased per event. To follow one question across events, the [Issues](issues.html) page files every proposition of a compared event under an **issue**: a short neutral name for the question at issue, such as "Sanctions on Iran" or "Euro area interest rate path". The filing is done by an AI model (currently Claude Haiku) right after the comparison. It sees the event's propositions and the list of existing issues, and for each proposition either picks an existing issue or names a new one. That is all it does: it never touches a stance or a quote, and it never rephrases a proposition.

An issue page is a running table: one row per proposition and event, in the event's own wording, with the date, a link to the event and each voice's stance with its quote. Below it, how often each voice asserts, qualifies or denies a proposition under this issue. These are counts, not a position: the propositions under one issue are worded differently, and denying "the sanctions are justified" and asserting "the sanctions should be lifted" are the same side of the question.

The honest caveat: **an issue is a model's grouping of differently worded propositions.** Two propositions that ask different things can end up under one issue, and one question can be filed under two issues with different names. That is why the original wording stays on every row and every proposition on an event page links to its issue: read the proposition, then the stances. No agreement or distance is computed across events, and the issue list is not curated; it grows as events are compared.

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
- **Joint texts.** A joint text is detected by text overlap. A statement that quotes most of another actor's text is treated as publishing it; a joint statement that one signatory paraphrases rather than reposts is not detected and that signatory is a column of its own.
- **Issue filing.** Which issue a proposition is filed under is the model's choice, made from the proposition's wording and the issue titles. See "Issues" above: the wording is on every row so that the filing can be checked.
- **Council records.** A record is split at its speaker lines by a fixed rule, not by the AI. A delegation that speaks through the President's chair, or a briefer the line does not place in a country, is left out.
- **Briefing splits.** Splitting a press briefing into issues is done by the AI. When a passage is attributed to the wrong issue, an actor can appear in the wrong event; the link to the original lets you check.

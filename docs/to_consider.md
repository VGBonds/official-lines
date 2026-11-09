# Things to consider:

## 1. Notable patterns ✅ resolved (bf89b44)
> Event pages show one line per group of actors with the passage length in words; new "Shared wording" page lists pairs and passages with links. Open: minimum passage length (8 words lets names and set phrases in), to be decided after a week on the server.

The section is alluring and worth expanding, I think. 

example:

Shared wording: France and United Kingdom use 121 identical 8-word sequences, e.g. “to target individuals for political expression and participation”.

Shared wording: Germany and United Kingdom use 114 identical 8-word sequences, e.g. “to target individuals for political expression and participation”.

Shared wording: Germany and France use 107 identical 8-word sequences, e.g. “to target individuals for political expression and participation”.

same examples of word sequences.
Can we have a link to explore these: patterns/wording + counts? 

## Sources ◐ partly resolved
> `official-lines check` added; server check 2026-11-09. Enabled: Canada (PM, foreign, finance, central bank), Australia (PM, treasurer, central bank), Indonesia (cabinet secretariat), Argentina (foreign ministry, few items), Vietnam government portal (editor decision: official channel), Bank Negara Malaysia. Refuse our server: Philippines, Chile, Pakistan foreign ministry and PM, Malaysia foreign ministry and PM, Australia foreign minister. Not readable: Pakistan finance (PDFs), Indonesia foreign ministry and central bank (JavaScript), Vietnam foreign ministry (Vietnamese only). Open: government.ru; Bank Negara Malaysia's URL contains the year (update in January).

http://government.ru/en/docs/

Add 
- Turkey: regional power + military 
- Pakistan : nuclear power 
- South East Asia (India is blocked) is underrepresented: add Vietnam/Indonesia/Malaysia/the Philippines
- Canada: G7, large economy, rich in natural resources
- Australia: Oceania is underrepresented
- Argentina/Chile: add at least one more LatAm country

## use cases ◐ partly resolved (bf89b44)
> Done: filter by country/organisation, compared, contested; sort by newest, most contested, most actors. Open: filter by topic (needs the fixed theme list) and a real controversiality ranking (needs the published formula).


comparison is the best use-case but how we land there:
1. select by topic and/or country -> see all events
2. then filter by comparisons and/or controversiality
3. order by date as well
4. dive deeper into an event

## same thing different words section ✅ resolved (bf89b44)
> A concept now needs at least two actors using different words; applied at site build and in the prompt.


https://official-lines.com/event/security-council-meeting-on-ukraine-following-29-october-att-591.html

Same thing, different words
Russia's military campaign in Ukraine	United Kingdom: “Russia's aggression”United Kingdom: “this war”

the comparison must be with respect to 2 or more different sources. In that case we do not
have real usage of different suggestive wording, but rather a trivial stylistic 
wording to avoid repetitions. 
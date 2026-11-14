# Sources

Two files decide what Official Lines reads:

- `sources/actors.yaml`: **who** we follow: 15 countries and about 15 organisations. Adding a country means adding a line here (with its ISO numeric code, used by the map).
- `sources/sources.yaml`: **where** we read them: one entry per feed or press page.

Run `uv run official-lines sources` to check the catalog and see each source's last result. The catalog is validated on every command; mistakes are reported with the source id.

## The format

```yaml
sources:
  - id: cn-mfa                # unique: <actor>-<short name>
    actor: CN                 # an id from actors.yaml
    kind: mfa                 # head_of_government | mfa | finance | central_bank | gov_press | org
    name: Ministry of Foreign Affairs of the People's Republic of China
    homepage: https://www.fmprc.gov.cn/eng/
    method: html              # rss (RSS/Atom feed) or html (a press listing page)
    url: https://www.fmprc.gov.cn/eng/xw/fyrbt/
    link_selector: "ul.list1 a"          # html only: which links on the page are statements
    link_pattern: "/eng/xw/.*\\.html$"   # optional: the link address must match this
    enabled: true             # false: listed on the Coverage page, but not read
    status: ok                # ok | candidate | blocked | js_only | pdf_only | no_english | not_found
    notes: "what we tried and when"
```

Rules the validator enforces:

- No news agencies, broadcasters or commercial media (Xinhua, TASS, RT, IRNA, Anadolu, CGTN, Reuters, BBC, ...).
- Organisations use `kind: org` (or `central_bank` for the ECB and BIS).
- `html` sources need a `link_selector`.

## Adding a source

**A feed (easiest).** Many official sites have RSS or Atom feeds: look for an RSS icon, or for `/feed`, `/rss`, `.atom` or `.xml` addresses. Check that it works:

```bash
curl -s -A "OfficialLinesBot" "https://example.gov/feed/" | head -20
```

If you see `<rss` or `<feed` and items with `<title>` and `<link>`, add it with `method: rss`.

**A press page.** If there is no feed, use the page listing press releases:

1. Open the page in your browser. Right-click a statement's link and choose **Inspect**.
2. Find a CSS selector that matches all statement links and nothing else, e.g. `div.news-list a` or `ul.list1 li a`. In the browser console, test it with `document.querySelectorAll("div.news-list a").length`.
3. If the selector also catches menu links, add a `link_pattern` that only real statement addresses match (e.g. `/press-releases/`).
4. Test it:
   ```bash
   uv run official-lines collect --source your-source-id -v
   uv run official-lines sources
   ```

Some sites build their pages with JavaScript, so the links aren't in the raw HTML. Official Lines can't read those; mark them `enabled: false, status: js_only`. Same for sites that block bots (`status: blocked`). **We do not get around blocks or CAPTCHAs.** Look for another official route instead: an embassy site, a different section of the same site, or a government press office.

**Permanent missions to the UN.** Several governments whose home sites refuse data-centre addresses or publish no English publish Council and Assembly statements through their New York mission (`*-unmission` in the catalog, kind `mfa`: a mission is a body of the foreign ministry). The UN Protocol list of missions gives the official sites. A site that answers a redirect with a cookie and then the page is fine: our client keeps cookies. A CDN page that answers 200 with a script "challenge" and no links is a block, and we leave it.

## Checking candidates

A new source starts as `enabled: false, status: candidate`. The `check` command tests it the way a real collection pass would (robots.txt, the same client, the same parsers) but stores nothing:

```bash
uv run official-lines check                     # every source with status: candidate
uv run official-lines check --source ca-gac     # one source
uv run official-lines check --status all        # every source in the catalog
```

**Run it on the server**, not only on your laptop: several sites answer a home connection but refuse data-centre addresses, and the server is where collection happens. Each source gets a verdict:

| Verdict | Meaning | What to do |
|---|---|---|
| `OK` | Links found and statement pages have real text | Set `enabled: true, status: ok` |
| `NEEDS_PATTERN` | The page answers, but we don't yet know which links are statements | Pick a `link_pattern` from the `link:` suggestions it prints, add `link_selector: "a[href]"`, check again |
| `THIN_TEXT` | Links found, but the pages give little text | Usually JavaScript pages; `status: js_only` |
| `NO_LINKS` | The page has no usable links | JavaScript page (`js_only`) or wrong address |
| `BLOCKED` | 403, timeout or refused | `status: blocked`; no workarounds |
| `ROBOTS` | robots.txt asks bots to stay away | `status: blocked`; we respect it |
| `NOT_FOUND` | 404 | Find the new address |

Also read the sample titles it prints. A feed can work technically and still carry the wrong thing (Argentina's English "RSS" lists trade statistics).

## Coverage gaps are part of the product

Coverage is uneven, and that must stay visible. The Coverage page lists every source, including disabled ones with the reason. When an actor looks "silent" on an event, readers can check whether we read that actor at all.

Aim for balance rather than volume: a fifth White House feed adds less than a first working Iranian, Indian or African Union source.

## Feeds break

Official sites redesign without notice. When `official-lines sources` shows a source failing for days:

1. Open its `url` in a browser. Moved? Update the URL.
2. A listing page whose layout changed? Find the new `link_selector`.
3. Gone or blocked? `enabled: false`, record the reason in `status` and `notes`.

Then `deploy/push.sh SERVER_IP` to send the catalog to the server.

A failure for a single run needs nothing from you: the next run reads the source's list again and picks up whatever is new. Statement pages that failed are retried for 2 days (see [Architecture](architecture.md)).

**Sites that refuse servers.** Some sites answer a home connection but refuse data-centre IP addresses (in 2026-11: the U.S. State Department and gov.za). The symptom is a source that works on your laptop but fails on the server, typically with `407`, `403` or "connection refused". We do not route around such blocks with proxies; mark the source `enabled: false`, `status: blocked`, and say so in `notes`.

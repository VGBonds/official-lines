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
    status: ok                # ok | blocked | js_only | no_english | not_found
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

## Coverage gaps are part of the product

Coverage is uneven, and that must stay visible. The Coverage page lists every source, including disabled ones with the reason. When an actor looks "silent" on an event, readers can check whether we read that actor at all.

Aim for balance rather than volume: a fifth White House feed adds less than a first working Iranian, Indian or African Union source.

## Feeds break

Official sites redesign without notice. When `official-lines sources` shows a source failing for days:

1. Open its `url` in a browser. Moved? Update the URL.
2. A listing page whose layout changed? Find the new `link_selector`.
3. Gone or blocked? `enabled: false`, record the reason in `status` and `notes`.

Then `deploy/push.sh SERVER_IP` to send the catalog to the server.

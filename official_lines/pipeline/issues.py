"""Step 4: file each proposition of a compared event under an issue.

The comparison phrases its propositions per event, so the same question ('should the
sanctions on Iran be lifted') is worded differently in every table and cannot be followed
across events. This step asks a cheap model to read an event's propositions and the list of
existing issues, and to choose one issue per proposition, or to name a new issue when none
fits. That is all the model does: it never touches a stance or a quote. An issue is thus a
model's grouping of differently worded propositions, and the issue page shows the original
wording of every proposition next to the issue it was filed under, so that a wrong filing
(two different questions treated as one) can be seen and checked.

An event is due when it has a comparison and no filing of exactly its propositions (each
filing records a fingerprint of the proposition texts), so a re-compared event whose
propositions changed is filed again on the next run, and an event whose filing failed is
retried.
`official-lines issues --all` discards every issue and files every compared event again,
oldest comparison first, so that the issue list grows the way it would have grown day by day.
"""

import hashlib
import logging
import re
import sqlite3
from datetime import UTC, datetime, timedelta

import anthropic

from official_lines.db import loads, now_iso, transaction
from official_lines.llm import prompts
from official_lines.llm.client import LLM, LLMError, cost_usd
from official_lines.llm.schemas import IssueMapping

log = logging.getLogger(__name__)

PURPOSE = "issues"
MAX_ISSUES_SHOWN = 300   # beyond this, the model sees the recently used ones + word matches
RECENT_ISSUE_DAYS = 90
# Rough token sizes for the cost estimate: prompt + per issue listed + per proposition in and out.
EST_BASE_TOKENS, EST_PER_ISSUE, EST_PER_PROP_IN, EST_PER_PROP_OUT = 500, 20, 40, 25


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].rstrip("-")


def fingerprint(propositions: list[dict]) -> str:
    """Identifies one set of propositions (ids and wording), so that a filing can be told
    stale once a re-comparison reworded them."""
    joined = "\n".join(f"{p['id']}\t{p['text']}" for p in propositions)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]


def filed_hashes(conn: sqlite3.Connection) -> dict[int, str]:
    """Event id -> fingerprint of the propositions its filing was made for."""
    return dict(conn.execute(
        "SELECT event_id, MIN(propositions_hash) FROM issue_propositions GROUP BY event_id"))


def events_due(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Compared events whose propositions have no filing, oldest comparison first."""
    filed = filed_hashes(conn)
    rows = conn.execute("SELECT * FROM events WHERE analysis IS NOT NULL"
                        " ORDER BY analysed_at, id").fetchall()
    return [r for r in rows if filed.get(r["id"]) != fingerprint(propositions_of(r))]


def propositions_of(event: sqlite3.Row) -> list[dict]:
    analysis = loads(event["analysis"]) or {}
    return analysis.get("llm", {}).get("propositions", [])


def candidate_issues(conn: sqlite3.Connection, propositions: list[dict]) -> list[sqlite3.Row]:
    """The issues the model may choose from: all of them while the list is short; past
    MAX_ISSUES_SHOWN, those used in the last RECENT_ISSUE_DAYS days plus any whose title
    shares a word of four or more letters with the propositions."""
    rows = conn.execute(
        """SELECT i.*, MAX(m.mapped_at) AS last_used FROM issues i
           LEFT JOIN issue_propositions m ON m.issue_id = i.id
           GROUP BY i.id ORDER BY last_used DESC, i.id DESC"""
    ).fetchall()
    if len(rows) <= MAX_ISSUES_SHOWN:
        return sorted(rows, key=lambda r: r["id"])
    since = (datetime.now(UTC) - timedelta(days=RECENT_ISSUE_DAYS)).isoformat()
    words = {w for p in propositions for w in re.findall(r"[a-z]{4,}", p["text"].lower())}
    kept = [r for r in rows if (r["last_used"] or "") >= since
            or words & set(re.findall(r"[a-z]{4,}", r["title"].lower()))]
    return sorted(kept, key=lambda r: r["id"])


def estimate_cost(n_events: int, n_issues: int, props_per_event: float, model: str) -> float:
    """What filing n_events would cost, from rough token counts (an upper estimate)."""
    n_issues = min(n_issues, MAX_ISSUES_SHOWN)
    tokens_in = EST_BASE_TOKENS + EST_PER_ISSUE * n_issues + EST_PER_PROP_IN * props_per_event
    tokens_out = EST_PER_PROP_OUT * props_per_event + 50
    return n_events * cost_usd(model, int(tokens_in), int(tokens_out))


def map_due(conn: sqlite3.Connection, llm: LLM, model: str, limit: int | None = None) -> int:
    """File every due event. Returns how many events were filed."""
    done = 0
    events = events_due(conn)
    for event in events[:limit] if limit else events:
        try:
            map_event(conn, llm, model, event)
            done += 1
        except (LLMError, anthropic.APIError) as e:
            log.warning("filing under issues failed for %s: %s", event["slug"], e)
    return done


def map_event(conn: sqlite3.Connection, llm: LLM, model: str, event: sqlite3.Row) -> int:
    """One model call for one event: a choice per proposition, applied with the guards in
    apply_mapping(). Returns how many propositions were filed."""
    propositions = propositions_of(event)
    if not propositions:
        return 0
    issues = candidate_issues(conn, propositions)
    user = prompts.ISSUE_USER.format(
        title=event["title"],
        propositions="\n".join(f"{p['id']}: {p['text']}" for p in propositions),
        issues="\n".join(f"I{r['id']}: {r['title']}" for r in issues) or "(none yet)")
    mapping = llm.structured(purpose=PURPOSE, model=model, system=prompts.ISSUE_SYSTEM,
                             user=user, schema=IssueMapping, max_tokens=4000, effort="low")
    return apply_mapping(conn, event, propositions, mapping, {r["id"] for r in issues})


def apply_mapping(conn: sqlite3.Connection, event: sqlite3.Row, propositions: list[dict],
                  mapping: IssueMapping, offered: set[int]) -> int:
    """Store the model's choices. Guards: a choice must name an offered issue or a declared
    new key; a new issue whose title already exists (ignoring case) reuses the existing one;
    the first choice per proposition wins; unknown proposition ids are ignored. The event's
    earlier filing is replaced as a whole, because a re-comparison renumbers propositions."""
    new_titles = {_new_key(n.key): n.title.strip() for n in mapping.new_issues
                  if n.title.strip()}
    valid_ids = {p["id"] for p in propositions}
    chosen: dict[str, str] = {}
    for c in mapping.choices:
        if c.proposition_id in valid_ids:
            choice = c.issue.strip()
            chosen.setdefault(c.proposition_id, _new_key(choice) if choice.lower()
                              .startswith("new:") else choice)
    created: dict[str, int] = {}  # new key -> issue id
    event_id, digest = event["id"], fingerprint(propositions)
    filed = 0
    with transaction(conn):
        conn.execute("DELETE FROM issue_propositions WHERE event_id=?", (event_id,))
        for pid in [p["id"] for p in propositions]:  # in order: new issues get ids in order
            choice = chosen.get(pid)
            if choice is None:
                log.warning("event %s: proposition %s got no issue", event_id, pid)
                continue
            if choice.startswith("new:"):
                if choice not in new_titles:  # declared under no key: the key names it
                    log.info("event %s: %s names an undeclared new issue %r; its key is used"
                             " as the title", event_id, pid, choice)
                    new_titles[choice] = _title_from_key(choice)
                if choice not in created:
                    created[choice] = find_or_create_issue(conn, new_titles[choice])
                issue_id = created[choice]
            else:
                m = re.fullmatch(r"I?(\d+)", choice)
                issue_id = int(m.group(1)) if m else None
                if issue_id not in offered:
                    log.warning("event %s: %s names an unknown issue %r", event_id, pid, choice)
                    continue
            conn.execute(
                "INSERT INTO issue_propositions (event_id, proposition_id, issue_id,"
                " propositions_hash, mapped_at) VALUES (?, ?, ?, ?, ?)",
                (event_id, pid, issue_id, digest, now_iso()))
            filed += 1
    return filed


def _new_key(key: str) -> str:
    """'new:Sanctions on Iran', 'NEW: sanctions-on-iran' and 'sanctions on iran' are the same
    key, so a choice and its declaration match whatever the model's spelling."""
    key = key.strip()
    if key.lower().startswith("new:"):
        key = key[4:]
    return "new:" + slugify(key)


def _title_from_key(key: str) -> str:
    words = key[4:].replace("-", " ").strip()
    return (words[:1].upper() + words[1:]) or "Untitled issue"


def find_or_create_issue(conn: sqlite3.Connection, title: str) -> int:
    row = conn.execute("SELECT id FROM issues WHERE lower(title)=lower(?)", (title,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO issues (slug, title, created_at) VALUES (?, ?, ?)",
                       (f"new-{now_iso()}", title, now_iso()))
    issue_id = cur.lastrowid
    conn.execute("UPDATE issues SET slug=? WHERE id=?",
                 (f"{slugify(title) or 'issue'}-{issue_id}", issue_id))
    return issue_id


def remap_all(conn: sqlite3.Connection, llm: LLM, model: str) -> int:
    """Discard every issue and filing and file every compared event again. Issue slugs
    change, so links to issue pages break; use it after a prompt change, not routinely."""
    with transaction(conn):
        conn.execute("DELETE FROM issue_propositions")
        conn.execute("DELETE FROM issues")
    return map_due(conn, llm, model)


def drop_empty_issues(conn: sqlite3.Connection) -> int:
    """Issues no proposition is filed under any more (after re-filings). Returns how many."""
    with transaction(conn):
        cur = conn.execute("DELETE FROM issues WHERE id NOT IN"
                           " (SELECT DISTINCT issue_id FROM issue_propositions)")
    return cur.rowcount

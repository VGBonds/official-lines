"""Numbers computed in plain Python from the LLM's stance table. No LLM here.

Definitions (also in docs/methodology.md):

stance value      asserts = 1, qualifies = 0.5, denies = 0. Silence has no value.
pair agreement    for two actors, over the propositions BOTH took a stance on:
                  mean of (1 - |value_a - value_b|). 1 = same line, 0 = opposite lines.
shared floor      propositions that EVERY actor in the stance table asserts (no silence, no
                  qualification, no denial). Needs at least 2 actors. True common ground.
uncontested majority
                  propositions asserted by more than half of the actors in the stance table
                  and denied by none, but not asserted by all: the rest are silent or qualify.
contested         propositions that at least one actor asserts and another denies.
(The "actors in the stance table" are those that took at least one stance in the comparison,
i.e. the columns of the table on the event page.)
polar pair        the actor pair with the lowest agreement (needs >= 2 shared propositions).
unusual alignment a pair whose agreement here differs by >= 0.5 from its average over
                  earlier events (needs >= 3 earlier events with both actors).
shared wording    two different actors whose texts share long identical word sequences
                  (8+ words): a sign of a joint statement or common talking points.
joint voice       a text that several actors publish (a joint statement, a republication) is
                  ONE column in the stance table, "joint:CA+FR+GB", however many publish it.
                  For pair agreement each publisher inherits the joint voice's stances. The
                  agreement between two co-publishers of the same text is recorded but
                  flagged "joint" and left out of the polar pair, the unusual-alignment flags
                  and the history baseline: co-signing is shared wording, not a measurement.
"""

import re
from collections import defaultdict
from itertools import combinations

STANCE_VALUE = {"asserts": 1.0, "qualifies": 0.5, "denies": 0.0}
UNUSUAL_DELTA = 0.5
MIN_HISTORY = 3
SHINGLE_WORDS = 8


def pair_key(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


_CAUTION = {"denies": 2, "qualifies": 1, "asserts": 0}


def _record(table: dict[str, dict[str, str]], actor: str, pid: str, stance: str) -> None:
    """Keep the most cautious of several stances: a denial wins over a qualification, which
    wins over an assertion."""
    current = table[actor].get(pid)
    if current is None or _CAUTION[stance] > _CAUTION[current]:
        table[actor][pid] = stance


def stance_table(positions: list[dict]) -> dict[str, dict[str, str]]:
    """voice -> proposition id -> stance. A voice is an actor id or a joint voice id."""
    table: dict[str, dict[str, str]] = defaultdict(dict)
    for p in positions:
        _record(table, p["actor"], p["proposition_id"], p["stance"])
    return dict(table)


def fill_from_joint(table: dict[str, dict[str, str]],
                    voices: dict[str, list[str]]) -> dict[str, dict[str, str]]:
    """A publisher of a joint text that also spoke on its own has a column of its own. Where
    that column is blank, it takes the joint text's stance, so that the actor's own column
    is never read as silence on something it signed. Publishers without a column of their
    own are represented by the joint voice alone."""
    out = {voice: dict(stances) for voice, stances in table.items()}
    for voice, members in voices.items():
        for actor in members:
            if actor in out:
                for pid, stance in table.get(voice, {}).items():
                    out[actor].setdefault(pid, stance)
    return out


def expand_voices(table: dict[str, dict[str, str]],
                  voices: dict[str, list[str]]) -> dict[str, dict[str, str]]:
    """The stance table per actor: each publisher of a joint voice inherits its stances,
    combined with the actor's own stances by the cautious rule."""
    out: dict[str, dict[str, str]] = defaultdict(dict)
    for voice, stances in table.items():
        for actor in voices.get(voice, [voice]):
            for pid, stance in stances.items():
                _record(out, actor, pid, stance)
    return dict(out)


def joint_pairs(voices: dict[str, list[str]]) -> set[str]:
    """Pairs of actors that published the same text."""
    return {pair_key(a, b) for members in voices.values()
            for a, b in combinations(sorted(members), 2)}


def pair_agreements(table: dict[str, dict[str, str]],
                    joint: set[str] | None = None) -> dict[str, dict]:
    result = {}
    for a, b in combinations(sorted(table), 2):
        shared = set(table[a]) & set(table[b])
        if not shared:
            continue
        diffs = [abs(STANCE_VALUE[table[a][p]] - STANCE_VALUE[table[b][p]]) for p in shared]
        key = pair_key(a, b)
        result[key] = {"score": round(1 - sum(diffs) / len(diffs), 3), "shared": len(shared)}
        if joint and key in joint:
            result[key]["joint"] = True
    return result


def measured(pairs: dict[str, dict]) -> dict[str, dict]:
    """Pairs whose agreement was measured, i.e. not co-publishers of one text."""
    return {k: v for k, v in pairs.items() if not v.get("joint")}


def _speakers(table: dict[str, dict[str, str]]) -> list[str]:
    return [a for a in table if table[a]]


def shared_floor(table: dict[str, dict[str, str]], proposition_ids: list[str]) -> list[str]:
    speakers = _speakers(table)
    if len(speakers) < 2:
        return []
    return [pid for pid in proposition_ids
            if all(table[a].get(pid) == "asserts" for a in speakers)]


def uncontested_majority(table: dict[str, dict[str, str]],
                         proposition_ids: list[str]) -> list[str]:
    speakers = _speakers(table)
    floor = set(shared_floor(table, proposition_ids))
    out = []
    for pid in proposition_ids:
        stances = [table[a].get(pid) for a in speakers]
        if pid not in floor and "denies" not in stances \
                and 2 * stances.count("asserts") > len(speakers):
            out.append(pid)
    return out


def contested(table: dict[str, dict[str, str]], proposition_ids: list[str]) -> list[str]:
    out = []
    for pid in proposition_ids:
        stances = {t.get(pid) for t in table.values()}
        if "asserts" in stances and "denies" in stances:
            out.append(pid)
    return out


def polar_pair(pairs: dict[str, dict]) -> dict | None:
    candidates = [(v["score"], k) for k, v in measured(pairs).items() if v["shared"] >= 2]
    if not candidates:
        return None
    score, key = min(candidates)
    return {"pair": key.split("|"), "score": score} if score < 0.5 else None


def unusual_alignment(pairs: dict[str, dict], history: dict[str, list[float]]) -> list[dict]:
    flags = []
    for key, v in measured(pairs).items():
        past = history.get(key, [])
        if len(past) < MIN_HISTORY:
            continue
        baseline = sum(past) / len(past)
        delta = v["score"] - baseline
        if abs(delta) >= UNUSUAL_DELTA:
            flags.append({
                "pair": key.split("|"),
                "kind": "unusual agreement" if delta > 0 else "unusual disagreement",
                "score": v["score"], "baseline": round(baseline, 3), "events": len(past),
            })
    return flags


def _shingles(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {" ".join(words[i:i + SHINGLE_WORDS]) for i in range(len(words) - SHINGLE_WORDS + 1)}


def shared_wording(texts_by_actor: dict[str, str], min_shared: int = 2) -> list[dict]:
    """Pairs of actors whose texts share long identical phrases."""
    shingles = {a: _shingles(t) for a, t in texts_by_actor.items() if t}
    found = []
    for a, b in combinations(sorted(shingles), 2):
        common = shingles[a] & shingles[b]
        if len(common) >= min_shared:
            found.append({"pair": [a, b], "shared_phrases": len(common),
                          "example": max(common, key=len)})
    return sorted(found, key=lambda f: -f["shared_phrases"])


def agreement_labels(table: dict[str, dict[str, str]], proposition_ids: list[str]) -> dict:
    """The per-proposition labels. Recomputed from the stored stance table whenever the site
    or the brief is built, so stored comparisons always follow the current definitions."""
    return {
        "shared_floor": shared_floor(table, proposition_ids),
        "uncontested_majority": uncontested_majority(table, proposition_ids),
        "contested": contested(table, proposition_ids),
    }


def contrasting_terms(terminology: list[dict]) -> list[dict]:
    """Concepts that at least two actors name with different words. One actor varying its
    own wording is style, not a difference between official lines."""
    kept = []
    for t in terminology:
        actors = {u["actor"] for u in t["usages"]}
        terms = {u["term"].strip().lower() for u in t["usages"]}
        if len(actors) >= 2 and len(terms) >= 2:
            kept.append(t)
    return kept


def one_sided_denials(table: dict[str, dict[str, str]], proposition_ids: list[str]) -> list[str]:
    """Propositions that someone denies and nobody asserts: usually the mirror image of
    another proposition, which the prompt asks the model to avoid."""
    out = []
    for pid in proposition_ids:
        stances = {t.get(pid) for t in table.values()}
        if "denies" in stances and "asserts" not in stances:
            out.append(pid)
    return out


def compute(analysis: dict, texts_by_actor: dict[str, str], history: dict[str, list[float]],
            voices: dict[str, list[str]] | None = None) -> dict:
    """voices: joint voice id -> the actors that published that text (see analyze.py)."""
    voices = voices or {}
    table = fill_from_joint(stance_table(analysis["positions"]), voices)
    prop_ids = [p["id"] for p in analysis["propositions"]]
    pairs = pair_agreements(expand_voices(table, voices), joint_pairs(voices))
    return {
        "stance_table": table,
        "pairs": pairs,
        **agreement_labels(table, prop_ids),
        "polar_pair": polar_pair(pairs),
        "unusual_alignment": unusual_alignment(pairs, history),
        "shared_wording": shared_wording(texts_by_actor),
    }


def issue_counts(rows: list[dict]) -> dict:
    """Plain counts for one issue over its rows (one per proposition and event; each row's
    `cells` maps a voice to its stance): events, propositions, contested rows, and per voice
    how often it asserts, qualifies and denies. No score: the propositions under one issue
    are worded differently, so stances on them do not add up to a position."""
    voices: dict[str, dict[str, int]] = {}
    events_of: dict[str, set] = {}
    for r in rows:
        for voice, cell in r["cells"].items():
            stance = cell["stance"] if isinstance(cell, dict) else cell
            counts = voices.setdefault(voice, {"asserts": 0, "qualifies": 0, "denies": 0,
                                               "events": 0})
            counts[stance] += 1
            events_of.setdefault(voice, set()).add(r["event_id"])
    for voice, counts in voices.items():
        counts["events"] = len(events_of[voice])
    return {"events": len({r["event_id"] for r in rows}), "propositions": len(rows),
            "contested": sum(1 for r in rows if r.get("contested")), "voices": voices}

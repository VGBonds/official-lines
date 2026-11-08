"""Numbers computed in plain Python from the LLM's stance table. No LLM here.

Definitions (also in docs/methodology.md):

stance value      asserts = 1, qualifies = 0.5, denies = 0. Silence has no value.
pair agreement    for two actors, over the propositions BOTH took a stance on:
                  mean of (1 - |value_a - value_b|). 1 = same line, 0 = opposite lines.
shared floor      propositions asserted by at least 60% of the actors that took any stance,
                  and denied by nobody. "What the official lines do not fight about."
contested         propositions that at least one actor asserts and another denies.
polar pair        the actor pair with the lowest agreement (needs >= 2 shared propositions).
unusual alignment a pair whose agreement here differs by >= 0.5 from its average over
                  earlier events (needs >= 3 earlier events with both actors).
shared wording    two different actors whose texts share long identical word sequences
                  (8+ words): a sign of a joint statement or common talking points.
"""

import re
from collections import defaultdict
from itertools import combinations
from math import ceil

STANCE_VALUE = {"asserts": 1.0, "qualifies": 0.5, "denies": 0.0}
FLOOR_SHARE = 0.6
UNUSUAL_DELTA = 0.5
MIN_HISTORY = 3
SHINGLE_WORDS = 8


def pair_key(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


def stance_table(positions: list[dict]) -> dict[str, dict[str, str]]:
    """actor -> proposition id -> stance. If an actor has several stances, a denial wins
    over a qualification, which wins over an assertion (the most cautious reading)."""
    rank = {"denies": 2, "qualifies": 1, "asserts": 0}
    table: dict[str, dict[str, str]] = defaultdict(dict)
    for p in positions:
        current = table[p["actor"]].get(p["proposition_id"])
        if current is None or rank[p["stance"]] > rank[current]:
            table[p["actor"]][p["proposition_id"]] = p["stance"]
    return dict(table)


def pair_agreements(table: dict[str, dict[str, str]]) -> dict[str, dict]:
    result = {}
    for a, b in combinations(sorted(table), 2):
        shared = set(table[a]) & set(table[b])
        if not shared:
            continue
        diffs = [abs(STANCE_VALUE[table[a][p]] - STANCE_VALUE[table[b][p]]) for p in shared]
        result[pair_key(a, b)] = {"score": round(1 - sum(diffs) / len(diffs), 3),
                                  "shared": len(shared)}
    return result


def shared_floor(table: dict[str, dict[str, str]], proposition_ids: list[str]) -> list[str]:
    speakers = [a for a in table if table[a]]
    if len(speakers) < 2:
        return []
    needed = max(2, ceil(FLOOR_SHARE * len(speakers)))
    floor = []
    for pid in proposition_ids:
        stances = [table[a].get(pid) for a in speakers]
        if "denies" not in stances and stances.count("asserts") >= needed:
            floor.append(pid)
    return floor


def contested(table: dict[str, dict[str, str]], proposition_ids: list[str]) -> list[str]:
    out = []
    for pid in proposition_ids:
        stances = {t.get(pid) for t in table.values()}
        if "asserts" in stances and "denies" in stances:
            out.append(pid)
    return out


def polar_pair(pairs: dict[str, dict]) -> dict | None:
    candidates = [(v["score"], k) for k, v in pairs.items() if v["shared"] >= 2]
    if not candidates:
        return None
    score, key = min(candidates)
    return {"pair": key.split("|"), "score": score} if score < 0.5 else None


def unusual_alignment(pairs: dict[str, dict], history: dict[str, list[float]]) -> list[dict]:
    flags = []
    for key, v in pairs.items():
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


def compute(analysis: dict, texts_by_actor: dict[str, str],
            history: dict[str, list[float]]) -> dict:
    table = stance_table(analysis["positions"])
    prop_ids = [p["id"] for p in analysis["propositions"]]
    pairs = pair_agreements(table)
    return {
        "stance_table": table,
        "pairs": pairs,
        "shared_floor": shared_floor(table, prop_ids),
        "contested": contested(table, prop_ids),
        "polar_pair": polar_pair(pairs),
        "unusual_alignment": unusual_alignment(pairs, history),
        "shared_wording": shared_wording(texts_by_actor),
    }

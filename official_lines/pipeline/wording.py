"""Identical passages published by different actors: joint statements, common talking points.

Plain text comparison, no AI. A passage is a run of at least SHINGLE_WORDS words (ignoring
case and punctuation) that appears in statements of two or more different actors. Repeats
within one actor's own statements are not counted.
"""

import re
from collections import defaultdict
from itertools import combinations

from official_lines.pipeline.metrics import SHINGLE_WORDS

WORD = re.compile(r"[A-Za-z0-9']+")
EXCERPT_WORDS = 30  # the site never quotes more than about 30 words


def _words(text: str) -> list[re.Match]:
    return list(WORD.finditer(text or ""))


def _shingle(words: list[re.Match], i: int) -> int:
    return hash(" ".join(w.group().lower() for w in words[i:i + SHINGLE_WORDS]))


def find_passages(statements: list[dict]) -> list[dict]:
    """statements: dicts with id, actor and text. Returns the shared passages, longest first:
    {"words", "excerpt", "occurrences": [{"statement_id", "actor", "start", "end"}],
    "actors"}. start/end are character offsets into that statement's text."""
    words = {s["id"]: _words(s["text"]) for s in statements}
    actor = {s["id"]: s["actor"] for s in statements}
    shingles = {sid: [_shingle(ws, i) for i in range(len(ws) - SHINGLE_WORDS + 1)]
                for sid, ws in words.items()}

    owner: dict[int, str | None] = {}  # shingle -> its only actor, or None when shared
    for sid, hs in shingles.items():
        for h in hs:
            if owner.setdefault(h, actor[sid]) not in (actor[sid], None):
                owner[h] = None
    where: dict[int, set[int]] = defaultdict(set)
    for sid, hs in shingles.items():
        for h in hs:
            if owner[h] is None:
                where[h].add(sid)

    passages: dict[str, dict] = {}
    for sid, hs in shingles.items():
        hits: dict[int, list[int]] = defaultdict(list)  # other statement -> positions here
        for i, h in enumerate(hs):
            for other in where.get(h, ()):
                if other > sid and actor[other] != actor[sid]:
                    hits[other].append(i)
        for other, positions in hits.items():
            for first, last in _runs(positions):
                ws = words[sid][first:last + SHINGLE_WORDS]
                key = " ".join(w.group().lower() for w in ws)
                p = passages.setdefault(key, {"words": len(ws), "excerpt": _excerpt(ws),
                                              "statements": {}})
                p["statements"].setdefault(sid, (ws[0].start(), ws[-1].end()))
                p["statements"].setdefault(other, _locate(words[other], key))
    return _finish(passages, actor)


def _runs(positions: list[int]) -> list[tuple[int, int]]:
    runs = []
    for i in positions:
        if runs and i == runs[-1][1] + 1:
            runs[-1][1] = i
        else:
            runs.append([i, i])
    return [(a, b) for a, b in runs]


def _excerpt(ws: list[re.Match]) -> str:
    text = ws[0].string[ws[0].start():ws[min(len(ws), EXCERPT_WORDS) - 1].end()]
    return " ".join(text.split()) + (" …" if len(ws) > EXCERPT_WORDS else "")


def _locate(ws: list[re.Match], key: str) -> tuple[int, int]:
    target = key.split()
    n = len(target)
    for i in range(len(ws) - n + 1):
        if [w.group().lower() for w in ws[i:i + n]] == target:
            return ws[i].start(), ws[i + n - 1].end()
    return 0, 0


def _finish(passages: dict[str, dict], actor: dict[int, str]) -> list[dict]:
    """Drop fragments of a longer passage that the same actors share, then shape."""
    kept: list[tuple[str, dict, set[str]]] = []
    for key, p in sorted(passages.items(), key=lambda kv: -kv[1]["words"]):
        actors = {actor[sid] for sid in p["statements"]}
        if any(key in k and actors <= a for k, _, a in kept):
            continue
        kept.append((key, p, actors))
    out = []
    for _, p, _ in kept:
        occurrences = [{"statement_id": sid, "actor": actor[sid], "start": a, "end": b}
                       for sid, (a, b) in sorted(p["statements"].items())]
        out.append({"words": p["words"], "excerpt": p["excerpt"], "occurrences": occurrences,
                    "actors": sorted({o["actor"] for o in occurrences})})
    return out


def in_span(occurrence: dict, start: int | None, end: int | None) -> bool:
    """Whether an occurrence overlaps a part's span (None = the part's span is unknown)."""
    if start is None or end is None:
        return True
    return occurrence["start"] < end and occurrence["end"] > start


def group_by_actors(passages: list[dict]) -> list[dict]:
    """One line per set of actors: how many passages they share and the longest one."""
    groups: dict[tuple[str, ...], dict] = {}
    for p in passages:
        g = groups.setdefault(tuple(p["actors"]), {"actors": p["actors"], "passages": 0,
                                                   "longest": p})
        g["passages"] += 1
        if p["words"] > g["longest"]["words"]:
            g["longest"] = p
    return sorted(groups.values(), key=lambda g: (-len(g["actors"]), -g["longest"]["words"]))


JOINT_MIN_WORDS = 60   # a shared text shorter than this is a quote, not a joint text
JOINT_MIN_SHARE = 0.6  # share of the shorter text's word sequences the other must contain
# 0.6, not higher: one publisher's copy of a joint text differs from another's by spelling
# (honour/honor), an intro line, and page furniture the text extractor leaves in.


def same_text_groups(texts: dict) -> list[set]:
    """Keys whose texts are the same text: a joint statement published by several actors, or
    a verbatim republication. Two texts belong together when the shorter one has at least
    JOINT_MIN_WORDS words and at least JOINT_MIN_SHARE of its SHINGLE_WORDS-word sequences
    occur in the other. Membership is transitive. Only groups of two or more are returned."""
    shingles = {}
    for key, text in texts.items():
        ws = [w.group().lower() for w in _words(text)]
        if len(ws) >= JOINT_MIN_WORDS:
            shingles[key] = {" ".join(ws[i:i + SHINGLE_WORDS])
                             for i in range(len(ws) - SHINGLE_WORDS + 1)}
    parent = {k: k for k in shingles}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for a, b in combinations(shingles, 2):
        small, big = sorted((shingles[a], shingles[b]), key=len)
        if len(small & big) >= JOINT_MIN_SHARE * len(small):
            parent[find(a)] = find(b)
    groups: dict = defaultdict(set)
    for k in shingles:
        groups[find(k)].add(k)
    return [g for g in groups.values() if len(g) > 1]

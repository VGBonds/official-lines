"""The golden set: comparisons judged by hand, which a prompt or metrics change must not break.

Each case in tests/golden/*.json holds one event's input exactly as the comparison step sees
it (title and part records, see analyze.part_record) and expectations about the result.
`official-lines golden` compares every case again with the current prompts and model and
checks the expectations; `official-lines golden --export SLUG` writes a new case from the
local database, with an empty "expect" block for the editor to fill in.

Expectations are deliberately coarse, because the model phrases propositions differently on
each run. They say what must hold whatever the phrasing:

  joint              [["DE", "FR"], ...]  these actors published one text: one joint voice each
  contested_min / contested_max           number of contested propositions
  opposed            [["CN", "GB"], ...]  pairs that take opposite stances (one asserts, the
                                          other denies) on at least 2 propositions
  aligned            [["FR", "GB"], ...]  pairs with the same stance on at least 2 propositions
                                          and opposite stances on none
  no_one_sided_denials  true              no proposition that someone denies and nobody asserts
                                          (the mirror image of another proposition)
  min_propositions / max_propositions     size of the stance table
"""

import json
from pathlib import Path

from official_lines.catalog import Catalog
from official_lines.config import PROJECT_ROOT
from official_lines.llm.client import LLM
from official_lines.pipeline import metrics
from official_lines.pipeline.analyze import JOINT_PREFIX, compare, part_record, select_parts

GOLDEN_DIR = PROJECT_ROOT / "tests" / "golden"
MIN_SHARED = 2


def export_case(conn, slug: str, out_dir: Path = GOLDEN_DIR) -> Path:
    event = conn.execute("SELECT * FROM events WHERE slug=?", (slug,)).fetchone()
    if event is None:
        raise KeyError(slug)
    parts = [part_record(r) for r in select_parts(conn, event["id"])]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{slug}.json"
    old = json.loads(path.read_text()) if path.exists() else {}  # keep the editor's judgement
    path.write_text(json.dumps({
        "why": old.get("why", ""),
        "title": event["title"],
        "actors": sorted({p["actor"] for p in parts}),
        "expect": old.get("expect", {}),
        "parts": parts,
    }, ensure_ascii=False, indent=1))
    return path


def _stances(payload: dict, a: str, b: str) -> tuple[int, int]:
    """(propositions with the same stance, propositions with opposite stances) for a pair,
    with each publisher of a joint text taking that text's stances."""
    members = {vid: v["members"] for vid, v in payload.get("voices", {}).items()}
    table = metrics.expand_voices(payload["metrics"]["stance_table"], members)
    ta, tb = table.get(a, {}), table.get(b, {})
    both = ta.keys() & tb.keys()
    same = sum(1 for pid in both if ta[pid] == tb[pid])
    opposite = sum(1 for pid in both if {ta[pid], tb[pid]} == {"asserts", "denies"})
    return same, opposite


def check(payload: dict, expect: dict) -> list[str]:
    """What the comparison got wrong, in words; empty when every expectation holds."""
    m = payload["metrics"]
    failures = []
    voices = {tuple(v["members"]) for v in payload.get("voices", {}).values()}
    for members in expect.get("joint", []):
        if tuple(sorted(members)) not in voices:
            failures.append(f"no joint voice for {'+'.join(members)} (found: "
                            f"{[JOINT_PREFIX + '+'.join(v) for v in voices] or 'none'})")
    n = len(m["contested"])
    if n < expect.get("contested_min", 0):
        failures.append(f"{n} contested propositions, expected at least "
                        f"{expect['contested_min']}")
    if n > expect.get("contested_max", 10 ** 6):
        failures.append(f"{n} contested propositions, expected at most "
                        f"{expect['contested_max']}")
    for a, b in expect.get("opposed", []):
        same, opposite = _stances(payload, a, b)
        if opposite < MIN_SHARED:
            failures.append(f"{a} and {b} should take opposite stances on at least "
                            f"{MIN_SHARED} propositions, got {opposite} (same on {same})")
    for a, b in expect.get("aligned", []):
        same, opposite = _stances(payload, a, b)
        if same < MIN_SHARED or opposite:
            failures.append(f"{a} and {b} should share at least {MIN_SHARED} stances and "
                            f"oppose on none, got same={same} opposite={opposite}")
    props = [p["id"] for p in payload["llm"]["propositions"]]
    if expect.get("no_one_sided_denials"):
        bad = metrics.one_sided_denials(m["stance_table"], props)
        if bad:
            failures.append(f"one-sided denials (mirror-image propositions?): {bad}")
    if len(props) < expect.get("min_propositions", 0):
        failures.append(f"{len(props)} propositions, expected at least "
                        f"{expect['min_propositions']}")
    if len(props) > expect.get("max_propositions", 10 ** 6):
        failures.append(f"{len(props)} propositions, expected at most "
                        f"{expect['max_propositions']}")
    return failures


def describe(payload: dict) -> str:
    """The stance table in text, for the editor to read next to the verdict."""
    table = payload["metrics"]["stance_table"]
    symbol = {"asserts": "●", "qualifies": "◐", "denies": "○"}
    columns = list(table)
    lines = ["    " + "  ".join(f"{c[:14]:14}" for c in columns)]
    for p in payload["llm"]["propositions"]:
        cells = "  ".join(f"{symbol.get(table[c].get(p['id']), '·'):14}" for c in columns)
        lines.append(f"{p['id']:4}{cells}  {p['text']}")
    pairs = ", ".join(f"{k} {v['score']}/{v['shared']}{' joint' if v.get('joint') else ''}"
                      for k, v in payload["metrics"]["pairs"].items())
    return "\n".join(lines) + f"\npairs: {pairs}"


def run_cases(catalog: Catalog, llm: LLM, model: str, paths: list[Path]) -> int:
    """Compare each case again and print a verdict. Returns the number of failed cases."""
    failed = 0
    for path in paths:
        case = json.loads(path.read_text())
        payload = compare(catalog, llm, model, case["title"], case["parts"], history={})
        failures = check(payload, case.get("expect") or {})
        failed += bool(failures)
        print(f"{'FAIL' if failures else 'PASS'}  {path.stem}")
        for f in failures:
            print(f"      - {f}")
        print(describe(payload).replace("\n", "\n      ") + "\n")
    return failed

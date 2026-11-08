from official_lines.pipeline import metrics


def pos(actor, pid, stance):
    return {"actor": actor, "proposition_id": pid, "stance": stance}


POSITIONS = [
    pos("US", "p1", "asserts"), pos("CN", "p1", "asserts"), pos("RU", "p1", "asserts"),
    pos("US", "p2", "asserts"), pos("CN", "p2", "denies"), pos("RU", "p2", "denies"),
    pos("US", "p3", "qualifies"), pos("CN", "p3", "asserts"),
]


def test_stance_table_prefers_most_cautious():
    table = metrics.stance_table([pos("US", "p1", "asserts"), pos("US", "p1", "denies")])
    assert table == {"US": {"p1": "denies"}}


def test_pair_agreement():
    pairs = metrics.pair_agreements(metrics.stance_table(POSITIONS))
    assert pairs["CN|US"] == {"score": 0.5, "shared": 3}   # (1 + 0 + 0.5) / 3
    assert pairs["CN|RU"] == {"score": 1.0, "shared": 2}
    assert pairs["RU|US"] == {"score": 0.5, "shared": 2}


def test_floor_and_contested():
    table = metrics.stance_table(POSITIONS)
    assert metrics.shared_floor(table, ["p1", "p2", "p3"]) == ["p1"]
    assert metrics.contested(table, ["p1", "p2", "p3"]) == ["p2"]


def test_polar_pair_only_when_far_apart():
    assert metrics.polar_pair({"A|B": {"score": 0.2, "shared": 3}})["pair"] == ["A", "B"]
    assert metrics.polar_pair({"A|B": {"score": 0.8, "shared": 3}}) is None
    assert metrics.polar_pair({"A|B": {"score": 0.0, "shared": 1}}) is None


def test_unusual_alignment_needs_history():
    pairs = {"RU|US": {"score": 1.0, "shared": 3}}
    assert metrics.unusual_alignment(pairs, {"RU|US": [0.1, 0.2]}) == []
    flags = metrics.unusual_alignment(pairs, {"RU|US": [0.1, 0.2, 0.0]})
    assert flags[0]["kind"] == "unusual agreement" and flags[0]["baseline"] == 0.1


def test_shared_wording():
    common = "we call on all parties to exercise maximum restraint and avoid escalation"
    found = metrics.shared_wording({
        "CN": f"Today {common} in the region.",
        "RU": f"Moscow says {common} now.",
        "US": "Something entirely different was said here by the spokesperson today.",
    })
    assert len(found) == 1 and found[0]["pair"] == ["CN", "RU"]

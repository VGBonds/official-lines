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


def test_agreement_labels_treat_silence_as_silence():
    t = metrics.stance_table([
        *(pos(a, "p1", "asserts") for a in "ABCD"),                      # everyone
        *(pos(a, "p2", "asserts") for a in "ABC"),                       # D silent
        pos("A", "p3", "asserts"), pos("B", "p3", "asserts"), pos("C", "p3", "qualifies"),
        *(pos(a, "p4", "asserts") for a in "ABC"), pos("D", "p4", "denies"),
        *(pos(a, "p5", "asserts") for a in "ABC"), pos("D", "p5", "qualifies"),
    ])
    labels = metrics.agreement_labels(t, ["p1", "p2", "p3", "p4", "p5"])
    assert labels["shared_floor"] == ["p1"]
    assert labels["uncontested_majority"] == ["p2", "p5"]  # p3: 2 of 4 is not more than half
    assert labels["contested"] == ["p4"]


def test_terminology_needs_two_actors_with_different_words():
    def term(*usages):
        return {"concept": "c", "usages": [{"actor": a, "term": t} for a, t in usages]}
    one_actor = term(("GB", "Russia's aggression"), ("GB", "this war"))
    same_words = term(("GB", "the war"), ("FR", "The war"))
    contrast = term(("GB", "the war"), ("RU", "the special military operation"))
    assert metrics.contrasting_terms([one_actor, same_words, contrast]) == [contrast]


def test_joint_voice_is_one_column_and_its_publishers_are_not_measured():
    voices = {"joint:FR+GB": ["FR", "GB"]}
    analysis = {
        "propositions": [{"id": "p1", "text": "x"}, {"id": "p2", "text": "y"}],
        "positions": [pos("joint:FR+GB", "p1", "asserts"), pos("joint:FR+GB", "p2", "asserts"),
                      pos("CN", "p1", "asserts"), pos("CN", "p2", "denies"),
                      pos("GB", "p2", "qualifies")],  # the UK also spoke on its own
    }
    m = metrics.compute(analysis, {}, {}, voices=voices)
    # Labels count voices: two voices, one text each side.
    assert m["shared_floor"] == ["p1"] and m["contested"] == ["p2"]
    # Pairs are per actor: FR inherits the joint stances; GB combines them cautiously.
    assert m["pairs"]["CN|FR"] == {"score": 0.5, "shared": 2}
    assert m["pairs"]["CN|GB"] == {"score": 0.75, "shared": 2}
    assert m["pairs"]["FR|GB"]["joint"] is True
    assert metrics.polar_pair({"FR|GB": {"score": 0.0, "shared": 3, "joint": True}}) is None
    assert metrics.unusual_alignment({"FR|GB": {"score": 1.0, "shared": 3, "joint": True}},
                                     {"FR|GB": [0.0, 0.0, 0.0]}) == []
    assert metrics.one_sided_denials(metrics.stance_table([pos("CN", "p3", "denies")]),
                                     ["p3"]) == ["p3"]

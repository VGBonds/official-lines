from official_lines.pipeline import wording

JOINT = ("We the undersigned foreign ministers are deeply concerned by the sentencing today and "
         "call for the immediate release of all those detained for peaceful expression.")


def st(sid, actor, text):
    return {"id": sid, "actor": actor, "text": text}


def test_joint_text_is_one_passage_for_all_actors():
    passages = wording.find_passages([
        st(1, "FR", "Paris, 9 November. " + JOINT + " More French text follows here."),
        st(2, "DE", "Berlin. " + JOINT),
        st(3, "GB", JOINT + " The UK adds its own closing remark."),
        st(4, "CN", "An entirely different statement about other matters altogether today."),
    ])
    assert len(passages) == 1
    p = passages[0]
    assert p["actors"] == ["DE", "FR", "GB"] and p["words"] == len(JOINT.split())
    assert p["excerpt"] == JOINT.rstrip(".")  # under 30 words: quoted whole
    fr = next(o for o in p["occurrences"] if o["actor"] == "FR")
    assert fr["start"] == len("Paris, 9 November. ")


def test_repeats_within_one_actor_are_not_shared_wording():
    assert wording.find_passages([st(1, "RU", JOINT), st(2, "RU", JOINT)]) == []


def test_group_by_actors_and_spans():
    passages = wording.find_passages([st(1, "FR", JOINT), st(2, "GB", JOINT)])
    groups = wording.group_by_actors(passages)
    assert groups[0]["actors"] == ["FR", "GB"] and groups[0]["passages"] == 1
    o = passages[0]["occurrences"][0]
    assert wording.in_span(o, None, None) and not wording.in_span(o, o["end"], o["end"] + 50)

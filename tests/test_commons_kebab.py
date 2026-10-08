from scripts.commons_kebab import select


def row(pageid, category, auto_reject=""):
    return {"pageid": pageid, "category": category, "auto_reject": auto_reject}


def test_select_round_robin_cached_first_and_cap():
    rows = [row(1, "A"), row(2, "A"), row(3, "A"), row(4, "B"), row(5, "C", "license"), row(6, "C")]
    picked = [r["pageid"] for r in select(rows, cached={"3": "3.jpg"}, max_new=4)]
    assert picked == [3, 4, 6, 1]          # A (cached first), B, C, then A again
    assert [r["pageid"] for r in select(rows, {}, 0)] == [1, 4, 6, 2, 3]  # no cap; rejected 5 never picked

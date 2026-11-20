"""Feature B: allergen and dietary guard (typical ingredients only)."""
import copy
import json

import pytest

from app import guard
from app import main as api
from app.ingredients import IngredientError, load_content
from tests.test_api import fastapi_testclient

CONTENT = load_content()
DATA = guard.load_allergens(CONTENT)


def run(dish, variant, rid, lang="en"):
    return guard.evaluate(DATA, CONTENT, dish, variant, lang, [rid])["restrictions"][0]


# ---------- content integrity: every ingredient line is tagged, nothing stale ----------

def test_allergen_content_is_valid_and_covers_every_ingredient_line():
    assert guard.validate_allergens(DATA, CONTENT) == []
    lines = sum(len(i["ingredients"]["en"]) for i in guard.entry_keys(CONTENT).values())
    assert lines == sum(len(v) for v in DATA["entries"].values()) == 40


def test_validator_catches_untagged_stale_and_bad_tags():
    missing = copy.deepcopy(DATA)
    missing["entries"]["pizza"].pop("Tomato sauce")
    assert any("Tomato sauce" in p for p in guard.validate_allergens(missing, CONTENT))
    stale = copy.deepcopy(DATA)
    stale["entries"]["pizza"]["Pineapple"] = {}
    assert any("Pineapple" in p for p in guard.validate_allergens(stale, CONTENT))
    bad = copy.deepcopy(DATA)
    bad["entries"]["pizza"]["Tomato sauce"] = {"contains": ["lactose"]}
    assert any("unknown tags" in p for p in guard.validate_allergens(bad, CONTENT))
    star = copy.deepcopy(DATA)
    star["entries"]["pizza"]["Tomato sauce"] = {"contains": ["*"]}
    assert any("'*'" in p for p in guard.validate_allergens(star, CONTENT))
    nodish = copy.deepcopy(DATA)
    nodish["entries"].pop("hot_dog")
    assert any("entries" in p for p in guard.validate_allergens(nodish, CONTENT))
    nolabel = copy.deepcopy(DATA)
    nolabel["restrictions"]["halal"]["label"].pop("ko")
    assert any("label" in p for p in guard.validate_allergens(nolabel, CONTENT))


def test_content_change_without_allergen_update_is_caught():
    changed = copy.deepcopy(CONTENT)
    changed["dishes"]["pizza"]["ingredients"]["en"].append("Pineapple")
    changed["dishes"]["pizza"]["ingredients"]["ko"].append("파인애플")
    assert any("Pineapple" in p for p in guard.validate_allergens(DATA, changed))


# ---------- the three states ----------

def test_warning_names_the_ingredient_that_caused_it():
    r = run("pizza", None, "gluten")
    assert r["status"] == "warning"
    assert [(m["ingredient"], m["kind"]) for m in r["matches"]] == [("Leavened wheat-based dough", "contains")]
    r = run("hamburger", None, "egg")
    assert r["status"] == "warning" and r["matches"][0]["kind"] == "may"
    assert "mayonnaise" in r["matches"][0]["ingredient"]


def test_halal_catches_pork_and_alcohol_options():
    r = run("kebab", "skewered", "halal")
    assert r["status"] == "warning"
    assert {t for m in r["matches"] for t in m["tags"]} == {"pork", "alcohol"}
    r = run("hot_dog", None, "halal")
    assert r["status"] == "warning" and "pork" in r["matches"][0]["ingredient"]
    assert "slaughter" in r["note"]                          # the halal limits are always stated


def test_cheesecake_halal_is_unverified_when_cheese_enzymes_are_unspecified():
    r = run("dessert", "cheesecake", "halal")
    assert r["status"] == "unknown" and r["matches"] == []
    assert [u["ingredient"] for u in r["unverified"]] == ["Soft fresh cheese such as cream cheese, ricotta or quark"]


def test_safe_means_no_match_and_still_asks_to_check():
    r = run("hamburger", None, "nuts")
    assert r["status"] == "safe" and r["matches"] == [] and r["unverified"] == []
    assert "still check" in r["message"]
    assert run("dessert", "chocolate_cake", "sesame")["status"] == "safe"


def test_unknown_when_a_line_does_not_say():
    r = run("pizza", None, "nuts")                           # "Other toppings, which vary"
    assert r["status"] == "unknown" and r["matches"] == []
    assert [u["ingredient"] for u in r["unverified"]] == ["Other toppings, which vary"]
    assert "Not verified" in r["message"]
    assert run("pizza", None, "halal")["status"] == "unknown"        # toppings may be pork: not "safe"


def test_a_match_wins_over_unverified_lines():
    r = run("pizza", None, "dairy")                          # cheese matches; toppings are also unverified
    assert r["status"] == "warning" and r["unverified"]


def test_every_dish_and_restriction_gets_exactly_one_known_status():
    for key in guard.entry_keys(CONTENT):
        dish, _, variant = key.partition("/")
        res = guard.evaluate(DATA, CONTENT, dish, variant or None, "en", list(DATA["restrictions"]))["restrictions"]
        assert [r["id"] for r in res] == list(DATA["restrictions"])
        assert all(r["status"] in guard.STATUSES and r["message"] for r in res)


def test_korean_names_the_korean_ingredient_line():
    en = run("pizza", None, "gluten", "en")["matches"][0]["ingredient"]
    ko = run("pizza", None, "gluten", "ko")["matches"][0]["ingredient"]
    assert en != ko and ko == CONTENT["dishes"]["pizza"]["ingredients"]["ko"][0]
    assert run("pizza", None, "gluten", "ko")["label"] == "글루텐"


def test_synthetic_content_covers_each_branch():
    content = {"dishes": {"x": {"ingredients": {"en": ["A", "B", "C", "D"], "ko": ["가", "나", "다", "라"]}}}}
    data = {
        "restrictions": {"r": {"tags": ["nuts"], "label": {"en": "R", "ko": "R"}, "note": None}},
        "messages": {s: {"en": s, "ko": s} for s in guard.STATUSES}, "basis": {"en": "b", "ko": "b"},
        "entries": {"x": {"A": {"contains": ["nuts"]}, "B": {"may": ["nuts"]}, "C": {"unknown": ["*"]}, "D": {}}},
    }
    r = guard.evaluate(data, content, "x", None, "en", ["r"])["restrictions"][0]
    assert r["status"] == "warning"
    assert [(m["ingredient"], m["kind"]) for m in r["matches"]] == [("A", "contains"), ("B", "may")]
    assert [u["ingredient"] for u in r["unverified"]] == ["C"]
    data["entries"]["x"] = {"A": {}, "B": {}, "C": {}, "D": {}}
    assert guard.evaluate(data, content, "x", None, "en", ["r"])["restrictions"][0]["status"] == "safe"


# ---------- request parsing ----------

def test_parse_avoid():
    assert guard.parse_avoid(None, DATA) == [] and guard.parse_avoid("", DATA) == [] and guard.parse_avoid(" ", DATA) == []
    assert guard.parse_avoid("halal, nuts,halal", DATA) == ["halal", "nuts"]
    for bad in ("peanuts", "halal,,nuts", "halal;nuts", "HALAL"):
        with pytest.raises(IngredientError) as e:
            guard.parse_avoid(bad, DATA)
        assert e.value.status_code == 400 and e.value.code == "unknown_restriction"


# ---------- API ----------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("FOOD_LENS_RUN_DIR", raising=False)
    with fastapi_testclient.TestClient(api.app) as c:
        yield c


def test_endpoint_without_avoid_has_no_guard(client):
    r = client.get("/api/ingredients/pizza")
    assert r.status_code == 200 and r.json()["guard"] is None


def test_endpoint_with_avoid(client):
    r = client.get("/api/ingredients/kebab", params={"variant": "skewered", "avoid": "halal,nuts", "lang": "ko"})
    assert r.status_code == 200
    g = r.json()["guard"]
    assert [x["id"] for x in g["restrictions"]] == ["halal", "nuts"]
    assert g["restrictions"][0]["status"] == "warning" and g["restrictions"][0]["label"] == "할랄 / 돼지고기 제외"
    assert g["basis"] and r.json()["ingredients"]


@pytest.mark.parametrize("path, params, status, code", [
    ("/api/ingredients/pizza", {"avoid": "peanuts"}, 400, "unknown_restriction"),
    ("/api/ingredients/pizza", {"avoid": "halal,x"}, 400, "unknown_restriction"),
    ("/api/ingredients/kebab", {"avoid": "halal"}, 400, "variant_required"),
    ("/api/ingredients/sushi", {"avoid": "halal"}, 404, "unknown_dish"),
])
def test_endpoint_errors(client, path, params, status, code):
    r = client.get(path, params=params)
    assert (r.status_code, r.json()["code"]) == (status, code)


def test_restriction_ids_match_the_frontend():
    import re
    from pathlib import Path
    ts = (Path(__file__).resolve().parent.parent / "web" / "src" / "lib" / "restrictions.ts").read_text(encoding="utf-8")
    ids = re.search(r"RESTRICTIONS = \[(.*?)\]", ts, re.S).group(1)
    assert re.findall(r'"(\w+)"', ids) == list(DATA["restrictions"])

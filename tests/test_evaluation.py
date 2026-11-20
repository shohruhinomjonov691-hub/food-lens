"""Feature A (results): the evaluation summary is built from the verified run folder only."""
import csv
import json
import os

import pytest

from app import evaluation as ev
from app import main as api
from app.model import verify_run
from food_lens.classes import CLASSES
from tests.test_api import fastapi_testclient, make_run

pytest.importorskip("torch")


def write_predictions(run, rows):
    with open(os.path.join(run, "test_predictions.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sample_id", "target", "variant", "predicted", "confidence", "not_sure"])
        for i, (t, p, c) in enumerate(rows):
            w.writerow([f"s{i}", t, "", p, f"{c:.4f}", c < 0.6])


def test_tier_table_counts_and_accuracy():
    rows = [("pizza", "pizza", 0.95), ("pizza", "pizza", 0.80), ("kebab", "pizza", 0.85),    # high 3, 2 right
            ("kebab", "kebab", 0.79), ("kebab", "dessert", 0.60),                             # low 2, 1 right
            ("kebab", "kebab", 0.59), ("pizza", "hot_dog", 0.1)]                              # abstain 2, 1 right
    t = ev.tier_table(rows, 0.6, 0.8)
    assert (t["high"]["n"], t["low"]["n"], t["abstain"]["n"]) == (3, 2, 2)
    assert t["high"]["accuracy"] == pytest.approx(2 / 3) and t["low"]["accuracy"] == 0.5
    assert sum(v["share"] for v in t.values()) == pytest.approx(1.0)
    empty = ev.tier_table([], 0.6, 0.8)
    assert all(v["n"] == 0 and v["share"] is None and v["accuracy"] is None for v in empty.values())


@pytest.fixture
def run_dir(tmp_path):
    return make_run(str(tmp_path))


def test_evaluation_without_prediction_file_has_no_tier_table(run_dir):
    info = verify_run(run_dir)
    e = info.evaluation
    assert e["tiers"] is None and e["n"] == 50 and [c["class"] for c in e["per_class"]] == list(CLASSES)
    assert e["thresholds"] == {"abstain_below": 0.6, "high_from": 0.8}
    assert set(ev.STATIC_LIMITS) <= set(e["limits"])


def test_evaluation_with_prediction_file(run_dir):
    write_predictions(run_dir, [("pizza", "pizza", 0.9)] * 40 + [("kebab", "pizza", 0.7)] * 10)
    e = verify_run(run_dir).evaluation
    assert e["tiers"]["high"]["n"] == 40 and e["tiers"]["low"]["n"] == 10 and e["tiers"]["abstain"]["n"] == 0
    assert e["tiers"]["high"]["accuracy"] == 1.0 and e["tiers"]["low"]["accuracy"] == 0.0


@pytest.mark.parametrize("rows_or_text", [
    [("pizza", "pizza", 0.9)] * 49,                                  # wrong number of rows
    [("pizza", "sushi", 0.9)] * 50,                                  # unknown class
    [("pizza", "pizza", 1.5)] * 50,                                  # confidence out of range
    "not,a,csv\nnope",                                                # wrong columns
    "sample_id,target,variant,predicted,confidence,not_sure\ns,pizza,,pizza,abc,False\n",
])
def test_bad_prediction_file_drops_only_the_tier_table(run_dir, rows_or_text):
    if isinstance(rows_or_text, str):
        open(os.path.join(run_dir, "test_predictions.csv"), "w").write(rows_or_text)
    else:
        write_predictions(run_dir, rows_or_text)
    info = verify_run(run_dir)                                       # the model is still accepted
    assert info.evaluation["tiers"] is None and info.evaluation["accuracy"] > 0


def test_small_samples_are_flagged(run_dir):
    e = verify_run(run_dir).evaluation
    assert "small_variant_test" in e["limits"] and e["per_variant"][0]["small_n"] is True
    assert all(c["small_n"] == (c["support"] < ev.SMALL_N) for c in e["per_class"])


def test_support_comes_from_the_confusion_matrix(run_dir):
    path = os.path.join(run_dir, "test_metrics.json")
    with open(path, encoding="utf-8") as f:
        metrics = json.load(f)
    metrics["per_class"]["kebab"].pop("support")
    metrics["per_class"]["pizza"]["support"] = 999
    with open(path, "w", encoding="utf-8") as f:
        json.dump(metrics, f)

    result = verify_run(run_dir).evaluation
    expected = [sum(counts) for counts in metrics["confusion_matrix"]]
    assert [dish["support"] for dish in result["per_class"]] == expected
    assert sum(expected) == result["n"]


def test_endpoint(monkeypatch, tmp_path):
    monkeypatch.delenv("FOOD_LENS_RUN_DIR", raising=False)
    with fastapi_testclient.TestClient(api.app) as c:
        r = c.get("/api/evaluation")
        assert r.status_code == 503 and r.json()["code"] == "MODEL_NOT_READY"
    run = make_run(str(tmp_path))
    write_predictions(run, [("pizza", "pizza", 0.9)] * 50)
    monkeypatch.setenv("FOOD_LENS_RUN_DIR", run)
    with fastapi_testclient.TestClient(api.app) as c:
        r = c.get("/api/evaluation")
        assert r.status_code == 200 and r.json()["tiers"]["high"]["n"] == 50
        assert r.headers["cache-control"] == "no-store"


# ---------- the real run (outside the repository): runs only when FOOD_LENS_REAL_RUN points at it ----------

REAL = os.environ.get("FOOD_LENS_REAL_RUN")


@pytest.mark.skipif(not REAL or not os.path.isdir(REAL), reason="set FOOD_LENS_REAL_RUN to the verified run folder")
def test_real_run_evaluation_matches_the_published_numbers():
    e = verify_run(REAL).evaluation
    assert e["n"] == 806 and round(e["accuracy"], 3) == 0.935 and round(e["macro_f1"], 3) == 0.928
    kebab = next(c for c in e["per_class"] if c["class"] == "kebab")
    assert kebab["support"] == 56 and round(kebab["recall"], 3) == 0.893
    small = {v["variant"]: v["n"] for v in e["per_variant"] if v["small_n"]}
    assert small == {"minced_skewer": 13, "doner_shawarma": 9}
    assert e["tiers"] and sum(v["n"] for v in e["tiers"].values()) == 806
    assert e["tiers"]["abstain"]["n"] == 12                          # "not sure for 1.5%" of 806
    assert "small_variant_test" in e["limits"]

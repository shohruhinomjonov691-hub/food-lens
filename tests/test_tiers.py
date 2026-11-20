"""Feature A: result tiers (high / low / abstain / non_food), blank-image detection, the concurrency gate."""
import asyncio
import io
import json
import os

import numpy as np
import pytest
from PIL import Image

from app import limits, tiers
from app import main as api
from app.model import ModelNotReady, verify_run
from tests.test_api import fastapi_testclient, image_bytes, make_run

pytest.importorskip("torch")


# ---------- pure tier rule ----------

@pytest.mark.parametrize("top1, expected", [
    (0.0, "abstain"), (0.4999, "abstain"), (0.5, "low"),          # threshold: below abstains, equal is "low"
    (0.7999, "low"), (0.8, "high"), (1.0, "high"),                # high boundary: equal is "high"
])
def test_classify_boundaries(top1, expected):
    assert tiers.classify(top1, 0.5, 0.8) == expected


def test_classify_when_high_equals_threshold_there_is_no_low_band():
    assert [tiers.classify(p, 0.8, 0.8) for p in (0.79, 0.8, 0.9)] == ["abstain", "high", "high"]


def model_input(arr):
    from food_lens import preprocess as pp
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "JPEG", quality=95)
    return pp.inference_tensor(buf.getvalue())


def test_flat_images_are_flat_and_photos_are_not():
    rng = np.random.default_rng(0)
    solid = lambda c: np.full((240, 320, 3), c, np.uint8)
    for c in (0, 128, 255):
        assert tiers.is_flat(model_input(solid(c))), c
    assert not tiers.is_flat(model_input(rng.integers(0, 255, (240, 320, 3), dtype=np.uint8)))
    # A smooth but real gradient (std ~74) and a faint one (std ~7) are both above the limit.
    ramp = np.tile(np.linspace(0, 255, 320, dtype=np.uint8), (240, 1))
    assert not tiers.is_flat(model_input(np.stack([ramp] * 3, -1)))
    faint = np.tile(np.linspace(120, 140, 320, dtype=np.uint8), (240, 1))
    assert not tiers.is_flat(model_input(np.stack([faint] * 3, -1)))


def test_grey_std_matches_the_pixel_std():
    from food_lens import preprocess as pp
    rng = np.random.default_rng(1)
    arr = rng.integers(0, 255, (224, 224, 3), dtype=np.uint8)
    spec = pp.MODEL_INPUT                                     # normalize directly: no resampling in between
    x = ((arr / 255.0 - np.array(spec["mean"])) / np.array(spec["std"])).transpose(2, 0, 1).astype(np.float32)
    expected = float(np.mean(arr.reshape(-1, 3).astype(float).std(axis=0)))
    assert tiers.grey_std(x) == pytest.approx(expected, rel=0.01)


# ---------- the API returns each tier ----------

@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("FOOD_LENS_RUN_DIR", make_run(str(tmp_path)))
    with fastapi_testclient.TestClient(api.app) as c:
        assert api.PREDICTOR.ready, api.PREDICTOR.reason
        yield c


def set_bounds(threshold, high):
    api.PREDICTOR.info.threshold, api.PREDICTOR.info.high_threshold = threshold, high


def test_tier_high_and_low_show_top3_and_abstain_shows_nothing(client):
    data = image_bytes(seed=5)
    set_bounds(0.0, 0.0)                                      # everything is "high"
    r = client.post("/api/predict", content=data).json()
    assert r["tier"] == "high" and len(r["predictions"]) == 3
    set_bounds(0.0, 1.01)                                     # nothing reaches "high", nothing abstains
    r = client.post("/api/predict", content=data).json()
    assert r["tier"] == "low" and len(r["predictions"]) == 3
    set_bounds(1.0, 1.0)                                      # everything is below the threshold
    r = client.post("/api/predict", content=data).json()
    assert r["tier"] == "abstain" and r["predictions"] == []
    assert "dish" not in json.dumps(r).replace("high_threshold", "")     # no dish or percentage leaves the server
    assert r["non_food_reason"] is None


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
@pytest.mark.parametrize("color", [(0, 0, 0), (255, 255, 255), (127, 127, 127), (200, 30, 30)])
def test_blank_image_is_non_food_without_calling_the_model(client, monkeypatch, fmt, color):
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), color).save(buf, fmt)

    def boom(*a, **k):
        raise AssertionError("the model must not run on a blank image")

    monkeypatch.setattr(api.PREDICTOR, "model", boom)
    r = client.post("/api/predict", content=buf.getvalue())
    assert r.status_code == 200
    body = r.json()
    assert body["tier"] == "non_food" and body["non_food_reason"] == "blank_image" and body["predictions"] == []


def test_transparent_png_is_blank_too(client):
    buf = io.BytesIO()
    Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(buf, "PNG")        # transparency is flattened onto white
    assert client.post("/api/predict", content=buf.getvalue()).json()["tier"] == "non_food"


def test_health_reports_the_boundaries(client):
    h = client.get("/health").json()
    assert h["model"]["threshold"] == 0.6 and h["model"]["high_threshold"] == 0.8
    assert h["fallback_available"] is False and "halal" in h["restrictions"]


# ---------- high_threshold in final.json ----------

def rewrite_final(run, **changes):
    path = os.path.join(run, "final.json")
    final = json.load(open(path))
    final.update(changes)
    json.dump(final, open(path, "w"))


def test_run_can_lock_its_own_high_threshold(tmp_path):
    run = make_run(str(tmp_path))
    rewrite_final(run, high_threshold=0.9)
    assert verify_run(run).high_threshold == 0.9


@pytest.mark.parametrize("bad", [0.5, 0.59, 1.5, float("nan"), "0.9", True, None])
def test_invalid_high_threshold_is_rejected(tmp_path, bad):
    run = make_run(str(tmp_path))
    final = json.load(open(os.path.join(run, "final.json")))
    final["high_threshold"] = bad
    open(os.path.join(run, "final.json"), "w").write(json.dumps(final))      # NaN is written as NaN
    with pytest.raises(ModelNotReady, match="high_threshold"):
        verify_run(run)


def test_default_high_never_below_the_locked_threshold(tmp_path):
    run = make_run(str(tmp_path))
    rewrite_final(run, threshold=0.95)
    assert verify_run(run).high_threshold == 0.95


# ---------- concurrency gate (measured problem: 8 parallel requests took ~10 s each) ----------

def test_gate_limits_running_and_refuses_beyond_the_queue():
    async def scenario():
        gate = limits.ConcurrencyGate(max_running=2, max_waiting=1)
        peak, running, done = 0, 0, []

        async def job(i, hold):
            nonlocal peak, running
            async with gate:
                running += 1
                peak = max(peak, running)
                await asyncio.sleep(hold)
                running -= 1
                done.append(i)

        tasks = [asyncio.create_task(job(i, 0.05)) for i in range(3)]      # 2 run, 1 waits
        await asyncio.sleep(0.01)
        with pytest.raises(limits.Busy):                                    # the 4th is refused at once
            async with gate:
                pass
        await asyncio.gather(*tasks)
        assert peak == 2 and sorted(done) == [0, 1, 2]
        assert gate.running == 0 and gate.waiting == 0
        async with gate:                                                    # usable again afterwards
            pass

    asyncio.run(scenario())


def test_gate_releases_after_an_error():
    async def scenario():
        gate = limits.ConcurrencyGate(1, 0)
        with pytest.raises(RuntimeError):
            async with gate:
                raise RuntimeError("boom")
        async with gate:
            pass

    asyncio.run(scenario())


def test_api_answers_503_busy_when_saturated(client, monkeypatch):
    gate = limits.ConcurrencyGate(1, 0)
    gate.running = 1
    monkeypatch.setattr(api, "PREDICT_GATE", gate)
    r = client.post("/api/predict", content=image_bytes())
    assert r.status_code == 503 and r.json()["code"] == "SERVER_BUSY" and r.headers["retry-after"]
    gate.running = 0
    assert client.post("/api/predict", content=image_bytes()).status_code == 200

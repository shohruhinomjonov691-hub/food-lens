import builtins
import hashlib
import io
import json
import logging
import os
import tempfile

import numpy as np
import pytest
from PIL import Image

from app import image_io
from app import main as api
from app.config import MAX_UPLOAD_BYTES
from app.ingredients import load_content, lookup, validate_content
from app.model import ModelNotReady, Predictor, verify_run
from food_lens import preprocess as pp
from food_lens.classes import CLASSES

fastapi_testclient = pytest.importorskip("fastapi.testclient")


def image_bytes(fmt="JPEG", size=(320, 240), seed=0, **save):
    arr = np.random.default_rng(seed).integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, fmt, **save)
    return buf.getvalue()


# ---------- a run folder with a real (randomly initialised) checkpoint: tests the plumbing only ----------

def make_run(root, smoke=False, classes=CLASSES, recipe_id=None, spec=None, with_test=True):
    torch = pytest.importorskip("torch")
    from torch import nn
    from torchvision.models import mobilenet_v2

    run = os.path.join(root, "20261009T000000Z_test_seed42")
    os.makedirs(run)
    torch.manual_seed(0)
    model = mobilenet_v2(weights=None)
    model.classifier[1] = nn.Linear(model.last_channel, len(CLASSES))
    buf = io.BytesIO()
    torch.save({"state_dict": model.state_dict(), "classes": list(CLASSES), "arch": "mobilenet_v2"}, buf)
    open(f"{run}/best.pt", "wb").write(buf.getvalue())
    w = lambda name, obj: json.dump(obj, open(f"{run}/{name}", "w"))
    w("config.json", {"smoke_test": smoke})
    w("class_mapping.json", {"classes": list(classes)})
    w("preprocessing.json", {"dataset_cache": {"recipe_id": recipe_id or pp.recipe_id()},
                             "model_input": {"spec": spec or pp.MODEL_INPUT}})
    w("final.json", {"checkpoint": "best.pt", "checkpoint_sha256": hashlib.sha256(buf.getvalue()).hexdigest(),
                     "temperature": 1.7, "threshold": 0.6})
    if with_test:
        w("test_metrics.json", notebook_test_metrics())
    return run


def notebook_test_metrics(n=50, seed=0):
    """The dict notebooks/01_train_mobilenetv2.ipynb cell 11 writes (same keys, same helpers)."""
    from food_lens import train_utils as tu
    rng = np.random.default_rng(seed)
    y = rng.integers(0, len(CLASSES), n)
    p = np.where(rng.random(n) < 0.8, y, (y + 1) % len(CLASSES))
    overall = tu.summary(y, p, len(CLASSES))
    return {
        **overall, "classes": list(CLASSES),
        "per_class": {c: {"precision": overall["precision"][i], "recall": overall["recall"][i],
                          "f1": overall["f1"][i], "support": overall["support"][i]} for i, c in enumerate(CLASSES)},
        "per_variant": [{"target": "pizza", "variant": "pizza", "n": 10, "recall": 0.8, "predicted_as": {"pizza": 8},
                         "small_n": True}],
        "selective_at_threshold": {**tu.selective(np.eye(len(CLASSES))[p], y, 0.6), "threshold": 0.6},
        "bootstrap_95ci": tu.bootstrap_ci(y, p, len(CLASSES), n_boot=50, seed=0),
        "bootstrap_subset": "kebab recall", "note": "test used once",
    }


@pytest.fixture
def client_not_ready(monkeypatch):
    monkeypatch.delenv("FOOD_LENS_RUN_DIR", raising=False)
    with fastapi_testclient.TestClient(api.app) as c:
        yield c


@pytest.fixture
def client_ready(monkeypatch, tmp_path):
    monkeypatch.setenv("FOOD_LENS_RUN_DIR", make_run(str(tmp_path)))
    with fastapi_testclient.TestClient(api.app) as c:
        assert api.PREDICTOR.ready, api.PREDICTOR.reason
        yield c


# ---------- MODEL_NOT_READY: no invented predictions ----------

def test_health_and_predict_without_model(client_not_ready):
    h = client_not_ready.get("/health").json()
    assert h["status"] == "ok" and h["model_ready"] is False and "not set" in h["model_reason"]
    assert h["classes"] == list(CLASSES)
    r = client_not_ready.post("/api/predict", content=image_bytes())
    assert r.status_code == 503
    assert r.json()["code"] == "MODEL_NOT_READY" and "predictions" not in r.json()


@pytest.mark.parametrize("change, reason", [
    (dict(smoke=True), "smoke test"),
    (dict(classes=list(reversed(CLASSES))), "class order"),
    (dict(recipe_id="0" * 16), "cache recipe"),
    (dict(spec={**pp.MODEL_INPUT, "crop": 256}), "model-input"),
    (dict(with_test=False), "no test evaluation"),
])
def test_run_folder_is_rejected(tmp_path, change, reason):
    run = make_run(str(tmp_path), **change)
    with pytest.raises(ModelNotReady, match=reason):
        verify_run(run)
    p = Predictor()
    assert p.load(run) is False and reason in p.reason and not p.ready
    with pytest.raises(ModelNotReady):
        p.predict(image_bytes())


def test_tampered_checkpoint_is_rejected(tmp_path):
    run = make_run(str(tmp_path))
    with open(f"{run}/best.pt", "ab") as f:
        f.write(b"x")
    with pytest.raises(ModelNotReady, match="SHA-256"):
        verify_run(run)


# ---------- prediction contract ----------

def test_predict_contract(client_ready):
    data = image_bytes()
    r = client_ready.post("/api/predict", content=data)
    assert r.status_code == 200, r.text
    body = r.json()
    preds = body["predictions"]
    assert len(preds) == 3 and len({p["class"] for p in preds}) == 3
    assert all(p["class"] in CLASSES and 0 <= p["confidence"] <= 1 for p in preds)
    assert [p["confidence"] for p in preds] == sorted((p["confidence"] for p in preds), reverse=True)
    assert body["uncertain"] == (preds[0]["confidence"] < 0.6) and body["threshold"] == 0.6
    assert body["variant"] is None and "user chooses" in body["variant_note"]
    assert "calibrated" in body["confidence"]
    assert r.headers["cache-control"] == "no-store"
    # Same numbers as the eval path with the locked temperature.
    import torch
    with torch.no_grad():
        logits = api.PREDICTOR.model(torch.from_numpy(pp.inference_tensor(data))[None]).double().numpy()[0]
    probs = np.exp(logits / 1.7 - (logits / 1.7).max())
    probs /= probs.sum()
    assert preds[0]["class"] == CLASSES[int(probs.argmax())]
    assert preds[0]["confidence"] == pytest.approx(round(float(probs.max()), 4))


def test_predict_writes_no_files_and_logs_no_image(client_ready, monkeypatch, caplog):
    real_open = builtins.open

    def no_write_open(file, mode="r", *a, **k):
        if any(m in mode for m in "wax+"):
            raise AssertionError(f"write attempted: {file}")
        return real_open(file, mode, *a, **k)

    def no_tempfile(*a, **k):
        raise AssertionError("temporary file attempted")

    monkeypatch.setattr(builtins, "open", no_write_open)
    for name in ("TemporaryFile", "NamedTemporaryFile", "SpooledTemporaryFile", "mkstemp"):
        monkeypatch.setattr(tempfile, name, no_tempfile)
    data = image_bytes(seed=3)
    with caplog.at_level(logging.DEBUG):
        assert client_ready.post("/api/predict", content=data).status_code == 200
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "JFIF" not in logged and data[:64].hex() not in logged


# ---------- upload validation ----------

def bad_cases():
    good = image_bytes()
    big_header = io.BytesIO()
    Image.new("L", (9000, 10)).save(big_header, "PNG")
    many_pixels = io.BytesIO()
    Image.new("L", (6000, 5000)).save(many_pixels, "PNG")
    frames = [Image.new("RGB", (40, 40), c) for c in ("red", "blue")]
    animated = io.BytesIO()
    frames[0].save(animated, "WEBP", save_all=True, append_images=frames[1:])
    gif = io.BytesIO()
    Image.new("RGB", (40, 40)).save(gif, "GIF")
    return [
        (b"", 400, "empty_file"),
        (b"<html>not an image</html>", 415, "unsupported_format"),
        (gif.getvalue(), 415, "unsupported_format"),
        (good[: len(good) // 2], 422, "corrupt_image"),
        (b"\xff\xd8\xff" + b"\x00" * 200, 422, "corrupt_image"),
        (big_header.getvalue(), 413, "image_too_large"),
        (many_pixels.getvalue(), 413, "image_too_large"),
        (animated.getvalue(), 415, "animated_image"),
    ]


@pytest.mark.parametrize("data, status, code", bad_cases())
def test_validation(data, status, code):
    with pytest.raises(image_io.ImageError) as e:
        image_io.validate_image(data)
    assert (e.value.status_code, e.value.code) == (status, code)


@pytest.mark.parametrize("fmt", ["JPEG", "PNG", "WEBP"])
def test_accepted_formats(fmt):
    assert image_io.validate_image(image_bytes(fmt)) == fmt


def test_api_validation_errors(client_ready):
    r = client_ready.post("/api/predict", content=b"<html>")
    assert (r.status_code, r.json()["code"]) == (415, "unsupported_format")
    r = client_ready.post("/api/predict", content=b"\0" * (MAX_UPLOAD_BYTES + 1))
    assert (r.status_code, r.json()["code"]) == (413, "file_too_large")


def test_api_reads_raw_body_not_uploadfile():
    import ast
    tree = ast.parse(open(api.__file__, encoding="utf-8").read())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "UploadFile" not in names and "File" not in names        # would spool uploads to disk
    assert "request.stream()" in open(api.__file__, encoding="utf-8").read()


# ---------- ingredients ----------

def test_content_is_valid_and_complete():
    content = load_content()
    assert validate_content(content) == []
    assert list(content["dishes"]["kebab"]["variants"]) == ["skewered", "minced_skewer", "doner_shawarma"]
    assert list(content["dishes"]["dessert"]["variants"]) == ["cheesecake", "chocolate_cake"]


@pytest.mark.parametrize("dish, variant", [("pizza", None), ("hamburger", None), ("hot_dog", None),
                                            ("kebab", "skewered"), ("kebab", "minced_skewer"),
                                            ("kebab", "doner_shawarma"), ("dessert", "cheesecake"),
                                            ("dessert", "chocolate_cake")])
@pytest.mark.parametrize("lang", ["en", "ko"])
def test_ingredient_endpoint(client_not_ready, dish, variant, lang):
    params = {"lang": lang, **({"variant": variant} if variant else {})}
    r = client_not_ready.get(f"/api/ingredients/{dish}", params=params)     # works without a model
    assert r.status_code == 200
    body = r.json()
    assert body["ingredients"] and all(s["url"].startswith("https://") for s in body["sources"])
    assert body["variant_chosen_by"] == ("user" if variant else None)
    if lang == "en":
        assert "not identified from your photo" in body["disclaimer"]
    assert body["translated"] is (lang == "ko") and body["source_language"] == "en"


@pytest.mark.parametrize("path, params, status, code", [
    ("/api/ingredients/kebab", {}, 400, "variant_required"),
    ("/api/ingredients/dessert", {"lang": "ko"}, 400, "variant_required"),
    ("/api/ingredients/kebab", {"variant": "gyros"}, 404, "unknown_variant"),
    ("/api/ingredients/pizza", {"variant": "margherita"}, 400, "variant_not_applicable"),
    ("/api/ingredients/sushi", {}, 404, "unknown_dish"),
    ("/api/ingredients/pizza", {"lang": "uz"}, 400, "unsupported_language"),
])
def test_ingredient_errors(client_not_ready, path, params, status, code):
    r = client_not_ready.get(path, params=params)
    assert (r.status_code, r.json()["code"]) == (status, code)


def test_content_validator_catches_problems():
    content = load_content()
    merged = json.loads(json.dumps(content))
    merged["dishes"]["kebab"]["ingredients"] = {"en": ["Meat"], "ko": ["고기"]}
    assert any("merged list" in p for p in validate_content(merged))
    no_source = json.loads(json.dumps(content))
    no_source["dishes"]["pizza"]["sources"] = []
    assert any("source" in p for p in validate_content(no_source))
    claim = json.loads(json.dumps(content))
    claim["disclaimer"]["en"] = "Ingredients detected in your photo."
    assert any("disclaimer" in p for p in validate_content(claim))
    lopsided = json.loads(json.dumps(content))
    lopsided["dishes"]["hot_dog"]["ingredients"]["ko"].pop()
    assert any("equal-length" in p for p in validate_content(lopsided))

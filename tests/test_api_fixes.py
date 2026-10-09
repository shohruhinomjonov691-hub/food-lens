"""Regressions for the Codex review of the API (develop@b146deb)."""
import copy
import hashlib
import io
import json
import os

import pytest

from app import main as api
from app.config import MAX_UPLOAD_BYTES
from app.model import ModelNotReady, Predictor, verify_run
from tests.test_api import image_bytes, make_run, notebook_test_metrics

torch = pytest.importorskip("torch")
fastapi_testclient = pytest.importorskip("fastapi.testclient")


def rewrite(run, name, obj=None, raw=None):
    with open(os.path.join(run, name), "w", encoding="utf-8") as f:
        f.write(raw if raw is not None else json.dumps(obj))


def read(run, name):
    return json.load(open(os.path.join(run, name)))


def other_weights():
    from torch import nn
    from torchvision.models import mobilenet_v2
    torch.manual_seed(123)
    m = mobilenet_v2(weights=None)
    m.classifier[1] = nn.Linear(m.last_channel, 5)
    buf = io.BytesIO()
    torch.save({"state_dict": m.state_dict(), "classes": ["dessert", "hamburger", "hot_dog", "kebab", "pizza"],
                "arch": "mobilenet_v2"}, buf)
    return buf.getvalue()


# 1) High: the loaded checkpoint is exactly the verified one.
def test_codex_reproducer_locked_pt_with_swapped_best_pt(tmp_path):
    run = make_run(str(tmp_path))
    locked = open(f"{run}/best.pt", "rb").read()
    open(f"{run}/locked.pt", "wb").write(locked)
    final = read(run, "final.json")
    rewrite(run, "final.json", {**final, "checkpoint": "locked.pt"})
    open(f"{run}/best.pt", "wb").write(other_weights())          # a different model under the loaded name
    p = Predictor()
    assert p.load(run) is False and "best.pt" in p.reason


@pytest.mark.parametrize("name", ["../best.pt", "/tmp/best.pt", "best.pth", None])
def test_only_best_pt_is_accepted(tmp_path, name):
    run = make_run(str(tmp_path))
    final = read(run, "final.json")
    rewrite(run, "final.json", {**{k: v for k, v in final.items() if k != "checkpoint"},
                                **({"checkpoint": name} if name else {})})
    with pytest.raises(ModelNotReady, match="best.pt"):
        verify_run(run)


def test_loader_uses_the_verified_bytes(tmp_path, monkeypatch):
    run = make_run(str(tmp_path))
    verified = open(f"{run}/best.pt", "rb").read()
    import app.model as model_module
    real_verify = model_module.verify_run

    def verify_then_swap(run_dir):
        info = real_verify(run_dir)
        open(f"{run_dir}/best.pt", "wb").write(other_weights())   # file changes after verification
        return info

    monkeypatch.setattr(model_module, "verify_run", verify_then_swap)
    p = Predictor()
    assert p.load(run), p.reason
    expected = torch.load(io.BytesIO(verified), weights_only=True)["state_dict"]
    for k, v in p.model.state_dict().items():
        assert torch.equal(v, expected[k]), k
    assert p.info.checkpoint_sha256 == hashlib.sha256(verified).hexdigest()


# 2) Medium: run readiness.
@pytest.mark.parametrize("config", [{}, {"smoke_test": None}, {"smoke_test": "false"}, {"smoke_test": 0},
                                    {"smoke_test": True}])
def test_config_must_say_smoke_test_false(tmp_path, config):
    run = make_run(str(tmp_path))
    rewrite(run, "config.json", config)
    with pytest.raises(ModelNotReady, match="smoke_test"):
        verify_run(run)


def broken_metrics():
    good = notebook_test_metrics()
    cases = {"not json": None, "empty object": {}, "a list": [1, 2]}
    def drop(key):
        m = copy.deepcopy(good)
        m.pop(key)
        return m
    for key in ("n", "accuracy", "macro_f1", "classes", "confusion_matrix", "per_class"):
        cases[f"missing {key}"] = drop(key)
    cases["n zero"] = {**good, "n": 0}
    cases["n bool"] = {**good, "n": True}
    cases["accuracy NaN"] = {**good, "accuracy": float("nan")}
    cases["macro_f1 > 1"] = {**good, "macro_f1": 1.5}
    cases["matrix sum != n"] = {**good, "n": good["n"] + 1}
    bad_pc = copy.deepcopy(good)
    bad_pc["per_class"]["kebab"]["recall"] = float("inf")
    cases["per-class inf"] = bad_pc
    return cases


@pytest.mark.parametrize("label", list(broken_metrics()))
def test_incomplete_test_metrics_are_rejected(tmp_path, label):
    run = make_run(str(tmp_path))
    value = broken_metrics()[label]
    if value is None:
        rewrite(run, "test_metrics.json", raw="not json")
    else:
        rewrite(run, "test_metrics.json", value)
    with pytest.raises(ModelNotReady, match="test_metrics.json"):
        verify_run(run)
    assert Predictor().load(run) is False


def test_real_notebook_metrics_with_extra_fields_are_accepted(tmp_path):
    run = make_run(str(tmp_path))
    rewrite(run, "test_metrics.json", {**notebook_test_metrics(), "future_field": {"x": 1}})
    assert verify_run(run).temperature == 1.7


@pytest.mark.parametrize("name", ["config.json", "final.json", "class_mapping.json", "preprocessing.json"])
def test_broken_json_is_not_ready(tmp_path, name):
    run = make_run(str(tmp_path))
    rewrite(run, name, raw="{broken")
    with pytest.raises(ModelNotReady, match="not valid JSON"):
        verify_run(run)


# 3) Medium: calibration values.
@pytest.mark.parametrize("key, value", [
    ("temperature", True), ("temperature", float("nan")), ("temperature", float("inf")),
    ("temperature", float("-inf")), ("temperature", 0.0), ("temperature", 25.0), ("temperature", "1.5"),
    ("temperature", None),
    ("threshold", True), ("threshold", float("nan")), ("threshold", float("inf")), ("threshold", -0.1),
    ("threshold", 1.5), ("threshold", "0.5"), ("threshold", None),
])
def test_bad_calibration_is_rejected(tmp_path, key, value):
    run = make_run(str(tmp_path))
    rewrite(run, "final.json", raw=json.dumps({**read(run, "final.json"), key: value}))   # NaN/Infinity tokens
    with pytest.raises(ModelNotReady, match=key):
        verify_run(run)


@pytest.mark.parametrize("temperature, threshold", [(0.05, 0.0), (20.0, 1.0), (1, 0), (0.33, 0.95)])
def test_calibration_boundaries_are_accepted(tmp_path, temperature, threshold):
    run = make_run(str(tmp_path))
    rewrite(run, "final.json", {**read(run, "final.json"), "temperature": temperature, "threshold": threshold})
    info = verify_run(run)
    assert (info.temperature, info.threshold) == (float(temperature), float(threshold))


# 4) Low: Content-Length.
@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("FOOD_LENS_RUN_DIR", make_run(str(tmp_path)))
    with fastapi_testclient.TestClient(api.app, raise_server_exceptions=False) as c:
        yield c


@pytest.mark.parametrize("value, status, code", [
    ("9" * 5000, 400, "invalid_content_length"),
    ("1" + "0" * 19, 400, "invalid_content_length"),
    ("-1", 400, "invalid_content_length"),
    ("abc", 400, "invalid_content_length"),
    ("1e6", 400, "invalid_content_length"),
    ("\u00b2", 400, "invalid_content_length"),           # "²": str.isdigit() is True, int() fails
    (str(MAX_UPLOAD_BYTES + 1), 413, "file_too_large"),
    ("9" * 19, 413, "file_too_large"),
])
def test_content_length_header(client, value, status, code):
    r = client.post("/api/predict", content=b"x", headers={"content-length": value.encode("latin-1")})
    assert (r.status_code, r.json()["code"]) == (status, code)


def test_stream_limit_still_applies(client):
    r = client.post("/api/predict", content=iter([b"\0" * (1 << 20)] * 11))   # chunked, no Content-Length
    assert (r.status_code, r.json()["code"]) == (413, "file_too_large")
    assert client.post("/api/predict", content=image_bytes()).status_code == 200

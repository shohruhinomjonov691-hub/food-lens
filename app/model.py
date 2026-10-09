"""Loading a trained run and predicting. Until a verified run is loaded the API is not ready.

A run folder comes from notebooks/01_train_mobilenetv2.ipynb. It is accepted only if:
- config.json says smoke_test is exactly false,
- final.json names "best.pt" (the notebook contract), and the bytes of best.pt match the locked
  SHA-256 — the API then loads exactly those verified bytes,
- temperature (finite, 0.05–20, the fitting range) and threshold (finite, 0–1) are real numbers,
- test_metrics.json is a complete notebook test result (positive n, finite metrics in [0, 1]),
- class_mapping.json and the checkpoint use exactly food_lens.classes.CLASSES in the same order,
- preprocessing.json uses the same cache recipe ID and model-input spec as food_lens.preprocess.
Predictions use food_lens.preprocess.inference_tensor (the same steps as the test split), the locked
temperature and the locked "not sure" threshold.
"""
import hashlib
import io
import json
import math
import os
import re
from dataclasses import dataclass, field

import numpy as np

from food_lens import preprocess as pp
from food_lens.classes import CLASSES


class ModelNotReady(Exception):
    pass


CHECKPOINT_NAME = "best.pt"
TEMPERATURE_RANGE = (0.05, 20.0)   # food_lens.train_utils.fit_temperature search interval


@dataclass
class RunInfo:
    run_dir: str
    run_name: str
    checkpoint_sha256: str
    temperature: float
    threshold: float
    extra: dict = field(default_factory=dict)
    checkpoint_bytes: bytes = field(default=b"", repr=False)   # the verified bytes; dropped after loading


def _read_json(run_dir, name):
    path = os.path.join(run_dir, name)
    if not os.path.exists(path):
        raise ModelNotReady(f"{name} is missing in the run folder")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, UnicodeDecodeError):
        raise ModelNotReady(f"{name} is not valid JSON")
    if not isinstance(data, dict):
        raise ModelNotReady(f"{name} must be a JSON object")
    return data


def _real_number(value, name, low, high):
    """A finite int/float (not bool) within [low, high]."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or not low <= value <= high:
        raise ModelNotReady(f"{name} must be a finite number in [{low}, {high}], got {value!r}")
    return float(value)


def check_test_metrics(metrics):
    """Fields that notebooks/01_train_mobilenetv2.ipynb (cell 11) always writes; extra fields are fine."""
    n = metrics.get("n")
    if isinstance(n, bool) or not isinstance(n, int) or n <= 0:
        raise ModelNotReady("test_metrics.json: n must be a positive integer")
    for key in ("accuracy", "macro_f1"):
        _real_number(metrics.get(key), f"test_metrics.json {key}", 0.0, 1.0)
    if list(metrics.get("classes", [])) != list(CLASSES):
        raise ModelNotReady("test_metrics.json: classes do not match")
    cm = metrics.get("confusion_matrix")
    k = len(CLASSES)
    if not (isinstance(cm, list) and len(cm) == k and all(isinstance(r, list) and len(r) == k for r in cm)
            and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0 for r in cm for v in r)
            and sum(map(sum, cm)) == n):
        raise ModelNotReady("test_metrics.json: confusion_matrix must be KxK non-negative counts summing to n")
    per_class = metrics.get("per_class")
    if not isinstance(per_class, dict) or set(per_class) != set(CLASSES):
        raise ModelNotReady("test_metrics.json: per_class must cover every class")
    for c, v in per_class.items():
        if not isinstance(v, dict):
            raise ModelNotReady(f"test_metrics.json: per_class.{c} must be an object")
        for key in ("precision", "recall", "f1"):
            _real_number(v.get(key), f"test_metrics.json per_class.{c}.{key}", 0.0, 1.0)


def verify_run(run_dir):
    """Check a run folder without importing torch. Returns RunInfo or raises ModelNotReady."""
    if not run_dir or not os.path.isdir(run_dir):
        raise ModelNotReady("no trained model is configured (FOOD_LENS_RUN_DIR is not set or not a folder)")
    config = _read_json(run_dir, "config.json")
    if config.get("smoke_test") is not False:
        raise ModelNotReady("config.json must say smoke_test: false (smoke test or incomplete run)")
    final = _read_json(run_dir, "final.json")
    mapping = _read_json(run_dir, "class_mapping.json")
    prep = _read_json(run_dir, "preprocessing.json")
    if not os.path.exists(os.path.join(run_dir, "test_metrics.json")):
        raise ModelNotReady("the run has no test evaluation yet")
    check_test_metrics(_read_json(run_dir, "test_metrics.json"))
    if list(mapping.get("classes", [])) != list(CLASSES):
        raise ModelNotReady(f"class order {mapping.get('classes')} does not match {list(CLASSES)}")
    if prep.get("dataset_cache", {}).get("recipe_id") != pp.recipe_id():
        raise ModelNotReady("the run used a different image cache recipe")
    if prep.get("model_input", {}).get("spec") != pp.MODEL_INPUT:
        raise ModelNotReady("the run used a different model-input preprocessing")
    if final.get("checkpoint") != CHECKPOINT_NAME:
        raise ModelNotReady(f"final.json must name {CHECKPOINT_NAME!r} as the checkpoint")
    locked = final.get("checkpoint_sha256")
    if not (isinstance(locked, str) and re.fullmatch(r"[0-9a-f]{64}", locked)):
        raise ModelNotReady("final.json checkpoint_sha256 is not a SHA-256 hex digest")
    temperature = _real_number(final.get("temperature"), "temperature", *TEMPERATURE_RANGE)
    threshold = _real_number(final.get("threshold"), "threshold", 0.0, 1.0)
    path = os.path.join(run_dir, CHECKPOINT_NAME)
    if not os.path.isfile(path):
        raise ModelNotReady("checkpoint file is missing")
    with open(path, "rb") as f:
        data = f.read()
    digest = hashlib.sha256(data).hexdigest()
    if digest != locked:
        raise ModelNotReady("checkpoint does not match the SHA-256 locked in final.json")
    return RunInfo(run_dir, os.path.basename(os.path.normpath(run_dir)), digest, temperature, threshold,
                   checkpoint_bytes=data)


class Predictor:
    """Holds the loaded model, or the reason why there is none."""

    def __init__(self):
        self.info, self.model, self.reason = None, None, "not loaded"

    @property
    def ready(self):
        return self.model is not None

    def load(self, run_dir, torch_threads=2):
        self.info, self.model = None, None
        try:
            info = verify_run(run_dir)
            import torch
            from torch import nn
            from torchvision.models import mobilenet_v2

            torch.set_num_threads(torch_threads)
            # Exactly the bytes whose SHA-256 was verified — the file is not opened a second time.
            ckpt = torch.load(io.BytesIO(info.checkpoint_bytes), map_location="cpu", weights_only=True)
            if ckpt.get("arch") != "mobilenet_v2" or list(ckpt.get("classes", [])) != list(CLASSES):
                raise ModelNotReady("checkpoint architecture or classes do not match")
            model = mobilenet_v2(weights=None)
            model.classifier[1] = nn.Linear(model.last_channel, len(CLASSES))
            model.load_state_dict(ckpt["state_dict"], strict=True)
            model.eval()
        except ModelNotReady as exc:
            self.reason = str(exc)
            return False
        except Exception as exc:  # torch missing, broken checkpoint, ...
            self.reason = f"model could not be loaded: {type(exc).__name__}"
            return False
        info.checkpoint_bytes = b""
        self.info, self.model, self.reason = info, model, None
        return True

    def predict(self, image_bytes):
        """Validated image bytes -> top-3 calibrated probabilities and the 'not sure' flag."""
        if not self.ready:
            raise ModelNotReady(self.reason)
        import torch

        x = torch.from_numpy(pp.inference_tensor(image_bytes))[None]
        with torch.no_grad():
            logits = self.model(x).double().numpy()[0]
        z = logits / self.info.temperature
        probs = np.exp(z - z.max())
        probs /= probs.sum()
        order = np.argsort(-probs, kind="stable")[:3]
        top = [{"class": CLASSES[i], "confidence": round(float(probs[i]), 4)} for i in order]
        return {
            "predictions": top,
            "uncertain": bool(probs[order[0]] < self.info.threshold),
            "threshold": round(self.info.threshold, 4),
            "confidence": "calibrated probability (temperature scaling fitted on the validation split)",
        }

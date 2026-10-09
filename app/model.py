"""Loading a trained run and predicting. Until a verified run is loaded the API is not ready.

A run folder comes from notebooks/01_train_mobilenetv2.ipynb. It is accepted only if:
- it is not a smoke-test run (config.json),
- best.pt matches the SHA-256 locked in final.json,
- class_mapping.json and the checkpoint use exactly food_lens.classes.CLASSES in the same order,
- preprocessing.json uses the same cache recipe ID and model-input spec as food_lens.preprocess.
Predictions use food_lens.preprocess.inference_tensor (the same steps as the test split), the locked
temperature and the locked "not sure" threshold.
"""
import hashlib
import json
import os
from dataclasses import dataclass, field

import numpy as np

from food_lens import preprocess as pp
from food_lens.classes import CLASSES


class ModelNotReady(Exception):
    pass


@dataclass
class RunInfo:
    run_dir: str
    run_name: str
    checkpoint_sha256: str
    temperature: float
    threshold: float
    extra: dict = field(default_factory=dict)


def _read_json(run_dir, name):
    path = os.path.join(run_dir, name)
    if not os.path.exists(path):
        raise ModelNotReady(f"{name} is missing in the run folder")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def verify_run(run_dir):
    """Check a run folder without importing torch. Returns RunInfo or raises ModelNotReady."""
    if not run_dir or not os.path.isdir(run_dir):
        raise ModelNotReady("no trained model is configured (FOOD_LENS_RUN_DIR is not set or not a folder)")
    config = _read_json(run_dir, "config.json")
    if config.get("smoke_test"):
        raise ModelNotReady("the configured run is a smoke test, not a trained model")
    final = _read_json(run_dir, "final.json")
    mapping = _read_json(run_dir, "class_mapping.json")
    prep = _read_json(run_dir, "preprocessing.json")
    if not os.path.exists(os.path.join(run_dir, "test_metrics.json")):
        raise ModelNotReady("the run has no test evaluation yet")
    if list(mapping.get("classes", [])) != list(CLASSES):
        raise ModelNotReady(f"class order {mapping.get('classes')} does not match {list(CLASSES)}")
    if prep.get("dataset_cache", {}).get("recipe_id") != pp.recipe_id():
        raise ModelNotReady("the run used a different image cache recipe")
    if prep.get("model_input", {}).get("spec") != pp.MODEL_INPUT:
        raise ModelNotReady("the run used a different model-input preprocessing")
    path = os.path.join(run_dir, final.get("checkpoint", "best.pt"))
    if not os.path.exists(path):
        raise ModelNotReady("checkpoint file is missing")
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != final.get("checkpoint_sha256"):
        raise ModelNotReady("checkpoint does not match the SHA-256 locked in final.json")
    temperature, threshold = float(final["temperature"]), float(final["threshold"])
    if not (temperature > 0 and 0 <= threshold <= 1):
        raise ModelNotReady("invalid temperature or threshold in final.json")
    return RunInfo(run_dir, os.path.basename(os.path.normpath(run_dir)), h.hexdigest(), temperature, threshold)


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
            ckpt = torch.load(os.path.join(run_dir, "best.pt"), map_location="cpu", weights_only=True)
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

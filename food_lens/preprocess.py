"""Image preprocessing, versioned. Two separate stages:

1. DATASET CACHE (prepare once per image): original bytes -> `cache_image()` -> stored JPEG.
   Recipe `CACHE_RECIPE`: full decode with EXIF orientation and transparency on white
   (`food_lens.imaging.load_rgb`), resize so the shorter side is exactly 256 (bicubic, up or down),
   JPEG quality 95, 4:4:4. Every consumer decodes the *stored bytes*, so a freshly built (cold) cache
   and a reused (warm) cache give identical pixels. The recipe ID is part of every cache key.

2. MODEL INPUT (training eval, test and the inference API): `model_input(rgb)` -> float32 CHW tensor.
   Shorter side to 256 (bicubic; a no-op for cached images), center crop 224 (torchvision rounding),
   scale to [0, 1], normalize with ImageNet mean/std. It does not depend on where the image came from.
   `inference_tensor(bytes)` = cache stage + model input, so an uploaded photo goes through exactly
   the same steps as a dataset image.
"""
import hashlib
import io
import json
import os
import time

import numpy as np
from PIL import Image

from food_lens.imaging import load_rgb

CACHE_RECIPE = {
    "version": 1, "decode": "food_lens.imaging.load_rgb (EXIF orientation, alpha on white, RGB)",
    "short_side": 256, "resample": "BICUBIC", "format": "JPEG", "quality": 95, "subsampling": "4:4:4",
}
MODEL_INPUT = {
    "short_side": 256, "resample": "BICUBIC", "crop": 224, "crop_rounding": "torchvision CenterCrop",
    "scale": "uint8 / 255", "mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225],
    "layout": "float32 CHW, RGB",
}


def recipe_id(recipe=CACHE_RECIPE):
    return hashlib.sha256(json.dumps(recipe, sort_keys=True).encode()).hexdigest()[:16]


def resize_short_side(img, side, resample=Image.BICUBIC):
    """Shorter side -> `side`, longer side int(side * long / short) — the same sizes as torchvision Resize."""
    w, h = img.size
    if min(w, h) == side:
        return img
    if w <= h:
        size = (side, int(side * h / w))
    else:
        size = (int(side * w / h), side)
    return img.resize(size, resample)


def cache_image(data, recipe=CACHE_RECIPE):
    """Original image bytes -> cached JPEG bytes (stage 1)."""
    rgb = resize_short_side(load_rgb(data), recipe["short_side"])
    buf = io.BytesIO()
    rgb.save(buf, "JPEG", quality=recipe["quality"], subsampling=0)
    return buf.getvalue()


def decode_cached(data):
    with Image.open(io.BytesIO(data)) as im:
        return im.convert("RGB")


def center_crop(img, size):
    w, h = img.size
    left, top = int(round((w - size) / 2.0)), int(round((h - size) / 2.0))
    return img.crop((left, top, left + size, top + size))


def model_input(img, spec=MODEL_INPUT):
    """PIL RGB image -> normalized float32 CHW array (stage 2)."""
    img = center_crop(resize_short_side(img.convert("RGB"), spec["short_side"]), spec["crop"])
    x = np.asarray(img, dtype=np.float32) / 255.0
    x = (x - np.array(spec["mean"], dtype=np.float32)) / np.array(spec["std"], dtype=np.float32)
    return np.ascontiguousarray(x.transpose(2, 0, 1))


def inference_tensor(data):
    """Uploaded image bytes -> model input, through the same two stages as dataset images."""
    return model_input(decode_cached(cache_image(data)))


class CommonsCache:
    """Verified Commons images, stored with the cache recipe (one JPEG per sample + index.json).

    An entry is reused only if the manifest checksum of the original, the recipe ID and the SHA-256
    of the stored file all match; otherwise the original is fetched, verified and re-cached.
    `get()` always returns the stored bytes, cold or warm.
    """

    def __init__(self, root, checksum_ok, fetch, recipe=CACHE_RECIPE):
        self.root, self.checksum_ok, self.fetch = root, checksum_ok, fetch
        self.recipe, self.rid = recipe, recipe_id(recipe)
        os.makedirs(root, exist_ok=True)
        self.index_path = os.path.join(root, "index.json")
        index = {}
        if os.path.exists(self.index_path):
            with open(self.index_path, encoding="utf-8") as f:
                index = json.load(f)
        self.entries = index.get("entries", {})

    def path(self, sample_id):
        return os.path.join(self.root, f"{sample_id.replace(':', '_')}_{self.rid}.jpg")

    def get(self, row):
        sid, path = row["sample_id"], self.path(row["sample_id"])
        entry = self.entries.get(sid)
        if entry and entry.get("original_checksum") == row["checksum"] and entry.get("recipe_id") == self.rid \
                and os.path.exists(path):
            data = open(path, "rb").read()
            if hashlib.sha256(data).hexdigest() == entry["cached_sha256"]:
                return data, "warm"
        original = self.fetch(row["location"])
        if not self.checksum_ok(original, row["checksum"]):
            raise ValueError(f"Commons original does not match the manifest SHA-1: {sid} {row['location']}")
        data = cache_image(original, self.recipe)
        with open(path + ".tmp", "wb") as f:
            f.write(data)
        os.replace(path + ".tmp", path)
        self.entries[sid] = {"original_checksum": row["checksum"], "url": row["location"], "recipe_id": self.rid,
                             "cached_sha256": hashlib.sha256(data).hexdigest(),
                             "verified_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        self._save_index()
        return data, "cold"

    def _save_index(self):
        with open(self.index_path + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"recipe": self.recipe, "recipe_id": self.rid, "entries": self.entries}, f, indent=1,
                      sort_keys=True)
        os.replace(self.index_path + ".tmp", self.index_path)

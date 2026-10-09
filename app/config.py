"""API limits and settings. Values mirror the Face Blur API (CPU-only, conservative)."""
import os

MAX_UPLOAD_BYTES = 10 * 1024 * 1024   # 10 MB, as shown in the UI
MAX_PIXELS = 25_000_000               # 25 megapixels
MAX_SIDE = 8000                       # longest side in pixels
ACCEPTED_FORMATS = ("JPEG", "PNG", "WEBP")

# Folder of one training run (best.pt, final.json, class_mapping.json, preprocessing.json, config.json).
# Unset -> the API reports MODEL_NOT_READY; it never invents predictions.
RUN_DIR_ENV = "FOOD_LENS_RUN_DIR"
TORCH_THREADS = int(os.environ.get("FOOD_LENS_TORCH_THREADS", "2"))   # target server: 2 CPU

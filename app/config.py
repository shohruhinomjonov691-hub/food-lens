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

# Result tiers (see app/tiers.py). The "not sure" boundary is the threshold locked in final.json (fitted on the
# validation split). The "high" boundary was chosen a priori, NOT tuned on the test split; a run may lock its own
# value as final.json "high_threshold" (e.g. fitted on validation in the training notebook).
DEFAULT_HIGH_THRESHOLD = 0.80
# An image whose model input is this flat (standard deviation of the grey level, 0-255) shows nothing: not food.
FLAT_IMAGE_STD = 3.0

# Inference concurrency. Measured on the real model: 8 simultaneous requests took ~10 s each (one takes ~50 ms)
# because every request thread also runs torch threads. Requests beyond the running+waiting limit get 503 SERVER_BUSY.
MAX_CONCURRENT_PREDICTIONS = int(os.environ.get("FOOD_LENS_MAX_CONCURRENT", "2"))
MAX_WAITING_PREDICTIONS = int(os.environ.get("FOOD_LENS_MAX_WAITING", "8"))

# Optional extra analysis by a vision model (app/fallback.py). Off unless ANTHROPIC_API_KEY is set (and
# FOOD_LENS_FALLBACK is not "off"). The photo is sent to Anthropic ONLY when the user asks for it.
FALLBACK_ENV = "FOOD_LENS_FALLBACK"
# Default: the smallest, cheapest current model ($0.10 / $0.50 per million tokens): the task is one photo in, a few
# fixed JSON words out. Raise it (e.g. claude-sonnet-5-5) only if measured answers are not good enough. Keep in sync
# with compose.yaml (tested). Exact model IDs only, never date-suffixed.
DEFAULT_FALLBACK_MODEL = "claude-haiku-5-5"
FALLBACK_MODEL = os.environ.get("FOOD_LENS_FALLBACK_MODEL") or DEFAULT_FALLBACK_MODEL
FALLBACK_TIMEOUT_S = float(os.environ.get("FOOD_LENS_FALLBACK_TIMEOUT", "20"))
FALLBACK_MAX_PER_MINUTE = int(os.environ.get("FOOD_LENS_FALLBACK_MAX_PER_MINUTE", "10"))   # cost guard, whole service
FALLBACK_MAX_CONCURRENT = int(os.environ.get("FOOD_LENS_FALLBACK_MAX_CONCURRENT", "2"))
FALLBACK_MAX_IMAGE_BYTES = 5 * 1024 * 1024   # the vision API's per-image limit

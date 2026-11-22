"""Food Lens API. Uploaded images are validated and classified in memory only: never written to disk,
logs or a database.

The request body is read as raw bytes (not multipart/UploadFile), because Starlette's UploadFile spools
large uploads to a temporary file on disk. The browser crops the photo before uploading.

Endpoints
  GET  /health                         service status and whether a verified model is loaded
  POST /api/predict                    raw image bytes -> result tier (high | low | abstain | non_food) and, for
                                       high/low, the top-3 calibrated classes; 503 MODEL_NOT_READY while no trained
                                       run is configured; 503 SERVER_BUSY when too many requests are running
  POST /api/fallback                   raw image bytes -> extra analysis by a vision model, only on the user's request
                                       (status "used" | "unavailable"); needs ANTHROPIC_API_KEY
  GET  /api/evaluation                 test results of the loaded run (per class, per variant, tiers, limits)
  GET  /api/ingredients/{dish}         ?variant=…&lang=en|ko&avoid=halal,nuts -> typical ingredients with sources and,
                                       when `avoid` is given, the allergen/dietary guard for them
"""
import os
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app import guard
from app.config import (MAX_CONCURRENT_PREDICTIONS, MAX_UPLOAD_BYTES, MAX_WAITING_PREDICTIONS, RUN_DIR_ENV,
                        TORCH_THREADS)
from app.fallback import FallbackAnalyzer
from app.image_io import ImageError, validate_image
from app.ingredients import IngredientError, load_content, lookup
from app.limits import Busy, ConcurrencyGate
from app.model import ModelNotReady, Predictor
from food_lens.classes import CLASSES, VARIANTS

PREDICTOR = Predictor()
CONTENT = load_content()
ALLERGENS = guard.load_allergens(CONTENT)
FALLBACK = FallbackAnalyzer.from_env()
PREDICT_GATE = ConcurrencyGate(MAX_CONCURRENT_PREDICTIONS, MAX_WAITING_PREDICTIONS)


@asynccontextmanager
async def lifespan(app):
    PREDICTOR.load(os.environ.get(RUN_DIR_ENV), TORCH_THREADS)
    yield


app = FastAPI(title="Food Lens", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def error(status_code, code, detail):
    return JSONResponse(status_code=status_code, content={"code": code, "detail": detail})


@app.exception_handler(ImageError)
async def image_error_handler(request: Request, exc: ImageError):
    return error(exc.status_code, exc.code, exc.message)


@app.exception_handler(IngredientError)
async def ingredient_error_handler(request: Request, exc: IngredientError):
    return error(exc.status_code, exc.code, exc.message)


@app.exception_handler(Busy)
async def busy_handler(request: Request, exc: Busy):
    response = error(503, "SERVER_BUSY", "Too many photos are being analyzed right now. Please try again in a moment.")
    response.headers["Retry-After"] = "2"
    return response


@app.exception_handler(ModelNotReady)
async def not_ready_handler(request: Request, exc: ModelNotReady):
    return error(503, "MODEL_NOT_READY", str(exc))


CONTENT_LENGTH = re.compile(r"[0-9]{1,19}")   # ASCII digits only; 19 digits fit a signed 64-bit integer


async def read_limited_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None:
        # Checked before int(): a malformed, negative or absurdly long value is a client error (400),
        # never an exception inside the server; a well-formed value above the limit is 413.
        if not CONTENT_LENGTH.fullmatch(declared.strip()):
            raise ImageError(400, "invalid_content_length", "The Content-Length header is not a valid length.")
        if int(declared) > MAX_UPLOAD_BYTES:
            raise ImageError(413, "file_too_large", f"The file must be at most {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_UPLOAD_BYTES:
            raise ImageError(413, "file_too_large", f"The file must be at most {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    return bytes(body)


@app.get("/health")
def health():
    info = PREDICTOR.info
    return {
        "status": "ok",
        "model_ready": PREDICTOR.ready,
        "model_reason": PREDICTOR.reason,
        "model": {"run": info.run_name, "checkpoint_sha256": info.checkpoint_sha256,
                  "temperature": info.temperature, "threshold": info.threshold,
                  "high_threshold": info.high_threshold} if info else None,
        "classes": list(CLASSES),
        "variants": {k: list(v) for k, v in VARIANTS.items()},
        "restrictions": list(ALLERGENS["restrictions"]),
        "fallback_available": FALLBACK.configured,
    }


@app.post("/api/predict")
async def predict(request: Request):
    if not PREDICTOR.ready:
        raise ModelNotReady(PREDICTOR.reason)
    data = await read_limited_body(request)
    async with PREDICT_GATE:                      # at most a few at once; the rest wait briefly or get 503
        await run_in_threadpool(validate_image, data)
        result = await run_in_threadpool(PREDICTOR.predict, data)
    return {**result, "model": {"run": PREDICTOR.info.run_name, "checkpoint_sha256": PREDICTOR.info.checkpoint_sha256},
            "variant": None, "fallback_available": FALLBACK.configured,
            "variant_note": "The model predicts the class only; for kebab and dessert the user chooses the kind."}


@app.post("/api/fallback")
async def fallback(request: Request):
    """Extra analysis, only when the user asks. A provider problem is a normal answer (status "unavailable"), so the
    page keeps the earlier result; a bad image is still a client error."""
    data = await read_limited_body(request)
    # Decoding a photo (up to 25 Mpx) costs the same CPU and memory here as in /api/predict, so it goes through the same
    # gate: a few at once, a short queue, then 503. Only the decode holds a slot; waiting for the provider does not.
    async with PREDICT_GATE:
        fmt = await run_in_threadpool(validate_image, data)
    return await FALLBACK.analyze(data, fmt)


@app.get("/api/evaluation")
def evaluation():
    if not PREDICTOR.ready:
        raise ModelNotReady(PREDICTOR.reason)
    return PREDICTOR.info.evaluation


@app.get("/api/ingredients/{dish}")
def ingredients(dish: str, variant: str | None = None, lang: str = "en", avoid: str | None = None):
    result = lookup(CONTENT, dish, variant, lang)
    ids = guard.parse_avoid(avoid, ALLERGENS)
    result["guard"] = guard.evaluate(ALLERGENS, CONTENT, dish, variant, lang, ids) if ids else None
    return result

"""Food Lens API. Uploaded images are validated and classified in memory only: never written to disk,
logs or a database.

The request body is read as raw bytes (not multipart/UploadFile), because Starlette's UploadFile spools
large uploads to a temporary file on disk. The browser crops the photo before uploading.

Endpoints
  GET  /health                         service status and whether a verified model is loaded
  POST /api/predict                    raw image bytes -> top-3 calibrated classes + "not sure" flag,
                                       or 503 MODEL_NOT_READY while no trained run is configured
  GET  /api/ingredients/{dish}         ?variant=…&lang=en|ko -> typical ingredients with sources
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.config import MAX_UPLOAD_BYTES, RUN_DIR_ENV, TORCH_THREADS
from app.image_io import ImageError, validate_image
from app.ingredients import IngredientError, load_content, lookup
from app.model import ModelNotReady, Predictor
from food_lens.classes import CLASSES, VARIANTS

PREDICTOR = Predictor()
CONTENT = load_content()


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


@app.exception_handler(ModelNotReady)
async def not_ready_handler(request: Request, exc: ModelNotReady):
    return error(503, "MODEL_NOT_READY", str(exc))


async def read_limited_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
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
                  "temperature": info.temperature, "threshold": info.threshold} if info else None,
        "classes": list(CLASSES),
        "variants": {k: list(v) for k, v in VARIANTS.items()},
    }


@app.post("/api/predict")
async def predict(request: Request):
    if not PREDICTOR.ready:
        raise ModelNotReady(PREDICTOR.reason)
    data = await read_limited_body(request)
    await run_in_threadpool(validate_image, data)
    result = await run_in_threadpool(PREDICTOR.predict, data)
    return {**result, "model": {"run": PREDICTOR.info.run_name, "checkpoint_sha256": PREDICTOR.info.checkpoint_sha256},
            "variant": None,
            "variant_note": "The model predicts the class only; for kebab and dessert the user chooses the kind."}


@app.get("/api/ingredients/{dish}")
def ingredients(dish: str, variant: str | None = None, lang: str = "en"):
    return lookup(CONTENT, dish, variant, lang)

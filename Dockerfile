# Food Lens inference API — production image. Build context: the repository root (see .dockerignore, an allowlist).
# The trained run (best.pt and its JSON files) is NOT in the image: compose.yaml mounts it read-only from outside the
# repository and FOOD_LENS_RUN_DIR points at it. Without it the API reports MODEL_NOT_READY and the container is
# unhealthy; it never returns invented predictions.
# Tag and digest are pinned; update both together.
FROM python:3.13.16-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv/food-lens

COPY deploy/requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY app ./app
COPY food_lens ./food_lens
COPY config/classes.json ./config/classes.json
COPY content ./content
COPY LICENSE NOTICE.md ./

# Unprivileged user; the image needs no write access at runtime (run with a read-only root filesystem).
# The model mount point exists in the image, so `docker diff` of a running container stays empty.
RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin app \
 && mkdir -p /run/food-lens-model
USER 10001:10001

ENV FOOD_LENS_RUN_DIR=/run/food-lens-model \
    FOOD_LENS_TORCH_THREADS=2

EXPOSE 8000
# Healthy only when the verified model is loaded (model_ready), not merely when the process is up.
HEALTHCHECK --interval=30s --timeout=3s --start-period=30s --retries=3 \
  CMD ["python", "-c", "import json, sys, urllib.request; r = urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2); sys.exit(0 if r.status == 200 and json.load(r).get('model_ready') is True else 1)"]

# 0.0.0.0 inside the container only; compose publishes the port on 127.0.0.1 for the host's Nginx.
# One worker: the model is loaded once and inference uses FOOD_LENS_TORCH_THREADS threads.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header", "--workers", "1"]

# Food Lens

Upload a food photo, get the top-3 dish predictions with confidence, an "uncertain" answer below a
calibrated threshold and, after you confirm the dish, its **typical** ingredients with sources (not
the ingredients detected in the photo).

**Live demo: <https://food.gotrips.cloud>** — MVP complete (5 classes, EN/KO).

Status (2026-10-14): one MobileNetV2 model trained in Colab (2026-10-09) and evaluated once on the
held-out test split — accuracy **0.935**, macro-F1 **0.928** (n = 806; see
[Evaluation](#evaluation-run-20261009t124948z_9ab1801_seed42)). The FastAPI + Next.js app runs in Docker
behind Nginx and was deployed publicly on 2026-10-10. The trained weights and the dataset images are
**not** published. Whether Food-101 permits a public demo is still an open question — see
[Licenses](#licenses); deploying it was the project owner's decision and does not settle it.

## Classes

Fixed order (model output index), from [`config/classes.json`](config/classes.json):

| Index | Class | Sources |
| --- | --- | --- |
| 0 | `dessert` | Food-101 `cheesecake` + `chocolate_cake` |
| 1 | `hamburger` | Food-101 `hamburger` |
| 2 | `hot_dog` | Food-101 `hot_dog` |
| 3 | `kebab` | Wikimedia Commons, three variants: skewered pieces (shish/shashlik), minced on skewers (Adana/koobideh/seekh), döner/shawarma |
| 4 | `pizza` | Food-101 `pizza` |

The model predicts the class only. `kebab` and `dessert` group several dishes, so the app shows
typical ingredients **per variant the user picks** (never one merged list, and never as the contents
of the photo). Variants are recorded per image in the manifest and used for stratified splitting.

Plov/pilaf is out of scope. Calories, allergens and detecting the exact contents of a photo are out of
scope.

## Data

**No images are stored in this repository** (see `.gitignore`). The manifests list each image by
location and checksum:

| File | Content |
| --- | --- |
| `manifests/manifest_v1.csv` | Training images: source, class, location, checksum, perceptual hash, near-duplicate group, split, license/author for Commons |
| `manifests/exclusions_v1.csv` | Every file left out and why |
| `manifests/stats_v1.json` | Counts per class/split, duplicate statistics, provenance result |
| `manifests/kebab_commons.csv` | Accepted Commons kebab files: page, original URL, sha1, author, license |
| `manifests/kebab_commons_review.csv` | Decision for every Commons candidate (accepted / rejected + reason) |

Locations: Food-101 rows are paths relative to the private Drive copy `MyDrive/food101_dataset`;
Commons rows are `upload.wikimedia.org` URLs, verified by the Commons sha1 when downloaded.

### Licenses

- **Food-101** (Bossard, Guillaumin, Van Gool, ECCV 2014, ETH Zurich). The archive's
  `license_agreement.txt`: the images come from Foodspotting, are not the property of ETH Zurich, and
  "any use beyond scientific fair use must be negociated with the respective picture owners according
  to the Foodspotting terms of use". The ETH dataset page and the Hugging Face card (`ethz/food101`,
  license "unknown") add no other terms. Foodspotting's terms of service — archived copy
  <https://web.archive.org/web/20141230063229/http://www.foodspotting.com/terms> (captured 2014-12-30,
  "Effective on October 17, 2012") — say users keep the copyright of their photos, the service and its
  content are for personal, non-commercial use, and content may not be used without written permission
  from Foodspotting or the original license holder. The Foodspotting website is no longer reachable
  (on 2026-10-10 `foodspotting.com` and `www.foodspotting.com` had no address records); no permission
  was requested. Provenance: the Drive copy is compared byte-for-byte with the
  official archive (`scripts/food101_provenance.py`). Assessment of the three uses (not legal advice):

  | Use | Status | Basis |
  | --- | --- | --- |
  | Redistributing Food-101 images | **Redistribution permission not established** — not redistributed | Third-party copyright; no text grants it; the archived terms require written permission for copying or distributing content |
  | Publishing the trained weights | **Not covered** — not done | The texts do not address models; nothing grants it, so it is not assumed |
  | Public inference service (food.gotrips.cloud) | **Open** — deployed publicly on 2026-10-10 by the project owner's decision | The model is derived from the images; a public demo is not clearly "scientific fair use" and no text permits it. The deployment is a risk decision, not evidence of permission |

  Ways to settle it: ask the Food-101 authors (ETH) about a non-commercial demo of a trained model; get
  legal advice; or retrain the four Food-101 classes on images with verified open licenses (as was done
  for kebab). None of these has been done. The service returns class probabilities only; it does not
  show or distribute Food-101 images or the weights.
- **Wikimedia Commons** kebab photos: each file keeps its own license (CC0 / public domain / CC BY /
  CC BY-SA) and author, recorded per file in `manifests/kebab_commons.csv`. Attribution is required
  wherever these images are shown (the app shows none).
- The earlier Bing-scraped kebab images are **not used**: their licenses could not be verified.

### Dataset v1 (manifest_v1, seed 42)

| Class / variant | Train | Val | Test | Total |
| --- | ---: | ---: | ---: | ---: |
| dessert / cheesecake | 700 | 150 | 150 | 1000 |
| dessert / chocolate_cake | 698 | 150 | 150 | 998 |
| hamburger | 698 | 150 | 150 | 998 |
| hot_dog | 697 | 150 | 150 | 997 |
| kebab / skewered | 157 | 34 | 34 | 225 |
| kebab / minced_skewer | 58 | 13 | 13 | 84 |
| kebab / doner_shawarma | 41 | 9 | 9 | 59 |
| pizza | 699 | 150 | 150 | 999 |
| **Total** | **3748** | **806** | **806** | **5360** |

Food-101 part: 5000 Drive files, all byte-identical to the official archive
([`manifests/food101_provenance_v1.json`](manifests/food101_provenance_v1.json)); 8 removed (6 near
copies, 2 copies of an event flyer). Kebab: 368 Commons photos (370 accepted after review, minus 2
crops of other accepted files); every candidate was looked at, and re-checks are recorded next to
the first decision in `manifests/kebab_commons_review.csv`. `manifests/stats_v1.json` → `quota_check`
shows target vs actual val/test per variant and the per-variant minimum (9).

## Data preparation

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python scripts/food101_provenance.py --review-list data/review_ids.txt   # streams ~5 GB, saves only hashes
.venv/bin/python scripts/commons_kebab.py                                          # Commons: skewered + minced kebabs
.venv/bin/python scripts/commons_kebab.py --pass doner --append                    # Commons: döner/shawarma (no re-download)
.venv/bin/python scripts/build_kebab_manifest.py queue                             # automatic checks + contact sheets
.venv/bin/python scripts/build_kebab_manifest.py mark <sheet> --reject <sheet>:<cells>:<code>   # record a manual review
.venv/bin/python scripts/build_kebab_manifest.py finalize                          # apply config/kebab_review.json
.venv/bin/python scripts/prepare_manifest.py                                       # manifest, exclusions, stats
.venv/bin/python -m pytest
```

Inputs not in Git: `audit/files.csv` (output of `notebooks/00_dataset_audit.ipynb`, run read-only in
Colab) and `data/` (provenance hashes, Commons thumbnails).

Rules:

- one graph over the full candidate set, built **before** manual exclusion and dedup, with two
  thresholds: duplicate components (same checksum, or pHash ≤ 2 in one class) decide removal; split
  groups (pHash ≤ 8 in any class, derived pairs, one group per canonical author ID and variant for
  Commons) decide what stays together; keepers inherit the original groups, and a group is never split;
- unreadable files out; a manual exclusion removes its whole duplicate component (transitively);
- exact and near duplicates keep one copy (smallest location) per duplicate component;
- derived Commons files (crops, retouches) are listed in `config/data_prep.json`; a copy whose
  original stays is removed; a copy whose original is excluded or missing needs a manual exclusion or
  a `derived_reviewed` entry with evidence; an unlisted file with crop/retouch/derived hints in title,
  credit or author stops the build;
- author IDs: crop credits, "(talk)" and "at … Wikipedia" are dropped and the full uploader name is
  kept; anything else (e.g. "Name from City") is merged only through an evidenced `author_aliases` entry;
- cross-class near-duplicates need an explicit decision in `config/data_prep.json`;
- split: seed 42, 70/15/15 per variant; a group goes to val/test only if its variant-count vector fits
  the remaining quota of every variant in it; shortfalls are reported, never forced.
- the build is deterministic: the same inputs in any order give byte-identical outputs.

## Training (batch 3) — `notebooks/01_train_mobilenetv2.ipynb`

Colab notebook. Run once for real on 2026-10-09 (Tesla T4, torch 2.11.0+cu130, bundle `9ab1801`);
results in [Evaluation](#evaluation-run-20261009t124948z_9ab1801_seed42). Steps to reproduce:

1. `python scripts/make_colab_bundle.py` → `dist/food_lens_bundle_<commit>.zip` (code + manifest, no
   images; SHA-256 per file and the git commit in `BUNDLE.json`; refuses a dirty tree).
2. Upload the zip to `MyDrive/food-lens/bundles/`, set `BUNDLE_ZIP` in cell 1.
3. Run all cells with `SMOKE_TEST = True` (synthetic data; must end with `SMOKE TEST PASSED`), then
   with `SMOKE_TEST = False` on a GPU runtime.

What it does: verifies Food-101 files (read-only, SHA-256) and Commons originals (downloaded from
`upload.wikimedia.org`, SHA-1 of the original); MobileNetV2 (ImageNet weights), train augmentation,
class-weighted loss, seed 42; best checkpoint by val macro-F1; temperature (exact log-sum-exp NLL,
interval ends included) and "not sure" threshold fitted on val; `final.json` locks the choice before
the test split is used once, and once a run is locked no checkpoint or history can be written to it.

Preprocessing ([`food_lens/preprocess.py`](food_lens/preprocess.py)) has two separate, versioned stages:

1. **Dataset cache** (`cache_image`, recipe `CACHE_RECIPE`, ID in every cache key): decode with EXIF
   orientation and transparency on white → shorter side exactly 256 (bicubic, torchvision sizes) →
   JPEG q95 4:4:4. Commons images are stored once in `MyDrive/food-lens/commons_cache`
   (`index.json`: original SHA-1, recipe ID, stored SHA-256); training always decodes the stored bytes,
   so a fresh and a reused cache give identical pixels.
2. **Model input** (`model_input`, spec `MODEL_INPUT`): shorter side 256 → center crop 224 →
   [0, 1] → ImageNet mean/std, float32 CHW — the same for val, test and inference, whatever the source.
   `inference_tensor(upload bytes)` applies stage 1 + stage 2, so an uploaded photo is processed exactly
   like a test image. Train augmentation (RandomResizedCrop, flip, ColorJitter) works on the stage-1 image. Each run writes a new folder
`MyDrive/food-lens/runs/<UTC>_<commit>_seed42` (config, class mapping, preprocessing, checkpoint,
history, calibration, val/test metrics, confusion matrix, per-variant results, predictions).
Checkpoints stay private until the Food-101 public-use question is settled.

## Inference API (batch 4) and ingredients (batch 5) — `app/`

```bash
.venv/bin/pip install -e '.[api,dev]'
FOOD_LENS_RUN_DIR=/path/to/runs/<run> .venv/bin/uvicorn app.main:app --port 8000
```

| Endpoint | Result |
| --- | --- |
| `GET /health` | `status`, `model_ready`, `model_reason`, loaded run + checkpoint SHA-256, classes, variants |
| `POST /api/predict` (raw image bytes) | `predictions`: top-3 `{class, confidence}` (calibrated: locked temperature), `uncertain` (top-1 < locked threshold), `threshold`, `variant: null` |
| `GET /api/ingredients/{dish}?variant=…&lang=en\|ko` | typical ingredients, disclaimer, sources; kebab/dessert need the user's `variant` |

- **No verified run folder** (`FOOD_LENS_RUN_DIR` unset or failing the checks below) → `/api/predict`
  answers **503 `MODEL_NOT_READY`** with the reason; it never returns placeholder predictions. A run folder is loaded only if `config.json` has `smoke_test: false`;
  `test_metrics.json` is a complete notebook result (positive `n`, finite metrics in [0, 1],
  confusion matrix summing to `n`); `final.json` names `best.pt`, whose bytes match the locked SHA-256
  (those exact bytes are loaded, `weights_only=True`); temperature is a finite number in [0.05, 20]
  and the threshold in [0, 1]; classes are `config/classes.json` in the same order; and the
  preprocessing recipe/spec equal `food_lens/preprocess.py`. Broken JSON → `MODEL_NOT_READY`.
- `Content-Length` must be 1–19 ASCII digits (else 400 `invalid_content_length`); above 10 MB → 413;
  the streamed body is limited as well.
- Prediction uses `food_lens.preprocess.inference_tensor` — the same steps as the test split.
- Upload validation (in memory, like Face Blur): raw body (no multipart spooling), ≤ 10 MB, real
  format by magic bytes (JPEG, PNG, WebP), ≤ 8000 px side and ≤ 25 MP checked from the header before
  decoding, full decode (truncated/corrupt → 422), animated images rejected. Images are never written
  to disk or logs; errors return stable `code`s for the UI.
- The model predicts the class only. For **kebab** (skewered / minced on skewers / döner-shawarma) and
  **dessert** (cheesecake / chocolate cake) the user picks the kind, and the ingredient list is per kind.
- `content/ingredients.json`: EN + KO lists, each with the English Wikipedia articles read on
  2026-10-09 and what each source supports; Korean is a translation (source language: English).
  Disclaimer: "Typical ingredients; not identified from your photo."
- Latency and memory: see [Deployment](#deployment--composeyaml-dockerfile-webdockerfile-deploy).

## Frontend (batch 6) — `web/` (Next.js 16.3.8, React 19.3.0, TypeScript)

```bash
cd web && npm ci
npm test            # vitest (unit + component tests with mocked API)
npm run build && FOOD_LENS_API_URL=http://127.0.0.1:8000 npm start   # proxies /api/* to the FastAPI service
```

Flow (warm light theme from `design/food-lens/`, EN default + KO saved in `localStorage` `fl.lang`):
upload (JPEG/PNG/WebP, ≤ 10 MB, magic bytes and dimensions checked in the browser) → crop (drag the
frame or corners, keyboard arrows, reset, rotate) → **Analyze sends exactly the confirmed crop** (JPEG,
longest side ≤ 2048 px) → top-3 or "not sure" from the API → the user confirms (or picks) the dish →
kebab/dessert: the user must pick the kind (nothing preselected) → typical ingredients with sources
and "Typical ingredients; not identified from your photo".

- States: empty, reading, crop, analyzing, result, not sure, **MODEL_NOT_READY** (no verified model loaded:
  no numbers are shown; the user can still pick a dish for its ingredients), invalid file, server and
  network errors, ingredient loading/error.
- Async safety: every photo/crop/analysis has a sequence number and an `AbortController`; a late
  prediction or ingredient answer for an older choice is aborted and ignored.
- Object URLs (photo, rotated photo, sent crop) are revoked when no longer shown and on unmount;
  canvases are released after export.
- No mock or demo data in `src/` or `app/` (tested). `web/tests/e2e/mock-api.mjs` is a **test-only**
  mock used for browser checks of UI states; its numbers are fixtures, not model results.

## Deployment — `compose.yaml`, `Dockerfile`, `web/Dockerfile`, `deploy/`

Deployed on 2026-10-10 at <https://food.gotrips.cloud> from commit `e681f1b` (later commits change
documentation only), on an Ubuntu 24.04 x86_64 server (2 vCPU, 8 GB) that also hosts other apps, behind
its existing Nginx 1.24 with a Let's Encrypt certificate (webroot). Steps and checks: `deploy/nginx/README.md`.

Two containers in the Compose project `food-lens`. The API is FastAPI with CPU-only PyTorch; the web
container is Next.js standalone. Both images are built on pinned base images, run as non-root uid 10001
with a read-only root filesystem and `cap_drop: ALL`, `no-new-privileges`, memory/CPU/pids limits, a
healthcheck and json-file log rotation. They listen only on `127.0.0.1:18776` (api) and
`127.0.0.1:18775` (web).

- The trained run folder is **mounted read-only from outside the repository** (`FOOD_LENS_RUN_DIR_HOST`,
  required). Images never contain the model. The API healthcheck passes only when the verified model
  is loaded.
- One domain: Nginx routes `/api/` to the API and everything else to the web app. The browser only uses
  relative `/api/...` URLs. The web image's own `/api` rewrite points at `http://api:8000`, set at build
  time. The smoke test checks that no loopback or internal URL is in the browser assets.
- `deploy/nginx/`: site templates for Nginx 1.24 (`conf.d/food-lens.conf`, no `http2`, certbot
  webroot), proxy snippet (no temp files for uploads), `check-config.sh`, and a step-by-step README.
- `deploy/smoke/check.sh`: both containers plus Nginx 1.24 locally, with a real run folder and photo.

```bash
FOOD_LENS_RUN_DIR_HOST=/abs/path/to/run docker compose up -d --build --wait
deploy/nginx/check-config.sh
FOOD_LENS_RUN_DIR_HOST=/abs/path/to/run SMOKE_IMAGE=/abs/photo.jpg SMOKE_EXPECT=pizza deploy/smoke/check.sh
```

Measured on the **production server** (2026-10-10; the commands were run on the server by the owner and
the output was reported back): HTTP from inside the API container to itself, synthetic JPEGs, 8 warm-up
+ 60 sequential requests, `cpus: 2`, 2 torch threads; Nginx and the internet are not included.

| Input | p50 | p95 |
| --- | ---: | ---: |
| 2048×1536 (largest crop the web app sends) | 114 ms | 129 ms |
| 864×648 (typical crop) | 39 ms | 50 ms |
| 512×384 | 34 ms | 43 ms |

Memory peak (cgroup): API 348 MiB of its 1 GiB limit, web 76 MiB of 512 MiB. Concurrent load was not
measured. Production checks after deploy: HTTPS 200, HTTP → 301, Nginx wrote no request temp files,
`docker diff` of the API container empty. A phone test of the full flow on the live site was done by
the owner (user report, not independently verified).

## Evaluation (run `20261009T124948Z_9ab1801_seed42`)

**Model and data.** torchvision MobileNetV2 (ImageNet `IMAGENET1K_V2` initialisation), 224×224 input,
3 head-only epochs then 15 fine-tuning epochs (AdamW, cosine schedule), class-weighted cross-entropy,
seed 42. Data: dataset v1 above — 3748 train / 806 val / 806 test images, split per variant with
near-duplicate groups and Commons author series kept within one split.

**Model selection and calibration (val only).**
- Best epoch by val macro-F1: epoch 15 of 18 (val accuracy 0.943, macro-F1 0.941).
- Temperature scaling: T = 1.627; val ECE 0.034 → 0.018, NLL 0.236 → 0.199.
- "Not sure" threshold 0.462: the lowest one with val selective accuracy ≥ 0.95 (0.951 at coverage 0.989).
- Both were locked in `final.json` before the test split was used, once.

**Test (n = 806), with bootstrap 95% CI (1000 resamples):**

| Metric | Value |
| --- | --- |
| Accuracy | 0.935 (0.918–0.953) |
| Macro-F1 | 0.928 (0.907–0.947) |
| At the threshold | "not sure" for 1.5%; accuracy 0.945 on the remaining 98.5% |

| Class | Precision | Recall | F1 | n |
| --- | ---: | ---: | ---: | ---: |
| dessert | 0.936 | 0.977 | 0.956 | 300 |
| hamburger | 0.951 | 0.913 | 0.932 | 150 |
| hot_dog | 0.892 | 0.880 | 0.886 | 150 |
| kebab | 0.926 | 0.893 (CI 0.807–0.978) | 0.909 | 56 |
| pizza | 0.966 | 0.947 | 0.956 | 150 |

Kebab and dessert variants (recall; the model predicts the class, not the variant):

| Variant | n | Recall | Misclassified as |
| --- | ---: | ---: | --- |
| dessert / cheesecake | 150 | 0.967 | hot_dog 2, pizza 3 |
| dessert / chocolate_cake | 150 | 0.987 | kebab 1, pizza 1 |
| kebab / skewered | 34 | 0.941 | dessert 2 |
| kebab / minced_skewer | **13** | 0.769 | dessert 3 |
| kebab / doner_shawarma | **9** | 0.889 | hot_dog 1 |

The largest confusions are hot_dog → dessert (9), hamburger → hot_dog (8), hot_dog → hamburger (5),
pizza → hot_dog (5) and kebab → dessert (5). The two small kebab variants are reported for completeness; with 9 and 13 images
their recall is not a reliable estimate.

**Not evaluated:** the planned full-frame vs. cropped comparison and a **phone challenge set** (the
owner's own phone photos, never used for training or tuning) have not been run, so performance on real
phone photos and the Commons/Food-101 source gap are not measured. Checks done so far are anecdotal: a
few local photos through the live app and the local stack.

## Known limitations

- **Five classes only.** Any other dish is forced into one of them.
- **Non-food or out-of-distribution images are not reliably rejected.** The "not sure" threshold was
  fitted on in-distribution val images; a photo of a text page was classified as dessert at 48%, above
  the threshold (local check). There is no "not food" detector.
- **Crop-sensitive.** The same photo can score very differently with and without cropping to the dish
  (one hamburger test photo: 43% uncropped, 82% cropped). The app asks the user to crop.
- **Source gap.** Kebab comes from Wikimedia Commons, the other classes from Food-101; photo style,
  background and framing differ, so the model can learn source cues instead of the dish. Resizing to
  the same resolution does not remove this, and it has not been measured (no phone challenge set yet).
- **Ingredients are not detected from the photo.** They are typical ingredients of the confirmed dish
  and variant, from Wikipedia; the app says so.
- **Small subgroups.** Kebab test has 56 images (minced on skewers 13, döner/shawarma 9), so kebab and
  variant metrics have wide uncertainty.
- Food-101 training images were intentionally not cleaned by their authors and contain some label noise.
- `dessert` has about twice as many images as the other Food-101 classes, and `kebab` (368) about a
  third; training uses class weights and reports macro-F1 and per-class recall.
- Commons photos are grouped by author within a variant, so one photographer's series never spans
  train and test. Food-101 has no author information.
- Food-101 public-use terms are unresolved (see [Licenses](#licenses)); the weights stay private.

## Layout

```
config/       classes.json, data_prep.json, kebab_review.json
food_lens/    classes, imaging (load/EXIF/alpha, pHash), dedup, split, manifest validation
scripts/      provenance, Commons collection, kebab review, manifest build
manifests/    generated manifests (no images)
notebooks/    00_dataset_audit.ipynb (read-only Drive audit), 01_train_mobilenetv2.ipynb (training, Colab)
design/       food-lens mockup (EN/KO, warm light theme)
tests/        pytest
app/          FastAPI inference API; content/ ingredients
web/          Next.js frontend (own Dockerfile)
deploy/       API requirements, Nginx templates, local smoke test
```

# Food Lens

Upload a food photo, get the top-3 dish predictions with confidence, an "uncertain" answer below a
calibrated threshold and, after you confirm the dish, its **typical** ingredients with sources (not
the ingredients detected in the photo).

Status: batch 1–2 (repository skeleton and data preparation). No model has been trained yet; there
are no published metrics. The old 89.45% validation figure from the earlier `computer_vision`
notebook is a different, unseeded 6-class run and is not used here.

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
  license "unknown") add no other terms. Foodspotting's terms (archived copy, effective 2012-10-17) say
  users keep the copyright of their photos and allow use of content only for personal, non-commercial
  purposes or with written permission. Foodspotting no longer exists (`foodspotting.com` does not resolve), so
  permission cannot be obtained from it. Provenance: the Drive copy is compared byte-for-byte with the
  official archive (`scripts/food101_provenance.py`). Assessment of the three uses (not legal advice):

  | Use | Status | Basis |
  | --- | --- | --- |
  | Redistributing Food-101 images | **Not allowed** — not done | Third-party copyright; beyond scientific fair use; the terms forbid copying and distribution |
  | Publishing the trained weights | **Not covered** — not done | The texts do not address models; nothing grants it, so it is not assumed |
  | Public inference service (food.gotrips.cloud) | **Open** — not deployed | The model is derived from the images; a public demo is not clearly "scientific fair use" and no text permits it |

  Paths, from least extra work: (a) no public launch; the deploy files stay ready and the demo runs
  locally or for reviewers; (b) an access-restricted, non-commercial demo (Nginx basic auth, no weights
  or images distributed), which narrows exposure but is still not an explicit permission; (c) retrain
  the four Food-101 classes on images with verified open licenses (as was done for kebab), after which
  a public service has a documented basis. The decision belongs to the project owner.
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

Colab notebook; training has not been run yet.

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

- **No trained model yet** → `/api/predict` answers **503 `MODEL_NOT_READY`** with the reason; it never
  returns placeholder predictions. A run folder is loaded only if `config.json` has `smoke_test: false`;
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
- Not measured yet: latency/RAM on the 2-CPU server (needs the trained checkpoint).

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

- States: empty, reading, crop, analyzing, result, not sure, **MODEL_NOT_READY** (no trained model:
  no numbers are shown; the user can still pick a dish for its ingredients), invalid file, server and
  network errors, ingredient loading/error.
- Async safety: every photo/crop/analysis has a sequence number and an `AbortController`; a late
  prediction or ingredient answer for an older choice is aborted and ignored.
- Object URLs (photo, rotated photo, sent crop) are revoked when no longer shown and on unmount;
  canvases are released after export.
- No mock or demo data in `src/` or `app/` (tested). `web/tests/e2e/mock-api.mjs` is a **test-only**
  mock used for browser checks of UI states; its numbers are fixtures, not model results.

## Deployment (prepared, not deployed) — `compose.yaml`, `Dockerfile`, `web/Dockerfile`, `deploy/`

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

## Evaluation plan (batch 3)

- Internal test (manifest `test`, used once): accuracy, macro-F1, per-class precision/recall,
  per-variant kebab recall, confusion matrix, with bootstrap confidence intervals (kebab test is small).
- Temperature scaling and the "not sure" threshold are chosen on `val` only, never on `test`.
- Source check: the same test photos at full frame and cropped to the dish; kebab errors inspected.
- **Phone challenge set**: a small set of the user's own phone photos covering all five classes and the
  kebab variants, never used for training or tuning; it measures the source gap (Commons vs Food-101
  vs real phone photos). Size and collection are decided later; it is not part of this batch.

## Known limitations

- Kebab comes from a different source (Commons) than the other classes (Food-101). Photo style,
  background and framing differ, so the model can learn source cues instead of the dish. Resizing to
  the same resolution does not remove this. Evaluation must check kebab errors and confusions
  explicitly; more diverse kebab photos are the real fix.
- Food-101 training images were intentionally not cleaned by its authors and contain some label noise.
- `dessert` has about twice as many images as the other Food-101 classes, and `kebab` (372) about a
  third; training uses class weights and reports macro-F1 and per-class recall.
- Kebab test has only 56 images (döner/shawarma 9), so kebab metrics have wide uncertainty.
- Commons photos are grouped by author within a variant, so one photographer's series never spans
  train and test. Food-101 has no author information.

## Layout

```
config/       classes.json, data_prep.json, kebab_review.json
food_lens/    classes, imaging (load/EXIF/alpha, pHash), dedup, split, manifest validation
scripts/      provenance, Commons collection, kebab review, manifest build
manifests/    generated manifests (no images)
notebooks/    00_dataset_audit.ipynb (read-only Drive audit, Colab)
design/       food-lens mockup (EN/KO, warm light theme)
tests/        pytest
app/          FastAPI inference API; content/ ingredients
web/          Next.js frontend (own Dockerfile)
deploy/       API requirements, Nginx templates, local smoke test
```

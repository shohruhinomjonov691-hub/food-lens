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

- **Food-101** (Bossard, Guillaumin, Van Gool, ECCV 2014, ETH Zurich). The images come from
  Foodspotting and are not owned by ETH; its license agreement allows "scientific fair use" and asks
  for anything beyond that to be negotiated with the picture owners. It is used here for
  non-commercial research and education only, and images are never redistributed. **Whether a model
  trained on it may back a public deployment (food.gotrips.cloud) is not yet clarified** — open item
  before deploy. Provenance: the Drive copy is compared
  byte-for-byte with the official archive (`scripts/food101_provenance.py`).
- **Wikimedia Commons** kebab photos: each file keeps its own license (CC0 / public domain / CC BY /
  CC BY-SA) and author, recorded per file in `manifests/kebab_commons.csv`. Attribution is required
  wherever these images are shown.
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
`upload.wikimedia.org`, SHA-1 of the original, resized copy cached in `MyDrive/food-lens/commons_cache`);
MobileNetV2 (ImageNet weights), train augmentation, deterministic eval preprocessing, class-weighted
loss, seed 42; best checkpoint by val macro-F1; temperature and "not sure" threshold fitted on val;
`final.json` locks the choice before the test split is used once. Each run writes a new folder
`MyDrive/food-lens/runs/<UTC>_<commit>_seed42` (config, class mapping, preprocessing, checkpoint,
history, calibration, val/test metrics, confusion matrix, per-variant results, predictions).
Checkpoints stay private until the Food-101 public-use question is settled.

## Evaluation plan (batch 3, not started)

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
```

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
  Foodspotting and are not owned by ETH; the dataset is used here for non-commercial research and
  education only. Images are never redistributed. Provenance: the Drive copy is compared
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
| hamburger | 699 | 150 | 149 | 998 |
| hot_dog | 698 | 149 | 150 | 997 |
| kebab / skewered | 157 | 34 | 34 | 225 |
| kebab / minced_skewer | 60 | 13 | 13 | 86 |
| kebab / doner_shawarma | 43 | 9 | 9 | 61 |
| pizza | 699 | 150 | 150 | 999 |
| **Total** | **3754** | **805** | **805** | **5364** |

Food-101 part: 5000 Drive files, all byte-identical to the official archive
([`manifests/food101_provenance_v1.json`](manifests/food101_provenance_v1.json)); 8 removed (6 near
copies, 2 copies of an event flyer). Kebab: 372 Commons photos accepted out of 1006 candidates, each
looked at; döner/shawarma is the smallest variant.

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

Rules: unreadable files out; exact duplicates (same checksum) and near-duplicates (pHash Hamming
distance ≤ 2, same class) keep one copy; pairs with distance ≤ 8 share a group and therefore a split;
cross-class near-duplicates need an explicit decision in `config/data_prep.json`. Split: seed 42,
70/15/15, stratified by variant (cheesecake/chocolate cake and each kebab variant appear in every
split), group-aware.

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

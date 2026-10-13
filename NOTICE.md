# Food Lens — notices

Copyright (c) 2026 Shokhrukhbek Inomjonov

The project **code** (Python, TypeScript, notebooks, configuration) is licensed under the MIT License (see
`LICENSE`). The MIT License does **not** cover the images, the datasets or the trained model described below.

## Not in this repository

- **Images.** No dataset image is committed (enforced by `.gitignore` and `tests/test_repo_policy.py`).
- **Trained weights** (`best.pt`) and run folders. They are kept outside the repository, are not published, and are
  mounted read-only into the API container at deploy time.

## Food-101 (training data for dessert, hamburger, hot dog and pizza)

Bossard, Guillaumin, Van Gool, “Food-101 — Mining Discriminative Components with Random Forests”, ECCV 2014.
The archive’s `license_agreement.txt` states that the images come from Foodspotting, are not the property of
ETH Zurich, and that any use beyond scientific fair use must be negotiated with the respective picture owners
according to the Foodspotting terms of use. The `manifests/` files list Food-101 file names and checksums only.
The trained model is derived from these images; its public use is an **open question** — see
“Data → Licenses” in `README.md`. The demo at https://food.gotrips.cloud was made public by the project
owner's decision (2026-10-10); it returns class probabilities only and does not distribute the images or
the weights. Making it public does not settle the question.

## Wikimedia Commons (kebab images)

The kebab images come from Wikimedia Commons under their individual free licenses. They are not committed;
`manifests/kebab_commons.csv` and `manifests/manifest_v1.csv` record, per file, the author, the license, the
license URL and the Commons file page.

## Third-party components

- **MobileNetV2** architecture and ImageNet-pretrained initial weights from torchvision (BSD 3-Clause). The
  pretrained weights were trained on ImageNet; see the torchvision documentation for their terms.
- **Inter** typeface (SIL Open Font License 1.1), downloaded by `next/font` at build time and served by the web app.
- Ingredient lists in `content/ingredients.json` are short, project-written summaries of typical ingredients; each
  entry links to its Wikipedia source article.
- npm and PyPI dependencies keep their own licenses (`web/package-lock.json`, `deploy/requirements-api.txt`).

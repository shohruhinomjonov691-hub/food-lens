import csv
from pathlib import Path

import pytest

from food_lens.manifest import MANIFEST_COLUMNS, license_allowed, validate

ROOT = Path(__file__).resolve().parent.parent


def row(**kw):
    base = {c: "" for c in MANIFEST_COLUMNS}
    base.update(sample_id="food101:pizza/1.jpg", source="food101", source_folder="pizza", target="pizza", variant="pizza",
                location="pizza/1.jpg", checksum="sha256:" + "a" * 64, phash="0" * 16, group_id="g1", split="train")
    base.update(kw)
    return base


def commons_row(**kw):
    fields = dict(sample_id="commons:1", source="commons", source_folder="kebab_commons", target="kebab",
                  variant="doner_shawarma",
                  location="https://upload.wikimedia.org/wikipedia/commons/a/ab/K.jpg", checksum="sha1:" + "b" * 40,
                  author="A. Author", license="CC BY 2.0", license_url="https://creativecommons.org/licenses/by/2.0",
                  attribution_url="https://commons.wikimedia.org/wiki/File:K.jpg", group_id="g2")
    fields.update(kw)
    return row(**fields)


@pytest.mark.parametrize("name, ok", [
    ("CC BY-SA 4.0", True), ("CC BY 2.0", True), ("CC BY-SA 3.0 de", True), ("CC0", True),
    ("Public domain", True), ("GFDL", False), ("CC BY-NC 2.0", False), ("CC BY-ND 4.0", False),
    ("Copyrighted free use", False), ("", False), ("All rights reserved", False),
])
def test_license_allowlist(name, ok):
    assert license_allowed(name) is ok


def test_valid_rows():
    assert validate([row(), commons_row()]) == []


@pytest.mark.parametrize("bad, fragment", [
    (row(target="sushi"), "unknown target"),
    (row(source_folder="cheesecake"), "does not map"),
    (row(split="holdout"), "bad split"),
    (row(variant="cheesecake"), "variant"),
    (commons_row(variant="gyros"), "variant"),
    (row(source_folder="cheesecake", target="dessert", variant="pizza"), "variant"),
    (row(checksum="sha1:" + "a" * 40), "bad checksum"),
    (commons_row(license="CC BY-NC 2.0"), "license not allowed"),
    (commons_row(author=" "), "author missing"),
    (commons_row(attribution_url="https://example.com/x"), "attribution_url"),
])
def test_invalid_rows(bad, fragment):
    assert any(fragment in p for p in validate([bad]))


def test_duplicates_and_group_split_conflicts():
    problems = validate([row(), row(sample_id="x", location="pizza/2.jpg", split="test")])
    assert any("duplicate checksum" in p for p in problems)
    assert any("spans splits" in p for p in problems)


def test_exclusion_overlap():
    assert validate([row()], [{"checksum": row()["checksum"], "location": "pizza/1.jpg"}])
    # An excluded exact duplicate shares the checksum of the kept file: that is fine.
    assert validate([row()], [{"checksum": row()["checksum"], "location": "pizza/1-copy.jpg"}]) == []


def test_committed_manifest_is_valid():
    path = ROOT / "manifests" / "manifest_v1.csv"
    if not path.exists():
        pytest.skip("manifest not generated yet")
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with open(ROOT / "manifests" / "exclusions_v1.csv", newline="", encoding="utf-8") as f:
        exclusions = list(csv.DictReader(f))
    assert validate(rows, exclusions) == []
    assert {r["target"] for r in rows} == {"dessert", "hamburger", "hot_dog", "kebab", "pizza"}
    assert not any(r["source_folder"] == "kebab" for r in rows), "Bing kebab images must not be in the manifest"
    assert {r["variant"] for r in rows if r["target"] == "kebab"} <= {"skewered", "minced_skewer", "doner_shawarma"}



def test_committed_manifest_has_no_split_leakage():
    """Independent reconstruction from the manifest alone: near pairs and author series share a split."""
    from food_lens.commons import canonical_author
    from food_lens.dedup import near_pairs

    path = ROOT / "manifests" / "manifest_v1.csv"
    if not path.exists():
        pytest.skip("manifest not generated yet")
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by_loc = {r["location"]: r for r in rows}
    pairs = near_pairs({loc: int(r["phash"], 16) for loc, r in by_loc.items()}, 8)
    assert [(a, b) for a, b, _ in pairs if by_loc[a]["split"] != by_loc[b]["split"]] == []
    series = {}
    for r in rows:
        if r["source"] == "commons":
            series.setdefault((canonical_author(r["author"]), r["variant"]), set()).add(r["split"])
    assert {k: v for k, v in series.items() if len(v) > 1} == {}

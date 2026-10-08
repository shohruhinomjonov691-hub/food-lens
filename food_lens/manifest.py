"""Manifest format and validation.

A manifest row describes one training image without containing it:
- source "food101": `location` is a path relative to MyDrive/food101_dataset, `checksum` is sha256 of the file.
- source "commons": `location` is the Wikimedia Commons original URL, `checksum` is the Commons sha1
  of that original. Author, license and page URL are required.
"""
import csv
import re
from collections import defaultdict

from food_lens.classes import CLASSES, SOURCE_TO_CLASS, VARIANTS
from food_lens.split import SPLITS

MANIFEST_COLUMNS = (
    "sample_id", "source", "source_folder", "target", "variant", "location", "checksum", "phash",
    "group_id", "split", "official_split", "author", "license", "license_url", "attribution_url",
)
EXCLUSION_COLUMNS = ("source", "source_folder", "location", "checksum", "reason")
SOURCES = {"food101", "commons"}
CHECKSUM = {"food101": re.compile(r"^sha256:[0-9a-f]{64}$"), "commons": re.compile(r"^sha1:[0-9a-f]{40}$")}

# Licenses accepted for images without a dataset-level license (Commons LicenseShortName values).
LICENSE_ALLOWLIST = re.compile(
    r"^(cc0( 1\.0)?|public domain|pd(-[\w.-]+)?|cc by(-sa)? \d\.\d( [a-z\-]+)?)$", re.IGNORECASE)


def license_allowed(short_name):
    return bool(LICENSE_ALLOWLIST.match((short_name or "").strip()))


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, columns):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(columns), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})


def validate(rows, exclusions=()):
    """Return a list of problems (empty list = valid)."""
    problems = []
    if rows and tuple(rows[0]) != MANIFEST_COLUMNS:
        problems.append(f"columns {tuple(rows[0])} != {MANIFEST_COLUMNS}")
        return problems
    seen_ids, seen_checksums, seen_locations = set(), set(), set()
    group_splits = defaultdict(set)
    for i, r in enumerate(rows):
        where = f"row {i} ({r.get('location')})"
        if r["source"] not in SOURCES:
            problems.append(f"{where}: unknown source {r['source']!r}")
            continue
        if r["target"] not in CLASSES:
            problems.append(f"{where}: unknown target {r['target']!r}")
        if SOURCE_TO_CLASS.get(r["source_folder"]) != r["target"]:
            problems.append(f"{where}: folder {r['source_folder']!r} does not map to {r['target']!r}")
        allowed_variants = VARIANTS.get(r["target"], (r["target"],))
        if r["variant"] not in allowed_variants:
            problems.append(f"{where}: variant {r['variant']!r} not in {allowed_variants}")
        if r["split"] not in SPLITS:
            problems.append(f"{where}: bad split {r['split']!r}")
        if not CHECKSUM[r["source"]].match(r["checksum"]):
            problems.append(f"{where}: bad checksum {r['checksum']!r}")
        if not re.fullmatch(r"[0-9a-f]{16}", r["phash"]):
            problems.append(f"{where}: bad phash")
        if r["source"] == "commons":
            if not license_allowed(r["license"]):
                problems.append(f"{where}: license not allowed {r['license']!r}")
            if not r["author"].strip():
                problems.append(f"{where}: author missing")
            if not r["attribution_url"].startswith("https://commons.wikimedia.org/wiki/File:"):
                problems.append(f"{where}: attribution_url must be a Commons file page")
            if not r["location"].startswith("https://upload.wikimedia.org/"):
                problems.append(f"{where}: location must be an upload.wikimedia.org URL")
        for value, seen, label in ((r["sample_id"], seen_ids, "sample_id"),
                                   (r["checksum"], seen_checksums, "checksum"),
                                   (r["location"], seen_locations, "location")):
            if value in seen:
                problems.append(f"{where}: duplicate {label} {value}")
            seen.add(value)
        group_splits[r["group_id"]].add(r["split"])
    for group_id, splits in group_splits.items():
        if len(splits) > 1:
            problems.append(f"group {group_id} spans splits {sorted(splits)}")
    # By location: an excluded exact duplicate legitimately shares its checksum with the kept file.
    excluded = {e["location"] for e in exclusions}
    for r in rows:
        if r["location"] in excluded:
            problems.append(f"{r['location']}: listed in both manifest and exclusions")
    return problems

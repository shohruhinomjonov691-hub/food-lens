"""Build the training manifest (no images) from the audit, the Food-101 provenance check and the
reviewed Commons kebab list.

Inputs (defaults):
  audit/files.csv                        Drive dataset listing from notebooks/00_dataset_audit.ipynb
  data/food101_official/hashes.csv       scripts/food101_provenance.py (official archive SHA-256)
  manifests/kebab_commons.csv            scripts/build_kebab_manifest.py (accepted Commons files)
  config/data_prep.json                  seed, ratios, thresholds, manual decisions
Outputs:
  manifests/manifest_v1.csv, manifests/exclusions_v1.csv, manifests/stats_v1.json

Usage: python scripts/prepare_manifest.py [--out-dir manifests] [...input overrides]
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from food_lens.classes import CLASSES, SOURCE_TO_CLASS  # noqa: E402
from food_lens.dedup import UnionFind, near_pairs, summarize_groups  # noqa: E402
from food_lens.manifest import EXCLUSION_COLUMNS, MANIFEST_COLUMNS, read_csv, validate, write_csv  # noqa: E402
from food_lens.split import SPLITS, assign_splits  # noqa: E402

FOOD101_LICENSE_NOTE = "Food-101 (ETH Zurich); images from Foodspotting, see README"


class NeedsReview(Exception):
    pass


def build(drive_rows, official_rows, commons_rows, config):
    official = {(r["folder"], r["name"]): r for r in official_rows}
    excluded_folders = config["excluded_drive_folders"]
    manual = {m["location"]: m["reason"] for m in config.get("manual_exclusions", [])}
    included, exclusions = [], []

    def exclude(row, reason):
        exclusions.append({**{c: row.get(c, "") for c in EXCLUSION_COLUMNS}, "reason": reason})

    provenance = Counter()
    for r in drive_rows:
        folder, name = r["folder"], r["name"]
        row = {"source": "food101", "source_folder": folder, "location": f"{folder}/{name}",
               "checksum": f"sha256:{r['sha256']}" if r["sha256"] else "", "phash": r["phash"]}
        if folder in excluded_folders:
            exclude(row, excluded_folders[folder])
            continue
        if folder not in SOURCE_TO_CLASS:
            exclude(row, "folder not mapped to a class")
            continue
        if r["decode_ok"] != "True" or not r["phash"]:
            exclude(row, f"decode failed: {r['error']}")
            continue
        off = official.get((folder, name))
        if off is None:
            provenance["missing_from_official"] += 1
            exclude(row, "not found in the official Food-101 archive")
            continue
        if off["sha256"] != r["sha256"]:
            provenance["bytes_differ"] += 1
            exclude(row, "bytes differ from the official Food-101 file")
            continue
        provenance["byte_identical"] += 1
        row.update(sample_id=f"food101:{folder}/{name}", target=SOURCE_TO_CLASS[folder], variant=folder,
                   official_split=off["official_split"], license=FOOD101_LICENSE_NOTE)
        included.append(row)

    for r in commons_rows:
        included.append({
            "sample_id": f"commons:{r['pageid']}", "source": "commons", "source_folder": "kebab_commons",
            "target": SOURCE_TO_CLASS["kebab_commons"], "variant": r["variant"], "location": r["original_url"],
            "checksum": f"sha1:{r['original_sha1']}", "phash": r["phash"], "author": r["author"],
            "license": r["license"], "license_url": r["license_url"], "attribution_url": r["page_url"],
        })

    kept = []
    for row in included:
        if row["location"] in manual:
            exclude(row, manual[row["location"]])
        else:
            kept.append(row)
    included = kept

    # Exact duplicates: identical checksum, keep the smallest location.
    by_checksum = defaultdict(list)
    for row in included:
        by_checksum[row["checksum"]].append(row)
    exact = {"pairs": 0, "groups": 0, "redundant_files": 0}
    kept = []
    for rows in by_checksum.values():
        rows.sort(key=lambda r: r["location"])
        kept.append(rows[0])
        if len(rows) > 1:
            exact["groups"] += 1
            exact["pairs"] += len(rows) * (len(rows) - 1) // 2
            exact["redundant_files"] += len(rows) - 1
            for dup in rows[1:]:
                exclude(dup, f"exact duplicate of {rows[0]['location']}")
    included = kept

    # Near duplicates by perceptual hash.
    nd = config["near_duplicate"]
    by_loc = {row["location"]: row for row in included}
    pairs = near_pairs({loc: int(row["phash"], 16) for loc, row in by_loc.items()}, nd["group_max_distance"])
    same = [(a, b, d) for a, b, d in pairs if by_loc[a]["target"] == by_loc[b]["target"]]
    cross = [(a, b, d) for a, b, d in pairs if by_loc[a]["target"] != by_loc[b]["target"]]
    removable = [p for p in same if p[2] <= nd["remove_max_distance"]]
    near_stats = {
        "remove_max_distance": nd["remove_max_distance"],
        "group_max_distance": nd["group_max_distance"],
        "same_class_removable": summarize_groups(removable, list(by_loc)),
        "same_class_grouped_only": len([p for p in same if p[2] > nd["remove_max_distance"]]),
        "cross_class_pairs": len(cross),
    }

    decisions = {frozenset((c["a"], c["b"])): c for c in config.get("cross_class_reviewed", [])}
    unreviewed = [p for p in cross if frozenset(p[:2]) not in decisions]
    if unreviewed:
        raise NeedsReview("cross-class near-duplicates need a decision in config/data_prep.json "
                          "(cross_class_reviewed): " + "; ".join(f"{a} <-> {b} (d={d})" for a, b, d in unreviewed))

    removed = {}
    uf = UnionFind(list(by_loc))
    for a, b, _ in removable:
        uf.union(a, b)
    for root, members in uf.groups().items():
        for loc in members[1:]:
            removed[loc] = f"near duplicate (pHash d<={nd['remove_max_distance']}) of {members[0]}"
    for a, b, d in cross:
        if decisions[frozenset((a, b))]["decision"] == "exclude_both":
            note = decisions[frozenset((a, b))]["note"]
            removed.setdefault(a, f"cross-class near duplicate with {b} (d={d}): {note}")
            removed.setdefault(b, f"cross-class near duplicate with {a} (d={d}): {note}")
    for loc, reason in removed.items():
        exclude(by_loc[loc], reason)
    included = [row for row in included if row["location"] not in removed]

    # Groups: remaining near pairs (same or cross class, d <= group_max) stay in one split.
    remaining = {row["location"] for row in included}
    groups = UnionFind(sorted(remaining))
    for a, b, _ in pairs:
        if a in remaining and b in remaining:
            groups.union(a, b)
    # Commons photos by the same author within one variant (often one photo series) also stay in
    # one split, so test never shares a photographer's series with train. Grouping per variant keeps
    # each variant's split quotas reachable.
    if config.get("group_commons_by_author"):
        first_by_author = {}
        for row in included:
            if row["source"] == "commons":
                author = (row["author"].strip().lower(), row["variant"])
                if author in first_by_author:
                    groups.union(first_by_author[author], row["location"])
                else:
                    first_by_author[author] = row["location"]
    group_index = {root: f"g{i:05d}" for i, root in enumerate(sorted(groups.groups()))}
    for row in included:
        row["group_id"] = group_index[groups.find(row["location"])]

    splits = assign_splits(
        [row["location"] for row in included],
        {row["location"]: row["group_id"] for row in included},
        {row["location"]: row["variant"] for row in included},
        config["ratios"], config["seed"])
    for row in included:
        row["split"] = splits[row["location"]]
    included.sort(key=lambda r: (r["target"], r["variant"], r["source_folder"], r["location"]))
    exclusions.sort(key=lambda e: (e["source_folder"], e["location"]))

    stats = {
        "seed": config["seed"], "ratios": config["ratios"],
        "food101_provenance": dict(provenance),
        "exact_duplicates": exact,
        "near_duplicates": near_stats,
        "multi_member_groups": sum(1 for g in groups.groups().values() if len(g) > 1),
        "included": len(included), "excluded": len(exclusions),
        "per_class": {c: dict(Counter(r["split"] for r in included if r["target"] == c)) for c in CLASSES},
        "per_source_folder": {f: dict(Counter(r["split"] for r in included if r["source_folder"] == f))
                              for f in sorted({r["source_folder"] for r in included})},
        "per_variant": {f"{t}/{v}": dict(Counter(r["split"] for r in included if (r["target"], r["variant"]) == (t, v)))
                        for t, v in sorted({(r["target"], r["variant"]) for r in included})},
        "exclusion_reasons": dict(Counter(re.split(r" of [a-z_]+/| \(|:", e["reason"])[0] for e in exclusions)),
    }
    for c in CLASSES:
        stats["per_class"][c]["total"] = sum(stats["per_class"][c].get(s, 0) for s in SPLITS)
    return included, exclusions, stats


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--drive", default="audit/files.csv")
    parser.add_argument("--official", default="data/food101_official/hashes.csv")
    parser.add_argument("--commons", default="manifests/kebab_commons.csv")
    parser.add_argument("--config", default="config/data_prep.json")
    parser.add_argument("--out-dir", default="manifests")
    args = parser.parse_args(argv)
    with open(args.config, encoding="utf-8") as f:
        config = json.load(f)
    try:
        rows, exclusions, stats = build(read_csv(args.drive), read_csv(args.official),
                                        read_csv(args.commons), config)
    except NeedsReview as exc:
        print("NEEDS REVIEW:", exc)
        return 2
    problems = validate([{c: r.get(c, "") for c in MANIFEST_COLUMNS} for r in rows], exclusions)
    if problems:
        print("INVALID MANIFEST:\n  " + "\n  ".join(problems[:50]))
        return 1
    os.makedirs(args.out_dir, exist_ok=True)
    write_csv(os.path.join(args.out_dir, "manifest_v1.csv"), rows, MANIFEST_COLUMNS)
    write_csv(os.path.join(args.out_dir, "exclusions_v1.csv"), exclusions, EXCLUSION_COLUMNS)
    with open(os.path.join(args.out_dir, "stats_v1.json"), "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(json.dumps(stats, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

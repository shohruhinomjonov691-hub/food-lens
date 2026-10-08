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
from food_lens.commons import DERIVED_HINT, canonical_author  # noqa: E402
from food_lens.dedup import UnionFind, near_pairs, summarize_groups  # noqa: E402
from food_lens.imaging import hamming  # noqa: E402
from food_lens.manifest import EXCLUSION_COLUMNS, MANIFEST_COLUMNS, read_csv, validate, write_csv  # noqa: E402
from food_lens.split import SPLITS, assign_splits, quota_report  # noqa: E402

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

    aliases = config.get("author_aliases", {})
    for r in commons_rows:
        included.append({
            "sample_id": f"commons:{r['pageid']}", "source": "commons", "source_folder": "kebab_commons",
            "target": SOURCE_TO_CLASS["kebab_commons"], "variant": r["variant"], "location": r["original_url"],
            "checksum": f"sha1:{r['original_sha1']}", "phash": r["phash"], "author": r["author"],
            "license": r["license"], "license_url": r["license_url"], "attribution_url": r["page_url"],
            # Internal fields (not written to the manifest):
            "title": r.get("title", ""), "credit": r.get("credit", ""),
            "author_id": canonical_author(r["author"], aliases),
        })

    nd = config["near_duplicate"]
    kept, manual_rows = [], []
    for row in included:
        if row["location"] in manual:
            exclude(row, manual[row["location"]])
            manual_rows.append(row)
        else:
            kept.append(row)
    # A manual exclusion also removes every copy of that image (same bytes, or pHash d<=remove_max in
    # the same class), so listing only one copy can never leave another copy in the dataset.
    included = []
    for row in kept:
        source = next((m for m in manual_rows if m["checksum"] == row["checksum"] or (
            m["target"] == row["target"]
            and hamming(int(m["phash"], 16), int(row["phash"], 16)) <= nd["remove_max_distance"])), None)
        if source:
            exclude(row, f"copy of manually excluded {source['location']}")
        else:
            included.append(row)

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

    # Derived Commons files (crops, retouches) are invisible to pHash; they must be listed.
    by_id = {row["sample_id"]: row for row in included}
    derived = config.get("derived_copies", [])
    known = {d["copy"] for d in derived} | {d["original"] for d in derived} | {
        d["sample_id"] for d in config.get("derived_reviewed", [])}
    unlisted = [row["sample_id"] for row in included if row["source"] == "commons"
                and (DERIVED_HINT.search(row["title"]) or re.search(r"deriv", row["credit"], re.IGNORECASE))
                and row["sample_id"] not in known]
    if unlisted:
        raise NeedsReview("Commons files that look derived (crop/retouch) need an entry in config/data_prep.json "
                          "(derived_copies or derived_reviewed): " + ", ".join(sorted(unlisted)))

    # Near duplicates by perceptual hash.
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

    # Groups are computed on the graph BEFORE anything is removed, so a removed image that linked two
    # kept images (A ~ B ~ C, B removed) still keeps A and C together.
    groups = UnionFind(sorted(by_loc))
    for a, b, _ in pairs:
        groups.union(a, b)
    derived_count = 0
    for d in derived:
        if d["copy"] in by_id and d["original"] in by_id:
            groups.union(by_id[d["copy"]]["location"], by_id[d["original"]]["location"])
    # Commons photos by the same person (canonical author ID) within one variant stay in one split, so
    # test never shares a photographer's series with train. Per variant keeps the quotas reachable.
    if config.get("group_commons_by_author"):
        first_by_author = {}
        for row in included:
            if row["source"] == "commons":
                key = (row["author_id"], row["variant"])
                if key in first_by_author:
                    groups.union(first_by_author[key], row["location"])
                else:
                    first_by_author[key] = row["location"]

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
    for d in derived:
        if d["copy"] in by_id and d["original"] in by_id:
            derived_count += 1
            removed.setdefault(by_id[d["copy"]]["location"],
                               f"derived copy ({d['reason']}) of {by_id[d['original']]['location']}")
    for loc, reason in removed.items():
        exclude(by_loc[loc], reason)
    included = [row for row in included if row["location"] not in removed]

    roots = sorted({groups.find(row["location"]) for row in included})
    group_index = {root: f"g{i:05d}" for i, root in enumerate(roots)}
    for row in included:
        row["group_id"] = group_index[groups.find(row["location"])]

    items = [row["location"] for row in included]
    group_of = {row["location"]: row["group_id"] for row in included}
    stratum = {row["location"]: row["variant"] for row in included}
    splits = assign_splits(items, group_of, stratum, config["ratios"], config["seed"])
    for row in included:
        row["split"] = splits[row["location"]]
    included.sort(key=lambda r: (r["target"], r["variant"], r["source_folder"], r["location"]))
    exclusions.sort(key=lambda e: (e["source_folder"], e["location"]))

    group_sizes = Counter(group_of.values())
    stats = {
        "seed": config["seed"], "ratios": config["ratios"],
        "food101_provenance": dict(provenance),
        "exact_duplicates": exact,
        "near_duplicates": near_stats,
        "derived_copies_removed": derived_count,
        "multi_member_groups": sum(1 for n in group_sizes.values() if n > 1),
        "largest_groups": sorted(group_sizes.values(), reverse=True)[:5],
        "included": len(included), "excluded": len(exclusions),
        "per_class": {c: dict(Counter(r["split"] for r in included if r["target"] == c)) for c in CLASSES},
        "per_source_folder": {f: dict(Counter(r["split"] for r in included if r["source_folder"] == f))
                              for f in sorted({r["source_folder"] for r in included})},
        "per_variant": {f"{t}/{v}": dict(Counter(r["split"] for r in included if (r["target"], r["variant"]) == (t, v)))
                        for t, v in sorted({(r["target"], r["variant"]) for r in included})},
        "quota_check": quota_report(items, group_of, stratum, splits, config["ratios"],
                                    config.get("split_minimums")),
        "commons_authors_per_variant": {v: len({r["author_id"] for r in included
                                                if r["source"] == "commons" and r["variant"] == v})
                                        for v in sorted({r["variant"] for r in included if r["source"] == "commons"})},
        "exclusion_reasons": dict(Counter(re.split(r" of [a-z_]+/| of https| \(|:", e["reason"])[0] for e in exclusions)),
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

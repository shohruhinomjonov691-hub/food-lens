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
from food_lens.commons import DERIVED_HINT, DERIVED_TEXT, canonical_author  # noqa: E402
from food_lens.dedup import UnionFind, near_pairs, summarize_groups  # noqa: E402
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
    rmax, gmax = nd["remove_max_distance"], nd["group_max_distance"]
    if rmax > gmax:
        raise ValueError("remove_max_distance must not exceed group_max_distance")

    # One graph over the FULL candidate set, built before manual exclusion and dedup. Two thresholds:
    # duplicate components (same bytes, or pHash d<=rmax in one class) decide what is removed;
    # split groups (pHash d<=gmax in any class, derived pairs, author series) decide what stays
    # together. Keepers inherit the original graph, so a removed "bridge" never splits a group.
    by_loc = {row["location"]: row for row in included}
    by_id = {row["sample_id"]: row for row in included}
    pairs = near_pairs({loc: int(row["phash"], 16) for loc, row in by_loc.items()}, gmax)
    dup = UnionFind(sorted(by_loc))
    groups = UnionFind(sorted(by_loc))
    by_checksum = defaultdict(list)
    for loc in sorted(by_loc):
        by_checksum[by_loc[loc]["checksum"]].append(loc)
    for locs in by_checksum.values():
        for loc in locs[1:]:
            dup.union(locs[0], loc)
            groups.union(locs[0], loc)
    for a, b, d in pairs:
        groups.union(a, b)
        if d <= rmax and by_loc[a]["target"] == by_loc[b]["target"]:
            dup.union(a, b)
    derived = config.get("derived_copies", [])
    for d in derived:
        if d["copy"] in by_id and d["original"] in by_id:
            groups.union(by_id[d["copy"]]["location"], by_id[d["original"]]["location"])
    # Commons photos by the same person (canonical author ID) within one variant stay in one split, so
    # test never shares a photographer's series with train. Per variant keeps the quotas reachable.
    if config.get("group_commons_by_author"):
        first_by_author = {}
        for loc in sorted(by_loc):
            row = by_loc[loc]
            if row["source"] == "commons":
                key = (row["author_id"], row["variant"])
                if key in first_by_author:
                    groups.union(first_by_author[key], loc)
                else:
                    first_by_author[key] = loc

    # A manual rejection spreads over its whole duplicate component (transitively), so listing one
    # copy can never leave another copy in the dataset.
    removed = {}
    manual_root = {}
    for loc in sorted(manual):
        if loc in by_loc:
            manual_root.setdefault(dup.find(loc), loc)
    for loc in sorted(by_loc):
        if loc in manual:
            removed[loc] = manual[loc]
        elif dup.find(loc) in manual_root:
            removed[loc] = f"copy of manually excluded {manual_root[dup.find(loc)]}"

    # Exact duplicates (statistics as before: among files not manually excluded).
    exact = {"pairs": 0, "groups": 0, "redundant_files": 0}
    for locs in by_checksum.values():
        locs = [loc for loc in locs if loc not in removed]
        if len(locs) > 1:
            exact["groups"] += 1
            exact["pairs"] += len(locs) * (len(locs) - 1) // 2
            exact["redundant_files"] += len(locs) - 1
            for loc in locs[1:]:
                removed[loc] = f"exact duplicate of {locs[0]}"

    # Near duplicates: one keeper (smallest location) per remaining duplicate component.
    live = [loc for loc in sorted(by_loc) if loc not in removed]
    live_set = set(live)
    live_pairs = [(a, b, d) for a, b, d in pairs if a in live_set and b in live_set]
    same = [(a, b, d) for a, b, d in live_pairs if by_loc[a]["target"] == by_loc[b]["target"]]
    cross = [(a, b, d) for a, b, d in live_pairs if by_loc[a]["target"] != by_loc[b]["target"]]
    removable = [p for p in same if p[2] <= rmax]
    near_stats = {
        "remove_max_distance": rmax,
        "group_max_distance": gmax,
        "same_class_removable": summarize_groups(removable, live),
        "same_class_grouped_only": len([p for p in same if p[2] > rmax]),
        "cross_class_pairs": len(cross),
    }
    components = defaultdict(list)
    for loc in live:
        components[dup.find(loc)].append(loc)
    for members in components.values():
        for loc in members[1:]:
            removed[loc] = f"near duplicate (pHash d<={rmax}) of {members[0]}"

    decisions = {frozenset((c["a"], c["b"])): c for c in config.get("cross_class_reviewed", [])}
    unreviewed = [p for p in cross if frozenset(p[:2]) not in decisions]
    if unreviewed:
        raise NeedsReview("cross-class near-duplicates need a decision in config/data_prep.json "
                          "(cross_class_reviewed): " + "; ".join(f"{a} <-> {b} (d={d})" for a, b, d in unreviewed))
    for a, b, d in cross:
        if decisions[frozenset((a, b))]["decision"] == "exclude_both":
            note = decisions[frozenset((a, b))]["note"]
            removed.setdefault(a, f"cross-class near duplicate with {b} (d={d}): {note}")
            removed.setdefault(b, f"cross-class near duplicate with {a} (d={d}): {note}")

    # Derived Commons files (crops, retouches) are invisible to pHash. A listed copy is removed when its
    # original stays in the dataset; if the original is excluded or not a candidate, the copy is never
    # accepted silently: it needs a manual exclusion or a derived_reviewed entry with evidence.
    reviewed_derived = {}
    for entry in config.get("derived_reviewed", []):
        if not (entry.get("note") or entry.get("evidence")):
            raise NeedsReview(f"derived_reviewed entry for {entry.get('sample_id')} needs a note/evidence")
        reviewed_derived[entry["sample_id"]] = entry
    derived_count, orphaned = 0, []
    for d in derived:
        copy_row, orig_row = by_id.get(d["copy"]), by_id.get(d["original"])
        if copy_row is None or copy_row["location"] in removed:
            continue
        if orig_row is not None and orig_row["location"] not in removed:
            derived_count += 1
            removed[copy_row["location"]] = f"derived copy ({d['reason']}) of {orig_row['location']}"
        elif d["copy"] not in reviewed_derived:
            orphaned.append(f"{d['copy']} (original {d['original']} "
                            f"{'excluded' if orig_row is not None else 'not a candidate'})")
    if orphaned:
        raise NeedsReview("derived copies whose original is excluded or missing need a manual exclusion or a "
                          "derived_reviewed entry with evidence: " + ", ".join(orphaned))
    known = {d["copy"] for d in derived} | {d["original"] for d in derived} | set(reviewed_derived)
    unlisted = [row["sample_id"] for row in included if row["source"] == "commons"
                and row["location"] not in removed and row["sample_id"] not in known
                and (DERIVED_HINT.search(row["title"])
                     or DERIVED_TEXT.search(row["credit"]) or DERIVED_TEXT.search(row["author"]))]
    if unlisted:
        raise NeedsReview("Commons files that look derived (crop/retouch in title, credit or author) need an "
                          "entry in config/data_prep.json (derived_copies or derived_reviewed): "
                          + ", ".join(sorted(unlisted)))

    for loc in sorted(removed):
        exclude(by_loc[loc], removed[loc])
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

"""Deterministic, group-aware, stratified train/val/test split.

Every member of a group (near-duplicates) lands in the same split, so a test image never has a
near-copy in train. Groups are stratified by their first member's stratum (source folder).
"""
import random
from collections import defaultdict

SPLITS = ("train", "val", "test")


def assign_splits(items, groups, strata, ratios, seed):
    """Return dict item -> split.

    items:  iterable of ids
    groups: dict id -> group id (every item must be present)
    strata: dict id -> stratum name
    ratios: dict split -> fraction, e.g. {"train": 0.7, "val": 0.15, "test": 0.15}
    """
    if abs(sum(ratios.values()) - 1) > 1e-9 or set(ratios) != set(SPLITS):
        raise ValueError(f"ratios must cover {SPLITS} and sum to 1: {ratios}")
    members = defaultdict(list)
    for item in items:
        members[groups[item]].append(item)
    by_stratum = defaultdict(list)
    for group_id, group_items in members.items():
        by_stratum[strata[min(group_items)]].append(group_id)

    result = {}
    for stratum in sorted(by_stratum):
        group_ids = sorted(by_stratum[stratum])
        random.Random(f"{seed}:{stratum}").shuffle(group_ids)
        total = sum(len(members[g]) for g in group_ids)
        quota = {s: round(total * ratios[s]) for s in ("test", "val")}
        filled = {"test": 0, "val": 0}
        for group_id in group_ids:
            size = len(members[group_id])
            split = next((s for s in ("test", "val") if filled[s] + size <= quota[s]), "train")
            if split != "train":
                filled[split] += size
            for item in members[group_id]:
                result[item] = split
    return result

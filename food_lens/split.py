"""Deterministic, group-aware split stratified by variant.

Every member of a group (near-duplicates, derived copies, one author's series) lands in the same
split, so a test image never has a near-copy in train. A group may hold several variants (e.g. a
hamburger/hot dog look-alike pair); its variant counts are treated as a vector, and a group goes to
val/test only if it fits that split's remaining quota for *every* variant it contains. Groups are
never cut to fill a quota; whatever does not fit goes to train, and quota shortfalls are reported.
"""
import random
from collections import Counter, defaultdict

SPLITS = ("train", "val", "test")


def quotas(strata_sizes, ratios):
    """Per stratum target counts for val and test (train takes the rest)."""
    return {s: {split: round(n * ratios[split]) for split in ("val", "test")} for s, n in strata_sizes.items()}


def assign_splits(items, groups, strata, ratios, seed):
    """Return dict item -> split.

    items:  iterable of ids
    groups: dict id -> group id (every item must be present)
    strata: dict id -> stratum name (the variant)
    ratios: dict split -> fraction, e.g. {"train": 0.7, "val": 0.15, "test": 0.15}
    """
    if abs(sum(ratios.values()) - 1) > 1e-9 or set(ratios) != set(SPLITS):
        raise ValueError(f"ratios must cover {SPLITS} and sum to 1: {ratios}")
    members = defaultdict(list)
    for item in items:
        members[groups[item]].append(item)
    vectors = {g: Counter(strata[i] for i in m) for g, m in members.items()}
    target = quotas(Counter(strata[i] for g in members.values() for i in g), ratios)
    filled = {split: Counter() for split in ("val", "test")}

    # Largest groups first (they are the hardest to place), random but seeded order within a size.
    # Random keys are drawn over sorted group ids, so the result never depends on input order.
    rng = random.Random(f"{seed}")
    key = {g: rng.random() for g in sorted(members, key=lambda g: min(members[g]))}
    order = sorted(members, key=lambda g: (-len(members[g]), key[g], min(members[g])))
    result = {}
    for g in order:
        vec = vectors[g]
        options = []
        for split in ("test", "val"):
            room = {s: target[s][split] - filled[split][s] for s in vec}
            if all(vec[s] <= room[s] for s in vec):
                options.append((sum(room.values()), split == "test", split))
        split = max(options)[2] if options else "train"
        if split != "train":
            filled[split].update(vec)
        for item in members[g]:
            result[item] = split
    return result


def quota_report(items, groups, strata, splits, ratios, minimums=None):
    """Per stratum: target vs actual val/test counts, and whether configured minimums hold.

    minimums: dict stratum -> minimum count required in val and in test.
    """
    sizes = Counter(strata[i] for i in items)
    target = quotas(sizes, ratios)
    actual = {s: Counter() for s in sizes}
    for i in items:
        actual[strata[i]][splits[i]] += 1
    group_sizes = Counter(groups[i] for i in items)
    report = {}
    for s in sorted(sizes):
        row = {"total": sizes[s], "target_val": target[s]["val"], "target_test": target[s]["test"],
               "val": actual[s]["val"], "test": actual[s]["test"], "train": actual[s]["train"]}
        need = (minimums or {}).get(s)
        if need is not None:
            row["minimum"] = need
            row["minimum_met"] = row["val"] >= need and row["test"] >= need
            if not row["minimum_met"]:
                big = sorted({group_sizes[groups[i]] for i in items if strata[i] == s and group_sizes[groups[i]] > 1},
                             reverse=True)[:5]
                row["reason"] = (f"only {sizes[s]} images; target val/test {target[s]['val']}/{target[s]['test']}"
                                 f"; leakage groups are never split (largest multi-image groups: {big})")
        report[s] = row
    return report

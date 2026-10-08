from collections import Counter

import pytest

from food_lens.dedup import UnionFind, near_pairs, summarize_groups
from food_lens.split import assign_splits

RATIOS = {"train": 0.7, "val": 0.15, "test": 0.15}


def test_near_pairs_threshold():
    hashes = {"a": 0b0, "b": 0b11, "c": 0xFF, "d": (1 << 64) - 1}
    assert near_pairs(hashes, 2) == [("a", "b", 2)]
    assert ("a", "c", 8) in near_pairs(hashes, 8)


def test_summarize_counts_pairs_groups_and_redundant_files_separately():
    # Audit case: a 3-image group (3 pairs) + two 2-image groups (1 pair each).
    pairs = [("c1", "c2", 0), ("c1", "c3", 0), ("c2", "c3", 0), ("h1", "h2", 0), ("p1", "p2", 0)]
    ids = ["c1", "c2", "c3", "h1", "h2", "p1", "p2", "x"]
    assert summarize_groups(pairs, ids) == {"pairs": 5, "groups": 3, "redundant_files": 4}


def test_union_find_root_is_smallest():
    uf = UnionFind(["b", "a", "c"])
    uf.union("c", "b")
    uf.union("b", "a")
    assert uf.groups() == {"a": ["a", "b", "c"]}


def _items(n_per_stratum):
    items, strata = [], {}
    for stratum, n in n_per_stratum.items():
        for i in range(n):
            item = f"{stratum}/{i:04d}"
            items.append(item)
            strata[item] = stratum
    return items, strata


def test_split_ratios_per_stratum_and_determinism():
    items, strata = _items({"cheesecake": 1000, "chocolate_cake": 998, "kebab": 200})
    groups = {i: i for i in items}
    first = assign_splits(items, groups, strata, RATIOS, 42)
    assert first == assign_splits(list(reversed(items)), groups, strata, RATIOS, 42)
    assert first != assign_splits(items, groups, strata, RATIOS, 7)
    for stratum, n in {"cheesecake": 1000, "chocolate_cake": 998, "kebab": 200}.items():
        counts = Counter(first[i] for i in items if strata[i] == stratum)
        assert counts["test"] == round(n * 0.15)
        assert counts["val"] == round(n * 0.15)
        assert counts["train"] == n - 2 * round(n * 0.15)


def test_groups_never_span_splits():
    items, strata = _items({"hot_dog": 300})
    groups = {i: i for i in items}
    for k in range(0, 60, 3):  # 20 groups of 3
        for i in items[k:k + 3]:
            groups[i] = items[k]
    splits = assign_splits(items, groups, strata, RATIOS, 42)
    for k in range(0, 60, 3):
        assert len({splits[i] for i in items[k:k + 3]}) == 1


def test_bad_ratios():
    with pytest.raises(ValueError):
        assign_splits(["a"], {"a": "a"}, {"a": "s"}, {"train": 0.8, "val": 0.1}, 1)

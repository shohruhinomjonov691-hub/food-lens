"""Duplicate detection helpers: exact (checksum) and near (perceptual-hash Hamming distance)."""
from collections import defaultdict

from food_lens.imaging import hamming


class UnionFind:
    def __init__(self, items):
        self.parent = {item: item for item in items}

    def find(self, item):
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != root:
            self.parent[item], item = root, self.parent[item]
        return root

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Smallest id becomes the root, so results do not depend on input order.
            ra, rb = sorted((ra, rb))
            self.parent[rb] = ra

    def groups(self):
        result = defaultdict(list)
        for item in self.parent:
            result[self.find(item)].append(item)
        return {root: sorted(members) for root, members in result.items()}


def near_pairs(hashes, max_distance):
    """All pairs (a, b, distance) with a < b and Hamming distance <= max_distance.

    hashes: dict id -> 64-bit int. Brute force is fine for a few thousand images.
    """
    ids = sorted(hashes)
    values = [hashes[i] for i in ids]
    pairs = []
    for i, a in enumerate(values):
        for j in range(i + 1, len(values)):
            d = hamming(a, values[j])
            if d <= max_distance:
                pairs.append((ids[i], ids[j], d))
    return pairs


def summarize_groups(pairs, ids):
    """Number of pairs, groups (connected components with >1 member) and redundant files."""
    uf = UnionFind(ids)
    for a, b, _ in pairs:
        uf.union(a, b)
    groups = [g for g in uf.groups().values() if len(g) > 1]
    return {"pairs": len(pairs), "groups": len(groups), "redundant_files": sum(len(g) - 1 for g in groups)}

import copy
import hashlib

import pytest

from food_lens.manifest import MANIFEST_COLUMNS, validate
from scripts.prepare_manifest import NeedsReview, build

CONFIG = {
    "seed": 42,
    "ratios": {"train": 0.7, "val": 0.15, "test": 0.15},
    "near_duplicate": {"remove_max_distance": 2, "group_max_distance": 8},
    "excluded_drive_folders": {"kebab": "Bing, license not verified", "plov": "out of scope"},
    "manual_exclusions": [],
    "cross_class_reviewed": [],
}


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def far_hash(i):
    """Hashes that are pairwise far apart (> 8 bits)."""
    return int(hashlib.sha256(f"h{i}".encode()).hexdigest()[:16], 16)


def drive(folder, name, phash, content=None, decode_ok=True):
    return {"folder": folder, "name": name, "sha256": sha(content or f"{folder}/{name}"),
            "phash": f"{phash:016x}", "decode_ok": str(decode_ok), "error": "" if decode_ok else "decode: bad"}


def official(row, split="train", sha256=None):
    return {"folder": row["folder"], "name": row["name"], "official_split": split,
            "sha256": sha256 or row["sha256"]}


def commons(pageid, phash, variant="skewered"):
    return {"pageid": str(pageid), "variant": variant, "original_url": f"https://upload.wikimedia.org/wikipedia/commons/a/ab/K{pageid}.jpg",
            "original_sha1": hashlib.sha1(str(pageid).encode()).hexdigest(), "phash": f"{phash:016x}",
            "author": "Someone", "license": "CC BY-SA 4.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/4.0",
            "page_url": f"https://commons.wikimedia.org/wiki/File:K{pageid}.jpg"}


@pytest.fixture
def dataset():
    rows, off = [], []
    i = 0
    for folder in ("cheesecake", "chocolate_cake", "hamburger", "hot_dog", "pizza"):
        for n in range(40):
            i += 1
            r = drive(folder, f"{100000 + i}.jpg", far_hash(i))
            rows.append(r)
            off.append(official(r, "test" if n % 4 == 0 else "train"))
    variants = ("skewered", "minced_skewer", "doner_shawarma")
    kebab = [commons(5000 + k, far_hash(1000 + k), variants[k % 3]) for k in range(60)]
    return rows, off, kebab


def run(rows, off, kebab, config=CONFIG):
    included, exclusions, stats = build(rows, off, kebab, copy.deepcopy(config))
    assert validate([{c: r.get(c, "") for c in MANIFEST_COLUMNS} for r in included], exclusions) == []
    return included, exclusions, stats


def reasons(exclusions):
    return {e["location"]: e["reason"] for e in exclusions}


def test_clean_dataset(dataset):
    included, exclusions, stats = run(*dataset)
    assert len(included) == 260 and exclusions == []
    assert stats["per_class"]["dessert"]["total"] == 80
    assert stats["per_class"]["kebab"]["total"] == 60
    # Each kebab variant (20 images) is split on its own: 14 / 3 / 3.
    for v in ("skewered", "minced_skewer", "doner_shawarma"):
        assert stats["per_variant"][f"kebab/{v}"] == {"train": 14, "val": 3, "test": 3}
    assert stats["per_variant"]["dessert/cheesecake"] == {"train": 28, "val": 6, "test": 6}
    assert stats["food101_provenance"] == {"byte_identical": 200}
    assert {r["official_split"] for r in included if r["source"] == "food101"} == {"train", "test"}


def test_excluded_folders_and_bad_files(dataset):
    rows, off, kebab = dataset
    rows += [drive("kebab", "Image_1.jpg", far_hash(9001)), drive("plov", "Image_2.jpg", far_hash(9002)),
             drive("sushi", "1.jpg", far_hash(9003))]
    bad = drive("pizza", "999.jpg", far_hash(9004), decode_ok=False)
    rows.append(bad)
    off.append(official(bad))
    _, exclusions, _ = run(rows, off, kebab)
    r = reasons(exclusions)
    assert r["kebab/Image_1.jpg"].startswith("Bing")
    assert r["plov/Image_2.jpg"] == "out of scope"
    assert r["sushi/1.jpg"] == "folder not mapped to a class"
    assert r["pizza/999.jpg"].startswith("decode failed")


def test_provenance_mismatch_and_missing(dataset):
    rows, off, kebab = dataset
    off[0] = official(rows[0], sha256=sha("something else"))
    del off[1]
    included, exclusions, stats = run(rows, off, kebab)
    r = reasons(exclusions)
    assert r[f"cheesecake/{rows[0]['name']}"] == "bytes differ from the official Food-101 file"
    assert r[f"cheesecake/{rows[1]['name']}"] == "not found in the official Food-101 archive"
    assert stats["food101_provenance"] == {"byte_identical": 198, "bytes_differ": 1, "missing_from_official": 1}


def test_exact_and_near_duplicates_are_counted_and_removed(dataset):
    rows, off, kebab = dataset
    base = rows[100]  # hamburger
    exact = drive("hamburger", "999001.jpg", far_hash(7000), content=f"hamburger/{base['name']}")
    triple = [drive("chocolate_cake", f"99900{k}.jpg", 0xABCDEF0123456789 ^ k) for k in (2, 3, 6)]  # d <= 2
    grouped = drive("hot_dog", "999010.jpg", int(rows[140]["phash"], 16) ^ 0b11111)  # d = 5 -> grouped
    for r in (exact, *triple, grouped):
        rows.append(r)
        off.append(official(r))
    included, exclusions, stats = run(rows, off, kebab)
    r = reasons(exclusions)
    assert r["hamburger/999001.jpg"].startswith("exact duplicate of hamburger/")
    kept = [t for t in triple if f"chocolate_cake/{t['name']}" not in r]
    assert len(kept) == 1
    assert stats["exact_duplicates"] == {"pairs": 1, "groups": 1, "redundant_files": 1}
    assert stats["near_duplicates"]["same_class_removable"] == {"pairs": 3, "groups": 1, "redundant_files": 2}
    by_loc = {x["location"]: x for x in included}
    a, b = by_loc[f"hot_dog/{rows[140]['name']}"], by_loc["hot_dog/999010.jpg"]
    assert a["group_id"] == b["group_id"] and a["split"] == b["split"]


def test_cross_class_pair_requires_review(dataset):
    rows, off, kebab = dataset
    kebab.append(commons(6000, int(rows[100]["phash"], 16) ^ 0b111))  # kebab ~ hamburger, d = 3
    with pytest.raises(NeedsReview, match="hamburger/"):
        build(rows, off, kebab, copy.deepcopy(CONFIG))
    config = copy.deepcopy(CONFIG)
    config["cross_class_reviewed"] = [{"a": f"hamburger/{rows[100]['name']}", "b": kebab[-1]["original_url"],
                                       "decision": "exclude_both", "note": "same photo"}]
    included, exclusions, _ = run(rows, off, kebab, config)
    assert len([e for e in exclusions if "cross-class" in e["reason"]]) == 2
    config["cross_class_reviewed"][0]["decision"] = "keep_grouped"
    included, _, _ = run(rows, off, kebab, config)
    by_loc = {x["location"]: x for x in included}
    assert by_loc[f"hamburger/{rows[100]['name']}"]["split"] == by_loc[kebab[-1]["original_url"]]["split"]


def test_manual_exclusion(dataset):
    rows, off, kebab = dataset
    config = copy.deepcopy(CONFIG)
    config["manual_exclusions"] = [{"location": kebab[0]["original_url"], "reason": "not kebab"}]
    included, exclusions, _ = run(rows, off, kebab, config)
    assert reasons(exclusions)[kebab[0]["original_url"]] == "not kebab"
    assert len(included) == 259


def test_deterministic(dataset):
    first = run(*copy.deepcopy(dataset))[0]
    second = run(*copy.deepcopy(dataset))[0]
    assert [(r["location"], r["split"]) for r in first] == [(r["location"], r["split"]) for r in second]

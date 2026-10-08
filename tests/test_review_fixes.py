"""Regression tests for the Codex review of develop@28f2ab1 (one block per finding)."""
import copy
import csv
import json
import random
from pathlib import Path

import pytest

from food_lens.commons import DERIVED_HINT, canonical_author
from food_lens.kebab import kebab_variant
from food_lens.manifest import MANIFEST_COLUMNS, validate
from food_lens.split import assign_splits, quota_report
from scripts.prepare_manifest import NeedsReview, build
from tests.test_prepare_manifest import CONFIG, commons, drive, far_hash, official

ROOT = Path(__file__).resolve().parent.parent


def run(rows, off, kebab, config):
    included, exclusions, stats = build(rows, off, kebab, copy.deepcopy(config))
    assert validate([{c: r.get(c, "") for c in MANIFEST_COLUMNS} for r in included], exclusions) == []
    return included, exclusions, stats


def assert_far_apart(hashes, limit=8):
    """Fixture guard: no two fixture images may be pHash look-alikes by accident."""
    from food_lens.imaging import hamming
    close = [(a, b) for i, a in enumerate(hashes) for b in hashes[i + 1:] if hamming(a, b) <= limit]
    assert close == [], "fixture hashes collide"


def base(n=40):
    rows, off = [], []
    for i in range(n):
        r = drive("pizza", f"{500000 + i}.jpg", far_hash(i))
        rows.append(r)
        off.append(official(r))
    return rows, off


# Finding 1/4: re-checked decisions — no meatless accepts, tavuk şiş is skewered pieces.
def read(path):
    with open(ROOT / path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_rechecked_meatless_files_are_not_accepted():
    accepted = {r["pageid"]: r for r in read("manifests/kebab_commons.csv")}
    for pid in ("102957676", "40988311", "150126227", "37456407", "8189733"):
        assert pid not in accepted
    assert accepted["42996937"]["variant"] == "skewered"


def test_review_history_is_kept():
    review = {r["pageid"]: r for r in read("manifests/kebab_commons_review.csv")}
    veg = review["102957676"]
    assert veg["decision"] == "reject" and veg["initial_decision"] == "accept" and "evidence" in veg["reason"]
    tavuk = review["42996937"]
    assert tavuk["initial_variant"] == "minced_skewer" and tavuk["variant"] == "skewered"
    config = json.loads((ROOT / "config/kebab_review.json").read_text(encoding="utf-8"))
    assert config["variant_override"]["42996937"] == "minced_skewer"  # original override still recorded


@pytest.mark.parametrize("category", ["Category:Kebab-e barg", "Category:Tavuk şiş", "Category:Jujeh Kabab",
                                      "Category:Chicken kebabs", "Category:Shish taouk"])
def test_minced_regex_negatives(category):
    assert kebab_variant("Category:Skewered kebabs", category) == "skewered"


# Finding 2: dedup must not break a connected component through a removed "bridge".
def test_bridge_removed_by_dedup_keeps_component_in_one_split():
    rows, off = base()
    a, b, c = (drive("pizza", n, h) for n, h in (("900001.jpg", 0), ("900002.jpg", 3), ("900003.jpg", 1023)))
    for r in (a, b, c):
        rows.append(r)
        off.append(official(r))
    for seed in range(20):
        config = {**CONFIG, "seed": seed}
        included, exclusions, _ = run(rows, off, [], config)
        by_loc = {r["location"]: r for r in included}
        assert "pizza/900002.jpg" in {e["location"] for e in exclusions}       # B (d=2 from A) removed
        ra, rc = by_loc["pizza/900001.jpg"], by_loc["pizza/900003.jpg"]
        assert ra["group_id"] == rc["group_id"] and ra["split"] == rc["split"]


# Finding 3: derived copies (crops) and author aliases.
def crop_case():
    rows, off = base()
    orig = commons(2978616, far_hash(77), "doner_shawarma")
    crop = commons(20326189, far_hash(78), "doner_shawarma")          # pHash far apart, like the real pair
    orig.update(title="File:Doner kebap Istanbul 20071026.JPG", author="Pvasiliadis", credit="Own work")
    crop.update(title="File:Doner kebap Istanbul 20071026 crop.JPG",
                author="Pvasiliadis ; cropped by Beyond My Ken ( talk )", credit="Own work")
    return rows, off, [orig, crop]


def test_unlisted_crop_needs_review():
    with pytest.raises(NeedsReview, match="commons:20326189"):
        build(*crop_case(), copy.deepcopy(CONFIG))


def test_listed_crop_is_excluded():
    config = {**CONFIG, "derived_copies": [{"copy": "commons:20326189", "original": "commons:2978616",
                                            "reason": "crop"}]}
    included, exclusions, stats = run(*crop_case(), config)
    assert "commons:20326189" not in {r["sample_id"] for r in included}
    assert any(e["reason"].startswith("derived copy (crop) of") for e in exclusions)
    assert stats["derived_copies_removed"] == 1


@pytest.mark.parametrize("a, b", [
    ("Pvasiliadis", "Pvasiliadis ; cropped by Beyond My Ken ( talk ) 05:12"),
    ("E4024", "  e4024 "),
    ("Lakerda", "Iskender_kebap.jpg : The original uploader was Lakerda at Turkish Wikipedia."),
    ("Mizu basyo", "Mizu basyo at Japanese Wikipedia"),
    ("Spacekid", "User:Spacekid"),
])
def test_canonical_author(a, b):
    assert canonical_author(a) == canonical_author(b)


def test_author_alias_map():
    assert canonical_author("Jane P.", {"Jane P.": "jdoe"}) == canonical_author("JDoe")


def test_author_series_grouped_by_canonical_id():
    rows, off = base()
    kebab = [commons(7000 + k, far_hash(3000 + k), "skewered") for k in range(30)]
    for k, name in enumerate(["Pvasiliadis", "pvasiliadis ", "Pvasiliadis ; cropped by X ( talk )"]):
        kebab[k]["author"] = name
    # The "cropped by" credit trips the derived guard; this test is about authors, so record a review.
    config = {**CONFIG, "group_commons_by_author": True,
              "derived_reviewed": [{"sample_id": "commons:7002", "note": "test: crop credit, original not a candidate"}]}
    included, _, _ = run(rows, off, kebab, config)
    same = [r for r in included if r["sample_id"] in {f"commons:{7000 + k}" for k in range(3)}]
    assert len({r["group_id"] for r in same}) == 1 and len({r["split"] for r in same}) == 1


def test_derived_hint():
    assert DERIVED_HINT.search("File:Kawap (cropped).jpg")
    assert DERIVED_HINT.search("File:Doner kebap Istanbul 20071026 crop.JPG")
    assert not DERIVED_HINT.search("File:Shashlik-3.jpg")


# Manual exclusion removes the other copies too.
def test_manual_exclusion_removes_copies():
    rows, off = base()
    flyer = drive("pizza", "800001.jpg", far_hash(90), content="flyer")
    copy_exact = drive("pizza", "800002.jpg", far_hash(91), content="flyer")
    copy_near = drive("pizza", "800003.jpg", far_hash(90) ^ 1)
    for r in (flyer, copy_exact, copy_near):
        rows.append(r)
        off.append(official(r))
    config = {**CONFIG, "manual_exclusions": [{"location": "pizza/800001.jpg", "reason": "not food"}]}
    included, exclusions, _ = run(rows, off, [], config)
    reasons = {e["location"]: e["reason"] for e in exclusions}
    assert reasons["pizza/800002.jpg"] == "copy of manually excluded pizza/800001.jpg"
    assert reasons["pizza/800003.jpg"] == "copy of manually excluded pizza/800001.jpg"


# Finding 5: mixed-variant groups use the variant-count vector.
def test_mixed_variant_groups_reach_quota():
    items, groups, strata = [], {}, {}
    for k in range(10):                      # ten groups, each holds one A and one B image
        for v in ("A", "B"):
            item = f"{v}{k}"
            items.append(item)
            groups[item], strata[item] = f"g{k}", v
    splits = assign_splits(items, groups, strata, {"train": 0.6, "val": 0.2, "test": 0.2}, 42)
    for v in ("A", "B"):
        counts = {s: sum(1 for i in items if strata[i] == v and splits[i] == s) for s in ("train", "val", "test")}
        assert counts == {"train": 6, "val": 2, "test": 2}
    for k in range(10):
        assert splits[f"A{k}"] == splits[f"B{k}"]


def test_groups_are_never_cut_and_shortfall_is_reported():
    items = [f"k{i}" for i in range(20)]
    groups = {i: "big" if int(i[1:]) < 15 else i for i in items}   # one 15-image series + 5 singles
    strata = {i: "doner" for i in items}
    ratios = {"train": 0.5, "val": 0.25, "test": 0.25}
    splits = assign_splits(items, groups, strata, ratios, 1)
    assert len({splits[i] for i in items if groups[i] == "big"}) == 1
    report = quota_report(items, groups, strata, splits, ratios, {"doner": 5})
    row = report["doner"]
    assert row["minimum_met"] is False and "never split" in row["reason"] and "[15]" in row["reason"]


def test_hamburger_hot_dog_pair_does_not_steal_quota():
    rows, off = [], []
    # Fixed, distinct indices (no hash(): it is salted per process and produced pHash look-alikes).
    for f, folder in enumerate(("hamburger", "hot_dog")):
        for i in range(40):
            r = drive(folder, f"{folder}{i}.jpg", far_hash(20000 + 100 * f + i))
            rows.append(r)
            off.append(official(r))
    assert_far_apart([int(r["phash"], 16) for r in rows])
    pair = int(rows[0]["phash"], 16)
    twin = drive("hot_dog", "twin.jpg", pair ^ 0b1111111)       # d=7 cross-class look-alike
    rows.append(twin)
    off.append(official(twin))
    config = {**CONFIG, "cross_class_reviewed": [{"a": f"hamburger/{rows[0]['name']}", "b": "hot_dog/twin.jpg",
                                                  "decision": "keep_grouped", "note": "different photos"}]}
    _, _, stats = run(rows, off, [], config)
    for v in ("hamburger", "hot_dog"):
        q = stats["quota_check"][v]
        assert (q["val"], q["test"]) == (q["target_val"], q["target_test"])


# Finding 6 + determinism: shuffled inputs give byte-identical outputs.
def test_shuffled_inputs_same_result():
    rows, off = base(60)
    kebab = [commons(8000 + k, far_hash(4000 + k), ("skewered", "minced_skewer", "doner_shawarma")[k % 3])
             for k in range(45)]
    first = run(rows, off, kebab, {**CONFIG, "group_commons_by_author": True})
    rng = random.Random(3)
    for lst in (rows, off, kebab):
        rng.shuffle(lst)
    second = run(rows, off, kebab, {**CONFIG, "group_commons_by_author": True})
    key = lambda res: [(r["location"], r["group_id"], r["split"]) for r in res[0]]
    assert key(first) == key(second) and first[2] == second[2]


def test_committed_stats_meet_minimums():
    stats = json.loads((ROOT / "manifests/stats_v1.json").read_text(encoding="utf-8"))
    for v in ("skewered", "minced_skewer", "doner_shawarma"):
        assert stats["quota_check"][v]["minimum_met"] is True
    assert stats["derived_copies_removed"] == 2


# Follow-up review (develop@6840542), finding 2: manual exclusions on the full graph.
def add(rows, off, name, phash, folder="pizza"):
    r = drive(folder, name, phash)
    rows.append(r)
    off.append(official(r))
    return f"{folder}/{name}"


def test_manual_exclusion_spreads_over_duplicate_component():
    rows, off = base()
    a = add(rows, off, "910001.jpg", 0)       # A, manual
    b = add(rows, off, "910002.jpg", 3)       # d(A,B) = 2
    c = add(rows, off, "910003.jpg", 15)      # d(B,C) = 2, d(A,C) = 4
    config = {**CONFIG, "manual_exclusions": [{"location": a, "reason": "not food"}]}
    included, exclusions, _ = run(rows, off, [], config)
    reasons = {e["location"]: e["reason"] for e in exclusions}
    assert reasons[a] == "not food"
    assert reasons[b] == reasons[c] == f"copy of manually excluded {a}"
    assert not {b, c} & {r["location"] for r in included}


@pytest.mark.parametrize("seed", range(20))
def test_manual_bridge_keeps_group(seed):
    rows, off = base()
    a = add(rows, off, "920001.jpg", 255)     # d(A,B) = 8
    b = add(rows, off, "920002.jpg", 0)       # B, manual (the bridge)
    c = add(rows, off, "920003.jpg", 65280)   # d(B,C) = 8, d(A,C) = 16
    config = {**CONFIG, "seed": seed, "manual_exclusions": [{"location": b, "reason": "not food"}]}
    included, _, _ = run(rows, off, [], config)
    by_loc = {r["location"]: r for r in included}
    assert by_loc[a]["group_id"] == by_loc[c]["group_id"] and by_loc[a]["split"] == by_loc[c]["split"]


def test_remove_and_group_thresholds_are_separate():
    rows, off = base()
    a = add(rows, off, "930001.jpg", 0)
    b = add(rows, off, "930002.jpg", 0b111111)   # d = 6: grouped, not removed
    included, exclusions, _ = run(rows, off, [], CONFIG)
    by_loc = {r["location"]: r for r in included}
    assert a in by_loc and b in by_loc and by_loc[a]["group_id"] == by_loc[b]["group_id"]
    with pytest.raises(ValueError):
        build(rows, off, [], {**CONFIG, "near_duplicate": {"remove_max_distance": 9, "group_max_distance": 8}})


# Finding 3: derived copies are never accepted silently.
def test_crop_of_manually_excluded_original_needs_review():
    rows, off, kebab = crop_case()
    config = {**CONFIG, "derived_copies": [{"copy": "commons:20326189", "original": "commons:2978616",
                                            "reason": "crop"}],
              "manual_exclusions": [{"location": kebab[0]["original_url"], "reason": "not kebab"}]}
    with pytest.raises(NeedsReview, match="commons:20326189 \\(original commons:2978616 excluded\\)"):
        build(rows, off, kebab, copy.deepcopy(config))
    # An explicit exclusion of the copy, or an evidenced review, resolves it.
    config["manual_exclusions"].append({"location": kebab[1]["original_url"], "reason": "crop of excluded"})
    run(rows, off, kebab, config)


def test_crop_with_missing_original_needs_review_unless_reviewed():
    rows, off, kebab = crop_case()
    kebab = kebab[1:]                                            # original is not a candidate
    config = {**CONFIG, "derived_copies": [{"copy": "commons:20326189", "original": "commons:2978616",
                                            "reason": "crop"}]}
    with pytest.raises(NeedsReview, match="not a candidate"):
        build(rows, off, kebab, copy.deepcopy(config))
    config["derived_reviewed"] = [{"sample_id": "commons:20326189", "note": ""}]
    with pytest.raises(NeedsReview, match="needs a note/evidence"):
        build(rows, off, kebab, copy.deepcopy(config))
    config["derived_reviewed"] = [{"sample_id": "commons:20326189", "note": "original not available; crop kept"}]
    included, _, _ = run(rows, off, kebab, config)
    assert "commons:20326189" in {r["sample_id"] for r in included}


def test_crop_hint_in_author_needs_review():
    rows, off = base()
    k = commons(9100, far_hash(9100))
    k.update(title="File:Food.jpg", credit="Own work", author="Photographer ; cropped by Editor")
    with pytest.raises(NeedsReview, match="commons:9100"):
        build(rows, off, [k], copy.deepcopy(CONFIG))
    k.update(author="Photographer", credit="This file was derived from: Food original.jpg")
    with pytest.raises(NeedsReview, match="commons:9100"):
        build(rows, off, [k], copy.deepcopy(CONFIG))


# Finding 4: full names from the Wikipedia wrapper; no merge of different people.
@pytest.mark.parametrize("a, b, same", [
    ("The original uploader was John Smith at English Wikipedia", "The original uploader was John Jones at "
     "English Wikipedia", False),
    ("The original uploader was John Smith at English Wikipedia.", "John Smith", True),
    ("The original uploader was J. R. Smith at English Wikipedia", "J. R. Smith", True),
    ("John from Paris", "John from Rome", False),
    ("Ninara", "Ninara from Helsinki, Finland", False),      # needs an evidenced alias, not a heuristic
])
def test_canonical_author_boundaries(a, b, same):
    assert (canonical_author(a) == canonical_author(b)) is same


# Finding 5: a configured minimum for a variant that has no images is reported.
def test_quota_report_includes_absent_variant():
    report = quota_report(["a1", "a2"], {"a1": "a1", "a2": "a2"}, {"a1": "skewered", "a2": "skewered"},
                          {"a1": "train", "a2": "train"}, {"train": 0.7, "val": 0.15, "test": 0.15},
                          {"skewered": 1, "doner_shawarma": 9})
    row = report["doner_shawarma"]
    assert (row["total"], row["val"], row["test"], row["minimum_met"]) == (0, 0, 0, False)
    assert "absent" in row["reason"]

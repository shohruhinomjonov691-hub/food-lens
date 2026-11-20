"""Evaluation summary shown to users, built ONLY from the verified run folder (never typed in by hand):

- test_metrics.json (checked by app.model.check_test_metrics): accuracy, macro-F1, per class, per variant, CI;
- test_predictions.csv (optional): the test predictions, used to describe how the result tiers behave on the test split.

The tier boundaries were not tuned on the test split. The tier table is a description of the single test run
that already exists; it does not select anything.
"""
import csv
import math
import os

from food_lens.classes import CLASSES

SMALL_N = 30   # fewer test images than this: the estimate is shown with a "small sample" flag

# Limitations that hold for this run and are stated in the README ("Known limitations", "Not evaluated").
STATIC_LIMITS = ("five_classes_only", "non_food_not_evaluated", "phone_photos_not_evaluated")


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def tier_table(rows, threshold, high_threshold):
    """rows: [(target, predicted, confidence)] -> counts and accuracy of the top-1 per tier."""
    out = {t: {"n": 0, "correct": 0} for t in ("high", "low", "abstain")}
    for target, pred, conf in rows:
        t = "abstain" if conf < threshold else "high" if conf >= high_threshold else "low"
        out[t]["n"] += 1
        out[t]["correct"] += int(target == pred)
    total = sum(v["n"] for v in out.values())
    return {t: {"n": v["n"], "share": v["n"] / total if total else None,
                "accuracy": v["correct"] / v["n"] if v["n"] else None} for t, v in out.items()}


def read_test_predictions(run_dir, expected_n):
    """Parse test_predictions.csv; returns rows or None when the file is missing or does not look right."""
    path = os.path.join(run_dir, "test_predictions.csv")
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8", newline="") as f:
            rows = []
            for r in csv.DictReader(f):
                conf = float(r["confidence"])
                if r["target"] not in CLASSES or r["predicted"] not in CLASSES or not 0.0 <= conf <= 1.0:
                    return None
                rows.append((r["target"], r["predicted"], conf))
    except (OSError, ValueError, KeyError, UnicodeDecodeError, csv.Error):
        return None
    return rows if len(rows) == expected_n else None


def build_evaluation(run_dir, metrics, run_name, threshold, high_threshold):
    per_class = []
    for dish, counts in zip(CLASSES, metrics["confusion_matrix"]):
        row = metrics["per_class"][dish]
        support = sum(counts)
        per_class.append({
            "class": dish, "precision": _num(row["precision"]), "recall": _num(row["recall"]),
            "f1": _num(row["f1"]), "support": support, "small_n": support < SMALL_N,
        })
    variants = []
    for v in metrics.get("per_variant", []) if isinstance(metrics.get("per_variant"), list) else []:
        if isinstance(v, dict) and v.get("target") in CLASSES and isinstance(v.get("n"), int) and _num(v.get("recall")) is not None:
            variants.append({"target": v["target"], "variant": str(v.get("variant")), "n": v["n"],
                             "recall": float(v["recall"]), "small_n": v["n"] < SMALL_N})
    ci = metrics.get("bootstrap_95ci") if isinstance(metrics.get("bootstrap_95ci"), dict) else {}

    def pair(key):
        p = ci.get(key)
        return [float(x) for x in p] if isinstance(p, list) and len(p) == 2 and all(_num(x) is not None for x in p) else None

    rows = read_test_predictions(run_dir, metrics["n"])
    limits = list(STATIC_LIMITS)
    if any(v["small_n"] for v in variants):
        limits.append("small_variant_test")
    if any(c["small_n"] for c in per_class):
        limits.append("small_class_test")
    return {
        "run": run_name, "n": metrics["n"], "accuracy": float(metrics["accuracy"]), "macro_f1": float(metrics["macro_f1"]),
        "ci": {"accuracy": pair("accuracy"), "macro_f1": pair("macro_f1"), "subset_recall": pair("subset_recall")},
        "per_class": per_class, "per_variant": variants,
        "thresholds": {"abstain_below": threshold, "high_from": high_threshold},
        "tiers": tier_table(rows, threshold, high_threshold) if rows is not None else None,
        "limits": limits,
        "note": "Test split used once; tier boundaries were not tuned on it.",
    }

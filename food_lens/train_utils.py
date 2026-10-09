"""Training/evaluation helpers that do not need torch (tested locally; used by the Colab notebook).

Metrics, temperature scaling, the "not sure" threshold, bootstrap intervals, checksums and run
folders that are never overwritten.
"""
import hashlib
import json
import math
import os

import numpy as np


# ---------- class balance ----------

def class_weights(counts):
    """Inverse-frequency weights normalised so a balanced dataset gets 1.0: w_c = N / (K * n_c)."""
    counts = np.asarray(counts, dtype=np.float64)
    if (counts <= 0).any():
        raise ValueError(f"every class needs training images: {counts.tolist()}")
    return counts.sum() / (len(counts) * counts)


# ---------- metrics ----------

def confusion_matrix(y_true, y_pred, k):
    cm = np.zeros((k, k), dtype=np.int64)
    np.add.at(cm, (np.asarray(y_true), np.asarray(y_pred)), 1)
    return cm  # rows = true class, columns = predicted class


def per_class(cm):
    """Precision, recall, F1 and support per class from a confusion matrix (0 when undefined)."""
    tp = np.diag(cm).astype(np.float64)
    pred = cm.sum(axis=0).astype(np.float64)
    support = cm.sum(axis=1).astype(np.float64)
    precision = np.divide(tp, pred, out=np.zeros_like(tp), where=pred > 0)
    recall = np.divide(tp, support, out=np.zeros_like(tp), where=support > 0)
    denom = precision + recall
    f1 = np.divide(2 * precision * recall, denom, out=np.zeros_like(tp), where=denom > 0)
    return precision, recall, f1, support.astype(np.int64)


def summary(y_true, y_pred, k):
    cm = confusion_matrix(y_true, y_pred, k)
    precision, recall, f1, support = per_class(cm)
    present = support > 0
    return {
        "n": int(cm.sum()),
        "accuracy": float(np.trace(cm) / cm.sum()) if cm.sum() else 0.0,
        "macro_f1": float(f1[present].mean()) if present.any() else 0.0,
        "precision": precision.tolist(), "recall": recall.tolist(), "f1": f1.tolist(),
        "support": support.tolist(), "confusion_matrix": cm.tolist(),
    }


# ---------- probabilities and calibration ----------

def softmax(logits, temperature=1.0):
    z = np.asarray(logits, dtype=np.float64) / temperature
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def nll(logits, labels, temperature=1.0):
    """Mean negative log-likelihood, computed exactly with log-sum-exp (no probability clipping)."""
    z = np.asarray(logits, dtype=np.float64) / temperature
    labels = np.asarray(labels)
    m = z.max(axis=1, keepdims=True)
    log_norm = (m + np.log(np.exp(z - m).sum(axis=1, keepdims=True)))[:, 0]
    return float((log_norm - z[np.arange(len(labels)), labels]).mean())


def fit_temperature(logits, labels, low=0.05, high=20.0, iters=100):
    """Temperature T in [low, high] minimising validation NLL.

    Golden-section search on log T, then the interval ends are compared too, so a minimum at a
    boundary (NLL still falling at `high`, or rising from `low`) is returned instead of an inner point.
    """
    a, b = math.log(low), math.log(high)
    g = (math.sqrt(5) - 1) / 2
    c, d = b - g * (b - a), a + g * (b - a)
    fc, fd = nll(logits, labels, math.exp(c)), nll(logits, labels, math.exp(d))
    for _ in range(iters):
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - g * (b - a)
            fc = nll(logits, labels, math.exp(c))
        else:
            a, c, fc = c, d, fd
            d = a + g * (b - a)
            fd = nll(logits, labels, math.exp(d))
    candidates = [math.exp((a + b) / 2), low, high]
    return min(candidates, key=lambda t: (nll(logits, labels, t), t))


def ece(probs, labels, bins=15):
    """Expected calibration error of the top-1 confidence."""
    probs = np.asarray(probs)
    conf, pred = probs.max(axis=1), probs.argmax(axis=1)
    correct = (pred == np.asarray(labels)).astype(np.float64)
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (conf > lo) & (conf <= hi)
        if mask.any():
            total += mask.mean() * abs(correct[mask].mean() - conf[mask].mean())
    return float(total)


def select_threshold(probs, labels, target_accuracy):
    """Smallest confidence threshold whose confident predictions reach target accuracy on val.

    A prediction is "not sure" when its top-1 probability is below the threshold. Among thresholds
    that reach the target, the smallest one keeps the most predictions (highest coverage). If none
    reaches it, the threshold with the best selective accuracy is returned and flagged.
    """
    probs = np.asarray(probs)
    conf = probs.max(axis=1)
    correct = probs.argmax(axis=1) == np.asarray(labels)
    best = None
    for t in np.unique(np.concatenate([[0.0], conf])):
        keep = conf >= t
        if not keep.any():
            continue
        acc = float(correct[keep].mean())
        row = {"threshold": float(t), "selective_accuracy": acc, "coverage": float(keep.mean())}
        if acc >= target_accuracy:
            return {**row, "target_accuracy": target_accuracy, "target_met": True}
        if best is None or acc > best["selective_accuracy"]:
            best = row
    return {**best, "target_accuracy": target_accuracy, "target_met": False}


def selective(probs, labels, threshold):
    probs = np.asarray(probs)
    keep = probs.max(axis=1) >= threshold
    correct = probs.argmax(axis=1) == np.asarray(labels)
    return {"coverage": float(keep.mean()), "uncertain_rate": float(1 - keep.mean()),
            "selective_accuracy": float(correct[keep].mean()) if keep.any() else 0.0}


# ---------- uncertainty of small test sets ----------

def bootstrap_ci(y_true, y_pred, k, n_boot=1000, seed=0, alpha=0.05, mask=None):
    """Percentile bootstrap CIs for accuracy and macro-F1 (optionally recall on a subset `mask`)."""
    rng = np.random.default_rng(seed)
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    n = len(y_true)
    acc, mf1, sub = [], [], []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        s = summary(y_true[idx], y_pred[idx], k)
        acc.append(s["accuracy"])
        mf1.append(s["macro_f1"])
        if mask is not None:
            m = np.asarray(mask)[idx]
            if m.any():
                sub.append(float((y_true[idx][m] == y_pred[idx][m]).mean()))
    q = lambda v: [float(np.quantile(v, alpha / 2)), float(np.quantile(v, 1 - alpha / 2))] if v else None
    return {"accuracy": q(acc), "macro_f1": q(mf1), "subset_recall": q(sub), "n_boot": n_boot, "seed": seed}


# ---------- run lock ----------

LOCK_FILES = ("final.json", "test_metrics.json", "test_predictions.csv")


class RunLocked(RuntimeError):
    pass


def assert_unlocked(run_dir):
    """Raise if the run's final choice is locked or its test split was used; nothing may change then."""
    present = [name for name in LOCK_FILES if os.path.exists(os.path.join(run_dir, name))]
    if present:
        raise RunLocked(f"run is locked ({', '.join(present)} exists): refusing to write training outputs")


def guarded_write_bytes(run_dir, name, data):
    """Atomically write a training output (checkpoint, history) unless the run is locked."""
    assert_unlocked(run_dir)
    path = os.path.join(run_dir, name)
    with open(path + ".tmp", "wb") as f:
        f.write(data)
    os.replace(path + ".tmp", path)


# ---------- files ----------

def file_digest(path, algorithm):
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def checksum_ok(data, checksum):
    """`checksum` is 'sha256:<hex>' or 'sha1:<hex>' as in the manifest."""
    algorithm, expected = checksum.split(":", 1)
    if algorithm not in ("sha256", "sha1"):
        raise ValueError(f"unsupported checksum {checksum!r}")
    return hashlib.new(algorithm, data).hexdigest() == expected


def new_run_dir(root, name):
    """Create root/name; refuse if it exists, so an earlier run is never overwritten."""
    path = os.path.join(root, name)
    os.makedirs(root, exist_ok=True)
    os.makedirs(path, exist_ok=False)
    return path


def write_json(path, data, overwrite=False):
    if os.path.exists(path) and not overwrite:
        raise FileExistsError(f"refusing to overwrite {path}")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)

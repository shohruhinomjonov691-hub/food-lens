import numpy as np
import pytest

from food_lens import train_utils as tu


def test_class_weights_balance_the_loss():
    w = tu.class_weights([1398, 698, 697, 256, 699])
    assert np.isclose((w * np.array([1398, 698, 697, 256, 699])).sum(), 3748)   # sum of w_c * n_c = N
    assert w.argmax() == 3 and w.argmin() == 0                                  # kebab heaviest, dessert lightest
    assert np.allclose(tu.class_weights([10, 10]), [1, 1])
    with pytest.raises(ValueError):
        tu.class_weights([5, 0])


def test_summary_and_per_class():
    y_true = [0, 0, 1, 1, 2, 2]
    y_pred = [0, 1, 1, 1, 2, 0]
    s = tu.summary(y_true, y_pred, 3)
    assert s["confusion_matrix"] == [[1, 1, 0], [0, 2, 0], [1, 0, 1]]
    assert s["accuracy"] == pytest.approx(4 / 6)
    assert s["precision"] == pytest.approx([0.5, 2 / 3, 1.0])
    assert s["recall"] == pytest.approx([0.5, 1.0, 0.5])
    assert s["macro_f1"] == pytest.approx(np.mean([0.5, 0.8, 2 / 3]))
    assert s["support"] == [2, 2, 2]


def test_temperature_recovers_overconfidence():
    rng = np.random.default_rng(0)
    labels = rng.integers(0, 5, 4000)
    true_logits = rng.normal(0, 1, (4000, 5))
    true_logits[np.arange(4000), labels] += 1.5
    sampled = np.array([rng.choice(5, p=p) for p in tu.softmax(true_logits)])   # labels drawn from T=1
    over = true_logits * 3                                                       # model 3x overconfident
    t = tu.fit_temperature(over, sampled)
    assert 2.4 < t < 3.6
    assert tu.nll(over, sampled, t) < tu.nll(over, sampled, 1.0)
    assert tu.ece(tu.softmax(over, t), sampled) < tu.ece(tu.softmax(over), sampled)


def test_select_threshold():
    probs = np.array([[0.9, 0.1], [0.8, 0.2], [0.6, 0.4], [0.55, 0.45], [0.3, 0.7]])
    labels = np.array([0, 0, 1, 0, 1])     # third prediction (conf 0.6) is wrong
    r = tu.select_threshold(probs, labels, target_accuracy=1.0)
    assert r["target_met"] and r["threshold"] == pytest.approx(0.7) and r["coverage"] == pytest.approx(0.6)
    r = tu.select_threshold(probs, labels, target_accuracy=0.8)
    assert r["threshold"] == 0.0 and r["coverage"] == 1.0
    sel = tu.selective(probs, labels, 0.7)
    assert sel == {"coverage": 0.6, "uncertain_rate": pytest.approx(0.4), "selective_accuracy": 1.0}
    r = tu.select_threshold(np.array([[0.6, 0.4]]), np.array([1]), 0.9)
    assert r["target_met"] is False


def test_bootstrap_ci_contains_point_estimate_and_is_seeded():
    rng = np.random.default_rng(1)
    y = rng.integers(0, 3, 300)
    p = np.where(rng.random(300) < 0.8, y, (y + 1) % 3)
    ci = tu.bootstrap_ci(y, p, 3, n_boot=300, seed=7, mask=y == 2)
    acc = tu.summary(y, p, 3)["accuracy"]
    assert ci["accuracy"][0] <= acc <= ci["accuracy"][1]
    assert ci == tu.bootstrap_ci(y, p, 3, n_boot=300, seed=7, mask=y == 2)
    assert ci["subset_recall"] is not None


def test_checksums_and_run_dirs(tmp_path):
    assert tu.checksum_ok(b"abc", "sha1:a9993e364706816aba3e25717850c26c9cd0d89d")
    assert not tu.checksum_ok(b"abd", "sha1:a9993e364706816aba3e25717850c26c9cd0d89d")
    assert tu.checksum_ok(b"abc", "sha256:ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
    with pytest.raises(ValueError):
        tu.checksum_ok(b"abc", "md5:900150983cd24fb0d6963f7d28e17f72")
    run = tu.new_run_dir(str(tmp_path / "runs"), "r1")
    with pytest.raises(FileExistsError):
        tu.new_run_dir(str(tmp_path / "runs"), "r1")
    tu.write_json(f"{run}/a.json", {"x": 1})
    with pytest.raises(FileExistsError):
        tu.write_json(f"{run}/a.json", {"x": 2})
    tu.write_json(f"{run}/a.json", {"x": 3}, overwrite=True)

"""Regressions for the Codex review of the training notebook (develop@d58c3f0)."""
import hashlib
import io
import math
import os

import numpy as np
import pytest
from PIL import Image

from food_lens import preprocess as pp
from food_lens import train_utils as tu


# 1) Lock: locked checkpoint and history bytes never change.
@pytest.mark.parametrize("lock_file", tu.LOCK_FILES)
def test_locked_run_refuses_training_writes(tmp_path, lock_file):
    run = tu.new_run_dir(str(tmp_path), "run")
    tu.guarded_write_bytes(run, "best.pt", b"checkpoint-v1")
    tu.guarded_write_bytes(run, "history.csv", b"epoch,loss\n1,0.5\n")
    tu.guarded_write_bytes(run, "best.pt", b"checkpoint-v2")            # allowed before locking
    open(os.path.join(run, lock_file), "w").write("{}")
    before = {n: open(os.path.join(run, n), "rb").read() for n in ("best.pt", "history.csv")}
    for name in ("best.pt", "history.csv"):
        with pytest.raises(tu.RunLocked):
            tu.guarded_write_bytes(run, name, b"overwritten")
    with pytest.raises(tu.RunLocked):
        tu.assert_unlocked(run)
    assert before == {n: open(os.path.join(run, n), "rb").read() for n in before}
    assert before["best.pt"] == b"checkpoint-v2"
    assert not [f for f in os.listdir(run) if f.endswith(".tmp")]


# 3) Temperature: exact NLL and interval ends.
def test_nll_is_exact_for_extreme_logits():
    logits = np.array([[1000.0, 0.0], [0.0, 1000.0], [5.0, 0.0]])
    labels = np.array([1, 1, 0])
    expected = np.mean([1000.0, 0.0, math.log1p(math.exp(-5.0))])
    assert tu.nll(logits, labels) == pytest.approx(expected, rel=1e-12)
    assert np.isfinite(tu.nll(logits, labels, 0.05))


def test_codex_reproducer_temperature_goes_to_the_upper_bound():
    logits = np.array([[5.0, 0.0]] * 5 + [[100.0, 0.0]])
    labels = np.array([0] * 5 + [1])
    t = tu.fit_temperature(logits, labels)
    assert t == pytest.approx(20.0)
    assert tu.nll(logits, labels, t) < tu.nll(logits, labels, 0.1403)


def test_boundaries():
    confident = np.array([[2.0, 0.0], [0.0, 3.0]])
    assert tu.fit_temperature(confident, np.array([0, 1])) == pytest.approx(0.05)     # NLL falls as T -> 0
    assert tu.fit_temperature(confident, np.array([1, 0]), low=0.5, high=4.0) == pytest.approx(4.0)
    rng = np.random.default_rng(0)
    labels = rng.integers(0, 3, 2000)
    logits = rng.normal(0, 1, (2000, 3))
    logits[np.arange(2000), labels] += 2
    t = tu.fit_temperature(logits * 2, labels)
    assert 0.05 < t < 20 and tu.nll(logits * 2, labels, t) <= min(tu.nll(logits * 2, labels, x) for x in (0.05, 1, 20))


# 2) Cache and preprocessing.
def jpeg(size, seed, mode="RGB", fmt="JPEG"):
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 255, (size[1], size[0], 3), dtype=np.uint8)
    img = Image.fromarray(arr).convert(mode)
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()


@pytest.mark.parametrize("size", [(640, 480), (480, 640), (200, 150), (256, 300), (4361, 1250)])
def test_cache_recipe_sets_short_side(size):
    img = pp.decode_cached(pp.cache_image(jpeg(size, 1)))
    assert min(img.size) == 256


def test_recipe_id_tracks_the_recipe():
    assert pp.recipe_id() == pp.recipe_id(dict(pp.CACHE_RECIPE))
    assert pp.recipe_id() != pp.recipe_id({**pp.CACHE_RECIPE, "short_side": 288})
    assert pp.recipe_id() != pp.recipe_id({**pp.CACHE_RECIPE, "quality": 90})


class Fetcher:
    def __init__(self, files):
        self.files, self.calls = files, 0

    def __call__(self, url):
        self.calls += 1
        return self.files[url]


def row_for(data, sid="commons:1", url="https://upload.wikimedia.org/x.jpg"):
    return {"sample_id": sid, "location": url, "checksum": "sha1:" + hashlib.sha1(data).hexdigest()}


def test_commons_cold_and_warm_give_identical_bytes_and_pixels(tmp_path):
    original = jpeg((900, 700), 2, fmt="PNG")
    row = row_for(original)
    fetch = Fetcher({row["location"]: original})
    cold, how_cold = pp.CommonsCache(str(tmp_path), tu.checksum_ok, fetch).get(row)
    warm, how_warm = pp.CommonsCache(str(tmp_path), tu.checksum_ok, fetch).get(row)   # new session
    assert (how_cold, how_warm, fetch.calls) == ("cold", "warm", 1)
    assert cold == warm
    assert np.array_equal(np.asarray(pp.decode_cached(cold)), np.asarray(pp.decode_cached(warm)))


def test_commons_cache_rejects_wrong_recipe_corruption_and_bad_originals(tmp_path):
    original = jpeg((900, 700), 3)
    row = row_for(original)
    fetch = Fetcher({row["location"]: original})
    cache = pp.CommonsCache(str(tmp_path), tu.checksum_ok, fetch)
    data, _ = cache.get(row)
    other = pp.CommonsCache(str(tmp_path), tu.checksum_ok, fetch, recipe={**pp.CACHE_RECIPE, "short_side": 288})
    assert other.get(row)[1] == "cold" and fetch.calls == 2                 # other recipe: not reused
    open(cache.path(row["sample_id"]), "wb").write(b"corrupt")
    assert pp.CommonsCache(str(tmp_path), tu.checksum_ok, fetch).get(row) == (data, "cold")
    bad = {**row, "sample_id": "commons:2", "checksum": "sha1:" + "0" * 40}
    with pytest.raises(ValueError, match="SHA-1"):
        cache.get(bad)
    assert "commons:2" not in cache.entries


def test_inference_tensor_equals_the_eval_path():
    for size, fmt in (((640, 480), "JPEG"), ((300, 800), "PNG"), ((150, 120), "WEBP")):
        original = jpeg(size, 4, fmt=fmt)
        stored = pp.cache_image(original)                        # dataset cache stage
        eval_tensor = pp.model_input(pp.decode_cached(stored))   # what val/test feed the model
        assert eval_tensor.shape == (3, 224, 224) and eval_tensor.dtype == np.float32
        assert np.array_equal(eval_tensor, pp.inference_tensor(original))


def test_model_input_matches_torchvision():
    torch = pytest.importorskip("torch")
    transforms = pytest.importorskip("torchvision.transforms")
    tv = transforms.Compose([transforms.Resize(256, interpolation=transforms.InterpolationMode.BICUBIC),
                             transforms.CenterCrop(224), transforms.ToTensor(),
                             transforms.Normalize(pp.MODEL_INPUT["mean"], pp.MODEL_INPUT["std"])])
    for size in ((640, 480), (480, 641), (256, 999), (1001, 256), (333, 257)):
        img = Image.open(io.BytesIO(jpeg(size, 5))).convert("RGB")
        ours = torch.from_numpy(pp.model_input(img))
        assert torch.allclose(ours, tv(img), atol=1e-6), size

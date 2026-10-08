"""Images, weights and dataset archives must never be committed (Food-101/Commons licenses, size)."""
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
IMAGE_EXTS = ("jpg", "jpeg", "jpe", "png", "webp", "gif", "bmp", "tif", "tiff", "heic", "heif", "avif", "jxl",
              "dng", "raw", "cr2", "nef", "arw", "psd", "ico")
WEIGHT_EXTS = ("pth", "pt", "ckpt", "safetensors", "onnx", "h5", "hdf5", "keras", "pb", "tflite", "mlmodel",
               "engine", "bin", "npy", "npz", "pkl", "pickle", "joblib")
ARCHIVE_EXTS = ("zip", "tar", "tgz", "gz", "7z", "rar", "parquet")
BANNED = IMAGE_EXTS + WEIGHT_EXTS + ARCHIVE_EXTS
MAX_TRACKED_BYTES = 2_000_000  # the largest text file today (manifest) is ~1.7 MB


def git(*args):
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
    except OSError:
        pytest.skip("git not available")


def tracked():
    result = git("ls-files", "-z")
    if result.returncode:
        pytest.skip("not a git checkout")
    return [f for f in result.stdout.split("\0") if f]


@pytest.mark.parametrize("ext", BANNED)
def test_extension_is_ignored(ext):
    for path in (f"x.{ext}", f"sub/dir/x.{ext}", f"x.{ext.upper()}"):
        result = git("check-ignore", "-q", "--no-index", path)
        if result.returncode == 128:
            pytest.skip("not a git checkout")
        # Upper case relies on core.ignorecase (true on macOS); the tracked-file test below is case-insensitive.
        if path.endswith(ext.upper()) and git("config", "core.ignorecase").stdout.strip() != "true":
            continue
        assert result.returncode == 0, f"{path} is not ignored"


def test_no_banned_files_tracked():
    bad = [f for f in tracked() if f.rsplit(".", 1)[-1].lower() in BANNED]
    assert bad == []


def test_tracked_files_are_small_text():
    problems = []
    for f in tracked():
        path = ROOT / f
        if not path.is_file():
            continue
        data = path.read_bytes()
        if len(data) > MAX_TRACKED_BYTES:
            problems.append(f"{f}: {len(data)} bytes")
        if b"\0" in data[:8192]:
            problems.append(f"{f}: binary content")
    assert problems == []

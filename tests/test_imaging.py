import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from food_lens.imaging import hamming, load_rgb, phash64, sniff

ROOT = Path(__file__).resolve().parent.parent


def _bytes(im, fmt, **kw):
    buf = io.BytesIO()
    im.save(buf, fmt, **kw)
    return buf.getvalue()


def _photo(seed, size=(320, 240)):
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, (6, 8, 3), dtype=np.uint8)
    return Image.fromarray(base).resize(size, Image.BICUBIC)


@pytest.mark.parametrize("fmt, expected", [("JPEG", "JPEG"), ("PNG", "PNG"), ("WEBP", "WEBP"), ("GIF", "GIF")])
def test_sniff_uses_content_not_extension(fmt, expected):
    assert sniff(_bytes(_photo(1), fmt)[:16]) == expected


def test_sniff_unknown():
    assert sniff(b"<!DOCTYPE html>") == "unknown"


def test_transparent_pixels_become_white():
    im = Image.new("RGBA", (10, 10), (255, 0, 0, 0))
    rgb = load_rgb(_bytes(im, "PNG"))
    assert rgb.mode == "RGB"
    assert rgb.getpixel((5, 5)) == (255, 255, 255)


def test_palette_with_transparency_becomes_white():
    im = Image.new("P", (10, 10), 0)
    im.putpalette([0, 0, 0] * 256)
    data = _bytes(im, "PNG", transparency=0)
    assert load_rgb(data).getpixel((1, 1)) == (255, 255, 255)


def test_exif_orientation_is_applied():
    im = _photo(2, (40, 20))
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 degrees
    assert load_rgb(_bytes(im, "JPEG", exif=exif)).size == (20, 40)


def test_invalid_exif_orientation_is_ignored():
    exif = Image.Exif()
    exif[0x0112] = 56624  # value seen in the audit (hot_dog/54269.jpg)
    assert load_rgb(_bytes(_photo(3, (40, 20)), "JPEG", exif=exif)).size == (40, 20)


def test_max_side():
    assert max(load_rgb(_bytes(_photo(4, (1600, 900)), "JPEG"), max_side=512).size) == 512


def test_truncated_file_raises():
    data = _bytes(_photo(5), "JPEG")
    with pytest.raises(OSError):
        load_rgb(data[: len(data) // 2])


def _audit_phash():
    """phash64 exactly as written in notebooks/00_dataset_audit.ipynb (cell 3)."""
    nb = json.loads((ROOT / "notebooks" / "00_dataset_audit.ipynb").read_text())
    source = "".join(nb["cells"][3]["source"])
    start = source.index("_N = 32")
    end = source.index("EXT_FORMATS")
    namespace = {"np": np, "Image": Image}
    exec(source[start:end], namespace)
    return namespace["phash64"]


def test_phash_matches_audit_notebook():
    audit_phash = _audit_phash()
    for seed in range(10):
        im = _photo(seed)
        assert phash64(im) == audit_phash(im)


def test_phash_is_robust_to_resize_and_separates_different_images():
    a = _photo(10, (640, 480))
    assert hamming(phash64(a), phash64(a.resize((320, 240)))) <= 2
    assert hamming(phash64(a), phash64(_photo(11, (640, 480)))) > 8

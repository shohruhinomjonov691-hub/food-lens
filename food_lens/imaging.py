"""Image loading and perceptual hashing shared by the audit, data prep and training.

phash64 is the same algorithm as notebooks/00_dataset_audit.ipynb, so hashes are comparable
with audit/files.csv.
"""
import io

import numpy as np
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = 120_000_000

_N = 32
_k = np.arange(_N)[:, None]
_n = np.arange(_N)[None, :]
_DCT = np.cos(np.pi * (2 * _n + 1) * _k / (2 * _N)) * np.sqrt(2 / _N)
_DCT[0] /= np.sqrt(2)

MAGIC = (
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
)


def sniff(head):
    """Real format from magic bytes, independent of the file extension."""
    for prefix, name in MAGIC:
        if head.startswith(prefix):
            return name
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WEBP"
    return "unknown"


def to_rgb(im):
    """EXIF-orient and convert to RGB; transparent pixels are composited onto white."""
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        background = Image.new("RGBA", im.size, (255, 255, 255, 255))
        return Image.alpha_composite(background, im).convert("RGB")
    return im.convert("RGB")


def load_rgb(data, max_side=None):
    """Fully decode image bytes into an RGB image, optionally downscaled so the long side <= max_side."""
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        rgb = to_rgb(im)
    if max_side and max(rgb.size) > max_side:
        rgb.thumbnail((max_side, max_side), Image.LANCZOS)
    return rgb


def phash64(rgb):
    """64-bit perceptual hash: low-frequency DCT of a 32x32 grayscale image vs its median."""
    gray = np.asarray(rgb.convert("L").resize((_N, _N), Image.LANCZOS), dtype=np.float64)
    low = (_DCT @ gray @ _DCT.T)[:8, :8].flatten()
    bits = low > np.median(low[1:])
    return int("".join("1" if b else "0" for b in bits), 2)


def hamming(a, b):
    return (a ^ b).bit_count()

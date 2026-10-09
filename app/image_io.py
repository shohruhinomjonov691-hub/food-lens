"""Validate uploaded images entirely in memory (real format, size, pixels, decodability)."""
import io

from PIL import Image, UnidentifiedImageError

from app.config import ACCEPTED_FORMATS, MAX_PIXELS, MAX_SIDE, MAX_UPLOAD_BYTES
from food_lens.imaging import sniff


class ImageError(Exception):
    """A client error. `code` is stable and translated by the UI; `message` is English, for debugging."""

    def __init__(self, status_code, code, message):
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message


def check_dimensions(width, height):
    if width <= 0 or height <= 0:
        raise ImageError(422, "corrupt_image", "Image dimensions are invalid.")
    if max(width, height) > MAX_SIDE:
        raise ImageError(413, "image_too_large", f"The longest side must be at most {MAX_SIDE} px.")
    if width * height > MAX_PIXELS:
        raise ImageError(413, "image_too_large", f"The image must be at most {MAX_PIXELS // 1_000_000} megapixels.")


def validate_image(data):
    """Return the real format ("JPEG", "PNG", "WEBP") or raise ImageError. Nothing is written anywhere."""
    if not data:
        raise ImageError(400, "empty_file", "The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageError(413, "file_too_large", f"The file must be at most {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    fmt = sniff(data[:16])
    if fmt not in ACCEPTED_FORMATS:
        raise ImageError(415, "unsupported_format", "Only JPEG, PNG or WebP images are accepted.")
    try:
        with Image.open(io.BytesIO(data)) as img:
            if img.format != fmt:
                raise ImageError(415, "unsupported_format", "The file content does not match its format.")
            check_dimensions(*img.size)              # header only, before decoding pixels
            if getattr(img, "n_frames", 1) > 1:
                raise ImageError(415, "animated_image", "Animated images are not accepted.")
            img.load()                               # full decode: truncated/corrupt files fail here
    except ImageError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError, ValueError):
        raise ImageError(422, "corrupt_image", "The image could not be decoded.")
    return fmt

"""Result tiers. Pure functions, no torch.

  high      top-1 calibrated probability >= high_threshold   -> main dish and percentage
  low       threshold <= top-1 < high_threshold              -> "not confirmed", top-3 guesses
  abstain   top-1 < threshold (the locked "not sure" value)  -> the model does not guess; no dish is shown
  non_food  the image is flat (blank), or the extra analysis says it is not food

`non_food` from the model alone is limited to flat images: a general non-food detector was not trained or
evaluated (see README, Known limitations).
"""
import numpy as np

from app.config import FLAT_IMAGE_STD

HIGH, LOW, ABSTAIN, NON_FOOD = "high", "low", "abstain", "non_food"
TIERS = (HIGH, LOW, ABSTAIN, NON_FOOD)
BLANK_IMAGE = "blank_image"


def classify(top1: float, threshold: float, high_threshold: float) -> str:
    """Tier of a food prediction. Boundaries: below `threshold` abstains (as the locked rule), `high_threshold` and
    above is high."""
    if top1 < threshold:
        return ABSTAIN
    if top1 >= high_threshold:
        return HIGH
    return LOW


def grey_std(x: np.ndarray, mean_std=(0.229, 0.224, 0.225)) -> float:
    """Standard deviation of the grey level (0-255 scale) of a normalized CHW model input (undoes the ImageNet
    normalization per channel, then averages the channels)."""
    flat = x.reshape(x.shape[0], -1).astype(np.float64)
    return float(np.mean(flat.std(axis=1) * np.asarray(mean_std)) * 255.0)


def is_flat(x: np.ndarray, std_limit: float = FLAT_IMAGE_STD) -> bool:
    return grey_std(x) < std_limit

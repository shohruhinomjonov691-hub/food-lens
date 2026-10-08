import json

import pytest

from food_lens import classes


def test_class_order_is_fixed():
    # Model output order. Changing it breaks every checkpoint, so it is pinned here on purpose.
    assert classes.CLASSES == ("dessert", "hamburger", "hot_dog", "kebab", "pizza")
    assert classes.CLASS_TO_INDEX == {"dessert": 0, "hamburger": 1, "hot_dog": 2, "kebab": 3, "pizza": 4}


def test_source_folders():
    assert classes.target_for_folder("cheesecake") == "dessert"
    assert classes.target_for_folder("chocolate_cake") == "dessert"
    assert classes.target_for_folder("kebab_commons") == "kebab"
    assert classes.target_for_folder("plov") is None
    assert classes.target_for_folder("pilaf") is None
    assert {"plov", "pilaf"} <= classes.EXCLUDED_FOLDERS


def test_definitions_and_variants():
    assert set(classes.DEFINITIONS) == set(classes.CLASSES)
    assert "döner" in classes.DEFINITIONS["kebab"] and "Adana" in classes.DEFINITIONS["kebab"]
    assert classes.VARIANTS["kebab"] == ("skewered", "minced_skewer", "doner_shawarma")
    assert classes.VARIANTS["dessert"] == ("cheesecake", "chocolate_cake")


def _config(**changes):
    config = json.loads(classes.CONFIG_PATH.read_text())
    config.update(changes)
    return config


@pytest.mark.parametrize("changes, message", [
    ({"classes": ["dessert", "dessert", "hamburger", "hot_dog", "kebab", "pizza"]}, "duplicate"),
    ({"classes": ["pizza", "dessert", "hamburger", "hot_dog", "kebab"]}, "sorted"),
    ({"classes": ["dessert", "hamburger", "hot_dog", "kebab", "pizza", "sushi"]}, "without a source"),
    ({"excluded_folders": ["plov", "pizza"]}, "both mapped and excluded"),
    ({"definitions": {"pizza": "x"}}, "definition"),
    ({"variants": {"sushi": ["a"]}}, "unknown class"),
    ({"variants": {"kebab": ["a", "a"]}}, "unique"),
])
def test_invalid_configs_are_rejected(changes, message):
    with pytest.raises(ValueError, match=message):
        classes.validate_config(_config(**changes))


def test_unknown_target_rejected():
    config = _config()
    config["source_folders"] = {**config["source_folders"], "sushi": "sushi"}
    with pytest.raises(ValueError, match="unknown classes"):
        classes.validate_config(config)

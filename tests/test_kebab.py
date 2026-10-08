import pytest

from food_lens.kebab import kebab_variant


@pytest.mark.parametrize("root, category, expected", [
    ("Category:Döner kebab", "Category:Iskender Kebap", "doner_shawarma"),
    ("Category:Shawarma", "Category:Chicken shawarma", "doner_shawarma"),
    ("Category:Skewered kebabs", "Category:Adana Kebap", "minced_skewer"),
    ("Category:Skewered kebabs", "Category:Kabab Koobideh", "minced_skewer"),
    ("Category:Skewered kebabs", "Category:Seekh kabab in India", "minced_skewer"),
    ("Category:Skewered kebabs", "Category:Lula kebab", "minced_skewer"),
    ("Category:Skewered kebabs", "Category:Shashlik in Uzbekistan", "skewered"),
    ("Category:Skewered kebabs", "Category:Şiş kebap", "skewered"),
    ("Category:Skewered kebabs", "Category:Jujeh Kabab", "skewered"),
])
def test_variant(root, category, expected):
    assert kebab_variant(root, category) == expected

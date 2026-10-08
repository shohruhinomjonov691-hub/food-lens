"""Kebab variants for Commons files, derived from the category the file was found in.

The variant is only used for stratified splitting, per-variant counts and the variant-specific
ingredient lists; the model predicts the single class "kebab".
"""
import re

DONER_ROOTS = {"Category:Döner kebab", "Category:Shawarma"}
# Minced meat shaped on a skewer.
# "Kebab-e …" alone is not a hint: kebab-e barg is sliced meat (skewered).
MINCED = re.compile(r"adana|koobideh|kubideh|kobideh|seekh|sheekh|lula|köfte|kofte|kofta|beyti|urfa|kıyma|sheftalia",
                    re.IGNORECASE)


def kebab_variant(root, category):
    if root in DONER_ROOTS:
        return "doner_shawarma"
    if MINCED.search(category or ""):
        return "minced_skewer"
    return "skewered"

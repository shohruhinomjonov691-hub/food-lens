"""Typical ingredients per dish (and per variant for kebab and dessert), EN/KO, with sources.

The list describes the dish the user confirmed or picked. It is never a statement about the photo,
and the variant is always the user's choice (the model predicts the class only).
"""
import json
from pathlib import Path

from food_lens.classes import CLASSES, VARIANTS

CONTENT_PATH = Path(__file__).resolve().parent.parent / "content" / "ingredients.json"
LANGS = ("en", "ko")


class IngredientError(Exception):
    def __init__(self, status_code, code, message):
        super().__init__(message)
        self.status_code, self.code, self.message = status_code, code, message


def validate_content(data):
    """Return a list of problems (empty = valid)."""
    problems = []
    if "not identified from your photo" not in data.get("disclaimer", {}).get("en", ""):
        problems.append("English disclaimer must say the list is not identified from the photo")
    if set(data.get("disclaimer", {})) != set(LANGS) or set(data.get("variant_note", {})) != set(LANGS):
        problems.append("disclaimer and variant_note need en and ko")
    dishes = data.get("dishes", {})
    if set(dishes) != set(CLASSES):
        problems.append(f"dishes {sorted(dishes)} != classes {sorted(CLASSES)}")

    def check_entry(where, entry):
        ing = entry.get("ingredients", {})
        if set(ing) != set(LANGS) or not ing.get("en") or len(ing["en"]) != len(ing.get("ko", [])):
            problems.append(f"{where}: ingredients need equal-length en and ko lists")
        if set(entry.get("name", {})) != set(LANGS):
            problems.append(f"{where}: name needs en and ko")
        sources = entry.get("sources", [])
        if not sources:
            problems.append(f"{where}: at least one source is required")
        for s in sources:
            if not s.get("url", "").startswith("https://") or not s.get("checked") or not s.get("supports"):
                problems.append(f"{where}: every source needs an https url, a checked date and what it supports")

    for dish, entry in dishes.items():
        expected = VARIANTS.get(dish)
        if expected:
            if "ingredients" in entry:
                problems.append(f"{dish}: grouped class must not have one merged list")
            if tuple(entry.get("variants", {})) != expected:
                problems.append(f"{dish}: variants {list(entry.get('variants', {}))} != {list(expected)}")
            for v, ventry in entry.get("variants", {}).items():
                check_entry(f"{dish}/{v}", ventry)
        else:
            if "variants" in entry:
                problems.append(f"{dish}: unexpected variants")
            check_entry(dish, entry)
    return problems


def load_content(path=CONTENT_PATH):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    problems = validate_content(data)
    if problems:
        raise ValueError("invalid ingredient content: " + "; ".join(problems))
    return data


def lookup(content, dish, variant=None, lang="en"):
    if lang not in LANGS:
        raise IngredientError(400, "unsupported_language", f"lang must be one of {LANGS}")
    entry = content["dishes"].get(dish)
    if entry is None:
        raise IngredientError(404, "unknown_dish", f"dish must be one of {list(CLASSES)}")
    if "variants" in entry:
        if variant is None:
            raise IngredientError(400, "variant_required",
                                  f"{dish} has several kinds; choose one of {list(entry['variants'])}")
        if variant not in entry["variants"]:
            raise IngredientError(404, "unknown_variant", f"variant must be one of {list(entry['variants'])}")
        item, note = entry["variants"][variant], content["variant_note"][lang]
        name = f"{entry['name'][lang]} · {item['name'][lang]}"
    else:
        if variant is not None:
            raise IngredientError(400, "variant_not_applicable", f"{dish} has no variants")
        item, note, name = entry, None, entry["name"][lang]
    return {
        "dish": dish, "variant": variant, "variant_chosen_by": "user" if variant else None, "lang": lang,
        "name": name, "ingredients": item["ingredients"][lang], "disclaimer": content["disclaimer"][lang],
        "variant_note": note, "sources": item["sources"],
        "source_language": "en", "translated": lang != "en",
    }

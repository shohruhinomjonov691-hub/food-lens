"""Allergen and dietary guard for the TYPICAL ingredients of the dish the user confirmed.

It never looks at the photo. Each typical ingredient line in content/ingredients.json is tagged in
content/allergens.json as
  contains  the line names it (or it is part of the definition)          -> match
  may       the line lists it as one of several options / optional      -> match ("may contain")
  unknown   the line does not say, and real recipes often include it    -> unverified ("*" = anything)
and each restriction the user picked maps to a set of tags. Dish-level status per restriction:
  warning  at least one line matches (the lines are returned, so the user sees why)
  unknown  no match, but at least one line is unverified for this restriction
  safe     every line is known and none matches ("Safe / No Match": a reminder to check is still returned)
"""
import json
from pathlib import Path

from app.ingredients import IngredientError

ALLERGENS_PATH = Path(__file__).resolve().parent.parent / "content" / "allergens.json"
LANGS = ("en", "ko")
ANY = "*"
MAX_RESTRICTIONS = 8
STATUSES = ("safe", "warning", "unknown")


def entry_keys(content):
    """The keys of content["dishes"] flattened to "dish" and "dish/variant"."""
    keys = {}
    for dish, entry in content["dishes"].items():
        if "variants" in entry:
            for v, ventry in entry["variants"].items():
                keys[f"{dish}/{v}"] = ventry
        else:
            keys[dish] = entry
    return keys


def validate_allergens(data, content):
    """Return a list of problems (empty = valid). Every ingredient line must be tagged, and nothing stale remains."""
    problems = []
    vocab = set(data.get("tags", []))
    for rid, r in data.get("restrictions", {}).items():
        if not r.get("tags") or not set(r["tags"]) <= vocab:
            problems.append(f"restriction {rid}: tags must be a non-empty subset of the vocabulary")
        if set(r.get("label", {})) != set(LANGS):
            problems.append(f"restriction {rid}: label needs en and ko")
    for status in STATUSES:
        if set(data.get("messages", {}).get(status, {})) != set(LANGS):
            problems.append(f"message {status}: needs en and ko")
    if set(data.get("basis", {})) != set(LANGS):
        problems.append("basis needs en and ko")
    want = entry_keys(content)
    entries = data.get("entries", {})
    if set(entries) != set(want):
        problems.append(f"entries {sorted(entries)} != dishes {sorted(want)}")
    for key, item in want.items():
        lines = item["ingredients"]["en"]
        tagged = entries.get(key, {})
        if set(tagged) != set(lines):
            problems.append(f"{key}: tagged lines differ from ingredients.json: {sorted(set(tagged) ^ set(lines))}")
        for line, t in tagged.items():
            if not isinstance(t, dict) or set(t) - {"contains", "may", "unknown"}:
                problems.append(f"{key}/{line}: only contains, may, unknown are allowed")
                continue
            for field in ("contains", "may", "unknown"):
                tags = t.get(field, [])
                if not isinstance(tags, list) or not (set(tags) <= vocab | {ANY}):
                    problems.append(f"{key}/{line}: {field} has unknown tags")
                if field != "unknown" and ANY in tags:
                    problems.append(f"{key}/{line}: '*' is only allowed in unknown")
    return problems


def load_allergens(content, path=ALLERGENS_PATH):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    problems = validate_allergens(data, content)
    if problems:
        raise ValueError("invalid allergen content: " + "; ".join(problems))
    return data


def parse_avoid(raw, data):
    """"halal,nuts" -> ["halal", "nuts"] (order kept, duplicates dropped); unknown ids are a client error."""
    if raw is None or not raw.strip():
        return []
    ids = []
    for part in raw.split(","):
        rid = part.strip()
        if rid not in data["restrictions"]:
            raise IngredientError(400, "unknown_restriction", f"restriction must be one of {list(data['restrictions'])}")
        if rid not in ids:
            ids.append(rid)
    if len(ids) > MAX_RESTRICTIONS:
        raise IngredientError(400, "too_many_restrictions", f"at most {MAX_RESTRICTIONS} restrictions")
    return ids


def evaluate(data, content, dish, variant, lang, avoid):
    """Guard result for the confirmed dish (and the user's kind). dish/variant are already validated by lookup()."""
    if lang not in LANGS:
        raise IngredientError(400, "unsupported_language", f"lang must be one of {LANGS}")
    key = f"{dish}/{variant}" if variant else dish
    item = entry_keys(content)[key]
    lines_en, lines_shown = item["ingredients"]["en"], item["ingredients"][lang]
    tagged = data["entries"][key]
    results = []
    for rid in avoid:
        r = data["restrictions"][rid]
        tags = set(r["tags"])
        matches, unverified = [], []
        for i, line in enumerate(lines_en):
            t = tagged[line]
            for kind in ("contains", "may"):
                hit = sorted(tags & set(t.get(kind, [])))
                if hit:
                    matches.append({"ingredient": lines_shown[i], "kind": kind, "tags": hit})
                    break
            unk = t.get("unknown", [])
            if ANY in unk or tags & set(unk):
                unverified.append({"ingredient": lines_shown[i]})
        status = "warning" if matches else "unknown" if unverified else "safe"
        results.append({
            "id": rid, "label": r["label"][lang], "status": status, "matches": matches, "unverified": unverified,
            "message": data["messages"][status][lang], "note": (r["note"] or {}).get(lang),
        })
    return {"restrictions": results, "basis": data["basis"][lang], "dish": dish, "variant": variant}

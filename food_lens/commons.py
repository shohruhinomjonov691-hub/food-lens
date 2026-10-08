"""Wikimedia Commons helpers: canonical author IDs and derived-file hints."""
import re
import unicodedata

# Title hints that a file is a crop/retouch of another Commons file.
DERIVED_HINT = re.compile(r"\bcrop(ped)?\b|\bretouch(ed)?\b|\bedit(ed)?\b|\bderivative\b", re.IGNORECASE)

_SUFFIXES = (
    r";\s*cropped by.*$", r";\s*derivative work.*$", r"\bderivative work:.*$", r"\(\s*talk\s*\)",
    r"\bat [\w ]+ wikipedia\b", r"\bfrom [\w .,-]+$",
)


def canonical_author(author, aliases=None):
    """A stable ID for the person behind a Commons Artist string.

    Removes crop/derivative credits, "(talk)" links and "at X Wikipedia" suffixes, unwraps "the
    original uploader was X", normalizes Unicode/case/punctuation and applies a manual alias map.
    """
    text = unicodedata.normalize("NFKC", author or "").strip()
    m = re.search(r"original uploader was\s+([^\s.,;]+)", text, re.IGNORECASE)
    if m:
        text = m.group(1)
    for pattern in _SUFFIXES:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    text = re.sub(r"^user:\s*", "", text.strip(), flags=re.IGNORECASE)
    text = re.sub(r"[_\W]+", " ", text.casefold()).strip()
    aliases = {canonical_author(k): canonical_author(v) for k, v in (aliases or {}).items()}
    return aliases.get(text, text)

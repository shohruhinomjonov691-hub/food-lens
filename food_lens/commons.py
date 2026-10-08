"""Wikimedia Commons helpers: canonical author IDs and derived-file hints."""
import re
import unicodedata

# Title hints that a file is a crop/retouch of another Commons file.
DERIVED_HINT = re.compile(r"\bcrop(ped)?\b|\bretouch(ed)?\b|\bedit(ed)?\b|\bderivative\b", re.IGNORECASE)
# Hints in the Credit / Artist text ("cropped by …", "derivative work: …", "This file was derived from").
DERIVED_TEXT = re.compile(r"\bcrop(ped|ping)?\b|\bretouch(ed|ing)?\b|\bderiv(ed|ative)\b", re.IGNORECASE)

# Only credits that never belong to the name itself are removed. A place suffix such as
# "Name from City" is kept: stripping it could merge two different people ("John from Paris",
# "John from Rome"); such merges need an explicit, evidenced alias instead.
_SUFFIXES = (
    r";\s*cropped by.*$", r";\s*derivative work.*$", r"\bderivative work:.*$", r"\(\s*talk\s*\)",
    r"\s+at\s+[\w .-]*?\bwikipedia\b.*$",
)


def canonical_author(author, aliases=None):
    """A stable ID for the person behind a Commons Artist string.

    Removes crop/derivative credits, "(talk)" links and "at X Wikipedia" suffixes, unwraps "the
    original uploader was <full name> at X Wikipedia", normalizes Unicode/case/punctuation and
    applies a manual alias map.
    """
    text = unicodedata.normalize("NFKC", author or "").strip()
    m = re.search(r"original uploader was\s+(.+)$", text, re.IGNORECASE)
    if m:
        # The full name runs up to the "at <language> Wikipedia" suffix (or a sentence end).
        text = re.sub(r"\s+at\s+[\w .-]*?\bwikipedia\b.*$", "", m.group(1), flags=re.IGNORECASE)
        text = re.split(r"\s*;\s*", text)[0].rstrip(" .")
    for pattern in _SUFFIXES:
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    text = re.sub(r"^user:\s*", "", text.strip(), flags=re.IGNORECASE)
    text = re.sub(r"[_\W]+", " ", text.casefold()).strip()
    aliases = {canonical_author(k): canonical_author(v) for k, v in (aliases or {}).items()}
    return aliases.get(text, text)

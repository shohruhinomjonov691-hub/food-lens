"""Class list and source-folder mapping, loaded from config/classes.json.

The order of CLASSES is the model's output order. Changing it invalidates every checkpoint.
"""
import json
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "classes.json"


def load_config(path=CONFIG_PATH):
    with open(path, encoding="utf-8") as f:
        config = json.load(f)
    validate_config(config)
    return config


def validate_config(config):
    classes = config["classes"]
    if len(classes) != len(set(classes)):
        raise ValueError("duplicate class names")
    if classes != sorted(classes):
        raise ValueError("classes must be sorted so the index order is unambiguous")
    unknown = set(config["source_folders"].values()) - set(classes)
    if unknown:
        raise ValueError(f"source folders map to unknown classes: {sorted(unknown)}")
    unused = set(classes) - set(config["source_folders"].values())
    if unused:
        raise ValueError(f"classes without a source folder: {sorted(unused)}")
    overlap = set(config["source_folders"]) & set(config["excluded_folders"])
    if overlap:
        raise ValueError(f"folders both mapped and excluded: {sorted(overlap)}")


_CONFIG = load_config()
CLASSES = tuple(_CONFIG["classes"])
CLASS_TO_INDEX = {name: i for i, name in enumerate(CLASSES)}
SOURCE_TO_CLASS = dict(_CONFIG["source_folders"])
EXCLUDED_FOLDERS = frozenset(_CONFIG["excluded_folders"])


def target_for_folder(folder):
    """Target class for a source folder, or None if the folder is excluded or unknown."""
    return SOURCE_TO_CLASS.get(folder)

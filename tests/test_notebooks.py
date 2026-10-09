import ast
import json
import re
from pathlib import Path

import pytest

from scripts.make_colab_bundle import FILES

ROOT = Path(__file__).resolve().parent.parent
NOTEBOOKS = sorted((ROOT / "notebooks").glob("*.ipynb"))


def code_cells(path):
    nb = json.loads(path.read_text(encoding="utf-8"))
    return nb, ["".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"]


@pytest.mark.parametrize("path", NOTEBOOKS, ids=lambda p: p.name)
def test_notebook_is_clean_and_parses(path):
    nb, cells = code_cells(path)
    assert all(not c.get("outputs") and c.get("execution_count") is None
               for c in nb["cells"] if c["cell_type"] == "code"), "commit notebooks without outputs"
    for src in cells:
        ast.parse(src)


def test_training_notebook_defaults_and_bundle_contents():
    _, cells = code_cells(ROOT / "notebooks" / "01_train_mobilenetv2.ipynb")
    source = "\n".join(cells)
    assert re.search(r"^SMOKE_TEST = True$", cells[0], re.MULTILINE), "the smoke test must be the default"
    for module in set(re.findall(r"from food_lens(?:\.(\w+))? import", source)):
        assert f"food_lens/{module or '__init__'}.py" in FILES, f"food_lens.{module} missing from the bundle"
    assert "manifests/manifest_v1.csv" in FILES
    # The guard rails the notebook relies on.
    for needle in ("tu.new_run_dir(RUNS_ROOT", "final.json", "test was already evaluated",
                   "checkpoint changed after locking", "pp.CommonsCache(COMMONS_CACHE, tu.checksum_ok",
                   "fit_temperature(val_logits", "select_threshold(val_probs", "CrossEntropyLoss(weight=",
                   "tu.assert_unlocked(RUN_DIR)", 'tu.guarded_write_bytes(RUN_DIR, "best.pt"',
                   'tu.guarded_write_bytes(RUN_DIR, "history.csv"', "pp.model_input(img)"):
        assert needle in source, needle


def test_training_outputs_are_only_written_through_the_lock_guard():
    _, cells = code_cells(ROOT / "notebooks" / "01_train_mobilenetv2.ipynb")
    training = next(c for c in cells if c.startswith("# 9)"))
    assert "torch.save(" in training and "buf)" in training          # serialized to memory first
    assert "BEST_PATH + \".tmp\"" not in training and "os.replace" not in training
    assert 'open(f"{RUN_DIR}/history.csv"' not in training

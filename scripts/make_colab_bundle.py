"""Pack the code and manifests the training notebook needs into dist/food_lens_bundle_<commit>.zip.

The repository is not on GitHub, so the notebook gets its inputs from this zip (uploaded to Drive).
No images are included. BUNDLE.json records the git commit and the SHA-256 of every file; the
notebook verifies them. A dirty working tree is refused so a run always maps to a commit.

Usage: python scripts/make_colab_bundle.py [--out-dir dist]
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = [
    "config/classes.json",
    "food_lens/__init__.py", "food_lens/classes.py", "food_lens/imaging.py", "food_lens/train_utils.py",
    "manifests/manifest_v1.csv", "manifests/stats_v1.json",
]


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default=os.path.join(ROOT, "dist"))
    parser.add_argument("--allow-dirty", action="store_true", help="local smoke tests only; recorded in BUNDLE.json")
    args = parser.parse_args(argv)
    dirty = bool(git("status", "--porcelain"))
    if dirty and not args.allow_dirty:
        print("Working tree is not clean; commit first so the bundle maps to a commit.")
        return 1
    commit = git("rev-parse", "HEAD")
    meta = {"commit": commit, "dirty": dirty, "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "files": {}}
    os.makedirs(args.out_dir, exist_ok=True)
    out = os.path.join(args.out_dir, f"food_lens_bundle_{commit[:7]}{'_dirty' if dirty else ''}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in FILES:
            data = open(os.path.join(ROOT, rel), "rb").read()
            meta["files"][rel] = hashlib.sha256(data).hexdigest()
            z.writestr(rel, data)
        z.writestr("BUNDLE.json", json.dumps(meta, indent=2, sort_keys=True))
    print(f"{out}  ({os.path.getsize(out)} bytes, commit {commit[:7]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

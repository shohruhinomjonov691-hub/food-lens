"""Stream the official Food-101 archive and record SHA-256 of the images in our source folders.

The archive is read as a stream and never written to disk. Only these are kept:
- data/food101_official/hashes.csv  (class, image id, official split, sha256, bytes)
- data/food101_official/meta/*      (license, README, train/test lists)
- data/food101_official/review/*    (a few named images, for visual duplicate review only)

Usage: python scripts/food101_provenance.py [--review-list ids.txt]
"""
import argparse
import csv
import hashlib
import os
import sys
import tarfile
import time
import urllib.request

URL = "https://data.vision.ee.ethz.ch/cvl/food-101.tar.gz"
FOLDERS = ("cheesecake", "chocolate_cake", "hamburger", "hot_dog", "pizza")
OUT = os.path.join("data", "food101_official")
USER_AGENT = "FoodLensDatasetBuilder/0.1 (+https://github.com/shohruhinomjonov691-hub)"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-list", help="file with lines like 'hamburger/3578279' to save for review")
    args = parser.parse_args()
    review = set()
    if args.review_list:
        with open(args.review_list) as f:
            review = {line.strip() for line in f if line.strip()}

    os.makedirs(os.path.join(OUT, "meta"), exist_ok=True)
    os.makedirs(os.path.join(OUT, "review"), exist_ok=True)
    request = urllib.request.Request(URL, headers={"User-Agent": USER_AGENT})
    rows, other_members, t0 = [], [], time.time()
    with urllib.request.urlopen(request, timeout=120) as response:
        print("HTTP", response.status, "Content-Length", response.headers.get("Content-Length"), flush=True)
        with tarfile.open(fileobj=response, mode="r|gz") as tar:
            for member in tar:
                if not member.isfile():
                    continue
                parts = member.name.split("/")
                if len(parts) == 4 and parts[1] == "images":
                    folder, image_id = parts[2], os.path.splitext(parts[3])[0]
                    if folder not in FOLDERS:
                        continue
                    data = tar.extractfile(member).read()
                    rows.append({"folder": folder, "image_id": image_id, "name": parts[3],
                                 "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
                    if f"{folder}/{image_id}" in review:
                        with open(os.path.join(OUT, "review", f"{folder}__{parts[3]}"), "wb") as f:
                            f.write(data)
                    if len(rows) % 1000 == 0:
                        print(f"  {len(rows)} images hashed, {time.time() - t0:.0f}s", flush=True)
                elif len(parts) >= 2 and parts[1] != "images":
                    data = tar.extractfile(member).read()
                    name = "__".join(parts[1:])
                    with open(os.path.join(OUT, "meta", name), "wb") as f:
                        f.write(data)
                    other_members.append(member.name)

    splits = {}
    for split in ("train", "test"):
        path = os.path.join(OUT, "meta", f"meta__{split}.txt")
        if os.path.exists(path):
            with open(path) as f:
                for line in f:
                    splits[line.strip()] = split
    for row in rows:
        row["official_split"] = splits.get(f"{row['folder']}/{row['image_id']}", "")
    rows.sort(key=lambda r: (r["folder"], r["name"]))
    with open(os.path.join(OUT, "hashes.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["folder", "image_id", "name", "official_split", "bytes", "sha256"])
        writer.writeheader()
        writer.writerows(rows)
    print("Non-image members:", other_members)
    print(f"Done: {len(rows)} images in {time.time() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

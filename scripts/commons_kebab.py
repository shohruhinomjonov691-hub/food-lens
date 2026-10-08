"""Collect kebab image candidates from Wikimedia Commons with per-file license metadata.

Step 1 (this script): crawl the Commons category tree, keep only files whose license is on the
allowlist and whose author is known, download a review thumbnail to data/kebab_commons/ and write
data/kebab_commons/candidates.csv. Nothing is accepted automatically: every candidate still goes
through duplicate checks and a manual visual review (scripts/build_kebab_manifest.py).

Usage: python scripts/commons_kebab.py
"""
import csv
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from food_lens.imaging import load_rgb, phash64, sniff  # noqa: E402
from food_lens.manifest import license_allowed  # noqa: E402

API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "FoodLensDatasetBuilder/0.1 (+https://github.com/shohruhinomjonov691-hub)"
ROOT_CATEGORY = "Category:Skewered kebabs"
MAX_DEPTH = 3
# Döner/shawarma is a different-looking dish (vertical rotisserie, wraps); text and icon
# categories are not photos.
EXCLUDED_CATEGORY = re.compile(r"döner|doner|shawarma|gyros|\(text\)|icons?\b|logos?\b|restaurants?\b|stands?\b",
                               re.IGNORECASE)
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp"}
MIN_SHORT_SIDE = 256  # original image
THUMB_WIDTH = 640
OUT = os.path.join("data", "kebab_commons")


def api(**params):
    params.update(format="json", formatversion=2, maxlag=5)
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                data = json.load(response)
            if "error" in data and data["error"].get("code") == "maxlag":
                time.sleep(5)
                continue
            return data
        except Exception as exc:  # network hiccup: back off and retry
            print("  retry", attempt + 1, type(exc).__name__, exc, flush=True)
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"API failed: {params}")


def members(category, kind):
    params = dict(action="query", list="categorymembers", cmtitle=category, cmtype=kind, cmlimit=500)
    while True:
        data = api(**params)
        yield from data["query"]["categorymembers"]
        if "continue" not in data:
            return
        params.update(data["continue"])


def crawl():
    """File titles under ROOT_CATEGORY (BFS), with the first category each was found in."""
    files, seen, queue, skipped = {}, {ROOT_CATEGORY}, [(ROOT_CATEGORY, 0)], []
    while queue:
        category, depth = queue.pop(0)
        for m in members(category, "file"):
            files.setdefault(m["title"], category)
        if depth < MAX_DEPTH:
            for m in members(category, "subcat"):
                title = m["title"]
                if title in seen:
                    continue
                seen.add(title)
                if EXCLUDED_CATEGORY.search(title):
                    skipped.append(title)
                    continue
                queue.append((title, depth + 1))
        time.sleep(0.2)
    return files, sorted(seen), skipped


def plain(value):
    """Commons extmetadata values are HTML; keep readable text only."""
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def metadata(titles):
    for start in range(0, len(titles), 50):
        batch = titles[start:start + 50]
        data = api(action="query", titles="|".join(batch), prop="imageinfo",
                   iiprop="url|size|mime|sha1|extmetadata", iiurlwidth=THUMB_WIDTH)
        for page in data["query"]["pages"]:
            if "imageinfo" in page:
                yield page
        time.sleep(0.5)


def license_decision(meta, info):
    short = plain(meta.get("LicenseShortName", {}).get("value"))
    restrictions = plain(meta.get("Restrictions", {}).get("value"))
    author = plain(meta.get("Artist", {}).get("value"))
    if info["mime"] not in ALLOWED_MIME:
        return f"mime {info['mime']}"
    if min(info["width"], info["height"]) < MIN_SHORT_SIDE:
        return f"too small {info['width']}x{info['height']}"
    if not license_allowed(short):
        return f"license not on allowlist: {short or '(none)'}"
    if meta.get("NonFree", {}).get("value"):
        return "marked non-free"
    if restrictions:
        return f"restrictions: {restrictions}"
    if not author:
        return "author unknown"
    return ""


def download(url):
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.read()
        except Exception as exc:
            print("  download retry", attempt + 1, type(exc).__name__, flush=True)
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"download failed: {url}")


def main():
    os.makedirs(os.path.join(OUT, "thumbs"), exist_ok=True)
    files, categories, skipped = crawl()
    print(f"Categories crawled: {len(categories)}; skipped: {skipped}")
    print(f"File titles: {len(files)}", flush=True)
    rows = []
    for page in metadata(sorted(files)):
        info = page["imageinfo"][0]
        meta = info.get("extmetadata", {})
        row = {
            "pageid": page["pageid"],
            "title": page["title"],
            "category": files[page["title"]],
            "page_url": info["descriptionurl"],
            "original_url": info["url"],
            "original_sha1": info["sha1"],
            "mime": info["mime"],
            "width": info["width"],
            "height": info["height"],
            "author": plain(meta.get("Artist", {}).get("value"))[:300],
            "credit": plain(meta.get("Credit", {}).get("value"))[:300],
            "license": plain(meta.get("LicenseShortName", {}).get("value")),
            "license_url": plain(meta.get("LicenseUrl", {}).get("value")),
            "attribution_required": plain(meta.get("AttributionRequired", {}).get("value")),
            "restrictions": plain(meta.get("Restrictions", {}).get("value")),
            "thumb_url": info.get("thumburl", ""),
            "thumb_file": "", "thumb_sha256": "", "thumb_format": "", "phash": "",
            "auto_reject": license_decision(meta, info),
        }
        if not row["auto_reject"]:
            data = download(row["thumb_url"])
            fmt = sniff(data[:16])
            ext = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}.get(fmt, ".bin")
            name = f"{row['pageid']}{ext}"
            with open(os.path.join(OUT, "thumbs", name), "wb") as f:
                f.write(data)
            row.update(thumb_file=name, thumb_sha256=hashlib.sha256(data).hexdigest(), thumb_format=fmt)
            try:
                row["phash"] = f"{phash64(load_rgb(data)):016x}"
            except Exception as exc:
                row["auto_reject"] = f"decode: {type(exc).__name__}"
            time.sleep(0.3)
        rows.append(row)
        if len(rows) % 50 == 0:
            print(f"  {len(rows)} files processed", flush=True)

    with open(os.path.join(OUT, "candidates.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    ok = sum(1 for r in rows if not r["auto_reject"])
    print(f"Done: {len(rows)} files, {ok} passed license/size checks and were downloaded for review")
    return 0


if __name__ == "__main__":
    sys.exit(main())

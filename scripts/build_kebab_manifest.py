"""Turn Commons candidates into the accepted kebab list, with every decision recorded.

  queue     Apply automatic checks (license/size from commons_kebab.py, identical originals,
            near-duplicates within Commons and against the Drive audit) and draw numbered contact
            sheets for the manual review: data/kebab_commons/review_queue.csv, sheets/*.jpg
  finalize  Apply config/kebab_review.json (manual decisions) and write
            manifests/kebab_commons.csv (accepted) and manifests/kebab_commons_review.csv (all).

A candidate is accepted only if it passed every automatic check AND was explicitly reviewed.
"""
import argparse
import json
import os
import sys

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from food_lens.dedup import UnionFind, near_pairs  # noqa: E402
from food_lens.imaging import hamming, load_rgb  # noqa: E402
from food_lens.manifest import license_allowed, read_csv, write_csv  # noqa: E402

DIR = os.path.join("data", "kebab_commons")
REMOVE_MAX_DISTANCE = 2
FLAG_MAX_DISTANCE = 8
QUEUE_COLUMNS = ("pageid", "title", "auto_status", "note", "phash", "thumb_file", "sheet", "cell")
ACCEPTED_COLUMNS = ("pageid", "title", "page_url", "original_url", "original_sha1", "width", "height",
                    "author", "credit", "license", "license_url", "attribution_required", "category", "phash")
REVIEW_COLUMNS = ("pageid", "title", "page_url", "license", "decision", "reason")


def automatic(candidates, drive_rows):
    """pageid -> (status, note). status: 'reject' or 'review'."""
    result = {}
    alive = []
    for c in candidates:
        if c["auto_reject"]:
            result[c["pageid"]] = ("reject", c["auto_reject"])
        elif not license_allowed(c["license"]):  # belt and braces
            result[c["pageid"]] = ("reject", f"license not on allowlist: {c['license']}")
        else:
            alive.append(c)
    seen_sha1 = {}
    unique = []
    for c in sorted(alive, key=lambda c: int(c["pageid"])):
        if c["original_sha1"] in seen_sha1:
            result[c["pageid"]] = ("reject", f"identical original to pageid {seen_sha1[c['original_sha1']]}")
        else:
            seen_sha1[c["original_sha1"]] = c["pageid"]
            unique.append(c)
    hashes = {int(c["pageid"]): int(c["phash"], 16) for c in unique}
    pairs = near_pairs(hashes, FLAG_MAX_DISTANCE)
    uf = UnionFind(list(hashes))
    for a, b, d in pairs:
        if d <= REMOVE_MAX_DISTANCE:
            uf.union(a, b)
    for members in uf.groups().values():
        for pid in members[1:]:
            result[str(pid)] = ("reject", f"near duplicate (pHash d<={REMOVE_MAX_DISTANCE}) of pageid {members[0]}")
    notes = {}
    for a, b, d in pairs:
        if d > REMOVE_MAX_DISTANCE:
            for x, y in ((a, b), (b, a)):
                notes.setdefault(str(x), []).append(f"similar to pageid {y} (d={d})")
    drive = [(f"{r['folder']}/{r['name']}", int(r["phash"], 16)) for r in drive_rows if r["phash"]]
    for c in unique:
        if c["pageid"] in result:
            continue
        h = int(c["phash"], 16)
        close = [f"{loc} (d={hamming(h, ph)})" for loc, ph in drive if hamming(h, ph) <= FLAG_MAX_DISTANCE]
        if close:
            notes.setdefault(c["pageid"], []).append("similar to Drive " + ", ".join(close))
        result[c["pageid"]] = ("review", "; ".join(notes.get(c["pageid"], [])))
    return result


def draw_sheets(rows, per_sheet=30, cols=6, tile=230):
    os.makedirs(os.path.join(DIR, "sheets"), exist_ok=True)
    for start in range(0, len(rows), per_sheet):
        chunk = rows[start:start + per_sheet]
        sheet_no = start // per_sheet + 1
        n_rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * tile, n_rows * (tile + 22)), "white")
        draw = ImageDraw.Draw(sheet)
        for i, row in enumerate(chunk):
            with open(os.path.join(DIR, "thumbs", row["thumb_file"]), "rb") as f:
                im = load_rgb(f.read(), max_side=tile - 6)
            x, y = (i % cols) * tile, (i // cols) * (tile + 22)
            sheet.paste(im, (x + (tile - im.width) // 2, y + 20 + (tile - 6 - im.height) // 2))
            flag = " *" if row["note"] else ""
            draw.text((x + 4, y + 3), f"#{i + 1:02d}  {row['pageid']}{flag}", fill="black")
            row["sheet"], row["cell"] = sheet_no, i + 1
        sheet.save(os.path.join(DIR, "sheets", f"sheet_{sheet_no:02d}.jpg"), quality=88)


def cmd_queue(args):
    candidates = read_csv(os.path.join(DIR, "candidates.csv"))
    status = automatic(candidates, read_csv(args.drive))
    rows = []
    for c in sorted(candidates, key=lambda c: int(c["pageid"])):
        s, note = status[c["pageid"]]
        rows.append({"pageid": c["pageid"], "title": c["title"], "auto_status": s, "note": note,
                     "phash": c["phash"], "thumb_file": c["thumb_file"], "sheet": "", "cell": ""})
    draw_sheets([r for r in rows if r["auto_status"] == "review"])
    write_csv(os.path.join(DIR, "review_queue.csv"), rows, QUEUE_COLUMNS)
    n_review = sum(r["auto_status"] == "review" for r in rows)
    print(f"{len(rows)} candidates: {n_review} to review, {len(rows) - n_review} rejected automatically")
    return 0


def cmd_finalize(args):
    candidates = {c["pageid"]: c for c in read_csv(os.path.join(DIR, "candidates.csv"))}
    queue = read_csv(os.path.join(DIR, "review_queue.csv"))
    with open(args.review, encoding="utf-8") as f:
        review = json.load(f)
    rejects = {str(k): v for k, v in review["reject"].items()}
    reviewed_sheets = set(review["reviewed_sheets"])
    accepted, decisions, problems = [], [], []
    for q in queue:
        c = candidates[q["pageid"]]
        if q["auto_status"] == "reject":
            decision, reason = "reject", f"automatic: {q['note']}"
        elif q["pageid"] in rejects:
            decision, reason = "reject", f"manual: {rejects[q['pageid']]}"
        elif int(q["sheet"]) in reviewed_sheets:
            decision, reason = "accept", "manual: looked at, skewered kebab, usable" + (
                f" (checked: {q['note']})" if q["note"] else "")
        else:
            decision, reason = "pending", "not reviewed yet"
        decisions.append({"pageid": q["pageid"], "title": q["title"], "page_url": c["page_url"],
                          "license": c["license"], "decision": decision, "reason": reason})
        if decision == "accept":
            accepted.append({k: c[k] for k in ACCEPTED_COLUMNS})
    unknown = set(rejects) - {q["pageid"] for q in queue if q["auto_status"] == "review"}
    if unknown:
        problems.append(f"review rejects unknown or auto-rejected pageids: {sorted(unknown)}")
    if problems:
        print("\n".join(problems))
        return 1
    os.makedirs("manifests", exist_ok=True)
    write_csv(os.path.join("manifests", "kebab_commons.csv"), accepted, ACCEPTED_COLUMNS)
    write_csv(os.path.join("manifests", "kebab_commons_review.csv"), decisions, REVIEW_COLUMNS)
    counts = {}
    for d in decisions:
        counts[d["decision"]] = counts.get(d["decision"], 0) + 1
    print("Decisions:", counts)
    return 0


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("queue")
    q.add_argument("--drive", default="audit/files.csv")
    fz = sub.add_parser("finalize")
    fz.add_argument("--review", default="config/kebab_review.json")
    args = parser.parse_args()
    return {"queue": cmd_queue, "finalize": cmd_finalize}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())

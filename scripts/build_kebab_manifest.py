"""Turn Commons candidates into the accepted kebab list, with every decision recorded.

  queue     Apply automatic checks (license/size from commons_kebab.py, identical originals,
            near-duplicates within Commons and against the Drive audit) and draw numbered contact
            sheets for the manual review: data/kebab_commons/review_queue.csv, sheets/*.jpg
  mark      Record that a contact sheet was looked at: its pageids go to config/kebab_review.json
            ("reviewed"), so decisions survive re-numbered sheets. Rejects are added there by hand.
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
from food_lens.classes import VARIANTS  # noqa: E402
from food_lens.imaging import hamming, load_rgb  # noqa: E402
from food_lens.kebab import kebab_variant  # noqa: E402
from food_lens.manifest import license_allowed, read_csv, write_csv  # noqa: E402

DIR = os.path.join("data", "kebab_commons")
REMOVE_MAX_DISTANCE = 2
FLAG_MAX_DISTANCE = 8
QUEUE_COLUMNS = ("pageid", "title", "variant", "auto_status", "note", "phash", "thumb_file", "sheet", "cell")
ACCEPTED_COLUMNS = ("pageid", "title", "page_url", "original_url", "original_sha1", "width", "height",
                    "author", "credit", "license", "license_url", "attribution_required", "root", "category",
                    "variant", "phash")
REVIEW_COLUMNS = ("pageid", "title", "page_url", "license", "variant", "decision", "reason",
                  "initial_decision", "initial_variant", "initial_reason")
DEFAULT_ROOT = "Category:Skewered kebabs"  # rows collected before the "root" column existed
REJECT_CODES = {
    "scene": "kebab is not the main subject (people, grill or street scene)",
    "no_meat": "no kebab visible (fire, empty grill, equipment)",
    "raw": "raw or uncooked meat",
    "unclear": "not recognizable as kebab / a different dish",
    "blurry": "blurry, too dark or too small to judge",
    "text": "text, menu, collage or illustration",
    "face": "an identifiable person is prominent",
    "veg": "vegetable-only skewers",
    "dup": "same scene as another accepted photo (burst / near copy)",
}


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
    """One sheet series per variant in a new folder per run: sheets/run_NN/<variant>_NN.jpg."""
    base = os.path.join(DIR, "sheets")
    os.makedirs(base, exist_ok=True)
    run = 1 + max([int(n[4:]) for n in os.listdir(base) if n.startswith("run_")] or [0])
    out = os.path.join(base, f"run_{run:02d}")
    os.makedirs(out)
    by_variant = {}
    for row in rows:
        by_variant.setdefault(row["variant"], []).append(row)
    for variant, variant_rows in sorted(by_variant.items()):
        _draw_variant(out, variant, variant_rows, per_sheet, cols, tile)
    return out


def _draw_variant(out, variant, rows, per_sheet, cols, tile):
    for start in range(0, len(rows), per_sheet):
        chunk = rows[start:start + per_sheet]
        sheet_no = f"{variant}_{start // per_sheet + 1:02d}"
        n_rows = (len(chunk) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * tile, n_rows * (tile + 22)), "white")
        draw = ImageDraw.Draw(sheet)
        for i, row in enumerate(chunk):
            with open(os.path.join(DIR, "thumbs", row["thumb_file"]), "rb") as f:
                im = load_rgb(f.read(), max_side=tile - 6)
            x, y = (i % cols) * tile, (i // cols) * (tile + 22)
            sheet.paste(im, (x + (tile - im.width) // 2, y + 20 + (tile - 6 - im.height) // 2))
            flag = " *" if row["note"] else ""
            short = {"skewered": "SKW", "minced_skewer": "MIN", "doner_shawarma": "DON"}[row["variant"]]
            draw.text((x + 4, y + 3), f"#{i + 1:02d} {short} {row['pageid']}{flag}", fill="black")
            row["sheet"], row["cell"] = sheet_no, i + 1
        sheet.save(os.path.join(out, f"{sheet_no}.jpg"), quality=88)


def cmd_queue(args):
    candidates = read_csv(os.path.join(DIR, "candidates.csv"))
    status = automatic(candidates, read_csv(args.drive))
    rows = []
    for c in sorted(candidates, key=lambda c: int(c["pageid"])):
        s, note = status[c["pageid"]]
        variant = kebab_variant(c.get("root") or DEFAULT_ROOT, c["category"])
        rows.append({"pageid": c["pageid"], "title": c["title"], "variant": variant, "auto_status": s, "note": note,
                     "phash": c["phash"], "thumb_file": c["thumb_file"], "sheet": "", "cell": ""})
    out = draw_sheets(sorted((r for r in rows if r["auto_status"] == "review"), key=lambda r: (r["variant"], int(r["pageid"]))))
    write_csv(os.path.join(DIR, "review_queue.csv"), rows, QUEUE_COLUMNS)
    n_review = sum(r["auto_status"] == "review" for r in rows)
    print(f"{len(rows)} candidates: {n_review} to review, {len(rows) - n_review} rejected automatically; sheets in {out}")
    return 0


def cmd_finalize(args):
    candidates = {c["pageid"]: c for c in read_csv(os.path.join(DIR, "candidates.csv"))}
    queue = read_csv(os.path.join(DIR, "review_queue.csv"))
    accepted, decisions, problems = [], [], []
    with open(args.review, encoding="utf-8") as f:
        review = json.load(f)
    rejects = {str(k): v for k, v in review["reject"].items()}
    overrides = {str(k): v for k, v in review.get("variant_override", {}).items()}
    bad_variants = {k: v for k, v in overrides.items() if v not in VARIANTS["kebab"]}
    if bad_variants:
        problems.append(f"unknown variants in variant_override: {bad_variants}")
    reviewed = {str(p) for p in review["reviewed"]}
    # Later re-checks never overwrite the first decision; both are kept in the review CSV.
    revisions = {str(r["pageid"]): r for r in review.get("revisions", [])}
    for pid, r in revisions.items():
        if r["decision"] not in ("accept", "reject") or (r.get("variant") and r["variant"] not in VARIANTS["kebab"]):
            problems.append(f"bad revision for {pid}: {r}")
        if not r.get("reason") or not r.get("evidence"):
            problems.append(f"revision for {pid} needs a reason and evidence")
    for q in queue:
        c = candidates[q["pageid"]]
        variant = overrides.get(q["pageid"], q["variant"])
        if q["auto_status"] == "reject":
            decision, reason = "reject", f"automatic: {q['note']}"
        elif q["pageid"] in rejects:
            decision, reason = "reject", f"manual: {rejects[q['pageid']]}"
        elif q["pageid"] in reviewed:
            decision, reason = "accept", f"manual: looked at, kebab ({variant}), usable" + (
                f" (checked: {q['note']})" if q["note"] else "")
        else:
            decision, reason = "pending", "not reviewed yet"
        initial = {"initial_decision": "", "initial_variant": "", "initial_reason": ""}
        rev = revisions.get(q["pageid"])
        if rev:
            if q["auto_status"] == "reject":
                problems.append(f"revision for {q['pageid']} overrides an automatic reject: {q['note']}")
            initial = {"initial_decision": decision, "initial_variant": variant, "initial_reason": reason}
            decision, variant = rev["decision"], rev.get("variant") or variant
            reason = f"revised {rev['date']}: {rev['reason']} (evidence: {rev['evidence']})"
        decisions.append({"pageid": q["pageid"], "title": q["title"], "page_url": c["page_url"],
                          "license": c["license"], "variant": variant, "decision": decision, "reason": reason,
                          **initial})
        if decision == "accept":
            accepted.append({**{k: c.get(k, "") for k in ACCEPTED_COLUMNS},
                             "root": c.get("root") or DEFAULT_ROOT, "variant": variant})
    unknown = (set(rejects) | set(overrides) | set(revisions)) - {q["pageid"] for q in queue}
    if unknown:
        problems.append(f"review refers to pageids that are not candidates: {sorted(unknown)}")
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
    per_variant = {}
    for d in decisions:
        per_variant.setdefault(d["variant"], {}).setdefault(d["decision"], 0)
        per_variant[d["variant"]][d["decision"]] += 1
    print("Per variant:", json.dumps(per_variant, sort_keys=True))
    return 0


def cmd_mark(args):
    queue = read_csv(os.path.join(DIR, "review_queue.csv"))
    review = {"reviewed": [], "reject": {}, "variant_override": {}}
    if os.path.exists(args.review):
        with open(args.review, encoding="utf-8") as f:
            review = json.load(f)
    added = 0
    for sheet in args.sheets:
        pageids = [q["pageid"] for q in queue if q["sheet"] == sheet]
        if not pageids:
            print(f"no such sheet in the current queue: {sheet}")
            return 1
        for pid in pageids:
            if pid not in review["reviewed"]:
                review["reviewed"].append(pid)
                added += 1
    by_cell = {(q["sheet"], q["cell"]): q["pageid"] for q in queue}
    for item in args.reject:
        sheet, cells, code = item.split(":")
        if code not in REJECT_CODES:
            print(f"unknown reject code {code!r}; known: {sorted(REJECT_CODES)}")
            return 1
        for cell in cells.split(","):
            pid = by_cell.get((sheet, cell))
            if pid is None:
                print(f"no cell {cell} on sheet {sheet}")
                return 1
            review["reject"][pid] = f"{code}: {REJECT_CODES[code]}"
    for item in args.variant:
        sheet, cells, variant = item.split(":")
        if variant not in VARIANTS["kebab"]:
            print(f"unknown variant {variant!r}; known: {VARIANTS['kebab']}")
            return 1
        for cell in cells.split(","):
            pid = by_cell.get((sheet, cell))
            if pid is None:
                print(f"no cell {cell} on sheet {sheet}")
                return 1
            review["variant_override"][pid] = variant
    review["reviewed"].sort(key=int)
    with open(args.review, "w", encoding="utf-8") as f:
        json.dump(review, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")
    print(f"marked {added} pageids as reviewed; total {len(review['reviewed'])}; rejects {len(review['reject'])}")
    return 0


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("queue")
    q.add_argument("--drive", default="audit/files.csv")
    mk = sub.add_parser("mark")
    mk.add_argument("sheets", nargs="+", help="sheet names, e.g. skewered_01")
    mk.add_argument("--reject", action="append", default=[], help="SHEET:CELL,CELL:CODE, e.g. skewered_01:4,5:no_meat")
    mk.add_argument("--variant", action="append", default=[], help="SHEET:CELL,CELL:VARIANT, e.g. skewered_08:19:minced_skewer")
    mk.add_argument("--review", default="config/kebab_review.json")
    fz = sub.add_parser("finalize")
    fz.add_argument("--review", default="config/kebab_review.json")
    args = parser.parse_args()
    return {"queue": cmd_queue, "mark": cmd_mark, "finalize": cmd_finalize}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())

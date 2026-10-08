import argparse
import csv
import json

import pytest

from scripts import build_kebab_manifest as bkm

FAR = [0x0F0F0F0F0F0F0F0F, 0xF0F0F0F0F0F0F0F0, 0x00FF00FF00FF00FF, 0xFF00FF00FF00FF00, 0x0000FFFF0000FFFF]


def cand(pageid, phash, sha1=None, license="CC BY-SA 4.0", auto_reject="", root="Category:Skewered kebabs",
         category="Category:Shashlik"):
    return {"pageid": str(pageid), "title": f"File:K{pageid}.jpg", "phash": f"{phash:016x}",
            "original_sha1": sha1 or f"{pageid:040x}", "license": license, "auto_reject": auto_reject,
            "root": root, "category": category, "thumb_file": f"{pageid}.jpg",
            "page_url": f"https://commons.wikimedia.org/wiki/File:K{pageid}.jpg",
            "original_url": f"https://upload.wikimedia.org/k/K{pageid}.jpg", "width": "800", "height": "600",
            "author": "A", "credit": "", "license_url": "", "attribution_required": "true"}


def test_automatic_checks():
    cands = [cand(1, FAR[0]), cand(2, FAR[0] ^ 1),                    # near copy (d=1) -> reject the larger id
             cand(3, FAR[1], sha1="ab" * 20), cand(4, FAR[2], sha1="ab" * 20),  # identical original
             cand(5, FAR[3], license="GFDL"),                          # license
             cand(6, FAR[4], auto_reject="too small 100x100"),
             cand(7, FAR[4] ^ 0b11111)]                                # d=5 from 6 (6 is rejected anyway)
    drive = [{"folder": "pizza", "name": "1.jpg", "phash": f"{FAR[1] ^ 0b111:016x}"}]  # Commons 3 ~ Drive pizza
    status = bkm.automatic(cands, drive)
    assert status["1"][0] == "review"
    assert status["2"] == ("reject", "near duplicate (pHash d<=2) of pageid 1")
    assert status["4"] == ("reject", "identical original to pageid 3")
    assert status["5"][1].startswith("license not on allowlist")
    assert status["6"] == ("reject", "too small 100x100")
    assert status["3"][0] == "review" and "similar to Drive pizza/1.jpg (d=3)" in status["3"][1]


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bkm, "DIR", str(tmp_path / "kc"))
    (tmp_path / "kc").mkdir()
    cands = [cand(10, FAR[0]), cand(11, FAR[1]), cand(12, FAR[2], root="Category:Döner kebab",
                                                       category="Category:Iskender Kebap"),
             cand(13, FAR[3], category="Category:Adana Kebap"), cand(14, FAR[4], license="GFDL")]
    with open(tmp_path / "kc" / "candidates.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(cands[0]))
        w.writeheader()
        w.writerows(cands)
    queue = []
    for c in cands:
        variant = bkm.kebab_variant(c["root"], c["category"])
        queue.append({"pageid": c["pageid"], "title": c["title"], "variant": variant,
                      "auto_status": "reject" if c["license"] == "GFDL" else "review",
                      "note": "license not on allowlist: GFDL" if c["license"] == "GFDL" else "",
                      "phash": c["phash"], "thumb_file": c["thumb_file"],
                      "sheet": "" if c["license"] == "GFDL" else f"{variant}_01", "cell": "1"})
    for i, q in enumerate([q for q in queue if q["variant"] == "skewered"], 1):
        q["cell"] = str(i)
    bkm.write_csv(str(tmp_path / "kc" / "review_queue.csv"), queue, bkm.QUEUE_COLUMNS)
    return tmp_path


def args(**kw):
    return argparse.Namespace(**{"review": "review.json", "reject": [], "variant": [], **kw})


def read(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def test_mark_and_finalize(workdir):
    assert bkm.cmd_mark(args(sheets=["skewered_01", "doner_shawarma_01"],
                             reject=["skewered_01:2:raw"], variant=["skewered_01:1:minced_skewer"])) == 0
    review = json.loads((workdir / "review.json").read_text())
    assert review["reviewed"] == ["10", "11", "12"]
    assert review["reject"] == {"11": "raw: " + bkm.REJECT_CODES["raw"]}
    assert bkm.cmd_finalize(args()) == 0
    decisions = {d["pageid"]: d for d in read(workdir / "manifests" / "kebab_commons_review.csv")}
    assert decisions["10"]["decision"] == "accept" and decisions["10"]["variant"] == "minced_skewer"
    assert decisions["11"]["decision"] == "reject" and decisions["11"]["reason"].startswith("manual: raw")
    assert decisions["12"]["decision"] == "accept" and decisions["12"]["variant"] == "doner_shawarma"
    assert decisions["13"]["decision"] == "pending"          # its sheet was not marked
    assert decisions["14"]["decision"] == "reject" and decisions["14"]["reason"].startswith("automatic")
    accepted = read(workdir / "manifests" / "kebab_commons.csv")
    assert [a["pageid"] for a in accepted] == ["10", "12"]
    assert accepted[1]["root"] == "Category:Döner kebab"


def test_mark_rejects_unknown_codes_and_cells(workdir):
    assert bkm.cmd_mark(args(sheets=["skewered_01"], reject=["skewered_01:1:tasty"])) == 1
    assert bkm.cmd_mark(args(sheets=["skewered_01"], reject=["skewered_01:9:raw"])) == 1
    assert bkm.cmd_mark(args(sheets=["skewered_01"], variant=["skewered_01:1:gyros"])) == 1
    assert bkm.cmd_mark(args(sheets=["nope_01"])) == 1

"""What is the presenter saying when the montage shows B-roll, and when it shows the presenter? (episodes with a cut transcript)

    <core python> -m monteer.learn.style_study.broll_words <pair dir> [<pair dir> ...] --out <dir>  -> <dir>/broll_words.json

Needs video.json (pair_video) and asr_cut.json in each pair folder.
Each cut-transcript word gets the published picture at its time (presenter / B-roll / not used).
Compares: direct address («يا صديقي», «انت», «تخيل»...), numbers, and the words most typical of each side.
"""
import argparse
import json
import math
from collections import Counter
from pathlib import Path

from ...cut.common import normalize_ar

ADDRESS = {"صديقي", "ياصديقي", "انت", "انتا", "تخيل", "بص", "شوف", "خلينا", "تعالي", "تعالى", "عزيزي", "معايا", "فاكر", "فاكرين", "انا", "احنا"}
NUM = set("0123456789") | {"مليون", "مليار", "تريليون", "الف", "ألف", "مليار", "بالمية", "%", "سنه", "سنة"}


def main(ps, out):
    side_words = {"presenter": Counter(), "broll": Counter()}
    stats = {}
    for p in ps:
        d = Path(p)
        p = d.name
        rows = json.load(open(d / "video.json"))["rows"]
        words = json.load(open(d / "asr_cut.json", encoding="utf-8"))["words"]
        # cut time -> picture kind
        pics = sorted((r["tc"], r["kind"]) for r in rows if r["tc"] is not None)
        import bisect
        keys = [t for t, _ in pics]
        cnt = {"presenter": [0, 0, 0], "broll": [0, 0, 0]}  # words, address, numbers
        for w in words:
            i = bisect.bisect_left(keys, (w["s"] + w["e"]) / 2)
            if i >= len(pics) or abs(pics[i][0] - (w["s"] + w["e"]) / 2) > 0.6:
                continue
            k = pics[i][1]
            side = "presenter" if k in ("presenter", "partial") else "broll" if k == "insert" else None
            if not side:
                continue
            n = normalize_ar(w["w"])
            cnt[side][0] += 1
            cnt[side][1] += n in ADDRESS
            cnt[side][2] += any(c.isdigit() for c in n) or n in NUM
            side_words[side][n] += 1
        stats[p] = {s: {"words": c[0], "address_per_100": round(100 * c[1] / max(1, c[0]), 2),
                        "numbers_per_100": round(100 * c[2] / max(1, c[0]), 2)} for s, c in cnt.items()}
        print(p, stats[p])
    # most typical words of each side (log-odds with smoothing, min count 8)
    P, B = side_words["presenter"], side_words["broll"]
    tp, tb = sum(P.values()), sum(B.values())
    lo = {w: math.log((P[w] + 1) / tp) - math.log((B[w] + 1) / tb) for w in set(P) | set(B) if P[w] + B[w] >= 8}
    top_p = sorted(lo, key=lambda w: -lo[w])[:30]
    top_b = sorted(lo, key=lambda w: lo[w])[:30]
    res = {"per_project": stats, "typical_presenter": [(w, P[w], B[w]) for w in top_p],
           "typical_broll": [(w, P[w], B[w]) for w in top_b]}
    Path(out).mkdir(parents=True, exist_ok=True)
    json.dump(res, open(Path(out) / "broll_words.json", "w"), ensure_ascii=False, indent=1)
    print("presenter:", " ".join(w for w in top_p))
    print("broll:", " ".join(w for w in top_b))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="What is said under B-roll and under the presenter shot.")
    ap.add_argument("pairs", nargs="+", help="pair folders (video.json, asr_cut.json)")
    ap.add_argument("--out", required=True, help="folder for broll_words.json")
    opt = ap.parse_args()
    main(opt.pairs, opt.out)

"""Montage numbers for every sampled channel video (published only), from the saved features.

    <core python> -m monteer.learn.style_study.channel_summary --channel <channel dir> --out <dir>   -> <dir>/channel.json

<channel dir> is the download folder (download_channel.sh): media/ (videos + .info.json), feat/<id>/ (channel_extract,
label_detect, proto_clf) and videos_top40.txt (id|...|date|views|title lines, for titles of deleted downloads).
Per video: hard cuts (pacing), presenter on screen (presenter_reg.npy, studio matching), B-roll stretches,
cold-open length, zoom changes at cuts between presenter shots, key-word labels (labels.npy), white flashes,
music under the presenter's pauses (5 s blocks with no digital silence), loudness.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from . import reg

CH = FEAT = None   # set from --channel
INTRO = 180.0
# published videos whose cut is in a pair folder of the study: id -> pair name (--pair NAME=ID replaces)
LOCAL = {"xEv4jVhApaA": "p2", "vtNubor__8Y": "p3", "kSiA3ksTYKk": "p4", "bApzkjRm_jU": "p0"}
PRES = 0.6


def hard_cuts(d):
    med = np.array([np.median(d[max(0, i - 12): i + 13]) for i in range(len(d))])
    cut = (d > 14) & (d > 3.5 * np.maximum(med, 1.5))
    return [i / 24 for i in np.flatnonzero(cut) if not (i > 0 and cut[i - 1])]


def runs(mask):
    out, s = [], None
    for i, v in enumerate(list(mask) + [False]):
        if v and s is None:
            s = i
        elif not v and s is not None:
            out.append((s, i))
            s = None
    return out


def info(vid):
    j = CH / "media" / f"{vid}.info.json"
    if not j.exists():
        j = CH / "media" / f"short_{vid}.info.json"
    if j.exists():
        d = json.load(open(j))
        return d["title"], d["upload_date"], d.get("view_count")
    for line in open(CH / "videos_top40.txt", encoding="utf-8"):
        f = line.strip().split("|")
        if f[0] == vid:
            return f[4], f[2], int(f[3])
    return "", "", None


def one(vid):
    d = FEAT / vid
    meta = json.load(open(d / "meta.json"))
    dur = meta["duration"]
    title, date, views = info(vid)
    diff = np.load(d / "diff.npy")
    mean = np.load(d / "mean.npy")
    cuts = np.array(hard_cuts(diff))
    res = {"id": vid, "title": title, "date": date, "views": views, "minutes": round(dur / 60, 1),
           "vertical": meta.get("vertical", False), "project": LOCAL.get(vid),
           "hard_cuts_per_min": round(len(cuts) / (dur / 60), 1),
           "avg_shot_s": round(dur / (len(cuts) + 1), 2),
           "cuts_per_min_first3min": round(float((cuts < INTRO).sum()) / min(3, dur / 60), 1),
           "cuts_per_min_after3min": round(float((cuts >= INTRO).sum()) / max(1e-6, (dur - INTRO) / 60), 1) if dur > INTRO else None,
           "white_flashes": len(runs(mean > 225)),
           }
    # presenter
    pf = d / "presenter_none.npy"   # presenter share comes from the frame-by-frame visual check (visual.json)
    if pf.exists() and not res["vertical"]:
        sc = np.load(pf)
        pres = sc >= PRES
        # smooth single-frame flips
        for i in range(1, len(pres) - 1):
            if pres[i - 1] == pres[i + 1] != pres[i]:
                pres[i] = pres[i - 1]
        t = np.arange(len(pres)) / 2
        pr = [r for r in runs(pres) if r[1] - r[0] >= 2]
        br = [r for r in runs(~pres) if r[1] - r[0] >= 2]
        body = t >= INTRO
        res.update({
            "presenter_pct": round(float(pres.mean() * 100), 1),
            "presenter_pct_first3min": round(float(pres[~body].mean() * 100), 1),
            "presenter_pct_after3min": round(float(pres[body].mean() * 100), 1) if body.any() else None,
            "first_presenter_s": round(pr[0][0] / 2, 1) if pr else None,
            "broll_stretches_per_min_after3min": round(sum(1 for a, b in br if a / 2 >= INTRO) / max(1e-6, (dur - INTRO) / 60), 2),
            "broll_stretch_median_s": float(np.median([(b - a) / 2 for a, b in br if a / 2 >= INTRO])) if br else None,
            "presenter_stretch_median_s": float(np.median([(b - a) / 2 for a, b in pr if a / 2 >= INTRO])) if pr else None,
        })
    # at every hard cut: same picture at another size (punch-in change), same size (jump cut), or new shot
    if not res["vertical"]:
        g = np.load(d / "g2.npy")
        zc = same = 0
        scales = []
        for c in cuts:
            i0, i1 = int(np.floor(c * 2)) - 1, int(np.ceil(c * 2)) + 1
            if i0 < 0 or i1 >= len(g):
                continue
            f = reg.match(g[i1], g[i0])
            r = reg.match(g[i0], g[i1])
            if max(f[0], r[0]) < 0.75:
                continue
            s_ = f[1] if f[0] >= r[0] else 1 / r[1]
            if abs(np.log(s_)) >= np.log(1.08):
                zc += 1
                scales.append(round(max(s_, 1 / s_), 2))
            else:
                same += 1
        res.update({"zoom_change_cuts": zc, "zoom_change_cuts_per_min": round(zc / (dur / 60), 2),
                    "same_size_jump_cuts": same, "same_size_jump_cuts_per_min": round(same / (dur / 60), 2),
                    "zoom_step_median": float(np.median(scales)) if scales else None})
    lf = d / "labels.npy"
    if lf.exists():
        L = np.load(lf).astype(bool)
        lr = [r for r in runs(L) if r[1] - r[0] >= 2]
        res["labels"] = len(lr)
        res["labels_per_min"] = round(len(lr) / (dur / 60), 2)
        res["label_len_median_s"] = float(np.median([(b - a) / 2 for a, b in lr])) if lr else None
        if pf.exists() and not res["vertical"]:
            sc = np.load(pf)
            res["labels_on_presenter_pct"] = round(100 * float(np.mean([sc[min(len(sc) - 1, (a + b) // 2)] >= PRES for a, b in lr])), 0) if lr else None
    db = np.load(d / "db.npy")
    blocks = []
    for k in range(0, len(db) - 500, 500):
        blk = db[k:k + 500]
        blocks.append((blk < -80).mean() < 0.02 and np.percentile(blk, 5) > -70)
    blocks = np.array(blocks)
    nb3 = int(INTRO / 5)
    sp = db[db > -30]
    res.update({"music_blocks_pct": round(float(blocks.mean() * 100), 1),
                "music_blocks_pct_first3min": round(float(blocks[:nb3].mean() * 100), 1),
                "music_blocks_pct_after3min": round(float(blocks[nb3:].mean() * 100), 1) if len(blocks) > nb3 else None,
                "digital_silence_pct": round(float((db < -80).mean() * 100), 1),
                "speech_level_db": round(float(np.median(sp)), 1) if len(sp) else None})
    return res


def main():
    global CH, FEAT, LOCAL
    ap = argparse.ArgumentParser(description="Montage numbers for every sampled channel video, from the saved features.")
    ap.add_argument("--channel", required=True, help="channel download folder (media/, feat/, videos_top40.txt)")
    ap.add_argument("--out", required=True, help="folder for channel.json")
    ap.add_argument("--pair", action="append", metavar="NAME=ID", help="NAME=ID: pair folder name and the YouTube id of its published video (repeat; default: the study's four pairs)")
    opt = ap.parse_args()
    CH = Path(opt.channel)
    FEAT = CH / "feat"
    if opt.pair:
        LOCAL = {i: n for n, i in (x.split("=", 1) for x in opt.pair)}
    out = []
    for d in sorted(FEAT.iterdir()):
        if (d / "meta.json").exists():
            r = one(d.name)
            out.append(r)
            print(json.dumps(r, ensure_ascii=False), flush=True)
    out.sort(key=lambda r: r["date"], reverse=True)
    Path(opt.out).mkdir(parents=True, exist_ok=True)
    json.dump(out, open(Path(opt.out) / "channel.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

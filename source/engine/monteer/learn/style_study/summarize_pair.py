"""Numbers for the montage layer of one episode, from align.json / video.json / audio.json (+ the cut's transcript
asr_cut.json, if there).

    <core python> -m monteer.learn.style_study.summarize_pair <pair dir>   -> <pair dir>/montage.json
"""
import argparse
import json
from pathlib import Path

import numpy as np

INTRO = 180.0   # the opening ~3 minutes are treated apart (music, effects, dense B-roll)


def runs_of(kinds, val):
    out, s = [], None
    for i, k in enumerate(kinds + [None]):
        if k in val and s is None:
            s = i
        elif k not in val and s is not None:
            out.append((s, i))
            s = None
    return out


def tc(x):
    return f"{int(x // 60):02d}:{x % 60:04.1f}"


def main(p):
    d = Path(p)
    v = json.load(open(d / "video.json"))
    al = json.load(open(d / "align.json"))
    fs = v["fps_sample"]
    rows = v["rows"]
    kinds = [r["kind"] for r in rows]
    dur = len(rows) / fs
    words = []
    if (d / "asr_cut.json").exists():
        words = json.load(open(d / "asr_cut.json", encoding="utf-8"))["words"]

    def said(tc0, tc1):
        return " ".join(w["w"] for w in words if tc0 - 0.3 <= w["s"] < tc1)
    share = {k: round(100 * kinds.count(k) / len(kinds), 1) for k in ("presenter", "partial", "insert", "added")}
    # inserts: runs of non-presenter frames inside the mapped part (ignore 1-sample blips)
    ins = [(a, b) for a, b in runs_of(kinds, {"insert"}) if b - a >= 2]
    ins_list = []
    for a, b in ins:
        t0, t1 = a / fs, b / fs
        c0, c1 = rows[a]["tc"], rows[b - 1]["tc"]
        ins_list.append({"t": round(t0, 1), "dur": round(t1 - t0, 1), "tc0": c0, "text": said(c0, c1 + 0.5) if c0 else ""})
    body = [x for x in ins_list if x["t"] >= INTRO]
    intro = [x for x in ins_list if x["t"] < INTRO]
    body_min = max(1e-6, (dur - INTRO) / 60)
    # presenter shots and their zoom relative to the cut
    pres = [r for r in rows if r["kind"] in ("presenter", "partial")]
    s = np.array([r["s"] for r in pres])
    pr = runs_of(kinds, {"presenter", "partial"})
    shot_s, anim = [], 0
    for a, b in pr:
        ss = [rows[i]["s"] for i in range(a, b)]
        shot_s.append(float(np.median(ss)))
        if b - a >= 4 and max(ss) - min(ss) >= 0.08 and (np.all(np.diff(ss) >= -0.02) or np.all(np.diff(ss) <= 0.02)):
            anim += 1   # zoom moving steadily inside one presenter stretch: an animated push-in / pull-out
    changes = []
    for i in range(1, len(rows)):
        a, b = rows[i - 1], rows[i]
        if a["kind"] in ("presenter", "partial") and b["kind"] in ("presenter", "partial") and abs(a["s"] - b["s"]) >= 0.1:
            changes.append({"t": round(b["t"], 1), "from": a["s"], "to": b["s"], "text": said(b["tc"] - 1.5, b["tc"] + 1.5)})
    # partial overlays: where on screen (3x4 grid, top band excluded)
    part = [r for r in rows if r["kind"] == "partial"]
    where = np.zeros((3, 4))
    for r in part:
        where += np.array(r["cells"]) < 0.3
    pruns = [(a, b) for a, b in runs_of(kinds, {"partial"}) if b - a >= 2]
    # colour: published minus cut, presenter frames
    cp = np.array([r["col_pub"] for r in pres])
    cc = np.array([r["col_cut"] for r in pres])
    # shots
    sp, sc = v["shots_pub"], v["shots_cut"]
    pc = np.array(sp["cuts"])
    res = {
        "duration_s": round(dur, 1), "share_pct": share,
        "inserts": len(ins_list), "inserts_body": len(body), "inserts_intro": len(intro),
        "inserts_per_min_body": round(len(body) / body_min, 2),
        "insert_len_median_body": float(np.median([x["dur"] for x in body])) if body else None,
        "insert_len_p10_p90_body": np.percentile([x["dur"] for x in body], [10, 90]).tolist() if body else None,
        "insert_time_pct_intro": round(100 * sum(x["dur"] for x in intro) / INTRO, 1),
        "insert_time_pct_body": round(100 * sum(x["dur"] for x in body) / (dur - INTRO), 1),
        "presenter_zoom_vs_cut": {"s_1.00": round(float((s < 1.04).mean() * 100), 1),
                                  "s_1.04_1.3": round(float(((s >= 1.04) & (s < 1.3)).mean() * 100), 1),
                                  "s_1.3_1.6": round(float(((s >= 1.3) & (s < 1.6)).mean() * 100), 1),
                                  "s_over_1.6": round(float((s >= 1.6).mean() * 100), 1)},
        "zoom_changes_inside_presenter": len(changes),
        "zoom_changes_per_min_presenter": round(len(changes) / max(1e-6, len(pres) / fs / 60), 2),
        "animated_zoom_stretches": anim, "presenter_stretches": len(pr),
        "partial_runs": len(pruns), "partial_where_cells_pct": (100 * where / max(1, len(part))).round(0).tolist(),
        "colour_pub_minus_cut": {"luma": round(float((cp[:, 0] - cc[:, 0]).mean()), 1),
                                 "contrast": round(float((cp[:, 1] - cc[:, 1]).mean()), 1),
                                 "saturation": round(float((cp[:, 2] - cc[:, 2]).mean()), 3),
                                 "red_minus_blue": round(float((cp[:, 3] - cc[:, 3]).mean()), 1)},
        "pub_hard_cuts": len(pc), "pub_cuts_per_min": round(len(pc) / (dur / 60), 1),
        "pub_avg_shot_s": round(dur / (len(pc) + 1), 2),
        "pub_cuts_per_min_intro": round(float((pc < INTRO).sum()) / 3, 1),
        "pub_cuts_per_min_body": round(float((pc >= INTRO).sum()) / ((dur - INTRO) / 60), 1),
        "cut_video_hard_cuts": len(sc["cuts"]), "cut_video_cuts_per_min": round(len(sc["cuts"]) / (sc["n_frames"] / 24 / 60), 1),
        "white_flash_frames": len(sp["white"]), "black_frames": len(sp["black"]),
        "montage_removed_s": round(sum(r["dur"] for r in al["removed"]), 1), "montage_removed_n": len(al["removed"]),
        "added_s": round(sum(a["dur"] for a in al["added"]), 1),
        "insert_list": ins_list, "zoom_changes": changes,
    }
    json.dump(res, open(d / "montage.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in res.items() if k not in ("insert_list", "zoom_changes")}, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Montage-layer numbers of one episode.")
    ap.add_argument("pair", help="pair folder (align.json, video.json, audio.json); montage.json is written there")
    main(ap.parse_args().pair)

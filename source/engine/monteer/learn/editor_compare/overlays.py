"""Frames of the reference editor's cut that are not the raw frame the audio map points to (best of +-2 frames):
graphics, titles, cutaways / B-roll, or added intro/outro. For each run, where on screen it differs.

    <core python> -m monteer.learn.editor_compare.overlays --out <compare dir>

Needs <out>/editor_g160.u8, raw_g160.u8 (thumbs.sh), editor_map.json (map_fix) and editor_video.json (map_video).
Writes <out>/overlays.json.
"""
import argparse
import json
from pathlib import Path

import numpy as np

W, H = 160, 90


def main():
    ap = argparse.ArgumentParser(description="Frames of the editor's cut that are not raw frames (graphics, B-roll, titles).")
    ap.add_argument("--out", required=True, help="comparison folder (thumbnails, map, video check); result goes here")
    D = Path(ap.parse_args().out)
    E = np.fromfile(D / "editor_g160.u8", np.uint8).reshape(-1, H, W).astype(np.float32)
    R = np.fromfile(D / "raw_g160.u8", np.uint8).reshape(-1, H, W)
    m = json.load(open(D / "editor_map.json"))["segs"]
    v = json.load(open(D / "editor_video.json"))["segs"]
    n = len(E)
    best = np.zeros(n, np.float32)
    shift = np.zeros(n, np.int64)
    for a, b in zip(m, v):
        k0, k1 = int(round(a["ed_s"] * 24)), min(n, int(round(a["ed_e"] * 24)))
        D = int(round(a["off48"] / 2000)) + b["dv"]
        for k in range(k0, k1):
            sc = []
            for d in (-1, 0, 1):
                j = k + D + d
                if not 0 <= j < len(R):
                    sc.append(-1)
                    continue
                x = E[k].ravel() - E[k].mean()
                y = R[j].astype(np.float32).ravel()
                y -= y.mean()
                den = np.sqrt((x * x).sum() * (y * y).sum())
                sc.append(float((x * y).sum() / den) if den > 0 else 0)
            i = int(np.argmax(sc))
            best[k] = sc[i]
            shift[k] = D + (-1, 0, 1)[i]
    bad = best < 0.9
    d = np.diff(np.concatenate([[0], bad.astype(np.int8), [0]]))
    out = []
    for s, e in zip(np.where(d == 1)[0], np.where(d == -1)[0]):
        if e - s < 6:  # under 1/4 s: motion blur / compression, not a graphic
            continue
        diff = np.mean([np.abs(E[k] - R[k + shift[k]].astype(np.float32)) for k in range(s, e)
                        if 0 <= k + shift[k] < len(R)], axis=0)
        hot = diff > 25
        ys, xs = np.where(hot)
        box = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if len(xs) else None
        out.append({"ed_s": s / 24, "ed_e": e / 24, "min_ncc": round(float(best[s:e].min()), 3),
                    "mean_ncc": round(float(best[s:e].mean()), 3),
                    "changed_area_pct": round(100 * float(hot.mean()), 1), "box_160x90": box,
                    "edit_luma": round(float(E[s:e].mean()), 1)})
    json.dump({"runs": out, "frames_below_0_9": int(bad.sum()), "frames": n}, open(D / "overlays.json", "w"), indent=0)
    for r in out:
        print(r)
    print("frames not matching raw:", int(bad.sum()), "of", n)


if __name__ == "__main__":
    main()

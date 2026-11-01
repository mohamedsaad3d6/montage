"""Montage layer, picture side: what the published video shows at every moment, against the reference editor's cut.

    <core python> -m monteer.learn.style_study.pair_video <pair dir>

Needs <pair dir>/cut.mp4, pub.mp4 and align.json (pair_align). Decodes both videos (heavy). For every published frame at 2 fps:
  presenter  - the cut frame is on screen (zoom s >= 1 relative to the cut, position x/y, per-cell match)
  insert     - something else fills the screen (B-roll, image, graphic, screenshot, promo, ...)
  partial    - the cut frame is there but part of the screen is covered (text, label, split screen)
Shot changes are found on the published video at full frame rate (hard cuts, flashes, fades).
Colour: mean luma / saturation / red-blue balance of presenter frames, published vs cut.
Writes <pair dir>/video.json.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from . import reg

FPS_S = 2            # sampling rate for classification
PRESENTER = 0.65     # ncc above this: the cut frame is on screen


def colour_stats(rgb):
    x = rgb.reshape(-1, 3).astype(np.float32)
    mx, mn = x.max(1), x.min(1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    luma = 0.299 * x[:, 0] + 0.587 * x[:, 1] + 0.114 * x[:, 2]
    return [float(luma.mean()), float(luma.std()), float(sat.mean()), float((x[:, 0] - x[:, 2]).mean())]


def shots(path, dur=None):
    """Hard cuts and flash / black frames on the full-rate small grey video."""
    G = reg.frames(path, size=(64, 36)).astype(np.float32)
    d = np.r_[0, np.abs(np.diff(G, axis=0)).mean((1, 2))]
    med = np.array([np.median(d[max(0, i - 12): i + 13]) for i in range(len(d))])
    cut = (d > 14) & (d > 3.5 * np.maximum(med, 1.5))
    # one cut per spike (a cut over two frames counts once)
    idx = [i for i in np.flatnonzero(cut) if not (i > 0 and cut[i - 1])]
    mean = G.mean((1, 2))
    return {"n_frames": len(G), "cuts": [i / 24 for i in idx], "diff": d.round(2).tolist(),
            "white": [i / 24 for i in np.flatnonzero(mean > 225)], "black": [i / 24 for i in np.flatnonzero(mean < 12)]}


def main(p):
    d = Path(p)
    p = d.name
    al = json.load(open(d / "align.json"))
    P = reg.frames(d / "pub.mp4", fps=FPS_S)
    Pc = reg.frames(d / "pub.mp4", fps=FPS_S, size=(32, 18), gray=False)
    C = reg.frames(d / "cut.mp4")
    Cc = reg.frames(d / "cut.mp4", size=(32, 18), gray=False)
    print(p, "frames", P.shape, C.shape, flush=True)

    def cut_t(t):
        for s in al["segs"]:
            if s["p0"] <= t < s["p1"]:
                return t + s["off"]
        return None
    rows, last = [], None
    for k in range(len(P)):
        t = k / FPS_S
        tc = cut_t(t)
        row = {"t": t, "tc": tc}
        if tc is None or int(round(tc * 24)) >= len(C):
            row.update(kind="added", ncc=None)
            rows.append(row)
            last = None
            continue
        ci = int(round(tc * 24))
        # try last frame's zoom first; a full search only when it does not hold
        res = None
        if last:
            res = reg.match(P[k], C[ci], scales=[last[1]])
            if res[0] < 0.85:
                res = None
        if res is None:
            res = reg.match(P[k], C[ci])
        sc, s, x, y = res
        row.update(ncc=round(sc, 3), s=s, x=x, y=y)
        if sc >= PRESENTER:
            g = reg.cells(P[k], reg.aligned(C[ci], s, x, y))
            row["cells_low"] = int((g < 0.3).sum())
            row["cells"] = g.round(2).tolist()
            row["kind"] = "partial" if row["cells_low"] >= 2 else "presenter"
            row["col_pub"] = colour_stats(Pc[k])
            row["col_cut"] = colour_stats(Cc[ci])
            last = res
        else:
            row["kind"] = "insert"
            last = None
        rows.append(row)
        if k % 200 == 0:
            print(f"  {t:7.1f}s {row['kind']} {sc:.2f} s={s}", flush=True)
    sp = shots(d / "pub.mp4")
    sc_ = shots(d / "cut.mp4")
    json.dump({"fps_sample": FPS_S, "rows": rows, "shots_pub": sp, "shots_cut": sc_},
              open(d / "video.json", "w"))
    kinds = {}
    for r in rows:
        kinds[r["kind"]] = kinds.get(r["kind"], 0) + 1
    print(p, {k: f"{v / FPS_S:.0f}s" for k, v in kinds.items()},
          f"pub cuts {len(sp['cuts'])}, cut-video cuts {len(sc_['cuts'])}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="What the published video shows at every moment, against the editor's cut.")
    ap.add_argument("pair", help="pair folder (cut.mp4, pub.mp4, align.json); video.json is written there")
    main(ap.parse_args().pair)

"""Zoom changes already inside a cut video: at every hard cut of the cut video, is the next shot the same
camera picture scaled (a punch-in / pull-out made while cutting) or the same size?

    <core python> -m monteer.learn.style_study.cut_zoom <pair dir>   -> <pair dir>/cut_zoom.json

Needs <pair dir>/cut.mp4 and video.json (pair_video). Decodes the cut video (heavy).
"""
import argparse
import json
from pathlib import Path

from . import reg


def main(p):
    d = Path(p)
    v = json.load(open(d / "video.json"))
    C = reg.frames(d / "cut.mp4")
    out = []
    for t in v["shots_cut"]["cuts"]:
        k = int(round(t * 24))
        if k < 2 or k + 2 >= len(C):
            continue
        a, b = C[k - 2], C[k + 1]
        f = reg.match(b, a)    # b = a zoomed in?
        r = reg.match(a, b)    # a = b zoomed in? (pull-out)
        if max(f[0], r[0]) < 0.6:
            kind, s = "other", None   # black slot, different picture
        elif f[0] >= r[0]:
            s = f[1]
            kind = "zoom_in" if s >= 1.08 else "same_size"
        else:
            s = 1 / r[1]
            kind = "zoom_out" if r[1] >= 1.08 else "same_size"
        out.append({"t": round(t, 2), "kind": kind, "s": s, "ncc": round(max(f[0], r[0]), 2)})
    kinds = {}
    for o in out:
        kinds[o["kind"]] = kinds.get(o["kind"], 0) + 1
    mins = len(C) / 24 / 60
    json.dump({"cuts": out, "kinds": kinds, "minutes": mins}, open(d / "cut_zoom.json", "w"), indent=1)
    print(d.name, kinds, "zoom changes per min", round((kinds.get("zoom_in", 0) + kinds.get("zoom_out", 0)) / mins, 2),
          "scales", sorted({round(o["s"], 2) for o in out if o["kind"].startswith("zoom")}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Zoom changes at the hard cuts of a cut video.")
    ap.add_argument("pair", help="pair folder (cut.mp4, video.json); cut_zoom.json is written there")
    main(ap.parse_args().pair)

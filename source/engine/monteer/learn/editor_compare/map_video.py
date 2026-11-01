"""Video checks on top of the audio map: does each frame of an edit (the reference editor's cut, or our v2) equal the
raw frame the audio says it should (scale 1, no shift)? If not, look for a punch-in (scale + crop), overlays /
B-roll (no match at any scale), and a colour change (per-channel gain/offset vs raw).

    <core python> -m monteer.learn.editor_compare.map_video <name> --out <compare dir>

name = editor | v2. Needs <out>/<name>_g160.u8, <name>_c16.u8 (thumbs.sh), raw_g160.u8, raw_c16.u8 and
<name>_map.json (map_audio / map_fix). Writes <out>/<name>_video.json.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.ndimage import zoom

W, H = 160, 90


def frames(path, w, h, c=1):
    x = np.fromfile(path, np.uint8)
    return x.reshape(-1, h, w, c) if c > 1 else x.reshape(-1, h, w)


def ncc(a, b):
    a = a.astype(np.float32).ravel()
    b = b.astype(np.float32).ravel()
    a -= a.mean()
    b -= b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 0 else 0.0


def best_zoom(ed, raw):
    """Search scale 1.0-1.6 and crop position; returns (score, scale, cx, cy) in raw pixels."""
    best = (ncc(ed, raw), 1.0, W / 2, H / 2)
    for s in np.arange(1.04, 1.61, 0.04):
        cw, ch = W / s, H / s
        for cx in np.linspace(cw / 2, W - cw / 2, 9):
            for cy in np.linspace(ch / 2, H - ch / 2, 5):
                x0, y0 = int(round(cx - cw / 2)), int(round(cy - ch / 2))
                crop = raw[y0: y0 + int(round(ch)), x0: x0 + int(round(cw))]
                up = zoom(crop.astype(np.float32), (H / crop.shape[0], W / crop.shape[1]), order=1)[:H, :W]
                if up.shape != (H, W):
                    continue
                sc = ncc(ed, up)
                if sc > best[0]:
                    best = (sc, float(s), float(cx), float(cy))
    return best


def main():
    ap = argparse.ArgumentParser(description="Picture checks of an edit on top of its audio map.")
    ap.add_argument("name", help="editor | v2 (file prefix in the comparison folder)")
    ap.add_argument("--out", required=True, help="comparison folder (thumbnails, map); the result is written here")
    opt = ap.parse_args()
    name, D = opt.name, Path(opt.out)
    E = frames(D / f"{name}_g160.u8", W, H)
    R = frames(D / "raw_g160.u8", W, H)
    Ec = frames(D / f"{name}_c16.u8", 16, 9, 3).astype(np.float32)
    Rc = frames(D / "raw_c16.u8", 16, 9, 3).astype(np.float32)
    segs = json.load(open(D / f"{name}_map.json"))["segs"]
    out = []
    pairs_c = []
    for sg in segs:
        k0, k1 = int(round(sg["ed_s"] * 24)), int(round(sg["ed_e"] * 24))
        k1 = min(k1, len(E))
        shift = int(round((sg["src_s"] - sg["ed_s"]) * 24))
        scores = {}
        for dv in (-2, -1, 0, 1, 2):  # video may sit a frame or two off the audio
            ks = [k for k in range(k0, k1, max(1, (k1 - k0) // 6)) if 0 <= k + shift + dv < len(R)]
            scores[dv] = float(np.mean([ncc(E[k], R[k + shift + dv]) for k in ks])) if ks else 0
        dv = max(scores, key=scores.get)
        mid = (k0 + k1) // 2
        rec = {"ed_s": sg["ed_s"], "ed_e": sg["ed_e"], "src_s": sg["src_s"], "dv": dv,
               "ncc1": round(scores[dv], 3)}
        if 0 <= mid + shift + dv < len(R):
            if scores[dv] < 0.97:
                z = best_zoom(E[mid], R[mid + shift + dv])
                rec.update(zoom_ncc=round(z[0], 3), scale=round(z[1], 2), cx=z[2], cy=z[3])
            if scores[dv] > 0.9:
                for k in range(k0, k1, max(1, (k1 - k0) // 4)):
                    if 0 <= k + shift + dv < len(R):
                        pairs_c.append((Ec[k].reshape(-1, 3), Rc[k + shift + dv].reshape(-1, 3)))
        # per-frame match inside the segment (overlays / titles show as local drops)
        fr = [ncc(E[k], R[k + shift + dv]) for k in range(k0, k1) if 0 <= k + shift + dv < len(R)]
        rec["min_frame_ncc"] = round(min(fr), 3) if fr else None
        out.append(rec)
    # colour: per-channel linear fit edit = g * raw + o over matched frames
    col = {}
    if pairs_c:
        e = np.concatenate([p[0] for p in pairs_c])
        r = np.concatenate([p[1] for p in pairs_c])
        for i, ch in enumerate("RGB"):
            g, o = np.polyfit(r[:, i], e[:, i], 1)
            col[ch] = {"gain": round(float(g), 3), "offset": round(float(o), 1),
                       "mean_edit": round(float(e[:, i].mean()), 1), "mean_raw": round(float(r[:, i].mean()), 1)}
    json.dump({"segs": out, "colour": col}, open(D / f"{name}_video.json", "w"), indent=0)
    n_zoom = sum(1 for s in out if s.get("scale", 1) > 1.0 and s.get("zoom_ncc", 0) > s["ncc1"] + 0.02)
    print(f"{len(out)} segments, video/audio frame shift counts:",
          {d: sum(1 for s in out if s['dv'] == d) for d in (-2, -1, 0, 1, 2)},
          "punch-in segments:", n_zoom, "colour:", col)


if __name__ == "__main__":
    main()

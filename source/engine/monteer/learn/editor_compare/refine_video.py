"""Rebuild the reference editor's keep list, last step: pin the editor's cut points with the picture where the audio can't (the raw audio is gated: pauses
are digital silence, so any offset fits there).

For every boundary between two audio-mapped segments (offset A then offset B, in frames), each
edit frame between the last frame audio-confirmed on A and the first audio-confirmed on B is
compared with raw frame k+A and raw frame k+B; the switch frame that maximises the summed match
is the cut. The spread of near-best switch frames is kept as the uncertainty.

Writes editor_keep.json: [{ed_s, ed_e, src_s, src_e, shift_frames, src_audio_s, src_audio_e, audio_ncc, video_ncc,
unsure_in, unsure_out}] and editor_holes.json (inserted black + silent gaps, in the editor's time).

    <core python> -m monteer.learn.editor_compare.refine_video --out <compare dir>

Needs <out>/editor_map.json (map_fix) and the 160x90 grey thumbnails <out>/editor_g160.u8, raw_g160.u8 (thumbs.sh;
--edit-thumbs / --src-thumbs for other files).
"""
import argparse
import json
from pathlib import Path

import numpy as np

W, H = 160, 90


def frames(path):
    return np.fromfile(path, np.uint8).reshape(-1, H, W)


def nccs(E, R, ks, shift):
    out = []
    for k in ks:
        m = k + shift
        if not (0 <= m < len(R)):
            out.append(-1.0)
            continue
        a = E[k].astype(np.float32).ravel()
        b = R[m].astype(np.float32).ravel()
        a -= a.mean()
        b -= b.mean()
        d = np.sqrt((a * a).sum() * (b * b).sum())
        out.append(float((a * b).sum() / d) if d > 0 else 0.0)
    return np.array(out)


def main():
    ap = argparse.ArgumentParser(description="Pin the editor's cut points with the picture; writes the editor's keep list.")
    ap.add_argument("--out", required=True, help="comparison folder with editor_map.json; results go here")
    ap.add_argument("--edit-thumbs", help="160x90 grey frames of the editor's cut (default <out>/editor_g160.u8)")
    ap.add_argument("--src-thumbs", help="160x90 grey frames of the raw (default <out>/raw_g160.u8)")
    opt = ap.parse_args()
    D = Path(opt.out)
    E = frames(opt.edit_thumbs or D / "editor_g160.u8")
    R = frames(opt.src_thumbs or D / "raw_g160.u8")
    m = json.load(open(D / "editor_map.json"))
    fn = np.array(m["frame_ncc"])
    fdb = np.array(m["frame_db"])
    segs = m["segs"]
    # the editor's audio runs 51 ppm against the raw's audio (fitted on the sub-frame offsets of reference episode B)
    lum = E.reshape(len(E), -1).mean(1)
    hole = (lum < 5) & (fdb < -150)  # black picture + digital silence: inserted gap, not raw
    split = []
    for s in segs:
        k0, k1 = int(round(s["ed_s"] * 24)), int(round(s["ed_e"] * 24))
        k = k0
        while k < k1:
            if hole[k]:
                k += 1
                continue
            u = k
            while u < k1 and not hole[u]:
                u += 1
            split.append(dict(s, k0=k, k1=u))
            k = u
    holes = []
    d = np.diff(np.concatenate([[0], hole.astype(np.int8), [0]]))
    for a, b in zip(np.where(d == 1)[0], np.where(d == -1)[0]):
        holes.append({"ed_s": a / 24, "ed_e": b / 24})
    json.dump(holes, open(D / "editor_holes.json", "w"))
    segs = [s for s in split if s["k1"] - s["k0"] >= 1]
    # full-resolution checks: the editor's picture sits 0..1 frame after the editor's audio (vs the raw's own pairing),
    # so the picture shift is the audio offset rounded UP to a whole frame
    for s in segs:
        s["shift"] = int(np.ceil(s["off48"] / 2000 - 0.005))
        s["sub"] = int(round(s["shift"] * 2000 - s["off48"]))
    # audio-confirmed frames: audible and the waveform matches
    conf = (fn > 0.8) & (fdb > -60)
    out = []
    for i, s in enumerate(segs):
        out.append(dict(s))
    for i in range(len(out) - 1):
        a, b = out[i], out[i + 1]
        if a["k1"] != b["k0"]:  # an inserted gap sits between them: both edges are exact already
            continue
        lo = a["k0"]
        ca = [k for k in range(a["k0"], a["k1"]) if conf[k]]
        cb = [k for k in range(b["k0"], b["k1"]) if conf[k]]
        lo = (ca[-1] + 1) if ca else a["k0"]
        hi = cb[0] if cb else b["k1"]
        if hi <= lo:
            continue
        ks = list(range(lo, hi))
        ma = nccs(E, R, ks, a["shift"])
        mb = nccs(E, R, ks, b["shift"])
        # switch at j: frames lo..j-1 on A, j..hi-1 on B
        sc = np.array([ma[: j - lo].sum() + mb[j - lo:].sum() for j in range(lo, hi + 1)])
        j = lo + int(np.argmax(sc))
        near = [lo + x for x in np.where(sc >= sc.max() - 0.02)[0]]
        a["k1"] = j
        b["k0"] = j
        a["unsure_out"] = int(max(near) - min(near))
        b["unsure_in"] = int(max(near) - min(near))
    edl = []
    for s in out:
        if s["k1"] <= s["k0"]:
            continue
        ks = list(range(s["k0"], s["k1"]))
        vm = nccs(E, R, ks[:: max(1, len(ks) // 8)], s["shift"])
        edl.append({"ed_s": s["k0"] / 24, "ed_e": s["k1"] / 24,
                    "src_s": (s["k0"] + s["shift"]) / 24, "src_e": (s["k1"] + s["shift"]) / 24,
                    "shift_frames": s["shift"],
                    "src_audio_s": s["k0"] / 24 + s["off48"] / 48000, "src_audio_e": s["k1"] / 24 + s["off48"] / 48000, "audio_sub_samples48": s["sub"],
                    "audio_ncc": s["ncc_med"], "video_ncc": round(float(np.median(vm)), 3),
                    "unsure_in": s.get("unsure_in", 0), "unsure_out": s.get("unsure_out", 0)})
    json.dump(edl, open(D / "editor_keep.json", "w"), indent=0)
    print(len(edl), "segments; video ncc median", np.median([e["video_ncc"] for e in edl]),
          "; sub-frame audio offsets:", sorted(set(e["audio_sub_samples48"] for e in edl))[:20])


if __name__ == "__main__":
    main()

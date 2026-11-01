"""Second pass of the audio map: catch short cuts the first pass missed (removing part of a gated,
digitally silent pause looks the same on both sides, so only the next sound reveals the new offset).

Every 1/8 s window of the editor's audio with sound is located within +-8 s of its first-pass offset (16 kHz
waveform correlation, then refined to the 48 kHz sample). Those offsets join the candidate set and
the per-frame Viterbi of map_audio is run again.  Writes editor_map.json (first pass kept as editor_map1.json).

    <core python> -m monteer.learn.editor_compare.map_fix --src16 <raw 16k mono wav> --src48 <raw 48k wav> --out <compare dir>

Same arguments as map_audio (--edit16 / --edit48 default to <out>/editor16.wav, <out>/editor48s.wav).
"""
import json
import os

import numpy as np
from scipy.signal import fftconvolve

from .map_audio import FR48, args, load, ncc, refine

WIN16 = 4000      # 0.25 s at 16 kHz
STEP16 = 2000     # every 1/8 s
SPAN = 8.0


def main():
    opt = args("Second pass of the audio map: catch short cuts the first pass missed.")
    if not os.path.exists(opt.out / "editor_map1.json"):
        os.rename(opt.out / "editor_map.json", opt.out / "editor_map1.json")
    first = json.load(open(opt.out / "editor_map1.json"))["segs"]
    _, e16 = load(opt.edit16)
    _, r16 = load(opt.src16)
    _, e48 = load(opt.edit48)
    _, r48 = load(opt.src48)

    def off_at(t):
        s = next((s for s in first if s["ed_s"] <= t < s["ed_e"]), first[-1])
        return s["off48"]

    cands = []
    for i in range(0, len(e16) - WIN16, STEP16):
        w = e16[i: i + WIN16]
        if 20 * np.log10(np.sqrt((w * w).mean()) + 1e-9) < -40:
            continue
        t = i / 16000
        base = i + off_at(t) / 3
        lo = int(max(0, base - SPAN * 16000))
        hi = int(min(len(r16), base + SPAN * 16000 + WIN16))
        ref = r16[lo:hi]
        c = fftconvolve(ref, w[::-1], mode="valid")
        en = np.sqrt(np.maximum(fftconvolve(ref ** 2, np.ones(WIN16), mode="valid"), 1e-6)) * np.linalg.norm(w)
        nc = c / en
        k = int(np.argmax(nc))
        if nc[k] < 0.8:
            continue
        off10 = int(round(((lo + k) - i) / 160))
        r = refine(e48, r48, t, off10, span=0.25, lag=240)
        if r and r[1] > 0.8:
            cands.append((t, r[0], r[1]))
    for s in first:  # keep the first pass offsets as candidates too
        cands.append(((s["ed_s"] + s["ed_e"]) / 2, s["off48"], s["ncc_med"]))
    print("candidates", len(cands), flush=True)

    nfr = len(e48) // FR48
    K = 24
    ct = np.array([c[0] for c in cands])
    cv = np.array([c[1] for c in cands])
    cand = np.zeros((nfr, K), np.int64)
    for k in range(nfr):
        t = k / 24
        near = cv[np.abs(ct - t) <= 3]
        if len(near) == 0:
            near = cv[np.argsort(np.abs(ct - t))[:3]]
        vals, cnt = np.unique(near, return_counts=True)
        vals = vals[np.argsort(-cnt)][:K]
        cand[k] = np.resize(vals, K)
    cost = np.ones((nfr, K), np.float32)
    lev = np.zeros(nfr, np.float32)
    for k in range(nfr):
        a = e48[k * FR48:(k + 1) * FR48]
        lev[k] = 20 * np.log10(np.sqrt((a * a).mean()) + 1e-9)
        for j in range(K):
            s0 = k * FR48 + cand[k, j]
            if 0 <= s0 and s0 + FR48 <= len(r48):
                cost[k, j] = 1 - ncc(a, r48[s0: s0 + FR48])
    SW = 2.5
    acc = cost[0].astype(np.float64)
    back = np.zeros((nfr, K), np.int16)
    for k in range(1, nfr):
        same = cand[k][:, None] == cand[k - 1][None, :]
        trans = acc[None, :] + np.where(same, 0.0, SW)
        b = np.argmin(trans, 1)
        back[k] = b
        acc = trans[np.arange(K), b] + cost[k]
    j = int(np.argmin(acc))
    choice = np.zeros(nfr, np.int64)
    fcost = np.zeros(nfr, np.float32)
    for k in range(nfr - 1, -1, -1):
        choice[k] = cand[k, j]
        fcost[k] = cost[k, j]
        j = back[k, j]
    segs = []
    k = 0
    while k < nfr:
        u = k
        while u + 1 < nfr and choice[u + 1] == choice[k]:
            u += 1
        segs.append({"ed_s": k / 24, "ed_e": (u + 1) / 24, "off48": int(choice[k]),
                     "src_s": (k * FR48 + choice[k]) / 48000, "src_e": ((u + 1) * FR48 + choice[k]) / 48000,
                     "ncc_med": float(1 - np.median(fcost[k:u + 1])), "frames": u - k + 1})
        k = u + 1
    json.dump({"segs": segs, "frame_ncc": (1 - fcost).round(3).tolist(), "frame_db": lev.round(1).tolist()},
              open(opt.out / "editor_map.json", "w"))
    print(len(segs), "segments (first pass:", len(first), ")")


if __name__ == "__main__":
    main()

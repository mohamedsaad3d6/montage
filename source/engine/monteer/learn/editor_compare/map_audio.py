"""Rebuild the reference editor's keep list, step 1: map every frame of the editor's cut back onto the raw timeline
by audio.

1. Coarse: every 0.25 s a 2 s window of the editor's audio (24-band spectral shape, 10 ms frames)
   is located anywhere in the raw by FFT cross-correlation (top 3 peaks kept).
2. Refine each candidate offset to the sample at 48 kHz (waveform cross-correlation).
3. Per video frame (1/24 s = 2000 samples), score every nearby candidate by waveform
   correlation; a Viterbi pass with a switch penalty picks one offset per frame.
   Runs of one offset = the editor's kept segments.

    <core python> -m monteer.learn.editor_compare.map_audio --src16 <raw 16k mono wav> --src48 <raw 48k wav> --out <compare dir>

The editor's cut audio is <out>/editor16.wav (16 kHz mono) and <out>/editor48s.wav (48 kHz) unless --edit16 / --edit48
say otherwise. Writes <out>/coarse.json and <out>/editor_map.json. Next: map_fix, then refine_video.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import scipy.fft as sf
from scipy.io import wavfile
from scipy.signal import fftconvolve, stft

SR = 16000
HOP = 160
BANDS = 24
WIN, STEP = 200, 25  # coarse window / step in 10 ms frames
FR48 = 2000  # samples per video frame at 48 kHz


def band_features(x):
    _, _, Z = stft(x, fs=SR, nperseg=400, noverlap=400 - HOP, boundary=None, padded=False)
    P = np.abs(Z) ** 2
    edges = np.unique(np.geomspace(3, P.shape[0] - 1, BANDS + 1).astype(int))
    B = np.stack([P[a:b].sum(0) for a, b in zip(edges[:-1], edges[1:])], axis=1)
    L = np.log10(B + 1e-10)
    energy = L.max(1)
    L = L - L.mean(1, keepdims=True)
    L = L / (np.linalg.norm(L, axis=1, keepdims=True) + 1e-9)
    return L.astype(np.float32), energy


def load(path, mono=True):
    sr, x = wavfile.read(path)
    x = x.astype(np.float32) / 32768
    if x.ndim == 2 and mono:
        x = x.mean(1)
    return sr, x


def coarse(e16, r16):
    Fe, Ee = band_features(e16)
    Fr, Er = band_features(r16)
    thr = np.percentile(Er, 30)
    Fe[Ee < thr] = 0
    Fr[Er < thr] = 0
    N = sf.next_fast_len(len(Fr) + WIN)
    FR = sf.rfft(Fr, n=N, axis=0, workers=8)
    out = []
    for c0 in range(0, len(Fe) - WIN // 2, STEP):
        W = Fe[c0: c0 + WIN]
        act = int((np.abs(W).sum(1) > 0).sum())
        if act < 40:
            continue
        FW = sf.rfft(W[::-1], n=N, axis=0, workers=8)
        cc = sf.irfft((FR * FW).sum(1), n=N, workers=8)[len(W) - 1: len(W) - 1 + len(Fr)]
        cc /= act
        peaks = []
        for k in np.argsort(-cc)[:200]:
            if all(abs(k - p) > 50 for p, _ in peaks):
                peaks.append((int(k), float(cc[k])))
            if len(peaks) == 3:
                break
        out.append({"e": c0, "peaks": [(p - c0, s) for p, s in peaks]})  # offset in 10 ms frames
        if c0 % 5000 == 0:
            print("coarse", c0 * HOP / SR, peaks[0], flush=True)
    return out


def ncc(a, b):
    a = a - a.mean()
    b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 1e-12 else 0.0


def refine(e48, r48, at, off10, span=1.0, lag=600):
    """Sample offset (48 kHz) near off10 (10 ms frames) for edit time `at` (s)."""
    a = int(at * 48000)
    n = int(span * 48000)
    seg = e48[a: a + n]
    base = a + off10 * 480
    lo, hi = base - lag, base + lag + n
    if lo < 0 or hi > len(r48) or len(seg) < n:
        return None
    ref = r48[lo:hi]
    c = fftconvolve(ref, seg[::-1], mode="valid")
    k = int(np.argmax(c))
    return base - lag + k - a, ncc(seg, r48[lo + k: lo + k + n])


def args(desc):
    """Command line shared with map_fix: the four audio files and the output folder."""
    ap = argparse.ArgumentParser(description=desc)
    ap.add_argument("--out", required=True, help="comparison folder; the map is written here")
    ap.add_argument("--src16", required=True, help="raw (source) audio, 16 kHz mono wav")
    ap.add_argument("--src48", required=True, help="raw (source) audio, 48 kHz wav")
    ap.add_argument("--edit16", help="the editor's cut audio, 16 kHz mono wav (default <out>/editor16.wav)")
    ap.add_argument("--edit48", help="the editor's cut audio, 48 kHz wav (default <out>/editor48s.wav)")
    opt = ap.parse_args()
    opt.out = Path(opt.out)
    opt.edit16 = opt.edit16 or opt.out / "editor16.wav"
    opt.edit48 = opt.edit48 or opt.out / "editor48s.wav"
    return opt


def main():
    opt = args("Map the reference editor's cut onto the raw timeline by audio (first pass).")
    _, e16 = load(opt.edit16)
    _, r16 = load(opt.src16)
    co = coarse(e16, r16)
    json.dump(co, open(opt.out / "coarse.json", "w"))
    _, e48 = load(opt.edit48)
    _, r48 = load(opt.src48)

    # candidate offsets per coarse window: refine the best peaks to the sample
    cands = []  # (edit_time_s, offset_samples48, ncc)
    cache = {}
    for w in co:
        t = (w["e"] + WIN / 2) * HOP / SR - 0.5
        for off10, sc in w["peaks"][:2]:
            if sc < 0.25:
                continue
            key = (round(t * 2) / 2, off10)
            if key in cache:
                continue
            r = refine(e48, r48, t, off10)
            cache[key] = r
            if r and r[1] > 0.5:
                cands.append((t, r[0], r[1]))
    print("refined candidates", len(cands), flush=True)

    nfr = len(e48) // FR48
    K = 24
    cand = np.zeros((nfr, K), np.int64)
    ct = np.array([c[0] for c in cands])
    cv = np.array([c[1] for c in cands])
    for k in range(nfr):
        t = k / 24
        near = cv[np.abs(ct - t) <= 4]
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
    print(len(segs), "segments")


if __name__ == "__main__":
    main()

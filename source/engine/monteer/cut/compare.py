"""Stage 8: reconstruct the human editor's EDL from the reference cut, and diff it with ours.

1. Coarse: every 0.5 s, a 2 s window of the reference audio envelope is located in the
   source (synced external audio on the camera timeline) by FFT cross-correlation.
2. Fine: a Viterbi pass over 10 ms frames picks, per frame, one of the nearby candidate
   offsets using multi-band spectral similarity, with a penalty for switching. Runs of
   constant offset are the editor's kept segments.
"""
import numpy as np
from scipy.io import wavfile
from scipy.signal import fftconvolve, stft

from .common import SR, WORK, cached, load_json, save_json
from .sync import CAM16, REF16, SYNC16, envelope

REF_EDL = WORK / "ref_edl.json"
HOP = 160
BANDS = 24
SWITCH = 6.0


def band_features(x):
    _, _, Z = stft(x, fs=SR, nperseg=400, noverlap=400 - HOP, boundary=None, padded=False)
    P = np.abs(Z) ** 2  # (freq, frames)
    edges = np.unique(np.geomspace(3, P.shape[0] - 1, BANDS + 1).astype(int))
    B = np.stack([P[a:b].sum(0) for a, b in zip(edges[:-1], edges[1:])], axis=1)
    L = np.log10(B + 1e-10)
    energy = L.max(1)
    L = L - L.mean(1, keepdims=True)  # spectral shape only: robust to gain/compression
    L = (L - L.mean(0)) / (L.std(0) + 1e-6)
    return L.astype(np.float32), energy


def source_audio():
    _, s = wavfile.read(SYNC16)
    _, c = wavfile.read(CAM16)
    s = s.astype(np.float32) / 32768
    c = c.astype(np.float32) / 32768
    n = min(len(s), len(c))
    s, c = s[:n], c[:n]
    cov = load_json(WORK / "sync.json")["cam_covered"]
    mask = np.zeros(n, bool)
    for a, b in cov:
        mask[int(a * SR): int(b * SR)] = True
    # fallback to camera audio where there is no external audio (scaled to similar loudness)
    scale = (np.std(s[mask]) + 1e-9) / (np.std(c[mask]) + 1e-9)
    return np.where(mask, s, c * scale)


def word_anchors(ref_words, src_words, min_score=0.6):
    """Align the reference transcript to the source transcript (same DP as take selection:
    the editor's cut walks forward through the source, skipping retakes and pauses).
    Returns offsets (source - reference, seconds) for confidently matched words."""
    from .align import dp_align, similarity, BACK, CONT, INSERT, SKIP_FAR, SKIP_LIN, START
    ms = similarity([w["n"] for w in ref_words], [w["n"] for w in src_words])
    path = dp_align(ms)
    out = []
    for i, (t, j) in enumerate(path):
        if t in (CONT, SKIP_LIN, SKIP_FAR, BACK, START) and j >= 0 and ms[i, j] >= min_score:
            out.append((ref_words[i]["s"], src_words[j]["s"] - ref_words[i]["s"]))
    return out


def reconstruct(ref_words, src_words, force=False):
    if cached(REF_EDL) and not force:
        return load_json(REF_EDL)
    _, r = wavfile.read(REF16)
    r = r.astype(np.float32) / 32768
    src = source_audio()

    anchors = word_anchors(ref_words, src_words)
    print(f"reference words anchored to source: {len(anchors)} of {len(ref_words)}")
    # anchor offsets are approximate (word timestamps); add +-2 frame variants, the
    # Viterbi pass picks the one whose spectra actually line up
    conf = [(int(t * 100), int(round(o * 100)) + d) for t, o in anchors for d in (-2, -1, 0, 1, 2)]

    Fr, Er = band_features(r)
    Fs, Es = band_features(src)
    n = len(Fr)
    K = 16
    cf = np.array([f for f, _ in conf])
    co = np.array([o for _, o in conf])
    # per-frame candidate offsets: the distinct offsets of confident windows within +-4 s
    cand = np.zeros((n, K), dtype=np.int64)
    for t in range(0, n, 25):
        near = co[np.abs(cf - t) <= 300]
        if len(near) == 0:
            near = co[np.argsort(np.abs(cf - t))[:3]] if len(co) else np.array([0])
        vals, cnt = np.unique(near, return_counts=True)
        vals = vals[np.argsort(-cnt)][:K]
        row = np.resize(vals, K)
        cand[t: t + 25] = row

    # frame cost: 1 - cosine similarity of spectral shape, smoothed; neutral when ref is quiet
    idx = np.clip(np.arange(n)[:, None] + cand, 0, len(Fs) - 1)
    sim = np.einsum("nb,nkb->nk", Fr, Fs[idx]) / BANDS
    cost = 1 - sim
    quiet = Er < np.percentile(Er, 20)
    cost[quiet] = 0.6
    ker = np.ones(15) / 15
    cost = np.stack([np.convolve(cost[:, k], ker, mode="same") for k in range(K)], 1)

    # Viterbi: staying on the same offset is free, switching costs SWITCH
    acc = cost[0].copy()
    back = np.zeros((n, K), dtype=np.int16)
    for t in range(1, n):
        same = cand[t][:, None] == cand[t - 1][None, :]  # (K new, K old)
        trans = acc[None, :] + np.where(same, 0.0, SWITCH)
        b = np.argmin(trans, axis=1)
        back[t] = b
        acc = trans[np.arange(K), b] + cost[t]
    k = int(np.argmin(acc))
    choice = np.zeros(n, dtype=np.int64)
    for t in range(n - 1, -1, -1):
        choice[t] = cand[t, k]
        k = back[t, k]
    fcost = cost[np.arange(n), np.argmax(cand == choice[:, None], axis=1)]

    segs = []
    t = 0
    while t < n:
        u = t
        while u + 1 < n and choice[u + 1] == choice[t]:
            u += 1
        segs.append({"ref_s": t * HOP / SR, "ref_e": (u + 1) * HOP / SR,
                     "src_s": (t + choice[t]) * HOP / SR, "src_e": (u + 1 + choice[t]) * HOP / SR,
                     "cost": float(fcost[t: u + 1].mean())})
        t = u + 1
    save_json(REF_EDL, segs)
    good = [s for s in segs if s["cost"] < 0.5]
    print(f"reference EDL: {len(segs)} segments ({len(good)} well matched), "
          f"{sum(s['ref_e'] - s['ref_s'] for s in good):.0f}s of {n * HOP / SR:.0f}s matched")
    return segs


def to_mask(intervals, dur, res=0.01):
    m = np.zeros(int(dur / res) + 1, bool)
    for s, e in intervals:
        m[int(max(s, 0) / res): int(max(e, 0) / res)] = True
    return m


def runs(mask, res=0.01):
    out, t = [], 0
    while t < len(mask):
        if mask[t]:
            u = t
            while u + 1 < len(mask) and mask[u + 1]:
                u += 1
            out.append([t * res, (u + 1) * res])
            t = u + 1
        else:
            t += 1
    return out


def diff(auto_keep, ref_segs, cam_dur, min_len=1.0, bridge=0.6):
    """Second-by-second comparison of the two keep-lists in source (camera) time."""
    ref_keep = [[s["src_s"], s["src_e"]] for s in ref_segs if s["cost"] < 0.5]
    A, R = to_mask(auto_keep, cam_dur), to_mask(ref_keep, cam_dur)
    both, only_a, only_r = A & R, A & ~R, R & ~A
    res = 0.01

    def regions(mask):
        rs = runs(mask)
        merged = []
        for s, e in rs:  # bridge tiny gaps so one disagreement is one region
            if merged and s - merged[-1][1] < bridge:
                merged[-1][1] = e
            else:
                merged.append([s, e])
        return [r for r in merged if r[1] - r[0] >= min_len]

    return {"auto_s": A.sum() * res, "ref_s": R.sum() * res, "both_s": both.sum() * res,
            "auto_only_s": only_a.sum() * res, "ref_only_s": only_r.sum() * res,
            "auto_only": regions(only_a), "ref_only": regions(only_r), "ref_keep": ref_keep}

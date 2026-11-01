"""10 ms frame features of the raw audio for the join measurement (cached to <out>/feat.npz):
db (RMS level), voicing (normalized autocorrelation peak at 70-400 Hz: high = voiced speech), centroid (Hz),
flatness (1 = noise-like) of the spectrum, and the share of energy in 8 bands (100 Hz - 8 kHz, dB).

    <core python> -m monteer.learn.joins.feat --wav <episode work>/sync_ext16.wav --out <joins dir>
"""
import argparse
import os
from pathlib import Path

import numpy as np
from scipy.io import wavfile

FRAME = 0.01


def compute(path):
    sr, x = wavfile.read(path)
    x = x.astype(np.float32) / 32768.0
    if x.ndim == 2:
        x = x.mean(axis=1)
    hop, win = int(sr * FRAME), int(sr * 0.032)
    n = len(x) // hop
    pad = np.concatenate([np.zeros(win // 2, np.float32), x, np.zeros(win, np.float32)])
    idx = np.arange(win)[None, :] + (np.arange(n) * hop)[:, None]
    db = np.empty(n, np.float32)
    voi = np.empty(n, np.float32)
    cen = np.empty(n, np.float32)
    flat = np.empty(n, np.float32)
    bands = np.empty((n, 8), np.float32)
    w = np.hanning(win).astype(np.float32)
    freqs = np.fft.rfftfreq(1024, 1 / sr)
    lo, hi = int(sr / 400), int(sr / 70)
    edges = np.searchsorted(freqs, np.geomspace(100, 8000, 9))
    for c in range(0, n, 20000):
        f = pad[idx[c:c + 20000]]
        f = f - f.mean(axis=1, keepdims=True)
        mid = x[np.minimum((np.arange(c, min(n, c + 20000)) * hop)[:, None] + np.arange(hop)[None, :], len(x) - 1)]
        db[c:c + len(f)] = 20 * np.log10(np.sqrt((mid ** 2).mean(axis=1)) + 1e-6)
        F = np.fft.rfft(f * w, 1024, axis=1)
        P = np.abs(F) ** 2 + 1e-12
        cen[c:c + len(f)] = (P * freqs).sum(axis=1) / P.sum(axis=1)
        band = P[:, 4:480]  # ~60 Hz - 7.5 kHz
        flat[c:c + len(f)] = np.exp(np.log(band).mean(axis=1)) / band.mean(axis=1)
        be = np.stack([P[:, edges[i]:edges[i + 1]].sum(axis=1) for i in range(8)], axis=1)
        bands[c:c + len(f)] = 10 * np.log10(be / be.sum(axis=1, keepdims=True))
        ac = np.fft.irfft(np.abs(np.fft.rfft(f, 2048, axis=1)) ** 2, axis=1)[:, :hi + 1]
        voi[c:c + len(f)] = ac[:, lo:hi + 1].max(axis=1) / (ac[:, 0] + 1e-9)
    return {"db": db, "voi": voi, "cen": cen, "flat": flat, "bands": bands}


def load(wav, cache):
    """Features of wav, cached in the file cache (computed once)."""
    if os.path.exists(cache):
        z = np.load(cache)
        return {k: z[k] for k in z.files}
    f = compute(wav)
    np.savez(cache, **f)
    return f


def main():
    ap = argparse.ArgumentParser(description="10 ms frame features of the raw audio for the join measurement.")
    ap.add_argument("--wav", required=True, help="raw audio on the camera timeline, 16 kHz (the episode's sync_ext16.wav)")
    ap.add_argument("--out", required=True, help="joins folder; feat.npz is cached here")
    opt = ap.parse_args()
    f = load(opt.wav, Path(opt.out) / "feat.npz")
    print({k: (v.shape, float(np.median(v))) for k, v in f.items()})


if __name__ == "__main__":
    main()

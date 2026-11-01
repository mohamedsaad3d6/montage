"""Acoustic repeat test: does a stretch of audio sound like the words right after (or before) it?

Whisper often writes a stammered or restarted phrase only once, so the transcript can't show the
repeat. Two takes of the same words by the same speaker look alike in MFCCs; different words don't.
The distance is an open-end DTW cost per frame of the shorter stretch.
"""
import numpy as np
from scipy.fft import dct
from scipy.io import wavfile

from .sync import SYNC16

SR = 16000
HOP = 160
WIN = 400
N_MEL = 40
_audio = None


def audio():
    global _audio
    if _audio is None:
        sr, x = wavfile.read(str(SYNC16))
        _audio = x.astype(np.float32) / 32768.0
    return _audio


def _mel_fb():
    nfft = 512
    hz = np.linspace(0, 2595 * np.log10(1 + (SR / 2) / 700), N_MEL + 2)
    hz = 700 * (10 ** (hz / 2595) - 1)
    bins = np.floor((nfft + 1) * hz / SR).astype(int)
    fb = np.zeros((N_MEL, nfft // 2 + 1))
    for m in range(1, N_MEL + 1):
        a, b, c = bins[m - 1], bins[m], bins[m + 1]
        fb[m - 1, a:b] = (np.arange(a, b) - a) / max(1, b - a)
        fb[m - 1, b:c] = (c - np.arange(b, c)) / max(1, c - b)
    return fb


FB = _mel_fb()


def mfcc(t0, t1):
    x = audio()[max(0, int(t0 * SR)): int(t1 * SR)]
    if len(x) < WIN:
        return np.zeros((0, 12))
    x = np.append(x[0], x[1:] - 0.97 * x[:-1])
    n = 1 + (len(x) - WIN) // HOP
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx] * np.hamming(WIN)
    spec = np.abs(np.fft.rfft(frames, 512)) ** 2
    mel = np.log(spec @ FB.T + 1e-8)
    c = dct(mel, type=2, axis=1, norm="ortho")[:, 1:13]
    return c


def _norm(a, ref):
    mu, sd = ref.mean(0), ref.std(0) + 1e-6
    return (a - mu) / sd


def dtw_open_end(a, b):
    """Align all of a to a prefix of b; cost per frame of a."""
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return 9.0
    d = np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).sum(-1))
    D = np.full((n + 1, m + 1), np.inf)
    D[0, 0] = 0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D[i, j] = d[i - 1, j - 1] + min(D[i - 1, j - 1], D[i - 1, j], D[i, j - 1])
    return float(D[n, 1:].min() / (n + m) * 2)


def dtw_sub(a, b):
    """Best match of all of a anywhere inside b (subsequence DTW); cost per frame."""
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return 9.0
    d = np.sqrt(((a[:, None, :] - b[None, :, :]) ** 2).sum(-1))
    D = np.full((n + 1, m + 1), np.inf)
    D[0, :] = 0
    L = np.zeros((n + 1, m + 1))
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            opts = (D[i - 1, j - 1], D[i - 1, j], D[i, j - 1])
            k = int(np.argmin(opts))
            D[i, j] = d[i - 1, j - 1] + opts[k]
            L[i, j] = (L[i - 1, j - 1], L[i - 1, j], L[i, j - 1])[k] + 1
    j = int(np.argmin(D[n, 1:] / np.maximum(L[n, 1:], 1))) + 1
    return float(D[n, j] / max(L[n, j], 1))


def similarity(h0, h1, w0, w1, ctx=None):
    """Distance between audio [h0,h1] and the best-matching part of [w0,w1] (lower = more alike)."""
    c0, c1 = ctx or (min(h0, w0) - 2.0, max(h1, w1) + 2.0)
    ref = mfcc(c0, c1)
    a = _norm(mfcc(h0, h1), ref)
    b = _norm(mfcc(w0, w1), ref)
    return dtw_sub(a, b)

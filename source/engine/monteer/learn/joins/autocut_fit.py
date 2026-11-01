"""Measurement only: which AutoCut settings reproduce the reference editor's cut edges?

Simulates AutoCut on the raw audio (talk = level above a threshold; silences shorter than MIN_SIL are
not removed; talks shorter than MIN_TALK are dropped; a margin is kept before / after each talk;
edges on video frames) and measures how close each of the editor's cut edges is to a simulated edge.

    <core python> -m monteer.learn.joins.autocut_fit --wav <episode work>/sync_ext48.wav --editor <compare dir> --out <joins dir>

--editor is the editor_compare folder holding editor_keep.json; writes <out>/autocut_fit.json.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.io import wavfile

MS = 0.001
FPS = 24


def envelope(path):
    """1 ms RMS and 1 ms peak level (dBFS) of the raw audio (mono mix)."""
    sr, x = wavfile.read(path)
    x = x.astype(np.float32) / 32768.0
    if x.ndim == 2:
        x = x.mean(axis=1)
    hop = sr // 1000
    n = len(x) // hop
    f = x[: n * hop].reshape(n, hop)
    rms = 20 * np.log10(np.sqrt((f ** 2).mean(axis=1)) + 1e-9)
    peak = 20 * np.log10(np.abs(f).max(axis=1) + 1e-9)
    return rms, peak


def smooth_db(db, win_ms):
    """Level over a sliding window of win_ms (energy average), like a meter with some integration."""
    if win_ms <= 1:
        return db
    p = 10 ** (db / 10)
    k = np.ones(win_ms) / win_ms
    return 10 * np.log10(np.convolve(p, k, mode="same") + 1e-18)


def runs(mask):
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return np.where(d == 1)[0], np.where(d == -1)[0]


def autocut(level, thr, before, after, min_talk=0.1, min_sil=0.0):
    """Kept intervals in seconds."""
    s, e = runs(level > thr)
    if len(s) == 0:
        return []
    # silences shorter than min_sil stay (talks either side merge)
    keep_s, keep_e = [s[0]], [e[0]]
    for a, b in zip(s[1:], e[1:]):
        if (a - keep_e[-1]) * MS < min_sil:
            keep_e[-1] = b
        else:
            keep_s.append(a)
            keep_e.append(b)
    out = []
    for a, b in zip(keep_s, keep_e):
        if (b - a) * MS < min_talk:
            continue
        a2, b2 = a * MS - before, b * MS + after
        a2, b2 = round(a2 * FPS) / FPS, round(b2 * FPS) / FPS
        if out and a2 <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b2)
        else:
            out.append([a2, b2])
    return out


def edge_match(his, sim, tol=0.5 / FPS + 1e-6):
    """Share of the editor's cut edges (in / out, joins only) that have a simulated edge of the same kind within tol."""
    si = np.array([a for a, b in sim])
    so = np.array([b for a, b in sim])
    ins = [p[0] for p in his[1:]]
    outs = [p[1] for p in his[:-1]]
    def share(xs, ys):
        return float(np.mean([np.min(np.abs(ys - x)) <= tol for x in xs]))
    def off(xs, ys):
        return [float(ys[np.argmin(np.abs(ys - x))] - x) for x in xs]
    return share(ins, si), share(outs, so), off(ins, si), off(outs, so)


def main():
    ap = argparse.ArgumentParser(description="Which AutoCut settings reproduce the reference editor's cut edges?")
    ap.add_argument("--wav", required=True, help="raw audio on the camera timeline (the episode's sync_ext48.wav)")
    ap.add_argument("--editor", required=True, help="editor_compare folder with editor_keep.json")
    ap.add_argument("--out", required=True, help="joins folder; autocut_fit.json goes here")
    opt = ap.parse_args()
    rms, peak = envelope(opt.wav)
    editor = json.load(open(Path(opt.editor) / "editor_keep.json"))
    his = [[round(s["src_audio_s"] * FPS) / FPS, round(s["src_audio_e"] * FPS) / FPS] for s in editor]
    res = []
    for kind, base in (("rms", rms), ("peak", peak)):
        for win in (1, 10, 20, 50):
            lvl = smooth_db(base, win)
            for thr in range(-24, -50, -2):
                for m in (0.0, 0.025, 0.05, 0.075, 0.1, 0.125, 0.15):
                    for min_sil in (0.0, 0.1, 0.2, 0.3):
                        sim = autocut(lvl, thr, m, m, 0.1, min_sil)
                        a, b, _, _ = edge_match(his, sim)
                        res.append({"level": kind, "win_ms": win, "thr": thr, "margin": m, "min_sil": min_sil,
                                    "in": a, "out": b, "both": (a + b) / 2})
    res.sort(key=lambda r: -r["both"])
    for r in res[:15]:
        print(r)
    json.dump(res, open(Path(opt.out) / "autocut_fit.json", "w"), indent=0)


if __name__ == "__main__":
    main()

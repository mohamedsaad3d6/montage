"""Map the published video back onto the reference editor's cut video by audio (montage layer, measurement only).

    <core python> -m monteer.learn.style_study.pair_align <pair dir>

A pair folder holds one episode of the channel under study: cut.mp4 / cut16.wav (the reference editor's cut) and
pub.mp4 / pub16.wav (the published video made from it); every style-study tool reads and writes inside it.

1. Every 0.25 s, a 2 s window of the published audio's band envelope is located in the cut audio
   by FFT cross-correlation (normalised).  -> best offset (cut_t - pub_t) and its score.
2. Runs of windows sharing one offset (within 2 frames) with a good score are matched segments;
   everything else is material the montage added (intro, promo, B-roll with its own sound, ...).
3. Segment edges are refined to 10 ms by comparing the two band envelopes frame by frame.
4. Within each long segment, the offset drift gives any speed change.

Writes <pair dir>/align.json: {"segs": [{"p0","p1","c0","c1","off","score"}], "added": [...], "removed": [...]}.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import fftconvolve, stft

SR = 16000
HOP = 160          # 10 ms frames
WIN = 200          # 2 s windows
STEP = 25          # every 0.25 s
TOL = 0.09         # same offset within ~2 video frames
BANDS = 16


def bands(x):
    _, _, Z = stft(x, fs=SR, nperseg=400, noverlap=400 - HOP, boundary=None, padded=False)
    P = np.abs(Z) ** 2
    edges = np.unique(np.geomspace(6, 200, BANDS + 1).astype(int))  # ~240 Hz .. 8 kHz
    B = np.stack([P[a:b].sum(0) for a, b in zip(edges[:-1], edges[1:])], axis=1)
    return np.log10(B + 1e-9).astype(np.float32)


def env(B):
    """Speech-band loudness envelope in dB, floor-clipped so digital silence and quiet music look alike."""
    e = 10 * B.max(1)
    return np.maximum(e, e.max() - 60)


def locate(pe, ce, i):
    w = pe[i:i + WIN]
    if w.std() < 1.0:
        return None, 0.0
    w = (w - w.mean()) / w.std()
    num = fftconvolve(ce, w[::-1], mode="valid")
    # running mean/std of the cut envelope for a normalised correlation
    cs = np.cumsum(np.r_[0, ce])
    cs2 = np.cumsum(np.r_[0, ce ** 2])
    m = (cs[WIN:] - cs[:-WIN]) / WIN
    v = (cs2[WIN:] - cs2[:-WIN]) / WIN - m ** 2
    v = np.where(v < 4.0, np.inf, v)  # a flat cut window (silence, black slot) matches nothing
    r = num / (WIN * np.sqrt(v))
    j = int(np.argmax(r))
    return j, float(r[j])


def main(p):
    d = Path(p)
    p = d.name
    _, c = wavfile.read(d / "cut16.wav")
    _, q = wavfile.read(d / "pub16.wav")
    cb, qb = bands(c.astype(np.float32) / 32768), bands(q.astype(np.float32) / 32768)
    ce, qe = env(cb), env(qb)
    rows = []
    for i in range(0, len(qe) - WIN, STEP):
        j, r = locate(qe, ce, i)
        rows.append((i, j, r))
    # group windows into runs of one offset
    segs, cur = [], None
    for i, j, r in rows:
        ok = j is not None and r > 0.75
        off = (j - i) / 100 if ok else None
        if ok and cur and abs(off - cur["off"]) <= TOL and i - cur["last"] <= 4 * STEP:
            cur["last"], cur["n"], cur["rs"] = i, cur["n"] + 1, cur["rs"] + [r]
            cur["offs"].append(off)
        else:
            if ok:
                if cur:
                    segs.append(cur)
                cur = {"first": i, "last": i, "off": off, "n": 1, "rs": [r], "offs": [off]}
    if cur:
        segs.append(cur)
    segs = [s for s in segs if s["n"] >= 3]
    out = []
    for s in segs:
        off = float(np.median(s["offs"]))
        k = int(round(off * 100))
        # refine both edges frame by frame: extend while the two envelopes agree
        def agree(f):
            g = f + k
            if f < 0 or g < 0 or f >= len(qe) or g >= len(ce):
                return False
            return abs(qe[f] - ce[g]) < 6 or (qe[f] < qe.max() - 45 and ce[g] < ce.max() - 45)
        a, b = s["first"], s["last"] + WIN
        while a > 0 and agree(a - 1):
            a -= 1
        while b < len(qe) and agree(b):
            b += 1
        # drift (speed change): offset slope across the segment
        xs = np.array([s["first"] + n * STEP for n in range(len(s["offs"]))], float)
        slope = float(np.polyfit(xs / 100, s["offs"], 1)[0]) if len(xs) > 8 else 0.0
        out.append({"p0": a / 100, "p1": b / 100, "c0": (a + k) / 100, "c1": (b + k) / 100, "off": k / 100,
                    "score": round(float(np.median(s["rs"])), 3), "slope": round(slope, 5)})
    # merge overlaps of equal offset; trim overlaps between different offsets at the midpoint
    out.sort(key=lambda s: s["p0"])
    merged = []
    for s in out:
        if merged and abs(s["off"] - merged[-1]["off"]) < 0.015 and s["p0"] <= merged[-1]["p1"] + 0.3:
            merged[-1]["p1"] = max(merged[-1]["p1"], s["p1"])
            merged[-1]["c1"] = merged[-1]["p1"] + merged[-1]["off"]
        elif merged and s["p0"] < merged[-1]["p1"]:
            mid = (s["p0"] + merged[-1]["p1"]) / 2
            merged[-1]["p1"] = mid
            merged[-1]["c1"] = mid + merged[-1]["off"]
            s["p0"], s["c0"] = mid, mid + s["off"]
            merged.append(s)
        else:
            merged.append(s)
    merged = [s for s in merged if s["p1"] - s["p0"] > 0.2]
    # the montage keeps the cut in order: take the longest in-order chain (weighted by length);
    # an out-of-order piece survives only if it is long and certain (a re-used clip, e.g. a teaser)
    n = len(merged)
    best, prev = [0.0] * n, [-1] * n
    for i, s in enumerate(merged):
        best[i] = s["p1"] - s["p0"]
        for j in range(i):
            if merged[j]["c1"] <= s["c0"] + 1.0 and best[j] + s["p1"] - s["p0"] > best[i]:
                best[i], prev[i] = best[j] + s["p1"] - s["p0"], j
    chain, i = set(), int(np.argmax(best)) if n else -1
    while i >= 0:
        chain.add(i)
        i = prev[i]
    for i, s in enumerate(merged):
        s["in_order"] = i in chain
    merged = [s for i, s in enumerate(merged)
              if i in chain or (s["p1"] - s["p0"] >= 4 and s["score"] >= 0.9)]
    pub_dur, cut_dur = len(q) / SR, len(c) / SR
    added, t = [], 0.0
    for s in merged:
        if s["p0"] - t > 0.3:
            added.append({"p0": round(t, 2), "p1": round(s["p0"], 2), "dur": round(s["p0"] - t, 2)})
        t = max(t, s["p1"])
    if pub_dur - t > 0.3:
        added.append({"p0": round(t, 2), "p1": round(pub_dur, 2), "dur": round(pub_dur - t, 2)})
    # cut-video time that never shows up in the published video
    covered = np.zeros(int(cut_dur * 100) + 1, bool)
    for s in merged:
        covered[int(max(0, s["c0"]) * 100):int(s["c1"] * 100)] = True
    removed, k0 = [], None
    for f, v in enumerate(np.r_[covered, True]):
        if not v and k0 is None:
            k0 = f
        elif v and k0 is not None:
            if f - k0 >= 15:
                removed.append({"c0": k0 / 100, "c1": f / 100, "dur": (f - k0) / 100})
            k0 = None
    res = {"pub_dur": pub_dur, "cut_dur": cut_dur, "segs": merged, "added": added, "removed": removed,
           "order_monotonic": all(b["c0"] >= a["c1"] - 0.5 for a, b in zip(merged, merged[1:]))}
    json.dump(res, open(d / "align.json", "w"), indent=1, ensure_ascii=False)
    print(f"{p}: pub {pub_dur:.1f}s cut {cut_dur:.1f}s, {len(merged)} matched segments "
          f"({sum(s['p1'] - s['p0'] for s in merged):.1f}s), added {len(added)} "
          f"({sum(a['dur'] for a in added):.1f}s), cut-video time not used {sum(r['dur'] for r in removed):.1f}s, "
          f"monotonic {res['order_monotonic']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Map the published video onto the editor's cut by audio.")
    ap.add_argument("pair", help="pair folder (cut16.wav, pub16.wav); align.json is written there")
    main(ap.parse_args().pair)

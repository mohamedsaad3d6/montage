"""Stage 6: AutoCut-style silence detection (-32 dB) plus breath detection, on the synced ext audio."""
import re
import subprocess

import numpy as np
from scipy.io import wavfile

from .common import WORK, cached, load_json, save_json
from .sync import SYNC16, SYNC48

NOISE_DB = -32.0
MIN_SIL = 0.35   # seconds of continuous sub-threshold audio to count as a silence
FRAME = 0.01

SIL_JSON = WORK / "silences.json"


def detect_silences(force=False):
    if cached(SIL_JSON) and not force:
        return load_json(SIL_JSON)
    r = subprocess.run(["ffmpeg", "-v", "info", "-i", str(SYNC48), "-af",
                        f"silencedetect=noise={NOISE_DB}dB:d={MIN_SIL}", "-f", "null", "-"],
                       capture_output=True, text=True, check=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    sil = [[s, e] for s, e in zip(starts, ends)]
    if len(starts) > len(ends):
        sil.append([starts[-1], None])
    save_json(SIL_JSON, sil)
    print(f"silencedetect @ {NOISE_DB} dB / {MIN_SIL}s: {len(sil)} silences, "
          f"{sum((e or s) - s for s, e in sil):.0f}s total")
    return sil


def frame_db():
    """10 ms RMS level in dBFS of the synced external audio (camera timeline)."""
    sr, x = wavfile.read(SYNC16)
    x = x.astype(np.float32) / 32768.0
    hop = int(sr * FRAME)
    n = len(x) // hop
    rms = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    return 20 * np.log10(rms)


def quietest_point(db, t0, t1, prefer):
    """Time of the quietest 10 ms frame in [t0, t1]; ties broken toward `prefer`."""
    i0, i1 = int(max(t0, 0) / FRAME), int(max(t1, t0 + FRAME) / FRAME) + 1
    seg = db[i0:i1]
    if len(seg) == 0:
        return prefer
    # 3-frame smoothing so a single dip inside a word does not win
    sm = np.convolve(seg, np.ones(3) / 3, mode="same") if len(seg) >= 3 else seg
    dist = np.abs(np.arange(i0, i0 + len(seg)) * FRAME - prefer)
    k = int(np.argmin(sm + dist * 2.0))  # 2 dB per second of distance
    return (i0 + k) * FRAME


def breath_gaps(db, kept_words, min_gap=0.25, below_speech_db=12.0):
    """Gaps between consecutive kept words that are above the silence threshold but much quieter
    than the surrounding speech: breaths, lip noise, room tone. Returns [start, end, peak_db]."""
    out = []
    for a, b in zip(kept_words, kept_words[1:]):
        if b["i"] != a["i"] + 1:
            continue
        g0, g1 = a["e"], b["s"]
        if g1 - g0 < min_gap:
            continue
        i0, i1 = int(g0 / FRAME), int(g1 / FRAME)
        gap = db[i0:i1]
        if len(gap) == 0 or np.mean(gap < NOISE_DB) > 0.8:
            continue  # it is a real silence; silencedetect handles it
        ctx = db[max(0, i0 - 500): i1 + 500]
        speech_level = np.percentile(ctx, 80)
        peak = float(np.percentile(gap, 90))
        if peak < speech_level - below_speech_db:
            out.append([g0, g1, peak])
    return out


def speech_seconds(db):
    """Callable (t0, t1) -> seconds of audio above the silence threshold."""
    def f(t0, t1):
        return float(np.sum(db[int(max(t0, 0) / FRAME): int(max(t1, 0) / FRAME)] > NOISE_DB)) * FRAME
    return f

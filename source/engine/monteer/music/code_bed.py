"""Code-generated dark/tense documentary bed of any length: numpy/scipy synthesis, no AI, no samples, no licence.
The music step's fallback (engine/music.py); also usable alone:

    engine/.venv/bin/python engine/music_tools/code_bed.py --seconds 70 --seed 7 --out bed.wav

D minor, 80 bpm. The layout scales with the length (shares of the piece, not fixed seconds):
  drone   detuned saws on D1/D2 through a slowly breathing low-pass, from the start
  pulse   soft "heartbeat" sub (lub-dub) on every beat, from 20 %, grows over two bars
  pad     D-F-A-C triangle chord from 27 %; the top voice leans on Eb from 70 % for tension
  plucks  sparse low piano-like notes from 30 %, every 2 bars (notes picked by the seed)
  air     band-passed noise swell from 60 % and a faint high tone with tremolo from 67 %
  reverb  synthetic decaying-noise impulse; 2 s fade-out
"""
import argparse
import json
import time

import numpy as np
from scipy.io import wavfile
from scipy.signal import butter, fftconvolve, sosfilt

SR = 48000
BEAT = 60 / 80


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def make(seconds, seed):
    N = int(round(SR * seconds))
    t = np.arange(N) / SR
    rng = np.random.default_rng(seed)

    def saw(f, ph=0.0):
        return 2 * ((f * t + ph) % 1.0) - 1

    def tri_ph(ph):
        return 2 * np.abs(2 * (ph % 1.0) - 1) - 1

    def ramp(start, length):
        return np.clip((t - start) / length, 0, 1)

    def fade(x, fin, fout):
        g = np.ones(N)
        g[: int(fin * SR)] = np.linspace(0, 1, int(fin * SR))
        g[N - int(fout * SR):] = np.linspace(1, 0, int(fout * SR))
        return x * g

    def lowpass_sweep(x, lo_hz, hi_hz, rate):
        y = np.zeros_like(x)
        blocks = max(50, int(seconds * 10))
        edges = np.linspace(0, len(x), blocks + 1).astype(int)
        for a, b in zip(edges[:-1], edges[1:]):
            c = lo_hz + (hi_hz - lo_hz) * (0.5 - 0.5 * np.cos(2 * np.pi * rate * (a + b) / 2 / SR))
            lo, hi = max(0, a - 2048), min(len(x), b + 2048)
            y[a:b] = sosfilt(butter(2, c, "low", fs=SR, output="sos"), x[lo:hi])[a - lo:a - lo + b - a]
        return y

    S = seconds
    fade_out = min(2.5, S / 8)
    # drone
    drone = (saw(hz(26)) + saw(hz(26) * 1.004, 0.3)) * 0.6 + (saw(hz(38) * 0.997, 0.1) + saw(hz(38) * 1.003, 0.7)) * 0.35
    drone = fade(lowpass_sweep(drone, 90, 420, 1 / 15), min(4.0, S / 6), fade_out)
    # pulse
    pulse = np.zeros(N)
    kt = np.arange(int(0.35 * SR)) / SR
    kick = np.sin(2 * np.pi * np.cumsum(38 + 40 * np.exp(-kt * 30)) / SR) * np.exp(-kt * 9)
    b = 0.20 * S
    while b < S - fade_out:
        for off, g in [(0.0, 1.0), (0.22, 0.55)]:
            i = int((b + off) * SR)
            n = min(len(kick), N - i)
            if n > 0:
                pulse[i:i + n] += kick[:n] * g
        b += BEAT
    pulse *= ramp(0.20 * S, 8 * BEAT)
    # pad
    pad = sum(tri_ph(hz(m) * t) + 0.5 * tri_ph(hz(m) * 1.003 * t) for m in (50, 53, 57))
    top = np.where(t < 0.70 * S, hz(60), hz(63))
    pad = pad + tri_ph(np.cumsum(top) / SR)
    pad = sosfilt(butter(2, 900, "low", fs=SR, output="sos"), pad) * ramp(0.27 * S, 6) * (0.8 + 0.2 * np.sin(2 * np.pi * t / 7.5))
    # plucks: every 2 bars from 30 %, notes from a dark set, chosen by the seed
    pl = np.zeros(N)
    notes = [38, 41, 38, 39, 38, 37, 36, 38]
    k = int(rng.integers(len(notes)))
    st = 0.30 * S
    while st < S - fade_out - 1:
        i0 = int(st * SR)
        L = min(N - i0, int(3.5 * SR))
        tt = np.arange(L) / SR
        f = hz(notes[k % len(notes)] + 12)
        note = sum(np.sin(2 * np.pi * f * h * tt * (1 + 0.0004 * h * h)) * np.exp(-tt * (1.2 + 0.9 * h)) / h for h in range(1, 9))
        pl[i0:i0 + L] += note * (1 - np.exp(-tt * 400))
        k += int(rng.integers(1, 3))
        st += 8 * BEAT
    # air
    air = sosfilt(butter(2, [1800, 5200], "band", fs=SR, output="sos"), rng.standard_normal(N)) * ramp(0.60 * S, 0.30 * S) ** 2 * 0.5
    air += np.sin(2 * np.pi * hz(86) * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 5.3 * t)) * ramp(0.67 * S, 0.2 * S) * 0.08
    # mix, width, reverb
    layers = [(drone, 0.55, 0), (pulse, 0.9, 0), (pad, 0.16, 331), (pl, 0.45, 557), (air, 0.10, 911)]
    L = sum(x * g for x, g, _ in layers)
    R = sum(np.roll(x, d) * g for x, g, d in layers)
    ir_len = int(2.8 * SR)
    it = np.arange(ir_len) / SR
    out = []
    for ch in (L, R):
        ir = sosfilt(butter(1, 4000, "low", fs=SR, output="sos"), rng.standard_normal(ir_len)) * np.exp(-it * 2.4)
        wet = fftconvolve(ch, ir)[:N]
        out.append(ch + 0.35 * wet / np.abs(wet).max() * np.abs(ch).max())
    st = np.stack(out, 1) * fade(np.ones(N), 0.05, fade_out)[:, None]
    return st / np.abs(st).max() * 10 ** (-1.0 / 20)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, required=True)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    t0 = time.time()
    st = make(a.seconds, a.seed)
    wavfile.write(a.out, SR, (st * 32767).astype(np.int16))
    print(json.dumps({"generate_s": round(time.time() - t0, 2), "file": a.out}))


if __name__ == "__main__":
    main()

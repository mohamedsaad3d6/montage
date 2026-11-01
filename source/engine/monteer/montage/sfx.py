"""Sound effects, all made in code (rule 18): no download, no licence needed, usable on a monetised channel.
Filtered-noise whooshes, low hits, a pop and an old-camera sound for photo entries (rule 19).

    sfx.main(out_dir)   -> out_dir/<name>.wav (48 kHz, stereo, float) + sfx.json (length and what each is for)
Runs in the ml environment (the scipy version that made the earlier effects).
Whooshes are short (0.3-0.5 s) so they fit the narration's pauses (rule 18 as approved).
"""
import json
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import istft, stft, butter, sosfilt

SR = 48000


def swept_noise(dur, f0, f1, width, peak_at, attack, release, seed):
    r = np.random.default_rng(seed)
    n = int(dur * SR)
    x = r.standard_normal(n + 4096)
    f, t, Z = stft(x, SR, nperseg=1024, noverlap=768)
    fc = f0 * (f1 / f0) ** np.clip(t / dur, 0, 1)
    mask = np.exp(-0.5 * (np.log(f[:, None] + 1) - np.log(fc[None, :])) ** 2 / width ** 2)
    _, y = istft(Z * mask, SR, nperseg=1024, noverlap=768)
    y = y[:n]
    tt = np.arange(n) / SR
    env = np.where(tt < peak_at, (tt / peak_at) ** attack, np.exp(-(tt - peak_at) / release))
    return y * env


def stereo(y, pan_sweep=0.0):
    p = 0.5 + pan_sweep * (np.linspace(0, 1, len(y)) - 0.5)
    return np.stack([y * np.sqrt(1 - p), y * np.sqrt(p)], 1)


def norm(y, peak_db=-3):
    return y / (np.abs(y).max() + 1e-9) * 10 ** (peak_db / 20)


def fade_out(y, d=0.01):
    n = int(d * SR)
    y = y.copy()
    y[-n:] *= np.linspace(1, 0, n)[:, None] if y.ndim == 2 else np.linspace(1, 0, n)
    return y


def pop(seed=1):
    """60 ms: a sine blip falling 900 -> 500 Hz with a tiny click on top (label appears)"""
    n = int(0.06 * SR)
    tt = np.arange(n) / SR
    f = 900 * (500 / 900) ** (tt / 0.06)
    y = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.018)
    click = np.random.default_rng(seed).standard_normal(n) * np.exp(-tt / 0.0015) * 0.35
    return stereo(fade_out(norm(y + click, -3), 0.005))


def hit(seed=5, dur=1.4):
    """heavy hit: 48 Hz sine thump with a pitch drop, a short noise burst and a dark tail (big number / reveal)"""
    n = int(dur * SR)
    tt = np.arange(n) / SR
    f = 48 + 40 * np.exp(-tt / 0.04)
    thump = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.42)
    burst = sosfilt(butter(2, 2500, "low", fs=SR, output="sos"), np.random.default_rng(seed).standard_normal(n)) * np.exp(-tt / 0.05)
    tail = swept_noise(dur, 600, 120, 0.6, 0.01, 1, 0.35, seed + 1)
    return stereo(fade_out(norm(norm(thump, -2) + norm(burst, -9) + norm(tail, -14), -2), 0.05))


def camera(seed=9):
    """old camera: two-part shutter click, then a short film-advance ratchet (photo entry, rule 19)"""
    r = np.random.default_rng(seed)
    n = int(0.55 * SR)
    y = np.zeros(n)
    hp = butter(2, 1200, "high", fs=SR, output="sos")

    def click(at, dur, level, tone):
        k = int(dur * SR)
        tt = np.arange(k) / SR
        c = sosfilt(hp, r.standard_normal(k)) * np.exp(-tt / (dur / 4)) + 0.5 * np.sin(2 * np.pi * tone * tt) * np.exp(-tt / (dur / 5))
        i = int(at * SR)
        y[i:i + k] += level * c / (np.abs(c).max() + 1e-9)
    click(0.000, 0.012, 1.0, 2400)        # shutter opens
    click(0.045, 0.016, 0.8, 1800)        # shutter closes
    for j in range(7):                    # film advance: a quick ratchet of small ticks
        click(0.20 + j * 0.032 + r.uniform(-0.003, 0.003), 0.008, 0.35 + 0.05 * (j % 2), 3200)
    return stereo(fade_out(norm(y, -4), 0.02))


def paper(seed=21, dur=0.30):
    """a sheet of paper flicked or slid into place (Ramadan's guide: a paper sound when on-screen text appears): a short
    papery swish (band-passed noise) with the dry crackle of the sheet on top, 0.3 s"""
    r = np.random.default_rng(seed)
    n = int(dur * SR)
    tt = np.arange(n) / SR
    swish = sosfilt(butter(2, [700, 5200], "band", fs=SR, output="sos"), r.standard_normal(n))
    swish *= np.where(tt < 0.035, tt / 0.035, np.exp(-(tt - 0.035) / 0.07))
    crackle = np.zeros(n)
    for at in np.sort(r.uniform(0.0, 0.16, 26)):         # the sheet's small dry crackles
        k = int(0.004 * SR)
        i = int(at * SR)
        burst = r.standard_normal(k) * np.exp(-np.arange(k) / (0.0008 * SR)) * r.uniform(0.3, 1.0)
        crackle[i:i + k] += burst[:max(0, n - i)]
    crackle = sosfilt(butter(2, 2500, "high", fs=SR, output="sos"), crackle)
    y = norm(swish, -6) + norm(crackle, -9)
    return stereo(fade_out(norm(y, -3), 0.03), 0.3)


def tick(seed=31, dur=1.2):
    """a digital counter running: short bright ticks, 16 a second, fading out (a number counting up)"""
    r = np.random.default_rng(seed)
    n = int(dur * SR)
    y = np.zeros(n)
    for j in range(int(dur * 16)):
        k = int(0.006 * SR)
        i = int(j / 16 * SR)
        tt = np.arange(k) / SR
        c = np.sin(2 * np.pi * (3200 + 300 * (j % 3)) * tt) * np.exp(-tt / 0.0015) + 0.2 * r.standard_normal(k) * np.exp(-tt / 0.0008)
        y[i:i + k] += c[:max(0, n - i)] * (1 - 0.5 * j / (dur * 16))
    return stereo(fade_out(norm(y, -4), 0.05))


def projector(seed=41, dur=1.4):
    """an old film projector: the shutter's flutter (24 a second) over a soft motor hum, coming in and out (archive film)"""
    r = np.random.default_rng(seed)
    n = int(dur * SR)
    tt = np.arange(n) / SR
    hum = np.sin(2 * np.pi * 110 * tt) * 0.25 + np.sin(2 * np.pi * 220 * tt) * 0.12
    flutter = sosfilt(butter(2, [800, 4000], "band", fs=SR, output="sos"), r.standard_normal(n)) * (0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 24 * tt)))
    env = np.minimum(1, tt / 0.15) * np.minimum(1, (dur - tt) / 0.35)
    return stereo(fade_out(norm((hum + 0.6 * flutter) * env, -4), 0.05))


BEAT = {   # the on-beat sounds (owner's fix 8 of 21 Oct 2026), made only for the channels that place effects on their moment
    "whoosh_d": (lambda: stereo(swept_noise(0.55, 180, 2600, 0.50, 0.30, 2.2, 0.08, 11), -0.6), "whoosh, low and wide (transitions, in turn)"),
    "whoosh_e": (lambda: stereo(swept_noise(0.35, 500, 4500, 0.45, 0.17, 1.8, 0.06, 12), 0.7), "short bright whoosh (transitions, in turn)"),
    "riser_short": (lambda: stereo(swept_noise(0.70, 200, 3200, 0.45, 0.68, 3.0, 0.03, 7), 0.4), "0.7 s riser that ends on a hit (a beat)"),
    "tick": (lambda: tick(), "a digital counter running (a number counting up)"),
    "projector": (lambda: projector(), "an old film projector (archive film comes in)"),
}


def main(OUT, only=None):
    """all the effects -> OUT/<name>.wav + sfx.json; only = [names]: just those, added to an existing sfx.json"""
    OUT = Path(OUT)
    OUT.mkdir(parents=True, exist_ok=True)
    if only:
        made = {"paper": (paper(), "paper: on-screen text appears (Ramadan's guide; profiles with sound.text_sfx paper)"),
                "paper_b": (paper(22, 0.28), "second paper sound (alternated)")}
        made.update({k: (f(), what) for k, (f, what) in BEAT.items() if k in only})
        info = json.load(open(OUT / "sfx.json")) if (OUT / "sfx.json").exists() else {}
        for k in only:
            y, what = made[k]
            tmp = OUT / f".{k}.part.wav"
            wavfile.write(tmp, SR, fade_out(norm(y, -3), 0.005).astype(np.float32))
            tmp.replace(OUT / f"{k}.wav")
            info[k] = {"seconds": round(len(y) / SR, 3), "use": what, "source": "made in code by monteer/montage/sfx.py (our own work, no licence needed)"}
            print(k, info[k]["seconds"], "s")
        json.dump(info, open(OUT / "sfx.json", "w"), indent=1)
        return
    s = {
        "whoosh_a": (stereo(swept_noise(0.45, 350, 3000, 0.55, 0.22, 2.0, 0.07, 1), 0.8), "short whoosh, rising: section change / folder opening"),
        "whoosh_b": (stereo(swept_noise(0.50, 250, 2200, 0.60, 0.26, 2.5, 0.08, 2), -0.8), "airy whoosh: into a title card"),
        "whoosh_c": (stereo(swept_noise(0.40, 2800, 300, 0.50, 0.15, 1.5, 0.09, 3), 0.6), "short falling whoosh: out of a section"),
        "pop": (pop(), "60 ms pop: a label or card appears"),
        "pop_low": (pop(2) * 0.9, "second pop (alternated so repeats don't sound identical)"),
        "hit": (hit(), "heavy hit: big number or reveal"),
        "camera": (camera(), "old camera: shutter + film advance, for a photo entry where the source has no click"),
        "riser": (stereo(swept_noise(1.6, 150, 3500, 0.45, 1.55, 3.0, 0.05, 6), 0.4), "riser into a reveal (optional, 2 uses)"),
    }
    s["pop_low"] = (stereo(fade_out(norm(np.interp(np.arange(int(0.07 * SR)), np.arange(int(0.06 * SR)) * 0.07 / 0.06 * 1.0,
                                                    pop(2)[:, 0]), -3), 0.005)), "second pop, a little lower")
    info = {}
    for k, (y, what) in s.items():
        tmp = OUT / f".{k}.part.wav"
        wavfile.write(tmp, SR, fade_out(norm(y, -3), 0.005).astype(np.float32))
        tmp.replace(OUT / f"{k}.wav")
        info[k] = {"seconds": round(len(y) / SR, 3), "use": what, "source": "made in code by monteer/montage/sfx.py (our own work, no licence needed)"}
        print(k, info[k]["seconds"], "s")
    json.dump(info, open(OUT / "sfx.json", "w"), indent=1)


if __name__ == "__main__":
    import sys
    main(sys.argv[1], sys.argv[3:] if len(sys.argv) > 2 and sys.argv[2] == "--only" else None)

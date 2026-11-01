"""What a voice sounds like, in numbers (owner's decision of 21 Oct 2026: voice processing automatic for every channel
episode, from measurements). Three 60 s stretches of the file (at 30, 50 and 70 % of it), the voiced channel only:

  loudness   integrated LUFS and true peak (EBU R128)
  dynamics   loudness range (LRA, LU) and the spread of 400 ms speech levels (p95 - p10, dB)
  noise      the speech level (p90 of 50 ms frames) against the floor in the pauses (p5): snr_dB
  echo       how fast the sound dies when a word stops: the drop 40 ms after (decay40_dB; a dry voice falls further). The
             level 100-200 ms later (tail_dB) is kept for the record only: a music bed or room noise fills it, so it does
             not tell a room's echo (the echoey camera measured -8.8 dB, the published episodes -2 to -5 dB)
  tone       the spectrum's centre (Hz) and the 1-3, 3-6 and 6-10 kHz bands against 300-3000 Hz (dB)

  measure(path) -> {...};  python -m monteer.montage.voice_measure <file> [...]
"""
import json
import re
import subprocess
import sys

import numpy as np

from ..core.paths import FFMPEG, FFPROBE

FF, FP = str(FFMPEG), str(FFPROBE)
SR = 48000
WINDOWS = (0.3, 0.5, 0.7)


def duration(path):
    return float(subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                                capture_output=True, text=True).stdout or 0)


def voiced(path):
    """the louder channel's index (a camera mic often records one side only), and the two levels"""
    lv = []
    for ch in (0, 1):
        e = subprocess.run([FF, "-hide_banner", "-nostats", "-t", "600", "-i", str(path), "-vn", "-af", f"pan=mono|c0=c{ch},volumedetect",
                            "-f", "null", "-"], capture_output=True, text=True).stderr
        m = re.search(r"mean_volume:\s*(-?[\d.]+)", e)
        lv.append(float(m.group(1)) if m else -200.0)
    return (0 if lv[0] >= lv[1] else 1), lv


def _pcm(path, ch, at, seconds):
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{at:.3f}", "-t", str(seconds), "-i", str(path), "-vn", "-af", f"pan=mono|c0=c{ch}",
                          "-ar", str(SR), "-f", "f32le", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.float32).astype(np.float64)


def _loudness(path, ch, starts, seconds):
    """EBU R128 over the stretches joined (stereo of the voiced channel, as the episode will have it)"""
    parts = "".join(f"[0:a]atrim={s:.3f}:{s + seconds:.3f},asetpts=PTS-STARTPTS,pan=stereo|c0=c{ch}|c1=c{ch}[a{k}];" for k, s in enumerate(starts))
    fc = parts + "".join(f"[a{k}]" for k in range(len(starts))) + f"concat=n={len(starts)}:v=0:a=1,ebur128=peak=true[o]"
    e = subprocess.run([FF, "-hide_banner", "-nostats", "-i", str(path), "-filter_complex", fc, "-map", "[o]", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    s = e[e.rfind("Summary:"):]
    g = lambda k: float(re.search(k + r":\s+(-?[\d.]+)", s).group(1))      # noqa: E731
    return {"I_LUFS": g("I"), "LRA_LU": g("LRA"), "truepeak_dBTP": g("Peak")}


def _tail(m):
    """the level 100-200 ms after a word stops, against the word (dB, median over the word ends found)"""
    fr = 480                                    # 10 ms
    n = len(m) // fr
    db = 20 * np.log10(np.sqrt(np.mean(m[:n * fr].reshape(n, fr) ** 2, axis=1)) + 1e-9)
    sp = np.percentile(db, 90)
    out = []
    for i in range(10, n - 25):
        pre = db[i - 10:i].mean()
        if pre > sp - 10 and db[i + 2] < db[i - 1] - 6 and db[i:i + 3].mean() < pre - 6:
            out.append(db[i + 10:i + 20].mean() - pre)
    return (round(float(np.median(out)), 1), len(out)) if out else (None, 0)


def _decay(m, ms=40):
    """the drop (dB) ms milliseconds after a word stops, against the word (median over the word ends found)"""
    fr = 240                                    # 5 ms
    n = len(m) // fr
    db = 20 * np.log10(np.sqrt(np.mean(m[:n * fr].reshape(n, fr) ** 2, axis=1)) + 1e-9)
    sp = np.percentile(db, 90)
    out = []
    for i in range(20, n - 20):
        pre = db[i - 20:i - 2].mean()
        if pre > sp - 8 and db[i - 1] > pre - 4 and db[i + 4] < pre - 6:
            out.append(pre - db[i + ms // 5])
    return (round(float(np.median(out)), 1), len(out)) if out else (None, 0)


def measure(path, seconds=60.0):
    from scipy import signal
    L = duration(path)
    seconds = min(seconds, L / len(WINDOWS))
    starts = [max(0.0, min(L - seconds, L * q - seconds / 2)) for q in WINDOWS]
    ch, lv = voiced(path)
    m = np.concatenate([_pcm(path, ch, s, seconds) for s in starts])
    fr = int(0.05 * SR)
    n = len(m) // fr
    db = 20 * np.log10(np.sqrt(np.mean(m[:n * fr].reshape(n, fr) ** 2, axis=1)) + 1e-9)
    live = db[db > -90]                         # digital silence (a mic laid on the camera's timeline is padded with it) is no room
    speech, noise = float(np.percentile(live, 90)), float(np.percentile(live, 5))
    w = int(0.4 * SR)
    k = len(m) // w
    st = 20 * np.log10(np.sqrt(np.mean(m[:k * w].reshape(k, w) ** 2, axis=1)) + 1e-9)
    st = st[st > speech - 25]
    f, P = signal.welch(m, SR, nperseg=8192)
    tail, ends = _tail(m)
    decay, n_dec = _decay(m)
    return {"file": str(path), "voiced_channel": ch, "channel_levels_db": [round(x, 1) for x in lv],
            "measured_s": round(seconds * len(starts), 1), "loudness": _loudness(path, ch, starts, seconds),
            "speech_dBFS": round(speech, 1), "noise_floor_dBFS": round(noise, 1), "snr_dB": round(speech - noise, 1),
            "decay40_dB": decay, "word_ends": n_dec, "tail_dB": tail,
            "spread_dB": round(float(np.percentile(st, 95) - np.percentile(st, 10)), 1) if len(st) > 10 else None,
            "centre_Hz": int(np.sum(f * P) / np.sum(P)), "bands_dB": bands(m)}


def bands(m):
    """the tone: the 1-3, 3-6 and 6-10 kHz bands against 300-3000 Hz (dB) of a mono 48 kHz signal"""
    from scipy import signal
    f, P = signal.welch(m, SR, nperseg=8192)

    def band(a, b):
        return 10 * np.log10(np.sum(P[(f >= a) & (f < b)]) + 1e-20)
    ref = band(300, 3000)
    return {"1-3k": round(float(band(1000, 3000) - ref), 1), "3-6k": round(float(band(3000, 6000) - ref), 1),
            "6-10k": round(float(band(6000, 10000) - ref), 1)}


def excerpt(path, ch, out, seconds=20.0):
    """the measured stretches (30, 50, 70 %), seconds each, of the voiced channel joined -> out (mono 48 kHz): the chain's tone
    is fitted on it"""
    L = duration(path)
    seconds = min(seconds, L / len(WINDOWS))
    m = np.concatenate([_pcm(path, ch, max(0.0, min(L - seconds, L * q - seconds / 2)), seconds) for q in WINDOWS])
    subprocess.run([FF, "-v", "error", "-y", "-f", "f64le", "-ar", str(SR), "-ac", "1", "-i", "-", "-c:a", "pcm_s24le", str(out)],
                   input=m.tobytes(), check=True)
    return out


# ---------------------------------------------------------------------------------------------------- what is needed
# a professional voice when a channel has no published episodes to measure (its profile's sound.voice_reference)
DEFAULT_REFERENCE = {"name": "professional default", "snr_dB": 45.0, "decay40_dB": 11.0, "spread_dB": 7.0, "LRA_LU": 4.0,
                     "bands_dB": {"1-3k": -8.0, "3-6k": -15.0, "6-10k": -21.0}, "centre_Hz": 650}
# how far from the reference before something is done (set 21 Oct 2026 on: Ramadan's 3 published episodes, his new mic
# file, the camera recordings of «المملكة المتحدة تنهار»)
NOISE_LIGHT, NOISE_STRONG = 3.0, 10.0      # dB of signal-to-noise below the reference
ECHO_LIGHT, ECHO_STRONG = 2.0, 4.0         # dB less decay 40 ms after a word than the reference
TONE_DB = 2.5                              # dB any tone band may differ before an EQ toward the reference
EQ_MAX = 6.0                               # dB at most per band
SPREAD_DB, LRA_LU = 3.0, 3.0               # more spread (or loudness range) than the reference before levelling


def plan(m, ref):
    """the measured voice against the reference -> {"clean": none|light|denoise|restore, "eq": {band: dB} or None,
    "level": bool, "why": [...]}: only what is needed (a clean voice gets the loudness only)"""
    why = []
    d_noise = ref["snr_dB"] - m["snr_dB"]
    d_echo = ref["decay40_dB"] - (m["decay40_dB"] if m["decay40_dB"] is not None else 0.0)
    if d_echo > ECHO_STRONG:
        clean = "restore"
        why.append(f"echo: the sound falls {m['decay40_dB']} dB 40 ms after a word, {d_echo:.1f} dB less than the reference "
                   f"(more than {ECHO_STRONG:g}): restored (VoiceFixer)")
    elif d_noise > NOISE_STRONG or d_echo > ECHO_LIGHT:
        clean = "denoise"
        why.append(f"noise {d_noise:+.1f} dB / echo {d_echo:+.1f} dB against the reference: DeepFilterNet")
    elif d_noise > NOISE_LIGHT:
        clean = "light"
        why.append(f"noise: signal-to-noise {m['snr_dB']} dB, {d_noise:.1f} dB under the reference: a light noise reduction")
    else:
        clean = "none"
        why.append(f"clean enough: signal-to-noise {m['snr_dB']} dB (reference {ref['snr_dB']}), decay {m['decay40_dB']} dB "
                   f"(reference {ref['decay40_dB']}): no cleaning")
    eq = None
    diff = {b: round(ref["bands_dB"][b] - m["bands_dB"][b], 1) for b in ref["bands_dB"]}
    if clean != "restore" and any(abs(v) > TONE_DB for v in diff.values()):
        eq = {b: max(-EQ_MAX, min(EQ_MAX, v)) for b, v in diff.items()}
        why.append(f"tone: {', '.join(f'{b} {v:+.1f} dB' for b, v in diff.items())} from the reference: an EQ toward it")
    elif clean == "restore":
        why.append("tone: VoiceFixer's own EQ toward the channel's tone (tuned on Ramadan's episodes)")
    level = (m.get("spread_dB") or 0) > ref["spread_dB"] + SPREAD_DB or m["loudness"]["LRA_LU"] > ref["LRA_LU"] + LRA_LU or clean == "restore"
    why.append(f"dynamics: spread {m.get('spread_dB')} dB, range {m['loudness']['LRA_LU']} LU (reference {ref['spread_dB']} / "
               f"{ref['LRA_LU']}): " + ("levelling and compression" if level else "left as it is"))
    why.append("loudness: to -15 LUFS, true peak -1 dBTP (always)")
    return {"clean": clean, "eq": eq, "level": level, "why": why}


def reference_from(files):
    """a channel's reference sound from its published episodes: the median of each measure"""
    ms = [measure(f) for f in files]
    med = lambda k: round(float(np.median([x[k] for x in ms if x.get(k) is not None])), 1)      # noqa: E731
    return {"name": "the channel's published episodes", "from": [str(f) for f in files], "snr_dB": med("snr_dB"),
            "decay40_dB": med("decay40_dB"), "spread_dB": med("spread_dB"),
            "LRA_LU": round(float(np.median([x["loudness"]["LRA_LU"] for x in ms])), 1),
            "I_LUFS": round(float(np.median([x["loudness"]["I_LUFS"] for x in ms])), 1),
            "centre_Hz": int(np.median([x["centre_Hz"] for x in ms])),
            "bands_dB": {b: round(float(np.median([x["bands_dB"][b] for x in ms])), 1) for b in ("1-3k", "3-6k", "6-10k")}}


if __name__ == "__main__":
    for x in sys.argv[1:]:
        print(json.dumps(measure(x), ensure_ascii=False))

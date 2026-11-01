"""Stage 1+2: extract analysis audio and sync the external mic to the camera timeline.

Result (work/sync.json): a list of segments, each mapping external-audio time t to
camera time  cam = t + a + b*t  for t in [ext_start, ext_end].
Also writes the external audio laid onto the camera timeline:
  work/sync_ext16.wav (mono 16 kHz, analysis) and work/sync_ext48.wav (stereo 48 kHz, final mix).
"""
import numpy as np
from scipy.io import wavfile
from scipy.signal import fftconvolve

from .common import (EXT_AUDIO, RAW_VIDEO, REF_VIDEO, SR, WORK, cached, load_json, run,
                    save_json)

HOP = 160  # 10 ms envelope frames at 16 kHz
ENV_RATE = SR // HOP

CAM16, EXT16, REF16 = WORK / "cam16.wav", WORK / "ext16.wav", WORK / "ref16.wav"
EXT48 = WORK / "ext48.wav"
SYNC_JSON = WORK / "sync.json"
SYNC16, SYNC48 = WORK / "sync_ext16.wav", WORK / "sync_ext48.wav"


def extract():
    jobs = [(RAW_VIDEO, CAM16, ["-ac", "1", "-ar", str(SR)]),
            (EXT_AUDIO, EXT16, ["-ac", "1", "-ar", str(SR)]),
            (REF_VIDEO, REF16, ["-ac", "1", "-ar", str(SR)]),
            (EXT_AUDIO, EXT48, ["-ac", "2", "-ar", "48000"])]
    for src, dst, opts in jobs:
        if src is None:                # no reference edit (or no file of that kind): nothing to extract (owner's OK of 21 Oct 2026:
            continue                   # an episode with a separate mic file stopped here on «ffmpeg -i None»)
        if not cached(dst):
            run(["ffmpeg", "-y", "-v", "error", "-i", src, "-vn", *opts, "-c:a", "pcm_s16le", dst])


def read16(path):
    sr, x = wavfile.read(path)
    assert sr == SR, path
    return x.astype(np.float32) / 32768.0


def envelope(x):
    """High-passed log energy per 10 ms frame, z-normalized. Robust to gain/EQ differences."""
    n = len(x) // HOP
    e = np.log10(np.mean(x[: n * HOP].reshape(n, HOP) ** 2, axis=1) + 1e-9)
    k = 100  # 1 s moving average removed
    e = e - np.convolve(e, np.ones(k) / k, mode="same")
    return (e - e.mean()) / (e.std() + 1e-9)


def best_lag(ref_env, probe_env):
    """Lag (in frames) where probe best matches inside ref, plus peak prominence."""
    c = fftconvolve(ref_env, probe_env[::-1], mode="valid")
    i = int(np.argmax(c))
    prom = (c[i] - np.median(c)) / (np.std(c) + 1e-9)
    return i, float(prom)


def fine_lag(cam, ext, t_ext, coarse_off, win=8.0, search=0.03):
    """Sub-frame refinement on raw 16 kHz samples around one point; returns offset seconds."""
    s = int(t_ext * SR)
    seg = ext[s: s + int(win * SR)]
    c0 = int((t_ext + coarse_off - search) * SR)
    ref = cam[max(c0, 0): c0 + len(seg) + int(2 * search * SR)]
    if len(seg) < SR or len(ref) < len(seg) or np.std(seg) < 1e-4:
        return None
    c = fftconvolve(ref, seg[::-1], mode="valid")
    i = int(np.argmax(np.abs(c)))
    return (max(c0, 0) + i) / SR - t_ext


def analyse():
    cam, ext = read16(CAM16), read16(EXT16)
    ecam, eext = envelope(cam), envelope(ext)
    lag, prom = best_lag(ecam, eext[: min(len(eext), ENV_RATE * 600)])
    print(f"global offset ~ {lag / ENV_RATE:.2f}s (prominence {prom:.1f})")

    # windowed search over the whole camera track: detects drift and gaps in the external file
    W, H = 30 * ENV_RATE, 15 * ENV_RATE
    wins = []
    for st in range(0, len(eext) - W // 2, H):
        probe = eext[st: st + W]
        if len(probe) < W // 2:
            break
        l, p = best_lag(ecam, probe)
        wins.append({"ext_t": st / ENV_RATE, "off": (l - st) / ENV_RATE, "prom": p})

    good = [w for w in wins if w["prom"] > 8]
    # cluster consecutive windows sharing an offset (a jump means the ext file has a gap/edit)
    clusters = []
    for w in good:
        if clusters and abs(w["off"] - clusters[-1][-1]["off"]) < 0.08:
            clusters[-1].append(w)
        else:
            clusters.append([w])
    clusters = [c for c in clusters if len(c) >= 2 or c[0]["prom"] > 15]

    segments = []
    ext_dur = len(ext) / SR
    for ci, c in enumerate(clusters):
        start = 0.0 if ci == 0 else c[0]["ext_t"]
        end = ext_dur if ci == len(clusters) - 1 else clusters[ci + 1][0]["ext_t"]
        coarse = float(np.median([w["off"] for w in c]))
        pts = np.linspace(start + 2, max(start + 2, end - 10), num=min(12, max(2, int((end - start) // 60))))
        fine = [(t, fine_lag(cam, ext, t, coarse)) for t in pts]
        fine = [(t, o) for t, o in fine if o is not None and abs(o - coarse) < 0.05]
        if len(fine) >= 2:
            ts, os_ = np.array(fine).T
            b, a = np.polyfit(ts, os_, 1)
            resid = float(np.max(np.abs(os_ - (a + b * ts))) * 1000)
        else:
            a, b, resid = coarse, 0.0, float("nan")
        segments.append({"ext_start": start, "ext_end": end, "a": float(a), "b": float(b),
                         "drift_ms_total": float(b * (end - start) * 1000),
                         "fit_resid_ms": resid, "n_windows": len(c)})
    # refine segment boundaries where the ext file jumps: split at the midpoint of the transition
    for s0, s1 in zip(segments, segments[1:]):
        mid = (s0["ext_end"] + s1["ext_start"]) / 2
        s0["ext_end"] = s1["ext_start"] = mid
    info = {"segments": segments, "windows": wins, "global_prominence": prom,
            "cam_dur": len(cam) / SR, "ext_dur": ext_dur}
    save_json(SYNC_JSON, info)
    for s in segments:
        print(f"  ext {s['ext_start']:.1f}-{s['ext_end']:.1f}s  -> cam offset {s['a']:+.4f}s "
              f"drift {s['drift_ms_total']:+.1f}ms  resid {s['fit_resid_ms']:.2f}ms")
    return info


def ext_to_cam(t, segments):
    for s in segments:
        if s["ext_start"] <= t <= s["ext_end"]:
            return t + s["a"] + s["b"] * t
    return None


def lay_onto_camera(info, src, dst, sr):
    """Place ext audio on the camera timeline (silence where the ext file has no audio)."""
    rate, x = wavfile.read(src)
    assert rate == sr
    n_cam = int(info["cam_dur"] * sr)
    out = np.zeros((n_cam,) + x.shape[1:], dtype=x.dtype)
    covered = []
    for s in info["segments"]:
        cam0 = s["ext_start"] + s["a"] + s["b"] * s["ext_start"]
        cam1 = s["ext_end"] + s["a"] + s["b"] * s["ext_end"]
        i0, i1 = max(0, int(round(cam0 * sr))), min(n_cam, int(round(cam1 * sr)))
        if i1 <= i0:
            continue
        tau = np.arange(i0, i1) / sr
        # invert cam = t(1+b) + a
        t = (tau - s["a"]) / (1 + s["b"])
        idx = t * sr
        if abs(s["drift_ms_total"]) < 2:  # pure shift, no resampling
            j = np.clip(np.round(idx).astype(np.int64), 0, len(x) - 1)
            out[i0:i1] = x[j]
        else:
            lo = np.clip(np.floor(idx).astype(np.int64), 0, len(x) - 2)
            fr = (idx - lo).astype(np.float32)
            xf = x.astype(np.float32)
            if xf.ndim == 2:
                fr = fr[:, None]
            out[i0:i1] = (xf[lo] * (1 - fr) + xf[lo + 1] * fr).astype(x.dtype)
        covered.append([i0 / sr, i1 / sr])
    wavfile.write(dst, sr, out)
    return covered


def build_embedded(force=False):
    """Audio already synced onto the video (EXT_AUDIO is None): the video's own track is the mic.
    Identity mapping; the same wavs serve as 'external' and 'synced' audio."""
    if not force and cached(SYNC_JSON) and cached(SYNC16) and cached(SYNC48):
        return load_json(SYNC_JSON)
    for dst, opts in ((SYNC16, ["-ac", "1", "-ar", str(SR)]), (SYNC48, ["-ac", "2", "-ar", "48000"])):
        run(["ffmpeg", "-y", "-v", "error", "-i", RAW_VIDEO, "-map", "0:a:0", "-vn", *opts, "-c:a", "pcm_s16le", dst])
    for link, target in ((EXT16, SYNC16), (EXT48, SYNC48)):
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(target.name)
    dur = len(read16(SYNC16)) / SR
    info = {"segments": [{"ext_start": 0.0, "ext_end": dur, "a": 0.0, "b": 0.0, "drift_ms_total": 0.0,
                          "fit_resid_ms": 0.0, "n_windows": 0}],
            "cam_dur": dur, "ext_dur": dur, "cam_covered": [[0.0, dur]], "embedded": True}
    save_json(SYNC_JSON, info)
    return info


def build(force=False):
    if EXT_AUDIO is None:
        return build_embedded(force)
    extract()
    info = analyse() if force or not cached(SYNC_JSON) else load_json(SYNC_JSON)
    if force or not cached(SYNC16) or not cached(SYNC48):
        cov = lay_onto_camera(info, EXT16, SYNC16, SR)
        lay_onto_camera(info, EXT48, SYNC48, 48000)
        info["cam_covered"] = cov
        save_json(SYNC_JSON, info)
    return info


if __name__ == "__main__":
    build(force=True)

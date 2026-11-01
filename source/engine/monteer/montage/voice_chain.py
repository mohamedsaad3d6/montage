"""The camera-mic voice chain (owner's (b) of 20 Oct 2026): make a presenter's camera-mic voice sound like Ramadan's finished
الحدث الأخير episodes. SAMPLES ONLY for now: nothing here is used by an episode yet (the final mix still takes the voice
as it is); the owner judges the before/after samples first.

Measured (NOTES.md): Ramadan's episodes -14.0 to -15.7 LUFS, true peak -0.9..+0.3 dBTP, loudness range ~2 LU (heavily
compressed), tone centred ~690 Hz, dry (no room tail), pauses cleaned (-84 dBFS). The camera file: the voice on the LEFT
channel only (right silent), -25.9 LUFS, range 9.9 LU, darker (centre 528 Hz; 4-5 dB less at 1-6 kHz), noise -54 dBFS,
a room tail after each word. The chain, at the final mix only (the cut keeps reading the raw sound: its breath and
silence rules are tuned to it):

  1. the voiced channel, mono (the louder one)        4. EQ toward Ramadan's tone (EQ below; one set per cleaner)
  2. high-pass 80 Hz                                   5. phrase levelling + 4:1 compression
  3. noise and room: DeepFilterNet 3 (a free speech    6. loudness -15 LUFS, true peak -1 dBTP (two-pass), limiter
     model on this Mac's CPU) or ffmpeg's afftdn + a
     gentle gate in the pauses

  python -m monteer.montage.voice_chain samples <camera video> <out folder> [--at S] [--seconds 60] [--reference FILE]
  python -m monteer.montage.voice_chain echo <camera video> <out folder> [...]      (light / medium / strong echo removal)
"""
import json
import re
import subprocess
import sys
from pathlib import Path

from ..core.paths import ENVS, FFMPEG

FF = str(FFMPEG)
VOICE_PY = ENVS / "voice" / "bin" / "python"          # DeepFilterNet's own environment (torch 2.2.2, deepfilternet 0.5.6)
TARGET_LUFS, TARGET_TP, TARGET_LRA = -15.0, -1.0, 4.0
HIGHPASS = "highpass=f=80"
# VoiceFixer (owner's choice of 21 Oct 2026, sample 7) brightens the voice a lot (raw: centre 2465 Hz, 6-10 kHz at -5 dB
# vs 300-3000 Hz); this EQ, tuned on the sample against Ramadan's tone, brings it to centre ~810 Hz, 1-6 kHz within 1 dB and
# 6-10 kHz at -17 dB (Ramadan -20): a lift around 750 Hz, a little less at 4 kHz, a steep low-pass from 5.5 kHz
EQ_VOICEFIXER = "equalizer=f=750:t=q:w=1.5:g=5,equalizer=f=4000:t=q:w=1:g=-2,lowpass=f=5500,lowpass=f=5500,lowpass=f=7000"
# tuned once against Ramadan's measured tone (1-3 kHz -7.5, 3-6 kHz -13.6, 6-10 kHz -20.4 dB vs 300-3000 Hz): DeepFilterNet
# already takes the room's low-mid away, so its chain needs much less presence; both need the hiss band lowered
EQ = {"ffmpeg": "equalizer=f=300:t=q:w=1:g=-1.5,equalizer=f=2500:t=q:w=1:g=3.5,equalizer=f=4500:t=q:w=1:g=2,highshelf=f=6500:g=-7",
      "deepfilternet": "equalizer=f=300:t=q:w=1:g=-1,equalizer=f=2500:t=q:w=1:g=1,highshelf=f=6500:g=-8"}
LEVEL = "dynaudnorm=f=250:g=11:p=0.7:m=8,acompressor=threshold=-24dB:ratio=4:attack=5:release=120:makeup=3"
CLEAN_FFMPEG = "afftdn=nr=14:nf=-52:tn=1,agate=threshold=0.015:ratio=3:attack=8:release=160:range=0.15"


def voiced_channel(src, at=None, seconds=120):
    """the index of the louder channel (a camera mic often records on one side only)"""
    levels = []
    for ch in (0, 1):
        cmd = [FF, "-hide_banner", "-nostats"] + (["-ss", str(at)] if at is not None else []) + ["-t", str(seconds), "-i", str(src), "-vn",
                                                                                                  "-af", f"pan=mono|c0=c{ch},volumedetect", "-f", "null", "-"]
        e = subprocess.run(cmd, capture_output=True, text=True).stderr
        m = re.search(r"mean_volume:\s*(-?[\d.]+)", e)
        levels.append(float(m.group(1)) if m else -200.0)
    return 0 if levels[0] >= levels[1] else 1, levels


def chain(clean, ch=None):
    """the ffmpeg filter for steps 1-5 (clean: "ffmpeg" adds afftdn and the gate; "none" when DeepFilterNet already ran)"""
    parts = ([f"pan=mono|c0=c{ch}"] if ch is not None else []) + [HIGHPASS] + ([CLEAN_FFMPEG] if clean == "ffmpeg" else []) + \
        [EQ["ffmpeg" if clean == "ffmpeg" else "deepfilternet"], LEVEL]
    return ",".join(parts)


def loudness(path):
    e = subprocess.run([FF, "-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True).stderr
    s = e[e.rfind("Summary:"):]
    g = lambda k: float(re.search(k + r":\s+(-?[\d.]+)", s).group(1))      # noqa: E731
    return {"I_LUFS": g("I"), "LRA_LU": g("LRA"), "truepeak_dBTP": g("Peak")}


def to_target(src, out):
    """step 6: the voice on both sides (stereo, 48 kHz) first, then two-pass loudnorm to -15 LUFS / -1 dBTP measured on that
    stereo, then a limiter a little under -1 dB"""
    st = Path(src).parent / (Path(out).stem + "_stereo_in.wav")
    subprocess.run([FF, "-v", "error", "-y", "-i", str(src), "-af", "aresample=48000,pan=stereo|c0=c0|c1=c0", "-c:a", "pcm_s24le", str(st)], check=True)
    first = subprocess.run([FF, "-hide_banner", "-nostats", "-i", str(st), "-af",
                            f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA={TARGET_LRA}:print_format=json", "-f", "null", "-"],
                           capture_output=True, text=True).stderr
    j = json.loads(first[first.rfind("{"):first.rfind("}") + 1])
    af = (f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TP}:LRA={TARGET_LRA}:measured_I={j['input_i']}:measured_TP={j['input_tp']}:"
          f"measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}:offset={j['target_offset']}:linear=true,"
          f"aresample=192000,alimiter=limit=0.82:attack=5:release=50:level=false,aresample=48000")
    subprocess.run([FF, "-v", "error", "-y", "-i", str(st), "-af", af, "-c:a", "pcm_s24le", str(out)], check=True)


def deepfilter(src_wav, out_dir):
    """DeepFilterNet 3 on a mono 48 kHz wav -> the cleaned wav (its own environment; the model is downloaded once)"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    code = ("import sys; from df.enhance import enhance, init_df, load_audio, save_audio\n"
            "model, state, _ = init_df()\n"
            "audio, _ = load_audio(sys.argv[1], sr=state.sr())\n"
            "save_audio(sys.argv[2], enhance(model, state, audio), state.sr())\n")
    out = out_dir / (Path(src_wav).stem + "_dfn.wav")
    subprocess.run([str(VOICE_PY), "-c", code, str(src_wav), str(out)], check=True, capture_output=True)
    return out


# stronger echo removal (owner, 20 Oct 2026: DeepFilterNet chosen, but too much room echo left): WPE (weighted prediction
# error, a classic speech de-reverberation that keeps the voice natural) before DeepFilterNet, and from "medium" on a
# gentle downward expander that lowers what is left of the tail between words; "strong" adds DeepFilterNet's post-filter
ECHO = {"light": {"taps": 10, "delay": 3, "iterations": 3, "expander": None, "post_filter": False},
        "medium": {"taps": 24, "delay": 2, "iterations": 8, "expander": None, "post_filter": True},
        "strong": {"taps": 24, "delay": 2, "iterations": 8, "expander": (15, 3.0, 0.2), "post_filter": True}}


def wpe(src_wav, out_wav, taps, delay, iterations):
    """WPE de-reverberation of a mono 48 kHz wav (its own environment: nara_wpe)"""
    code = ("import sys, numpy as np, soundfile as sf\n"
            "from nara_wpe.wpe import wpe\n"
            "from nara_wpe.utils import stft, istft\n"
            "y, sr = sf.read(sys.argv[1]); y = y if y.ndim == 1 else y[:, 0]\n"
            "size, shift = 1536, 384\n"
            "Y = stft(y[None, :], size=size, shift=shift).transpose(2, 0, 1)\n"
            "Z = wpe(Y, taps=int(sys.argv[3]), delay=int(sys.argv[4]), iterations=int(sys.argv[5]), statistics_mode='full').transpose(1, 2, 0)\n"
            "z = istft(Z, size=size, shift=shift)[0][:len(y)]\n"
            "sf.write(sys.argv[2], z.astype(np.float32), sr, subtype='PCM_24')\n")
    subprocess.run([str(VOICE_PY), "-c", code, str(src_wav), str(out_wav), str(taps), str(delay), str(iterations)], check=True,
                   capture_output=True)
    return Path(out_wav)


def deepfilter_pf(src_wav, out_dir, post_filter=False):
    """DeepFilterNet 3, optionally with its post-filter (a little more suppression between and after words)"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    code = ("import sys; from df.enhance import enhance, init_df, load_audio, save_audio\n"
            "model, state, _ = init_df(post_filter=sys.argv[3] == '1')\n"
            "audio, _ = load_audio(sys.argv[1], sr=state.sr())\n"
            "save_audio(sys.argv[2], enhance(model, state, audio), state.sr())\n")
    out = out_dir / (Path(src_wav).stem + ("_dfnpf.wav" if post_filter else "_dfn.wav"))
    subprocess.run([str(VOICE_PY), "-c", code, str(src_wav), str(out), "1" if post_filter else "0"], check=True, capture_output=True)
    return out


def speech_level_db(path):
    """the 90th percentile of 50 ms levels (the voice's own level), dBFS"""
    import numpy as np
    raw = subprocess.run([FF, "-v", "error", "-i", str(path), "-ac", "1", "-ar", "48000", "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    fr = 2400
    n = len(x) // fr
    db = 20 * np.log10(np.sqrt(np.mean(x[:n * fr].reshape(n, fr) ** 2, axis=1)) + 1e-9)
    return float(np.percentile(db, 90))


def expander(path, below_db, ratio, rng):
    """a gentle downward expander: under (the voice's level - below_db) the sound is lowered by up to 1/rng, slowly"""
    thr = 10 ** ((speech_level_db(path) - below_db) / 20)
    return f"agate=threshold={thr:.5f}:ratio={ratio}:attack=10:release=120:range={rng}:knee=4"


def echo_samples(video, out_dir, at=1000.0, seconds=60.0, reference=None, log=print):
    """light / medium / strong echo removal, each WPE -> DeepFilterNet -> (expander) -> the same EQ, levelling and loudness
    as sample 3, plus the reference -> {name: file}, measured"""
    out_dir = Path(out_dir)
    work = out_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    ch, lv = voiced_channel(video, at)
    raw = work / "raw_voiced_mono.wav"
    subprocess.run([FF, "-v", "error", "-y", "-ss", str(at), "-t", str(seconds), "-i", str(video), "-vn", "-af", f"pan=mono|c0=c{ch},{HIGHPASS}",
                    "-ar", "48000", "-c:a", "pcm_s24le", str(raw)], check=True)
    files = {}
    for n, (name, e) in enumerate(ECHO.items(), start=4):
        w = wpe(raw, work / f"wpe_{name}.wav", e["taps"], e["delay"], e["iterations"])
        d = deepfilter_pf(w, work / name, e["post_filter"])
        af = (expander(d, *e["expander"]) + "," if e["expander"] else "") + chain("none")
        mid = work / f"{name}_chain.wav"
        subprocess.run([FF, "-v", "error", "-y", "-i", str(d), "-af", af, "-ar", "48000", "-c:a", "pcm_s24le", str(mid)], check=True)
        files[name] = out_dir / f"{n}_echo_{name}.wav"
        to_target(mid, files[name])
    if reference:
        r = subprocess.run([str(FFMPEG).replace("ffmpeg", "ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(reference)],
                           capture_output=True, text=True).stdout
        files["ramadan"] = out_dir / "0_reference_ramadan.wav"
        subprocess.run([FF, "-v", "error", "-y", "-ss", str(max(0.0, float(r or 0) / 2)), "-t", str(seconds), "-i", str(reference), "-vn", "-ar", "48000",
                        "-c:a", "pcm_s24le", str(files["ramadan"])], check=True)
    meas = {k: loudness(v) for k, v in files.items()}
    (out_dir / "measurements.json").write_text(json.dumps({"camera": str(video), "at_s": at, "seconds": seconds, "voiced_channel": ch,
                                                           "files": {k: str(v) for k, v in files.items()}, "loudness": meas, "echo": ECHO},
                                                          ensure_ascii=False, indent=1))
    return files


# speech-restoration models made for room echo (owner, 20 Oct 2026: WPE + DeepFilterNet still left too much echo), each in
# its own environment so nothing existing changes; the restored voice then gets the same EQ, levelling and loudness as
# sample 3. Each tool downloads its own model files once (VoiceFixer: ~/.cache/voicefixer; ClearerVoice: checkpoints/ in
# its work folder; Resemble Enhance: its package folder).
RESTORE = {
    "voicefixer": ("voice_voicefixer",
                   "import sys; from voicefixer import VoiceFixer\n"
                   "VoiceFixer().restore(input=sys.argv[1], output=sys.argv[2], cuda=False, mode=int(sys.argv[3]))\n"),
    "clearvoice": ("voice_clearvoice",
                   "import sys; from clearvoice import ClearVoice\n"
                   "cv = ClearVoice(task='speech_enhancement', model_names=[sys.argv[3]])\n"
                   "out = cv(input_path=sys.argv[1], online_write=False)\n"
                   "cv.write(out, output_path=sys.argv[2])\n"),
    "resemble": ("voice_resemble",
                 "import sys, torch, torchaudio, resemble_enhance\n"
                 "from pathlib import Path\n"
                 "from resemble_enhance.enhancer.inference import enhance\n"
                 "run = Path(resemble_enhance.__file__).parent / 'model_repo' / 'enhancer_stage2'   # fetched once from Hugging Face\n"
                 "dwav, sr = torchaudio.load(sys.argv[1]); dwav = dwav.mean(dim=0)\n"
                 "wav, new_sr = enhance(dwav, sr, 'cpu', nfe=64, solver='midpoint', lambd=float(sys.argv[3]), tau=0.5, run_dir=run)\n"
                 "torchaudio.save(sys.argv[2], wav[None].cpu(), new_sr)\n"),
}
RESTORE_RUNS = [("voicefixer", "0", "VoiceFixer (mode 0)"), ("clearvoice", "MossFormer2_SE_48K", "ClearerVoice MossFormer2 48 kHz"),
                ("resemble", "0.9", "Resemble Enhance (enhancer, denoise 0.9)")]


def restore(tool, arg, src, out, cwd):
    """one tool on a mono wav -> (out, seconds it took)"""
    import time
    env, code = RESTORE[tool]
    t0 = time.time()
    r = subprocess.run([str(ENVS / env / "bin" / "python"), "-c", code, str(Path(src).resolve()), str(Path(out).resolve()), arg],
                       capture_output=True, text=True, cwd=str(ENVS / env))     # a tool's own model files stay in its environment
    if r.returncode != 0 or not Path(out).exists():
        raise RuntimeError(f"{tool}: {(r.stderr or r.stdout).strip()[-600:]}")
    return Path(out), round(time.time() - t0, 1)


def restore_samples(video, out_dir, at=1000.0, seconds=60.0, reference=None, log=print):
    """each restoration tool on the same stretch, then sample 3's EQ, levelling and loudness; the reference too; the time
    each tool took per minute of audio -> measurements.json"""
    out_dir = Path(out_dir)
    work = out_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    ch, _ = voiced_channel(video, at)
    raw = work / "raw_voiced_mono.wav"
    subprocess.run([FF, "-v", "error", "-y", "-ss", str(at), "-t", str(seconds), "-i", str(video), "-vn", "-af", f"pan=mono|c0=c{ch},{HIGHPASS}",
                    "-ar", "48000", "-c:a", "pcm_s24le", str(raw)], check=True)
    files, timing, failed = {}, {}, {}
    for n, (tool, arg, label) in enumerate(RESTORE_RUNS, start=7):
        try:
            got, secs = restore(tool, arg, raw, work / f"{tool}.wav", work)
        except Exception as e:  # noqa: BLE001  (a tool that does not run here is reported, the others go on)
            failed[tool] = str(e)[-400:]
            log(f"{label}: failed ({str(e)[-200:]})")
            continue
        mid = work / f"{tool}_chain.wav"
        subprocess.run([FF, "-v", "error", "-y", "-i", str(got), "-af", chain("none"), "-ar", "48000", "-c:a", "pcm_s24le", str(mid)], check=True)
        files[tool] = out_dir / f"{n}_{tool}.wav"
        to_target(mid, files[tool])
        timing[tool] = {"label": label, "seconds": secs, "seconds_per_audio_minute": round(secs * 60 / seconds, 1)}
        log(f"{label}: {secs:.0f} s for {seconds:.0f} s of audio")
    if reference:
        r = subprocess.run([str(FFMPEG).replace("ffmpeg", "ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(reference)],
                           capture_output=True, text=True).stdout
        files["ramadan"] = out_dir / "0_reference_ramadan.wav"
        subprocess.run([FF, "-v", "error", "-y", "-ss", str(max(0.0, float(r or 0) / 2)), "-t", str(seconds), "-i", str(reference), "-vn", "-ar", "48000",
                        "-c:a", "pcm_s24le", str(files["ramadan"])], check=True)
    (out_dir / "measurements.json").write_text(json.dumps({"camera": str(video), "at_s": at, "seconds": seconds, "voiced_channel": ch,
                                                           "files": {k: str(v) for k, v in files.items()}, "loudness": {k: loudness(v) for k, v in files.items()},
                                                           "timing": timing, "failed": failed}, ensure_ascii=False, indent=1))
    return files


# ---------------------------------------------------------------------------------------------------- in an episode
# owner's decision of 21 Oct 2026: an episode with presenter whose voice is the camera's own mic (a camera video and no
# separate microphone file) gets VoiceFixer + the EQ + -15 LUFS at the final mix only (the cut keeps reading the raw sound);
# with a separate mic file nothing changes. It runs at the same time as the sources step; the mix waits for it.
CLEAN = "cut_voice_clean48.wav"
# owner's decision of 21 Oct 2026 (after the first episode): VoiceFixer on the RAW recording, before the cut, as the approved
# sample was made. Run on the cut voice it put a burst on 41 % of the cut's 804 edits (14 % elsewhere), and its fixed 30 s
# windows crossfaded two renders that do not line up (half of the 34 joins dipped over 2 dB)
CHAIN_SIG = "voicefixer-mode0-raw-before-cut-joins-in-pauses|" + EQ_VOICEFIXER + "|" + LEVEL + f"|{TARGET_LUFS}/{TARGET_TP}"
WIN_MAX = 29.5        # s: one VoiceFixer piece (it cuts a longer input into 30 s pieces with hard joins)
JOIN_FROM = 5.0       # s into a window: where the search for its join starts
JOIN_X = 0.075        # s each side of a join: the windows' crossfade (0.15 s), where its loudest 10 ms is the quietest found.
                      # On the first camera episode (noise floor only 26 dB under speech) that put the crossfades at the floor
                      # (median +0.4 dB); 0.5 s ones placed by a 0.3 s average still covered speech (median +18.6 dB)
MERGE_GAP, PAD = 3.0, 1.0   # kept stretches closer than this are one region; each region with 1 s of context each side
VF_WINDOWS = ("import sys, json, numpy as np, soundfile as sf\n"
              "from voicefixer import VoiceFixer\n"
              "vf = VoiceFixer()\n"
              "wav = vf._load_wav(sys.argv[1], sample_rate=44100)\n"
              "wins = json.load(open(sys.argv[2])); sr = 44100\n"
              "out = np.zeros(len(wav), dtype=np.float32); prev_b = -1\n"
              "for k, (a, b) in enumerate(wins):\n"
              "    a, b = int(round(a * sr)), min(len(wav), int(round(b * sr)))\n"
              "    seg = wav[a:b]\n"
              "    r = np.asarray(vf.restore_inmem(seg, cuda=False, mode=0)).reshape(-1)[:len(seg)].astype(np.float32)\n"
              "    if len(r) < len(seg): r = np.pad(r, (0, len(seg) - len(r)))\n"
              "    o = max(0, prev_b - a)\n"                       # the overlap with the window before: a join in a pause
              "    if o:\n"
              "        f = np.linspace(0, 1, o, dtype=np.float32)\n"
              "        out[a:a + o] = out[a:a + o] * (1 - f) + r[:o] * f; out[a + o:b] = r[o:]\n"
              "    else:\n"
              "        out[a:b] = r\n"
              "    prev_b = b\n"
              "    print(f'voicefixer: window {k + 1} of {len(wins)}', flush=True)\n"
              "sf.write(sys.argv[3], out, sr, subtype='PCM_24')\n")


def regions(keep, total):
    """the raw recording's stretches the cut keeps, merged when closer than MERGE_GAP, with PAD of context -> [(a, b)] s"""
    out = []
    for s_, e in sorted(keep):
        if out and s_ - out[-1][1] < MERGE_GAP:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s_, e])
    padded = []
    for s_, e in out:
        a, b = max(0.0, s_ - PAD), min(total, e + PAD)
        if padded and a <= padded[-1][1]:
            padded[-1][1] = b
        else:
            padded.append([a, b])
    return [tuple(x) for x in padded]


def plan_windows(level_db, fr, regs):
    """level_db: the voiced channel's level per frame of fr seconds -> windows [(a, b)] of at most WIN_MAX s; inside a region
    each window ends where a 2 x JOIN_X crossfade between JOIN_FROM and WIN_MAX - JOIN_X of it has the quietest loudest
    frame (a pause between words), the next starts JOIN_X before that point; and [(join s, the crossfade's loudest dB)]"""
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view
    lev = np.asarray(level_db, dtype=float)
    k = int(round(2 * JOIN_X / fr)) + 1
    mx = np.full(len(lev), 1e9)
    if len(lev) >= k:
        mx[k // 2: k // 2 + len(lev) - k + 1] = sliding_window_view(lev, k).max(axis=1)
    wins, joins = [], []
    for A, B in regs:
        a = A
        while B - a > WIN_MAX:
            i0, i1 = int((a + JOIN_FROM) / fr), int((a + WIN_MAX - JOIN_X) / fr)
            i = i0 + int(np.argmin(mx[i0:i1])) if i1 > i0 else i0
            j = round(i * fr + fr / 2, 3)
            wins.append((round(a, 3), round(j + JOIN_X, 3)))
            joins.append((j, round(float(mx[i]), 1)))
            a = j - JOIN_X
        wins.append((round(a, 3), round(B, 3)))
    return wins, joins


def frame_levels(path, fr=0.01, sr=8000):
    """the level of a mono file per frame (dB)"""
    import numpy as np
    x = np.frombuffer(subprocess.run([FF, "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True,
                                     check=True).stdout, np.float32).astype(np.float64)
    n = int(fr * sr)
    m = len(x) // n
    return 10 * np.log10(np.mean(x[:m * n].reshape(m, n) ** 2, axis=1) + 1e-12)


def lag_ms(a, b, ch_a=None, points=8, span=6.0):
    """how late b is against a (ms, envelopes in 1 ms steps) at a few points along them"""
    import numpy as np

    def env(path, ch, t):
        af = (f"pan=mono|c0=c{ch}," if ch is not None else "") + "aresample=16000"
        x = np.frombuffer(subprocess.run([FF, "-v", "error", "-ss", f"{t:.3f}", "-t", str(span), "-i", str(path), "-af", af, "-ac", "1", "-f", "f32le", "-"],
                                         capture_output=True, check=True).stdout, np.float32).astype(np.float64)
        m = len(x) // 16
        e = np.sqrt(np.mean(x[:m * 16].reshape(m, 16) ** 2, axis=1))
        return (e - e.mean()) / (e.std() + 1e-12)
    total = samples_of(a) / 48000
    span = min(span, total / 2)
    edge = min(20.0, total / 8)
    out = []
    for t in np.linspace(edge, max(edge, total - edge - span), points):
        x, y = env(a, ch_a, t), env(b, None, t)
        n = min(len(x), len(y))
        x, y = x[:n], y[:n]
        best = max(range(-150, 151), key=lambda L: float(np.dot(x[max(0, L): n + min(0, L)], y[max(0, -L): n - max(0, L)])))
        out.append(-best)              # the best shift lines b up L ms EARLIER than a: b is -L ms late
    return out


def cut_voice(p):
    """the finished cut's own sound, 48 kHz stereo (as the mix has always taken it)"""
    from ..core.io import atomic
    v = p.work / "cut_audio48.wav"
    cut = p.output / f"cut_v{int(p.opt('version', 1))}.mp4"
    stale = getattr(p, "profile", None) and v.exists() and cut.exists() and v.stat().st_mtime < cut.stat().st_mtime
    if stale:                          # a new version's cut (22 Oct 2026: v2 took v1's sound, 7 s longer): the old one kept aside
        old = p.work / "superseded" / f"cut_audio48_before_{cut.stem}.wav"
        old.parent.mkdir(exist_ok=True)
        v.replace(old)
    if not (v.exists() and v.stat().st_size > 1000):
        with atomic(v) as tmp:
            subprocess.run([FF, "-v", "error", "-y", "-i", str(p.output / f"cut_v{int(p.opt('version', 1))}.mp4"), "-vn", "-ac", "2",
                            "-ar", "48000", "-c:a", "pcm_s24le", str(tmp)], check=True)
    return v


def samples_of(path):
    r = subprocess.run([str(FFMPEG).replace("ffmpeg", "ffprobe"), "-v", "error", "-select_streams", "a:0", "-count_packets",
                        "-show_entries", "stream=duration_ts,sample_rate:format=duration", "-of", "json", str(path)], capture_output=True, text=True)
    j = json.loads(r.stdout or "{}")
    return int(round(float((j.get("format") or {}).get("duration") or 0) * 48000))


def clean_voice(src, out, work, log=print):
    """the whole chain on one voice file -> out (48 kHz stereo, exactly src's length) and a record of what was done"""
    import time
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    ch, lv = voiced_channel(src, None, 600)
    mono = work / "voice_mono.wav"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(src), "-af", f"pan=mono|c0=c{ch},{HIGHPASS}", "-ar", "44100", "-c:a", "pcm_s24le", str(mono)],
                   check=True)
    t0 = time.time()
    rec = {"voiced_channel": ch, "channel_levels_db": lv, "tool": "VoiceFixer (mode 0)"}
    vfo = work / "voice_voicefixer.wav"
    from ..core.io import save_json
    wins, _ = plan_windows(frame_levels(mono), 0.01, [(0.0, samples_of(mono) / 48000)])     # one file: its joins in pauses too
    save_json(work / "windows_s.json", wins)
    try:
        r = subprocess.run([str(ENVS / "voice_voicefixer" / "bin" / "python"), "-c", VF_WINDOWS, str(mono), str(work / "windows_s.json"), str(vfo)],
                           capture_output=True,
                           text=True, cwd=str(ENVS / "voice_voicefixer"))
        why = "" if r.returncode == 0 and vfo.exists() else (r.stderr or r.stdout).strip()
    except OSError as e:               # its environment is not on this Mac (setup has not made it)
        why = f"its environment is missing ({e})"
    if why:
        rec["tool"] = "ffmpeg (VoiceFixer failed: " + why[-300:] + ")"
        log(f"voice: VoiceFixer failed; the ffmpeg cleaning is used instead ({why[-160:]})")
        mid = work / "voice_chain.wav"
        subprocess.run([FF, "-v", "error", "-y", "-i", str(mono), "-af", chain("ffmpeg"), "-ar", "48000", "-c:a", "pcm_s24le", str(mid)], check=True)
    else:
        mid = work / "voice_chain.wav"
        subprocess.run([FF, "-v", "error", "-y", "-i", str(vfo), "-af", f"{EQ_VOICEFIXER},{LEVEL}", "-ar", "48000", "-c:a", "pcm_s24le", str(mid)],
                       check=True)
    rec["seconds"] = round(time.time() - t0, 1)
    tgt = work / "voice_target.wav"
    to_target(mid, tgt)
    n = samples_of(src)                # exactly the cut's length: the voice stays on the picture
    subprocess.run([FF, "-v", "error", "-y", "-i", str(tgt), "-af", f"apad=whole_len={n},atrim=end_sample={n}", "-ar", "48000",
                    "-c:a", "pcm_s24le", str(out)], check=True)
    rec["loudness"] = loudness(out)
    return rec


CLEAN_LIGHT = "afftdn=nr=8:nf=-55:tn=1"      # a light noise reduction (a voice a little noisier than the reference)
# before the levelling (which lifts the quiet stretches by up to 18 dB): the pauses lowered by up to 12 dB, from 30 dB under the
# voice's level; tried on Ramadan's mic file (21 Oct 2026): the levelling alone took its signal-to-noise from 41 to 29 dB, with
# this gate first it stays at 40
GATE = "agate=threshold={thr:.5f}:ratio=2:attack=10:release=150:range=0.25:knee=4"
GATE_BELOW = 30.0
# owner's fix 5 of 22 Oct 2026: the levelling raised the breaths of «المملكة المتحدة تنهار» by 17 dB (from 33 to 16 dB under the
# voice). Now (a voice not restored) it never lifts a stretch whose peak is more than 24 dB under the voice and at most 12 dB
# elsewhere: the breaths come up about 10 dB (to 22.6 dB under the voice, measured on its mic); the loudness range is wider
LEVEL_RAW = "dynaudnorm=f=250:g=11:p=0.7:m=4:t={t:.5f},acompressor=threshold=-24dB:ratio=4:attack=5:release=120:makeup=3"
BREATH_UNDER = 24.0
JOIN_JUMP_DB, JOIN_GAIN_MAX = 6.0, 9.0    # owner's fix 6: a kept piece this much louder or quieter than its neighbours is evened
FIT_TRIES = 3                                # the EQ corrected at most 3 times on the measured stretches (within 1 dB; the mic: 3)
# one filter per tone measure (6-10 kHz a peak, not a shelf: a shelf moved that band by 4 dB for 6 asked)
EQ_BANDS = {"1-3k": "equalizer=f=1800:t=o:w=1.2:g={g}", "3-6k": "equalizer=f=4300:t=o:w=0.9:g={g}", "6-10k": "equalizer=f=7700:t=o:w=0.8:g={g}"}
AUTO_SIG = "auto-v3|" + LEVEL_RAW + f"@{BREATH_UNDER}|joins{JOIN_JUMP_DB}/{JOIN_GAIN_MAX}|voicefixer-mode0-raw-before-cut-joins-in-pauses|dfn3|" + CLEAN_LIGHT + "|" + GATE + f"@{GATE_BELOW}|fit-eq{FIT_TRIES}|" + \
    "|".join(EQ_BANDS.values()) + "|" + EQ_VOICEFIXER + "|" + LEVEL + f"|{TARGET_LUFS}/{TARGET_TP}"
NARRATION_CLEAN = "narration_clean48.wav"


def auto_voice(p):
    """the voice of a channel episode is processed (owner's decision of 21 Oct 2026: every episode, every channel, no
    button; camera or separate mic, with presenter or audio only); classic projects and «cut only» never"""
    try:
        if not getattr(p, "profile", None) or p.opt("output", "montage") != "montage":
            return False
        return (p.input("video") or p.input("audio")) is not None
    except Exception:  # noqa: BLE001
        return False


def camera_voice(p):
    """kept for older callers: now every channel episode's voice (auto_voice)"""
    return auto_voice(p)


def voice_source(p):
    """the voice as recorded: with presenter the sound the cut is made from (the mic laid on the camera's timeline, or the
    camera's own), on the raw timeline; audio only the narration as it is"""
    return p.work / "sync_ext48.wav" if p.mode == "talking_head" else p.work / "voice" / "audio48.wav"


def clean_out(p):
    return p.work / (CLEAN if p.mode == "talking_head" else NARRATION_CLEAN)


def reference(p):
    """the channel's own reference sound (its profile's sound.voice_reference, measured on its published episodes) or the
    professional default"""
    from .voice_measure import DEFAULT_REFERENCE
    try:
        r = (p.profile_montage().get("sound") or {}).get("voice_reference")
    except Exception:  # noqa: BLE001
        r = None
    return r or DEFAULT_REFERENCE


def eq_filters(eq):
    """the EQ toward the reference: a band per tone measure"""
    if not eq:
        return []
    return [EQ_BANDS[b].format(g=round(g, 1)) for b, g in eq.items() if abs(g) >= 1.0]


def level_raw(m):
    return LEVEL_RAW.format(t=10 ** ((m["speech_dBFS"] - BREATH_UNDER) / 20))


def smooth_joins(src, keep, out, log=print):
    """owner's fix 6 of 22 Oct 2026: a kept piece whose voice is JOIN_JUMP_DB or more louder or quieter than the pieces
    around it (the median of up to 8 each side, itself included) is brought to them (at most JOIN_GAIN_MAX dB); the change sits on the
    cut itself -> [(start s, end s, dB)]"""
    import numpy as np
    raw = subprocess.run([FF, "-v", "error", "-i", str(src), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, np.float32)
    n = len(x) // 160
    db = 20 * np.log10(np.sqrt(np.mean(x[:n * 160].reshape(n, 160) ** 2, axis=1)) + 1e-9)
    sp = float(np.percentile(db, 90))
    spans, t = [], 0.0
    for a, b in keep:
        spans.append((t, t + (b - a)))
        t += b - a
    lv = []
    for a, b in spans:
        seg = db[int(a * 100):int(b * 100)]
        seg = seg[seg > sp - 25]
        lv.append(float(np.percentile(seg, 90)) if b - a >= 0.4 and len(seg) >= 15 else None)
    gains = []
    for i, L in enumerate(lv):
        if L is None:
            continue
        near = [lv[k] for k in range(max(0, i - 8), min(len(lv), i + 9)) if lv[k] is not None]    # itself included: robust
        if len(near) < 4:
            continue
        d = float(np.median(near)) - L
        if abs(d) >= JOIN_JUMP_DB:
            gains.append((round(spans[i][0], 3), round(spans[i][1], 3), round(max(-JOIN_GAIN_MAX, min(JOIN_GAIN_MAX, d)), 1)))
    af = ",".join(f"volume=volume={g}dB:enable='between(t,{a:.3f},{b - 0.001:.3f})'" for a, b, g in gains) or "anull"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(src), "-af", af, "-c:a", "pcm_s24le", str(out)], check=True)
    if gains:
        log(f"voice: {len(gains)} kept piece(s) evened with their neighbours (a jump of {JOIN_JUMP_DB:g} dB or more): "
            + ", ".join(f"{a:.1f} s {g:+.1f} dB" for a, b, g in gains[:12]))
    return gains


def pause_gate(m):
    return GATE.format(thr=10 ** ((m["speech_dBFS"] - GATE_BELOW) / 20))


def fit_eq(src, pre, eq, post, ref, work, tries=FIT_TRIES):
    """the EQ that brings the chain's result to the reference's tone (the levelling brightens a voice by 3-6 dB above
    3 kHz): the whole chain run on the measured stretches of src (mono), the bands measured, the EQ corrected -> (eq, bands)"""
    from . import voice_measure as VM
    ex = VM.excerpt(src, 0, Path(work) / "tone_excerpt.wav")
    eq = {b: float((eq or {}).get(b, 0.0)) for b in ref["bands_dB"]}
    for k in range(tries + 1):
        t = Path(work) / f"tone_try{k}.wav"
        subprocess.run([FF, "-v", "error", "-y", "-i", str(ex), "-af", ",".join(pre + eq_filters(eq) + post + ["anull"]), "-c:a", "pcm_s24le", str(t)],
                       check=True)
        got = VM.bands(VM._pcm(t, 0, 0.0, 10 ** 6))
        diff = {b: ref["bands_dB"][b] - got[b] for b in eq}
        if k == tries or all(abs(v) <= 1.0 for v in diff.values()):
            return {b: round(g, 1) for b, g in eq.items()}, got
        eq = {b: max(-VM.EQ_MAX, min(VM.EQ_MAX, eq[b] + diff[b])) for b in eq}


def clean_episode_voice(p, out, work, log=print, plan_=None):
    """the voice of an episode processed as its measurements ask (voice_measure.plan against the channel's reference) ->
    out (48 kHz stereo, exactly the cut's or the narration's length) and a record. With presenter it is done BEFORE the cut,
    on the raw timeline, then cut exactly as the cut was (cut/render.py render_audio); the loudness always -15 LUFS."""
    import time
    import numpy as np
    from ..core.io import load_json, save_json
    from . import voice_measure as VM
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    raw = voice_source(p)
    total = samples_of(raw) / 48000
    m = VM.measure(raw)
    ref = reference(p)
    pl = plan_ or VM.plan(m, ref)
    ch = m["voiced_channel"]
    rec = {"measured": m, "reference": ref, "plan": pl, "voiced_channel": ch, "channel_levels_db": m["channel_levels_db"]}
    for w in pl["why"]:
        log("voice: " + w)
    presenter = p.mode == "talking_head"
    if presenter:
        edl = load_json(p.output / "edl.json")
        keep, ins, fades = edl["keep"], edl.get("inserts", []), edl.get("fades", [])
        regs = regions(keep, total)
    else:
        keep, regs = None, [(0.0, total)]
    t0 = time.time()
    tail = ([level_raw(m)] if pl["level"] else [])   # VoiceFixer's own path keeps LEVEL (approved sample 7)
    if pl["clean"] == "restore":
        mono = work / "raw_voice_mono44.wav"
        subprocess.run([FF, "-v", "error", "-y", "-i", str(raw), "-af", f"pan=mono|c0=c{ch},{HIGHPASS}", "-ar", "44100", "-c:a", "pcm_s24le", str(mono)],
                       check=True)
        lev = frame_levels(mono)
        wins, joins = plan_windows(lev, 0.01, regs)
        speech, floor = float(np.percentile(lev, 90)), float(np.percentile(lev, 10))
        save_json(work / "windows.json", {"regions": regs, "windows": wins, "joins": joins, "speech_level_db": round(speech, 1),
                                          "floor_db": round(floor, 1)})
        save_json(work / "windows_s.json", wins)
        rec.update(tool="VoiceFixer (mode 0), before the cut", regions=len(regs), processed_s=round(sum(b - a for a, b in regs), 1),
                   windows=len(wins), joins=len(joins),
                   joins_vs_noise_floor_db=round(float(np.median([x for _, x in joins])) - floor, 1) if joins else None)
        log(f"voice: VoiceFixer on {rec['processed_s']:.0f} s of the {total:.0f} s recording, {len(wins)} windows, every join in a pause")
        vfo = work / "raw_voice_voicefixer44.wav"
        try:
            r = subprocess.run([str(ENVS / "voice_voicefixer" / "bin" / "python"), "-c", VF_WINDOWS, str(mono), str(work / "windows_s.json"), str(vfo)],
                               capture_output=True, text=True, cwd=str(ENVS / "voice_voicefixer"))
            why = "" if r.returncode == 0 and vfo.exists() else (r.stderr or r.stdout).strip()
        except OSError as e:               # its environment is not on this Mac (setup has not made it)
            why = f"its environment is missing ({e})"
        if why:
            rec["tool"] = "ffmpeg (VoiceFixer failed: " + why[-200:] + ")"
            log(f"voice: VoiceFixer failed; the ffmpeg cleaning is used instead ({why[-160:]})")
            src, af = mono, [chain("ffmpeg")]
        else:
            late = int(np.median(lag_ms(mono, vfo, points=12)))     # VoiceFixer's own offset (it comes out early), taken out
            rec["voicefixer_late_ms"] = late
            shift = [f"atrim=start={late / 1000:.3f},asetpts=PTS-STARTPTS"] if late > 0 else [f"adelay={-late}:all=1"] if late < 0 else []
            src, af = vfo, shift + [EQ_VOICEFIXER] + [LEVEL]
    if pl["clean"] in ("denoise", "light", "none"):
        mono = work / "raw_voice_mono48.wav"
        subprocess.run([FF, "-v", "error", "-y", "-i", str(raw), "-af", f"pan=mono|c0=c{ch},{HIGHPASS}", "-ar", "48000", "-c:a", "pcm_s24le", str(mono)],
                       check=True)
        pre, fit = [], True
        if pl["clean"] == "denoise":
            try:
                src = deepfilter(mono, work)
                rec["tool"] = "DeepFilterNet 3"
            except (OSError, subprocess.CalledProcessError) as e:      # its environment missing or broken: never a stop
                rec["tool"] = f"ffmpeg (DeepFilterNet failed: {str(e)[-200:]})"
                log("voice: DeepFilterNet failed; the ffmpeg cleaning is used instead")
                src, af, fit = mono, [chain("ffmpeg")], False
        else:
            rec["tool"] = "light noise reduction (ffmpeg)" if pl["clean"] == "light" else "no cleaning"
            src, pre = mono, ([CLEAN_LIGHT] if pl["clean"] == "light" else [])
        if fit:
            if pl["level"]:
                pre = pre + [pause_gate(m)]
            if pl["eq"] or pl["level"]:          # the tone fitted on the whole chain's result; a clean voice: nothing
                eq, got = fit_eq(src, pre, pl["eq"], tail, ref, work)
                rec.update(eq_planned=pl["eq"], eq_fitted=eq, bands_after_fit=got)
                log(f"voice: the EQ fitted on the chain's result: {', '.join(f'{b} {g:+.1f} dB' for b, g in eq.items())} "
                    f"(bands then {', '.join(f'{v:+.1f}' for v in got.values())}; the reference {', '.join(f'{v:+.1f}' for v in ref['bands_dB'].values())})")
            else:
                eq = None
            af = pre + eq_filters(eq) + tail
            rec["filters"] = af
    mid = work / "raw_voice_chain48.wav"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(src), "-af", ",".join(af + ["aresample=48000", "pan=stereo|c0=c0|c1=c0"]),
                    "-c:a", "pcm_s24le", str(mid)], check=True)
    rec["seconds"] = round(time.time() - t0, 1)
    if presenter:
        from ..cut.render import render_audio
        cut = work / "cut_voice_chain48.wav"
        render_audio(keep, mid, cut, work / "cut_pieces", ins, fades)
        ref_audio = cut_voice(p)
        if not ins:                    # the pieces' places on the cut (no inserted slot in between)
            even = work / "cut_voice_evened48.wav"
            rec["joins_evened"] = smooth_joins(cut, keep, even, log=log)
            cut = even
    else:
        cut, ref_audio = mid, raw
    tgt = work / "voice_target.wav"
    to_target(cut, tgt)
    n = samples_of(ref_audio)            # exactly the cut's (or the narration's) length: the voice stays on the picture
    subprocess.run([FF, "-v", "error", "-y", "-i", str(tgt), "-af", f"apad=whole_len={n},atrim=end_sample={n}", "-ar", "48000",
                    "-c:a", "pcm_s24le", str(out)], check=True)
    rec["loudness"] = loudness(out)
    rec["late_vs_the_cut_ms"] = lag_ms(ref_audio, out, ch_a=ch)      # against the cut's own sound (audio only: the narration)
    return rec


def step(p):
    """the montage step «voice_clean»: every channel episode's voice, measured and processed as it needs (owner's decision
    of 21 Oct 2026); classic projects and «cut only» nothing"""
    from ..core.io import save_json
    if not auto_voice(p):
        print("voice: not a channel episode with its montage: the voice as it is")
        return
    out = clean_out(p)
    print(f"voice: measured against {reference(p).get('name', 'the reference')}; only what it needs, then {TARGET_LUFS:g} LUFS", flush=True)
    rec = clean_episode_voice(p, out, p.work / "voice_chain", log=print)
    save_json(p.work / "montage" / "voice_chain.json", dict(rec, out=str(out), chain=AUTO_SIG))
    L = rec["loudness"]
    print(f"voice: done with {rec['tool']} in {rec['seconds']:.0f} s; {L['I_LUFS']:.1f} LUFS, true peak {L['truepeak_dBTP']:.1f} dBTP; "
          f"{rec['late_vs_the_cut_ms']} ms against the cut", flush=True)


def samples(video, out_dir, at=1000.0, seconds=60.0, reference=None, log=print):
    """before / ffmpeg / DeepFilterNet samples of the same stretch (and Ramadan's reference) -> {name: file}, measured"""
    out_dir = Path(out_dir)
    work = out_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    ch, lv = voiced_channel(video, at)
    log(f"voiced channel: {'left' if ch == 0 else 'right'} (mean levels {lv[0]:.1f} / {lv[1]:.1f} dB)")
    files = {}
    raw = work / "raw_voiced_mono.wav"
    subprocess.run([FF, "-v", "error", "-y", "-ss", str(at), "-t", str(seconds), "-i", str(video), "-vn", "-af", f"pan=mono|c0=c{ch}",
                    "-ar", "48000", "-c:a", "pcm_s24le", str(raw)], check=True)
    # 1 · before: what an episode gets today (the camera's two channels as they are; the mix only keeps the peak under -1 dBTP)
    before = out_dir / "1_before_camera_as_is.wav"
    subprocess.run([FF, "-v", "error", "-y", "-ss", str(at), "-t", str(seconds), "-i", str(video), "-vn", "-ar", "48000", "-c:a", "pcm_s24le",
                    str(before)], check=True)
    files["before"] = before
    # 2 · ffmpeg only
    mid = work / "ffmpeg_chain.wav"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(raw), "-af", chain("ffmpeg"), "-c:a", "pcm_s24le", str(mid)], check=True)
    files["ffmpeg"] = out_dir / "2_after_ffmpeg.wav"
    to_target(mid, files["ffmpeg"])
    # 3 · DeepFilterNet, then the same EQ, levelling and loudness
    hp = work / "raw_highpassed.wav"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(raw), "-af", HIGHPASS, "-c:a", "pcm_s24le", str(hp)], check=True)
    dfn = deepfilter(hp, work)
    mid2 = work / "dfn_chain.wav"
    subprocess.run([FF, "-v", "error", "-y", "-i", str(dfn), "-af", chain("none"), "-ar", "48000", "-c:a", "pcm_s24le", str(mid2)], check=True)
    files["deepfilternet"] = out_dir / "3_after_deepfilternet.wav"
    to_target(mid2, files["deepfilternet"])
    if reference:                       # Ramadan's sound, for the ear (60 s from the middle of a finished episode)
        r = subprocess.run([str(FFMPEG).replace("ffmpeg", "ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(reference)],
                           capture_output=True, text=True).stdout
        mid_s = max(0.0, float(r or 0) / 2)
        files["ramadan"] = out_dir / "0_reference_ramadan.wav"
        subprocess.run([FF, "-v", "error", "-y", "-ss", str(mid_s), "-t", str(seconds), "-i", str(reference), "-vn", "-ar", "48000", "-c:a", "pcm_s24le",
                        str(files["ramadan"])], check=True)
    meas = {k: loudness(v) for k, v in files.items()}
    (out_dir / "measurements.json").write_text(json.dumps({"camera": str(video), "at_s": at, "seconds": seconds, "voiced_channel": ch,
                                                           "files": {k: str(v) for k, v in files.items()}, "loudness": meas,
                                                           "chain": {"ffmpeg": chain("ffmpeg") + " + loudnorm", "deepfilternet":
                                                                     f"{HIGHPASS} + DeepFilterNet3 + {chain('none')} + loudnorm"}},
                                                          ensure_ascii=False, indent=1))
    for k, v in meas.items():
        log(f"{k:14} {v['I_LUFS']:6.1f} LUFS  range {v['LRA_LU']:4.1f} LU  true peak {v['truepeak_dBTP']:5.1f} dBTP  -> {files[k].name}")
    return files


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) >= 3 and a[0] in ("samples", "echo", "restore"):
        kw = {}
        for flag, key, conv in (("--at", "at", float), ("--seconds", "seconds", float), ("--reference", "reference", str)):
            if flag in a:
                i = a.index(flag)
                kw[key] = conv(a[i + 1])
        {"samples": samples, "echo": echo_samples, "restore": restore_samples}[a[0]](a[1], a[2], **kw)
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())

"""The sound: the voice exactly as it is + the music plan (rule 22) + sound effects (rule 18), then ONE fixed gain for
the whole mix so the true peak sits safely under 0 dB. -> work/montage/mix.wav, mix_plan.json

Music: each section's cue (from the music step) looped with 3 s crossfades to the section's length, 1.2 s crossfades at
section changes (or the section's own fade lengths), ~20 dB under the voice; about 1 s of silence before each key fact,
back just after it. A section can also be silent (null) or use a given file ("file", e.g. an earlier video's bed).
Sound effects (the sound-effects step's files) start only inside pauses of the narration: whooshes >= 0.3 s, pops >= 0.12 s,
hits >= 0.25 s; an effect with no pause near its moment is skipped and logged.

The sound plan (decision montage/sound):
  {"length_s", "music_gain_db",
   "sections": [{"music": cue name | null, "from", "to", "fade_in"?, "fade_out"?, "file"?, "filter"?, "note"?}],
   "stops": [[word, s]], "hits": [[word, s]], "pops": [[word, s]],
   "whoosh_scenes": [graphic names whose first appearance gets a whoosh], "whoosh_extra": [[s, why]],
   "intro_clicks": [s, ...]   (the phrase montage's fast intro: a low click under each cut, allowed over speech),
   "music_dips": [s, ...]     (where a channel clip goes in: the music fades out before it and back after; added in code),
   "papers": [[word, s]]      (a paper sound where on-screen text appears, in place of the pops: a channel profile's
                              sound.text_sfx "paper"; it starts in a pause and is cut short before the next word)}
"""
import json
import subprocess
from pathlib import Path

import numpy as np

from ..core.io import atomic, save_json
from ..core.paths import FFMPEG

FF = str(FFMPEG)
SR = 48000
XF = 1.2


def load(path, filt=None):
    a = [FF, "-v", "error", "-i", str(path)] + (["-af", filt] if filt else []) + ["-ac", "2", "-ar", str(SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(a, capture_output=True, check=True).stdout, np.float32).reshape(-1, 2).copy()


def db(x):
    return 10 ** (x / 20)


def cue(music_dir, name, seconds):
    """the cue's raw take at the music step's own finishing gain, cleaned under the voice, looped to 'seconds'"""
    j = json.load(open(Path(music_dir) / f"{name}.json"))
    raw = Path(j["takes"][-1]["file"])
    x = load(raw, f"volume={j['finish']['gain_db']}dB,highpass=f=70,lowshelf=f=150:g=-4")
    x = x[int(0.3 * SR):]                     # skip the very start of the take
    need = int(seconds * SR)
    xf = int(3.0 * SR)
    out = x.copy()
    while len(out) < need:                    # loop with a 3 s equal-power crossfade
        r = np.linspace(0, 1, xf)[:, None]
        nxt = x[int(4.0 * SR):]               # the repeat starts 4 s in, so the loop doesn't restart on the intro
        out = np.concatenate([out[:-xf], out[-xf:] * np.sqrt(1 - r) + nxt[:xf] * np.sqrt(r), nxt[xf:]])
    return out[:need]


WHOOSHES = ("whoosh_a", "whoosh_d", "whoosh_b", "whoosh_e", "whoosh_c")
PEAK = {"whoosh_a": 0.22, "whoosh_b": 0.26, "whoosh_c": 0.15, "whoosh_d": 0.30, "whoosh_e": 0.17}   # s into each (sfx.py peak_at)
WHOOSH_GAP = 55.0             # s between two transition sounds: about one a minute, as in Ramadan's published episodes
SECTION_GAP = 15.0            # (owner, 21 Oct 2026); a section change may have one this soon after the last
BEAT_DB = {"whoosh": -17, "riser": -18, "hit": -14, "tick": -22, "projector": -24, "pop": -17, "paper": -18, "camera": -16}


def on_beat(plan_d, cuts, add, plan, edl):
    """the effects on their moment, over speech when it is there (owner's fix 8 of 21 Oct 2026, measured on Ramadan's
    published episodes: his effects sit over his words, on beats): a whoosh's peak on its cut, about one a minute
    (WHOOSH_GAP s apart; a section change SECTION_GAP s after the last), a riser into a hit on each beat, a counter's
    ticks, a projector for archive film, the label sound and the camera on their frame"""
    last, k = -1e9, 0
    for t, why in sorted(cuts):
        gap = SECTION_GAP if "section" in str(why) else WHOOSH_GAP
        if t - last < gap:
            plan["skipped"].append({"sfx": "whoosh", "at": t, "why": f"within {gap:g} s of the last transition sound ({why})"})
            continue
        name = WHOOSHES[k % len(WHOOSHES)]
        add(name, max(0.0, t - PEAK[name]), BEAT_DB["whoosh"])
        last, k = t, k + 1
    for b in plan_d.get("beats", []):
        t, kind = b[0], b[1]
        if kind == "beat":
            add("riser_short", max(0.0, t - 0.68), BEAT_DB["riser"])
            add("hit", max(0.0, t - 0.02), BEAT_DB["hit"], maxlen=0.9, fade=0.45)
        elif kind == "tick":
            add("tick", t, BEAT_DB["tick"], maxlen=b[3] if len(b) > 3 else 1.2, fade=0.15)
        elif kind == "projector":
            add("projector", t, BEAT_DB["projector"], maxlen=1.4, fade=0.3)
    for k2, (w, t) in enumerate(plan_d.get("papers", [])):
        add("paper" if k2 % 2 == 0 else "paper_b", max(0.0, t - 0.08), BEAT_DB["paper"], maxlen=0.3, fade=0.06)
    for k2, (w, t) in enumerate(plan_d.get("pops", []) if not plan_d.get("papers") else []):
        add("pop" if k2 % 2 == 0 else "pop_low", max(0.0, t - 0.05), BEAT_DB["pop"])
    for s in edl["shots"]:
        if s.get("entry") and not s.get("on_click"):
            add("camera", max(0.0, s["f0"] / 24 - 0.05), BEAT_DB["camera"], maxlen=0.55, fade=0.1)


def mix(voice_wav, words, edl, plan_d, music_dir, sfx_dir, out_wav, out_plan, target_lufs=None):
    LEN = plan_d["length_s"]
    MUSIC_DB = plan_d["music_gain_db"]
    GAPS = [(words[i]["e"], words[i + 1]["s"]) for i in range(len(words) - 1) if words[i + 1]["s"] - words[i]["e"] > 0.05]

    def gap_near(t, lo, hi, minlen):
        c = [(a, b) for a, b in GAPS if b - a >= minlen and a <= t + hi and b >= t - lo]
        return min(c, key=lambda g: abs((g[0] + g[1]) / 2 - t)) if c else None

    n = int(LEN * SR)
    voice = load(voice_wav)
    voice = np.vstack([voice, np.zeros((max(0, n - len(voice)), 2), np.float32)])[:n]
    # ---- music
    mus = np.zeros((n, 2), np.float32)
    plan = {"sections": [], "stops": [], "sfx": [], "skipped": []}
    for sec in plan_d["sections"]:
        name, a, b = sec.get("music"), sec["from"], sec["to"]
        if name is None and not sec.get("file"):
            plan["sections"].append({"music": sec.get("note", "none"), "from": a, "to": b})
            continue
        a2 = max(0.0, a - XF / 2)
        b2 = min(LEN, b + XF / 2) if b < LEN else LEN
        if sec.get("file"):
            x = load(sec["file"], sec.get("filter", "highpass=f=70,lowshelf=f=150:g=-4"))[:int((b2 - a2) * SR)]
        else:
            x = cue(music_dir, name, b2 - a2)
        L = len(x)
        env = np.ones(L, np.float32)
        fi = int(sec.get("fade_in", XF) * SR) if a > 0 else int(0.5 * SR)
        fo = int(sec.get("fade_out", XF) * SR) if b < LEN else int(3.0 * SR)
        env[:fi] *= np.linspace(0, 1, fi)
        env[-fo:] *= np.linspace(1, 0, fo)
        i0 = int(a2 * SR)
        mus[i0:i0 + L] += x * env[:, None]
        plan["sections"].append({"music": name, "from": a, "to": b})
    # 1-second stops before key facts, music back just after the fact
    g = np.ones(n, np.float32)
    for w, t in plan_d.get("stops", []):
        s0, s1, back = t - 1.05, t - 0.05, t + 0.35
        r = int(0.15 * SR)
        i0, i1, i2 = int(s0 * SR), int(s1 * SR), int(back * SR)
        g[i0:i0 + r] = np.minimum(g[i0:i0 + r], np.linspace(1, 0, r))
        g[i0 + r:i2] = 0
        rr = int(0.6 * SR)
        g[i2:i2 + rr] = np.minimum(g[i2:i2 + rr], np.linspace(0, 1, rr))
        plan["stops"].append({"word": w, "at": t, "silent_from": round(s0, 2), "back_at": round(back, 2)})
    # the channel's own clips go in between two sentences (montage/structure.py): the music fades out before each and back after
    for t in plan_d.get("music_dips", []):
        r = int(0.8 * SR)
        i = int(t * SR)
        a0 = max(0, i - r)
        g[a0:i] = np.minimum(g[a0:i], np.linspace(1, 0, i - a0))
        g[i:i + r] = np.minimum(g[i:i + r], np.linspace(0, 1, len(g[i:i + r])))
        plan.setdefault("music_dips", []).append(round(t, 3))
    mus *= g[:, None] * db(MUSIC_DB)
    # ---- sound effects
    sfx = np.zeros((n, 2), np.float32)
    beat = plan_d.get("placement") == "on_beat"
    lib = {k: load(Path(sfx_dir) / f"{k}.wav") for k in ("whoosh_a", "whoosh_b", "whoosh_c", "pop", "pop_low", "hit", "camera")
           + (("paper", "paper_b") if plan_d.get("papers") else ())
           + (("whoosh_d", "whoosh_e", "riser_short", "tick", "projector") if beat else ())}

    def add(name, start, gain, maxlen=None, fade=0.08):
        x = lib[name]
        if maxlen:
            x = x[:int(maxlen * SR)].copy()
            f = min(len(x), int(fade * SR))
            x[-f:] *= np.linspace(1, 0, f)[:, None]
        i0 = int(start * SR)
        sfx[i0:i0 + len(x)] += x[:max(0, n - i0)] * db(gain)
        plan["sfx"].append({"sfx": name, "at": round(start, 3), "gain_db": gain, "seconds": round(len(x) / SR, 2)})

    WHOOSH_SCENES = set(plan_d.get("whoosh_scenes", []))
    seen = set()
    cuts = []
    for s in edl["shots"]:
        if s["kind"] == "gfx" and s["scene"] in WHOOSH_SCENES and s["scene"] not in seen:
            seen.add(s["scene"])
            cuts.append((s["f0"] / 24, s["scene"]))
    cuts += [tuple(x) for x in plan_d.get("whoosh_extra", [])]
    if beat:                           # owner's fix 8 of 21 Oct 2026: on their moment, over speech, as Ramadan places them
        on_beat(plan_d, cuts, add, plan, edl)
        cuts = []
    for k, (t, why) in enumerate(sorted(cuts)):
        gp = gap_near(t, 1.2, 0.4, 0.3)   # a whoosh may lead into its cut from a pause up to 1.2 s before it
        if not gp:
            plan["skipped"].append({"sfx": "whoosh", "at": t, "why": f"no pause of 0.3 s within 1.2 s before the cut ({why})"})
            continue
        st = max(gp[0] + 0.01, min(t - 0.25, gp[1] - 0.3))
        add(("whoosh_a", "whoosh_b", "whoosh_c")[k % 3], st, -15, maxlen=min(0.5, gp[1] - st + 0.1))
    for w, t in ([] if beat else plan_d.get("hits", [])):
        gp = next(((a, b) for a, b in GAPS if abs(b - t) < 0.05 and b - a >= 0.25), None)
        if not gp:
            plan["skipped"].append({"sfx": "hit", "at": t, "why": f"no pause of 0.25 s right before «{w}»"})
            continue
        add("hit", max(gp[0], t - 0.12), -14, maxlen=0.9, fade=0.45)
    for k, (w, t) in enumerate([] if beat else plan_d.get("pops", [])):
        gp = gap_near(t, 0.35, 0.05, 0.12)
        if not gp:
            plan["skipped"].append({"sfx": "pop", "at": t, "why": f"no pause near «{w}»"})
            continue
        add("pop" if k % 2 == 0 else "pop_low", max(gp[0] + 0.01, min(t - 0.07, gp[1] - 0.07)), -13)
    for k, (w, t) in enumerate([] if beat else plan_d.get("papers", [])):
        gp = gap_near(t, 0.35, 0.05, 0.12)
        if not gp:
            plan["skipped"].append({"sfx": "paper", "at": t, "why": f"no pause near «{w}»"})
            continue
        st = max(gp[0] + 0.01, min(t - 0.12, gp[1] - 0.12))
        add("paper" if k % 2 == 0 else "paper_b", st, -15, maxlen=min(0.3, gp[1] - st + 0.08), fade=0.06)
    # the fast intro (Ramadan's note, Phase C): a short click under every intro cut, kept low because in the intro it may
    # sit under speech (decision taken alone: rule 18's "pauses only" holds everywhere after the intro)
    for k, t in enumerate(plan_d.get("intro_clicks", [])):
        add("pop" if k % 2 == 0 else "pop_low", max(0.0, t - 0.03), -27)
    for s in ([] if beat else edl["shots"]):
        if s.get("entry") and not s.get("on_click"):
            t = s["f0"] / 24
            gp = gap_near(t, 0.8, 0.4, 0.25)
            if not gp:
                plan["skipped"].append({"sfx": "camera", "at": round(t, 2), "why": "no pause near this photo entry"})
                continue
            st = max(gp[0] + 0.01, min(t - 0.05, gp[1] - 0.25))
            add("camera", st, -14, maxlen=min(0.55, gp[1] - st + 0.15), fade=0.1)
    # ---- mix, then one fixed gain for a safe true peak
    mixed = voice + mus + sfx
    gain_db = -2.5
    out_wav = Path(out_wav)
    if target_lufs is not None:        # a channel episode: the gain that brings the whole mix to target_lufs (owner, 21 Oct 2026:
        with atomic(out_wav) as tmp:   # the fixed -2.5 dB left the first one at -17.5 LUFS); still one gain, the peak kept below
            subprocess.run([FF, "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-", "-c:a", "pcm_s24le", str(tmp)],
                           input=mixed.astype(np.float32).tobytes(), check=True)
        r = subprocess.run([FF, "-i", str(out_wav), "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True).stderr
        gain_db = target_lufs - float(r.split("Integrated loudness:")[1].split("I:")[1].split("LUFS")[0])
    for _ in range(4):
        y = mixed * db(gain_db)
        with atomic(out_wav) as tmp:
            subprocess.run([FF, "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-", "-c:a", "pcm_s24le", str(tmp)],
                           input=y.astype(np.float32).tobytes(), check=True)
        r = subprocess.run([FF, "-i", str(out_wav), "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True).stderr
        tp = float(r.split("True peak:")[1].split("Peak:")[1].split("dBFS")[0])
        lufs = float(r.split("Integrated loudness:")[1].split("I:")[1].split("LUFS")[0])
        if tp <= -1.0:
            break
        gain_db -= (tp + 1.2)
    plan.update({"mix_gain_db": round(gain_db, 2), "true_peak_dbtp": tp, "lufs": lufs, "music_gain_db": MUSIC_DB})
    if target_lufs is not None:
        plan["target_lufs"] = target_lufs
        if lufs < target_lufs - 0.5:   # the peak held the gain back: said, never a limiter on the voice
            plan["short_of_target_db"] = round(target_lufs - lufs, 1)
    save_json(out_plan, plan)
    print("mix", out_wav, "gain", round(gain_db, 2), "dB; TP", tp, "LUFS", lufs, "sfx", len(plan["sfx"]), "skipped", len(plan["skipped"]))
    return plan

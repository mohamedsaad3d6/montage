"""Self-check of the finished montage -> work/montage/selfcheck.json (the report copies it).

1. Format: h264 1920x1080 24 fps + aac; frame count and sound length match the cut list.
2. Voice unchanged and in sync: lag against the extracted voice, and the voice's gain inside the mix (should equal the one fixed
   mix gain, i.e. the same everywhere — checked per minute).
3. Level: true peak under -1 dBTP; loudness.
4. No empty or frozen shot: per shot, darkest frame and the longest run of identical frames (footage/photos must move).
5. Text inside the frame: every graphic's last frame inside the 5% title-safe margins (maps are skipped).
6. Music has no vocals: each cue's vocals check.
7. Sound effects never start over speech: each effect's start lies in a pause of the narration.
8. Re-hooks: the longest stretch without one.
9-12. The phrase montage: the intro (15-20 s, shots of 1-3 s, a transition on every cut), transitions after it, the
   material mix against the targets, and every downloaded asset's licence through the gate again.
13. On its word (phrase montage): every on-screen item and graphic element is shown when its word starts (2 frames
   before, like a cut), measured on the cut list as rendered (shot start + overlay delay); fails above 0.15 s.
14. Repeats (owner's decision of 16 Oct 2026): no picture file, subject or graphic shown more than twice within 75 s,
   measured on the cut list as rendered (files) and the plan's subjects.
15. With presenter (montage/steps_presenter.py): the intro (B-roll only, shots of 1-3 s, a transition and a click on every
   cut), B-roll cuts on sentence starts, key-word labels per minute (rule 11), the material mix over the B-roll shots,
   repeats, the presenter's share and punch-in rate, B-roll blocks per minute; with the channel's cold open (الحدث
   الأخير), the presenter's one short appearance in it, its teaser at its end and the body's alternation.
16. The channel's own clips (montage/structure.py; a channel profile with a sting, an intro clip or an outro): they are
   taken out again before items 1, 2 and 4, so the voice and the frames are checked on the narration's own timeline;
   their places and lengths on the finished video, and the music rule of the profile (in the cold open only).
18. Documented news (montage/news.py; channel profiles): every news shot of the cut list is a real screenshot scene (no
   card, no «المصدر» line), and the items that could not be shot, with why.
17. The intro's running subtitles (montage/subtitles.py; a channel profile with text.subtitles): every cue inside the
   intro, inside the title-safe area, every word one of the approved script's.
19. «عام» (montage/general.py): real pictures at least the profile's share of the B-roll time, no file shown more than
   twice or within 60 s, no subject over its share of the running time, labels drawn as the caption bar.
"""
import json
import subprocess

import numpy as np

from ..core.io import save_json
from ..core.paths import FFMPEG, FFPROBE

FF, FP = str(FFMPEG), str(FFPROBE)


def pcm(args, sr=48000):
    raw = subprocess.run([FF, "-v", "error"] + args + ["-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def run(p, VID):
    from .steps import M, V, words as words_of, decision
    edl = json.load(open(M(p, "edl.json")))
    plan = json.load(open(M(p, "mix_plan.json")))
    res = {}
    from .structure import of as structure_of
    S = structure_of(p)
    spl = json.load(open(M(p, "splices.json"))) if M(p, "splices.json").exists() else None
    clip_frames = [(round(c["finished_from_s"] * 24), round(c["finished_to_s"] * 24)) for c in spl["clips"]] if spl else []

    def narration_only(x, per_frame=1):
        """the finished video's frames (or samples: per_frame = 2000 at 48 kHz) without the channel's clips"""
        if not clip_frames:
            return x
        keep = np.ones(len(x), bool)
        for a, b in clip_frames:
            keep[a * per_frame:b * per_frame] = False
        return x[keep]
    extra = sum(b - a for a, b in clip_frames)
    pr = json.loads(subprocess.run([FP, "-v", "error", "-count_packets", "-show_entries",
                                    "stream=codec_name,width,height,r_frame_rate,nb_read_packets,duration,sample_rate", "-of", "json", str(VID)],
                                   capture_output=True, text=True).stdout)["streams"]
    v = next(s for s in pr if s["codec_name"] == "h264")
    a = next(s for s in pr if s["codec_name"] == "aac")
    res["format"] = {"video": f"h264 {v['width']}x{v['height']} {v['r_frame_rate']}", "frames": int(v["nb_read_packets"]), "expected_frames": edl["total_frames"] + extra,
                     "video_s": float(v["duration"]), "audio_s": float(a["duration"]),
                     "ok": int(v["nb_read_packets"]) == edl["total_frames"] + extra and abs(float(a["duration"]) - (edl["total_frames"] + extra) / 24) < 0.06}
    # 2 · voice
    voice = pcm(["-i", str(V(p, "audio48.wav") if p.mode == "voice_only" else p.work / "cut_audio48.wav")])
    mix = narration_only(pcm(["-i", str(VID)]), 2000)
    n = min(len(voice), len(mix))
    x, y = voice[:n], mix[:n]
    secs = n // 48000
    a0 = 200 if secs >= 240 else max(0, secs // 2 - 15)           # a 30 s window (videos shorter than 4 min: the middle)
    seg = slice(48000 * a0, 48000 * min(secs, a0 + 30))
    xc = np.fft.irfft(np.fft.rfft(y[seg], 2 * len(y[seg])) * np.conj(np.fft.rfft(x[seg], 2 * len(x[seg]))))
    lag = int(np.argmax(np.abs(np.concatenate([xc[-480:], xc[:481]])))) - 480
    gains = []
    step = 60 if secs >= 120 else max(10, secs // 2)              # per minute; short videos: two halves
    for m in range(0, max(1, secs - step + 1), step):
        s_ = slice(m * 48000, (m + step) * 48000)
        gains.append(float(np.dot(x[s_], y[s_]) / (np.dot(x[s_], x[s_]) + 1e-9)))
    g_db = 20 * np.log10(np.array(gains))
    res["voice"] = {"lag_samples_48k": lag, "voice_gain_db_per_minute_min": round(float(g_db.min()), 2), "max": round(float(g_db.max()), 2),
                    "expected_db": plan["mix_gain_db"], "ok": bool(abs(lag) <= 1 and abs(float(np.median(g_db)) - plan["mix_gain_db"]) < 0.3 and float(g_db.max() - g_db.min()) < 0.6)}
    # 3 · level
    r = subprocess.run([FF, "-i", str(VID), "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True).stderr
    tp = float(r.split("True peak:")[1].split("Peak:")[1].split("dBFS")[0])
    lufs = float(r.split("Integrated loudness:")[1].split("I:")[1].split("LUFS")[0])
    res["level"] = {"true_peak_dbtp": tp, "lufs": lufs, "ok": tp <= -1.0}
    # 4 · frames
    raw = subprocess.run([FF, "-v", "error", "-i", str(VID), "-vf", "scale=96:54", "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    fr = narration_only(np.frombuffer(raw, np.uint8).reshape(-1, 54, 96).astype(np.int16))
    shots = []
    for s in edl["shots"]:
        part = fr[s["f0"]:s["f1"]]
        d = np.abs(np.diff(part, axis=0)).mean(axis=(1, 2)) if len(part) > 1 else np.array([0])
        run = best = 0
        for v_ in d:
            run = run + 1 if v_ < 0.05 else 0
            best = max(best, run)
        skip = 8 if s.get("transition") == "slide" else 11 if s.get("entry") else 0     # a slide enters from black (0.3 s),
        lit = part[skip:] if skip and len(part) > skip else part                      # a photo entry from blur (rule 19, 0.45 s)
        shots.append({"t": round(s["f0"] / 24, 2), "kind": s["kind"], "what": s.get("asset") or s.get("scene") or "promo", "min_luma": round(float(lit.mean(axis=(1, 2)).min()), 1),
                      "still_run": best + 1 if best else 0})
    res["empty_shots"] = [s for s in shots if s["min_luma"] < 6]
    res["frozen_shots"] = [s for s in shots if s["kind"] in ("video", "photo", "ai") and s["still_run"] > 3]
    # 5 · text safe area (graphics' last frames; overlays by alpha)
    safe = []
    from .general import restyle
    scenes = {x["name"]: x for x in restyle(p, decision(p, "graphics", "scenes"))}
    PAPER = np.frombuffer(subprocess.run([FF, "-v", "error", "-i", str(p.asset_dir("textures") / "paper.png"), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                         capture_output=True).stdout, np.uint8).reshape(1080, 1920, 3).astype(int)
    for d_ in sorted(x for x in M(p, "gfx", "frames").iterdir() if x.is_dir() and not x.name.startswith(".")
                     and x.name in scenes):           # only this video's graphics (a copied project keeps older folders)
        last = sorted(d_.glob("*.png"))[-1]
        px = np.frombuffer(subprocess.run([FF, "-v", "error", "-i", str(last), "-f", "rawvideo", "-pix_fmt", "rgba", "-"], capture_output=True).stdout, np.uint8).reshape(1080, 1920, 4)
        if d_.name.startswith(("KW_", "LBL_")):
            m = px[:, :, 3] > 40
        elif d_.name.startswith(("MAP_",)) or any(it.get("type") == "map" for it in scenes.get(d_.name, {}).get("items", [])):
            continue                           # maps fill the frame by design; their captions are checked on the caption bands
        elif scenes.get(d_.name, {}).get("bg") == "image":   # paper cards: compare with the paper itself
            m = np.abs(px[:, :, :3].astype(int) - PAPER).max(axis=2) > 60
        else:                                  # the background is what the frame's border shows (a card may fill most of it)
            edge = np.concatenate([px[:6, :, :3].reshape(-1, 3), px[-6:, :, :3].reshape(-1, 3), px[:, :6, :3].reshape(-1, 3), px[:, -6:, :3].reshape(-1, 3)])
            bg = np.median(edge, axis=0)
            m = np.abs(px[:, :, :3].astype(int) - bg).max(axis=2) > 60
        ys, xs = np.nonzero(m)
        box = [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if len(xs) else None
        ok = box is None or (box[0] >= 96 and box[1] >= 54 and box[2] <= 1824 and box[3] <= 1026)
        safe.append({"graphic": d_.name, "box": box, "inside_title_safe": ok})
    res["text_outside_safe"] = [s for s in safe if not s["inside_title_safe"]]
    # 6 · music
    cues = {}
    for f in sorted(p.asset_dir("music").glob("*.json")):
        if "." in f.stem:                 # a cue set aside (<name>.replaced_… / .rejected_words_…), not in the video
            continue
        j = json.load(open(f))
        t = j["takes"][-1]
        cues[f.stem] = {"generator": j["generator"], "voice_score": t.get("vocal_check", {}).get("voice_score"), "vocals": t.get("vocal_check", {}).get("vocals")}
    res["music"] = {"cues": cues, "ok": all(c["generator"] in ("ace-step", "library-track") and c["vocals"] is False for c in cues.values())}
    # 7 · sound effects start in pauses
    words = words_of(p)
    over = []
    intro_end = decision(p, "montage", "timeline", {}).get("intro_end_s", 0) or 0
    for e in plan["sfx"]:
        t = e["at"]
        if t < intro_end and e.get("gain_db", 0) <= -26:
            continue                      # the fast intro's low clicks may sit under speech (decision taken alone, 15 Oct)
        if any(w["s"] + 0.02 < t < w["e"] - 0.02 for w in words):
            over.append(e)
    res["sfx"] = {"count": len(plan["sfx"]), "starting_over_speech": over, "skipped": plan["skipped"], "ok": not over}
    # 8 · re-hooks
    rh = set(decision(p, "montage", "timeline", {}).get("rehook_scenes", []))
    is_hook = (lambda n: n in rh) if rh else (lambda n: n.startswith("Q"))      # default: re-hook scenes are named Q...
    hooks = {s["f0"] / 24 for s in edl["shots"] if s["kind"] == "gfx" and is_hook(s["scene"])}
    for s in edl["shots"]:
        for o in s.get("overlays", []):
            if is_hook(o["name"]) and o["start_frame"] == 0 or (is_hook(o["name"]) and s["f0"] - o["start_frame"] >= 0):
                hooks.add(round((s["f0"] - o["start_frame"]) / 24, 2))
    hooks = sorted(hooks)
    gaps = np.diff([0.0] + hooks + [edl["total_frames"] / 24])
    inner = gaps[1:-1] if len(gaps) > 2 else gaps
    longest = float(inner.max()) if len(inner) else 0.0
    res["rehooks"] = {"times": [round(h, 1) for h in hooks], "longest_gap_s": round(longest, 1),
                      "ok": longest <= 180 or edl["total_frames"] / 24 < 150}
    # 9-13 · the phrase montage
    if p.montage == "phrases":
        tl = decision(p, "montage", "timeline", {})
        ie = tl.get("intro_end_s", 0)
        intro = [s for s in edl["shots"] if s["f1"] / 24 <= ie + 0.05]
        lens = [(s["f1"] - s["f0"]) / 24 for s in intro]
        if S.fast_open is None:                    # the channel has no fast intro (pace from its profile)
            res["intro"] = {"end_s": ie, "none_by_profile": True, "ok": ie <= 0.5}
        else:
            lo_ok = 10 if S.is_default_intro else S.fast_limits[0]
            fa, fb = S.fast_shot_limits
            res["intro"] = {"end_s": ie, "shots": len(intro), "lengths_s": [round(x, 2) for x in lens],
                            "ok": lo_ok <= ie <= S.fast_limits[1] and all(fa <= x <= fb for x in lens[:-1]) and all(s.get("transition") for s in intro[1:])}
        res["transitions"] = {"count": sum(1 for s in edl["shots"] if s.get("transition")),
                              "kinds": sorted({s["transition"] for s in edl["shots"] if s.get("transition")})}
        rep_ = json.load(open(M(p, "plan_report.json"))) if M(p, "plan_report.json").exists() else {}
        res["material_mix"] = {"share": rep_.get("mix"), "warnings": rep_.get("warnings")}
        from .sources import licence_ok
        led = json.load(open(M(p, "assets.json"))) if M(p, "assets.json").exists() else {}
        bad = {k: v.get("licence") for k, v in led.items() if not licence_ok(v.get("licence"))}
        res["licences"] = {"assets": len(led), "not_passing_the_gate": bad, "ok": not bad}
        # 13 · on its word: when each overlay really starts in the cut list (shot start + its delay), against its word
        first = {}
        for s in edl["shots"]:
            for o in s.get("overlays", []):
                t = (s["f0"] + o.get("delay_frames", 0) - o["start_frame"]) / 24
                first[o["name"]] = min(first.get(o["name"], t), t)
        sc = {x["name"]: x for x in decision(p, "graphics", "scenes", [])}
        on = {}
        for s in edl["shots"]:
            if s["kind"] == "gfx":
                on.setdefault(s["scene"], []).append((s["f0"] / 24, s["f1"] / 24))
        rows = []
        for a in tl.get("anchors", []):
            if a["kind"] == "graphic":           # the element's own start in the rendered scene file, if the scene is on screen
                x = sc.get(a["scene"], {})
                t0s = [it.get("t0", 0) for it in x.get("items", []) if it.get("type") in ("text", "pin")
                       and (it.get("text") or it.get("label") or "").replace("\u2009", "") == a["text"]]
                t = x.get("t_in", 0) + min(t0s) if t0s else None
                if t is not None and not any(f0 - 0.01 <= t < f1 for f0, f1 in on.get(a["scene"], [])):
                    t = None
            else:
                t = first.get(a["scene"])
            rows.append({"text": a["text"], "kind": a["kind"], "word_s": a["word_s"], "shown_s": None if t is None else round(t, 3),
                         "lead_s": None if t is None else round(a["word_s"] - t, 3)})
        late = [r for r in rows if r["shown_s"] is None or not -0.05 <= r["lead_s"] <= 0.15]
        res["on_its_word"] = {"items": len(rows), "not_on_word": late, "max_lead_s": max([r["lead_s"] for r in rows if r["lead_s"] is not None] or [0]),
                              "rows": rows, "ok": not late}
        # 14 · repeats: the files as rendered, and the subjects and graphics the build counted
        from .place import file_problems, repeats
        files = [(s["f0"] / 24, "file:" + str(s.get("asset") or s.get("src") or ""), round(s["f0"] / 24, 1)) for s in edl["shots"]
                 if s["kind"] in ("video", "photo", "ai") and (s.get("asset") or s.get("src"))]
        br = json.load(open(M(p, "build_report.json"))) if M(p, "build_report.json").exists() else {}
        over = [[k, [round(t, 1) for t in ts]] for k, ts in file_problems(files)] + br.get("repeats_over_limit", [])
        res["repeats"] = {"over_limit": over, "dropped_by_guard": br.get("repeat_guard_dropped", []), "ok": not over}
    from .steps_popups import on as popups_on, checks as popups_checks
    if p.montage == "presenter" and popups_on(p):   # اقتصاد احمس's one-shot layout has its own item 15
        res["presenter_type"] = popups_checks(p, edl)
    elif p.montage == "presenter":
        res["presenter_type"] = presenter_checks(p, edl, S)
    if spl or S.music_where != "all":
        res["channel_profile"] = profile_checks(p, edl, plan, spl, S)
    if M(p, "subtitles.json").exists() and (p.profile_montage().get("text") or {}).get("subtitles"):
        res["subtitles"] = subtitle_checks(p)
    from . import news as NEWS
    if NEWS.mode(p):
        rec = NEWS.record(p)
        sc = {x["name"]: x for x in decision(p, "graphics", "scenes", []) or []}
        if NEWS.scenes_file(p).exists():
            sc.update({x["name"]: x for x in json.load(open(NEWS.scenes_file(p)))})
        shots_n = [s["scene"] for s in edl["shots"] if s["kind"] == "gfx" and s["scene"].startswith("news")]
        not_shot = [n for n in shots_n if not sc.get(n, {}).get("news_item")]
        res["news"] = {"shown": sorted(set(shots_n)), "not_a_screenshot": not_shot,
                       "not_shot": {k: f"{v.get('status')}: {v.get('why', '')}" for k, v in rec.items() if v.get("status") != "ok"},
                       "ok": not not_shot}
    from . import general as GEN
    if GEN.rules(p):                                # 19. «عام»: v13's style with less repetition (montage/general.py)
        r, m = GEN.rules(p), GEN.measure(p, edl)
        from .learning import subjects
        sub = subjects(p, edl["total_frames"] / 24)
        bars = sum(1 for x in GEN.restyle(p, decision(p, "graphics", "scenes", []) or []) if any(i.get("type") == "captionbar" for i in x.get("items", [])))
        res["general_style"] = dict(m, subjects=sub, caption_bars=bars,
                                    ok=m["real_share"] + 1e-9 >= r["real_min"] and not m["files_over"]
                                    and all(v <= r["subject_max"] + 1e-9 for v in sub.values()) and (bars > 0 or not GEN.bar_on(p)))
    res["shots"] = shots
    save_json(M(p, "selfcheck.json"), res)
    print(json.dumps({k: v for k, v in res.items() if k != "shots"}, ensure_ascii=False, indent=1)[:4000])



def subtitle_checks(p):
    """item 17: the intro's running subtitles"""
    from .scripttext import not_in_script, vocabulary
    from .steps import M
    sub = json.load(open(M(p, "subtitles.json")))
    cs = sub.get("cues", [])
    if not cs:
        return {"cues": 0, "why": sub.get("why"), "ok": sub.get("why") != "no approved script"}
    until = sub.get("until_s", 0)
    vocab = vocabulary(p)
    late = [c["text"] for c in cs if c["to"] > until + 0.05]
    unsafe = [c["text"] for c in cs if c["x"] < 96 or c["x"] + c["w"] > 1824 or c["y"] + c["h"] > 1026]
    unknown = [w for c in cs for w in not_in_script(c["text"], vocab)] if vocab else []
    return {"cues": len(cs), "until_s": until, "after_the_intro": late, "outside_title_safe": unsafe, "not_in_script": unknown[:20],
            "ok": not late and not unsafe and not unknown}


def profile_checks(p, edl, plan, spl, S):
    """item 16: the channel's own clips on the finished video, and the profile's music rule"""
    from .structure import anchors
    out = {}
    ok = True
    if spl:
        want = edl["total_frames"] + sum(c["frames"] for c in spl["clips"])
        out["clips"] = [{k: c.get(k) for k in ("what", "at", "finished_from_s", "finished_to_s", "frames", "sound_gain_db", "sound_level")}
                        for c in spl["clips"]]
        out["corner_logo"] = "hidden while each clip plays (by construction)"
        ok = ok and spl["finished_frames"] == want
        out["finished_frames"] = {"got": spl["finished_frames"], "expected": want}
    if S.music_where == "cold_open_only":
        ce = anchors(p, edl).get("cold_open_end")
        late = [x for x in plan.get("sections", []) if x.get("music") and ce is not None and x["to"] > ce + 1.6]
        out["music_in_cold_open_only"] = {"cold_open_end_s": ce, "sections_after_it": late, "ok": not late}
        ok = ok and not late
    out["ok"] = ok
    return out


def presenter_checks(p, edl, S=None):
    """item 15: the presenter type's own measures, on the cut list as rendered"""
    from .place import file_problems
    from .steps import M, decision
    from . import steps_presenter as SPR, targets as TG
    from ..core.io import load_json
    ps = load_json(M(p, "presenter_sound.json"))
    tl = ps["timeline_snapped"]
    ie = ps["intro_end_s"]
    sh = edl["shots"]
    L = edl["total_frames"] / 24
    from .structure import Structure
    S = S or Structure()
    fa, fb = S.fast_shot_limits
    intro = [s for s in sh if s["f0"] / 24 < ie - 0.12]
    lens = [(s["f1"] - s["f0"]) / 24 for s in intro]
    intro_ok = (not any(s["kind"] in ("presenter", "black_beat") for s in intro) and all(fa <= x <= fb for x in lens[:-1])
                and all(s.get("transition") for s in intro[1:]) and len(ps["intro_clicks"]) == max(0, len(intro) - 1))
    cold = SPR.cold_open_problems(tl, sh, S, L) if S.cold_open else None
    st = SPR.starts(p)
    broll = [s for s in sh if s["kind"] in ("video", "photo", "ai", "gfx")]
    cuts = [s["f0"] / 24 for s in broll if s["f0"] > 0]
    on_sentence = sum(1 for t in cuts if any(abs(t - (x - 2 / 24)) <= 0.13 for x in st))
    rh = set(tl.get("rehook_scenes", []))
    n_labels = len([n for n in tl.get("overlays", []) if n not in rh and not n.startswith("ov_")])
    types = [SPR.material_of(s) for s in sh]
    from .news import has_news
    R = TG.rules_of(p)
    mix = TG.check(types, None, has_news(p), where="the cut list", R=R)
    V = TG.video_first(p)
    vshare, vprob = TG.video_share(SPR.video_parts(sh), V, "the cut list's B-roll footage") if V else (None, [])
    rep = file_problems([(s["f0"] / 24, "file:" + s["asset"]) for s in sh if s.get("asset")])
    scn = {x["name"]: x for x in decision(p, "graphics", "scenes", [])}
    lab_s = {n: round(scn[n]["t_out"] - scn[n]["t_in"], 2) for n in tl.get("overlays", []) if n not in rh and n in scn and not n.startswith("ov_")}
    from . import gfx_policy as GP
    pol = GP.of(p)
    gfx = None
    if pol:                            # the channel's graphics policy (owner, 22 Oct 2026): the share as rendered
        g_s = GP.share(edl, list(scn.values()), tl)
        held = [s["scene"] for s in sh if s["kind"] == "gfx" and s["scene"] in scn and not s["scene"].startswith("news_")
                and s["nframes"] / 24 > min(scn[s["scene"]]["t_out"] - scn[s["scene"]]["t_in"], pol["scene_s"][1]) + 0.35]
        gfx = {"seconds": round(g_s, 1), "share": round(g_s / L, 3), "max_share": pol["max_share"], "held_past_animation": held,
               "ok": g_s <= pol["max_share"] * L + 0.5 and not held}
    from . import labels as LB
    lbp = LB.of(p)                     # the channel's labels while said (owner, 22 Oct 2026): their own measure
    lab_ok = all(SPR.LABEL_S[0] <= v <= SPR.LABEL_S[1] for v in lab_s.values()) if not lbp else all(v <= 8.0 for v in lab_s.values())
    pres = [s for s in sh if s["kind"] == "presenter"]
    pres_s = sum(s["nframes"] for s in pres) / 24
    sizes = sum(1 for a, b in zip(pres, pres[1:]) if a["f1"] == b["f0"] and a.get("zoom") != b.get("zoom"))
    blocks, prev_b = 0, False
    for s in sh:
        b = s["kind"] in ("video", "photo", "ai", "gfx")
        if b and not prev_b and s["f0"] / 24 >= ie - 0.12:
            blocks += 1
        prev_b = b
    after_min = max(1e-6, (L - ie) / 60)
    return {"intro": {"end_s": ie, "shots": len(intro), "lengths_s": [round(x, 2) for x in lens], "clicks": len(ps["intro_clicks"]), "ok": intro_ok},
            "broll_cuts_on_sentence_starts": f"{on_sentence} of {len(cuts)}",
            "labels": {"count": n_labels, "per_minute": round(n_labels / (L / 60), 2), "range": TG.label_range(L), "seconds": lab_s,
                       "ok": (lbp is not None or not TG.check_labels(n_labels, L)) and lab_ok},
            "material_mix": {"share_of_broll": TG.share(types), "problems": mix, "ok": not mix},
            **({"video_share": {"share": round(vshare, 3), "min": V["video_min"], "problems": vprob, "ok": not vprob}} if V else {}),
            "repeats_over_limit": [[k, [round(t, 1) for t in ts]] for k, ts in rep],
            "presenter": {"share": round(pres_s / L, 3), "size_changes_per_presenter_minute": round(sizes / max(1e-6, pres_s / 60), 1)},
            "broll_blocks_per_minute_after_intro": round(blocks / after_min, 2),
            "transitions": sum(1 for s in sh if s.get("transition")),
            **({"cold_open": {"end_s": tl.get("cold_open_end_s"), "problems": cold, "ok": not cold}} if cold is not None else {}),
            **({"graphics": gfx} if gfx is not None else {}),
            "ok": intro_ok and not mix and not rep and (lbp is not None or not TG.check_labels(n_labels, L)) and lab_ok and not cold
            and (gfx is None or gfx["ok"])}

"""The video's own report: output/<name>_v<N>_report.md, written with the credits after the self-check (both video types).
It opens with "Watch these first": everything a person should look at before publishing (owner's decision 4a of
16 Oct 2026 on Works/output/agent_fixes_report.md: when the finished video misses a mix target, the run continues and
says so here), then the measures.

Measures (the cut list as rendered):
  pictures       shots of footage, photos and drawn images (our graphics and word cards are not pictures)
  moving share   pictures that are video clips (stock footage, archive film) / all pictures (owner, Phase 2: more moving
                 footage instead of stills)
  repeats        pictures whose file was already shown earlier in the video (owner, Phase 2: repeat pictures less)
"""
import json

from ..core.io import load_json, write_text

FPS = 24
PICTURE = ("video", "photo", "ai")


def material(s):
    if s["kind"] in ("presenter", "black_beat", "insert"):
        return None
    if s["kind"] == "gfx":
        return "card" if s["scene"].startswith("card_") else "news" if s["scene"].startswith("news") else "graphic"
    if s["kind"] == "ai":
        return "ai"
    a = s.get("asset", "")
    return "stock" if a.startswith("V:") else "own" if a.startswith("S:own_") else "archive"


def measure(edl):
    sh = edl["shots"]
    pics = [s for s in sh if s["kind"] in PICTURE]
    seen, rep, files = {}, [], {}
    for s in pics:
        a = s.get("asset")
        t = round(s["f0"] / FPS, 1)
        files.setdefault(a, []).append(t)
        if a in seen:
            rep.append({"file": a, "at_s": t, "first_at_s": seen[a]})
        else:
            seen[a] = t
    moving = [s for s in pics if s["kind"] == "video"]
    types = [material(s) for s in sh]
    counted = [t for t in types if t is not None]
    share = {t: round(counted.count(t) / max(1, len(counted)), 3) for t in ("stock", "archive", "own", "ai", "graphic", "news", "card")}
    return {"shots": len(sh), "pictures": len(pics), "moving_clips": len(moving),
            "moving_share_of_pictures": round(len(moving) / max(1, len(pics)), 3),
            "stills": {"photos": sum(1 for s in pics if s["kind"] == "photo"), "drawn": sum(1 for s in pics if s["kind"] == "ai")},
            "repeats": len(rep), "different_pictures": len(seen), "repeated_files": {k: v for k, v in files.items() if len(v) > 1},
            "repeat_list": rep, "mix_as_rendered": share, "cards": types.count("card")}


def write(p, out_path):
    """the report; returns its "watch these first" lines"""
    from .steps import M, decision
    from . import targets as TG
    edl = load_json(M(p, "edl.json"))
    sc = load_json(M(p, "selfcheck.json")) if M(p, "selfcheck.json").exists() else {}
    m = measure(edl)
    watch = []
    for k, v in sc.items():
        if isinstance(v, dict) and v.get("ok") is False:
            watch.append(f"self-check «{k}» did not pass: {json.dumps({x: y for x, y in v.items() if x not in ('rows', 'ok')}, ensure_ascii=False)[:400]}")
    for k in ("empty_shots", "frozen_shots", "text_outside_safe"):
        if sc.get(k):
            watch.append(f"self-check {k}: {json.dumps(sc[k], ensure_ascii=False)[:300]}")
    # the material mix on the finished video (the plan met it; a picture not found can make the video miss it): decision 4a
    types = [material(s) for s in edl["shots"]]
    from .news import has_news as _has_news
    has_news = _has_news(p)     # channel profiles: only the news with a screenshot (montage/news.py)
    from .steps_popups import on as popups_on
    R = TG.rules_of(p)
    miss = [] if popups_on(p) else TG.check([None if t == "card" else t for t in types], None, has_news, where="the finished video", R=R)
    for x in miss:
        watch.append(f"material mix missed on the finished video (the run went on, decision 4a): {x}")
    if TG.video_first(p) and not popups_on(p):     # the channel's video rule (owner's decision of 20 Oct 2026), on the finished video
        from .steps_presenter import video_parts
        for x in TG.video_share(video_parts(edl["shots"]), R, "the finished video's footage")[1]:
            watch.append(f"video rule missed (the run went on): {x}")
    if m["cards"]:
        watch.append(f"{m['cards']} plain word card(s) where no picture could be found: "
                     + ", ".join(f"{s['f0'] / FPS:.1f} s" for s in edl["shots"] if s["kind"] == "gfx" and s["scene"].startswith("card_")))
    rp = M(p, "replan.json")
    if rp.exists():
        r = load_json(rp)
        for k, v in r.get("shots", {}).items():
            watch.append(f"shot {k} was planned again (no picture fitted its first plan): {v.get('result', '')}")
    if m["repeated_files"]:
        watch.append("pictures shown more than once: " + "; ".join(f"{k} at {', '.join(f'{t:.1f}' for t in v)} s" for k, v in m["repeated_files"].items()))
    from . import screen_text as ST               # owner's answer 5a of 19 Oct 2026: words on screen spelled by the transcript
    tx = ST.from_transcript(p, edl)
    if tx:
        watch.append(f"{len(tx)} on-screen text(s) take their words from the transcription (no approved script): read their spelling — "
                     + "; ".join(f"{int(x['t'] // 60)}:{int(x['t'] % 60):02d} «{x['text']}»" for x in tx))
    for n, lines in ST.outside_band(p).items():   # answer 4a: text the renderer could not fit inside its card
        watch.append(f"text outside its card in {n}: " + "; ".join(lines))
    br = load_json(M(p, "build_report.json")) if M(p, "build_report.json").exists() else {}
    for x in br.get("repeat_guard_dropped", []):
        watch.append(f"repeat guard: {x}")
    L = [f"# Report: «{p.name}»", "", f"Type: {p.type_name} · montage: {p.montage} · {edl['total_frames'] / FPS:.1f} s · {m['shots']} shots", "",
         "## Watch these first", ""]
    from . import voice_check as VC
    if p.mode == "voice_only" and VC.asr(p):        # owner's answer 3: the mp3's likely retakes, for the owner to fix
        d = VC.asr(p)
        rt = VC.retakes(d["words"], d.get("segments", []))
        if rt:
            watch.append(f"{len(rt)} possible narrator retake(s) in the mp3, at " + ", ".join(VC.mmss(r["again_s"]) for r in rt[:10])
                         + " (see «The narration»; the voice is never cut)")
    L += [f"- {w}" for w in watch] or ["- nothing: every self-check passed, the material mix holds on the finished video, no word cards."]
    L += ["", "## Measures", "",
          f"- pictures: {m['pictures']} ({m['different_pictures']} different); repeats: {m['repeats']}",
          f"- moving clips: {m['moving_clips']} of {m['pictures']} pictures ({m['moving_share_of_pictures']:.0%}); stills: "
          f"{m['stills']['photos']} photos, {m['stills']['drawn']} drawn",
          "- material as rendered: " + ", ".join(f"{k} {v:.0%}" for k, v in m["mix_as_rendered"].items() if v)]
    if getattr(p, "profile", None):    # owner, 22 Oct 2026: the screen time by kind (the channel's graphics policy counts time)
        tot = max(1, edl["total_frames"])
        by = {}
        for s in edl["shots"]:
            k = "graphics" if s["kind"] == "gfx" and not s.get("scene", "").startswith("news_") else \
                "presenter" if s["kind"] in ("presenter", "black_beat") else "footage"
            by[k] = by.get(k, 0) + s["f1"] - s["f0"]
        L.append("- screen time: " + ", ".join(f"{k} {by.get(k, 0) / tot:.0%}" for k in ("footage", "presenter", "graphics"))
                 + " (full-frame graphics; labels and data over footage count as footage)")
    L += profile_lines(p, M)
    L += VC.report_lines(p)
    write_text(out_path, "\n".join(L) + "\n")
    try:                                          # the Result screen's data, kept beside the report (montage/result.py)
        from ..core.io import save_json
        from .result import data
        save_json(out_path.with_suffix(".json"), data(p))
    except Exception as e:  # noqa: BLE001  (the report itself is written; the panel computes the data when it is missing)
        print(f"report: the Result screen's data was not kept ({type(e).__name__}: {e})")
    return watch


def profile_lines(p, M):
    """what the channel profile changed in this video, and the values that are placeholders (owner's answer 5 of 18 Oct
    2026: where the channel gave no value, the engine's own is used and marked here)"""
    from .structure import of
    if not p.profile:
        return []
    S = of(p)
    prof = p.channel_profile()
    L = ["", "## The channel profile", "", f"- profile: {p.profile} «{prof.get('name', '')}»"]
    if S.fast_open is None:
        L.append("- no fast intro (the channel's slow pace)" + (f"; footage shots {S.footage_shot[0]:g}-{S.footage_shot[1]:g} s" if S.footage_shot else "")
                 + ("; a slow push-in or pull-out on every footage shot" if S.slow_zoom else ""))
    elif not S.is_default_intro:
        L.append(f"- fast intro of {S.fast_open[0]:g}-{S.fast_open[1]:g} s, shots of {S.fast_shot[0]:g}-{S.fast_shot[1]:g} s")
    if S.cold_open and p.montage == "phrases":      # audio only (3A): the cold open is montage, its end found in code
        ce = (load_json(M(p, "build_report.json")) if M(p, "build_report.json").exists() else {}).get("cold_open_end_s")
        L.append(f"- cold open of about {S.cold_open[0] / 60:g}-{S.cold_open[1] / 60:g} min, montage only (no presenter)"
                 + (f", ending at {ce:.1f} s of the narration" if ce is not None else "") + "; then the body" + (" (calm)" if S.calm_body else ""))
    elif S.cold_open:
        L.append(f"- cold open of about {S.cold_open[0] / 60:g}-{S.cold_open[1] / 60:g} min with the presenter about {S.presenter_for:g} s near "
                 f"{S.presenter_near:.0f} s and his teaser at its end; then the body" + (" (calm)" if S.calm_body else ""))
    if S.bw_open and p.montage == "phrases":         # اقتصاد احمس audio only (6A)
        be = (load_json(M(p, "build_report.json")) if M(p, "build_report.json").exists() else {}).get("bw_open_end_s")
        L.append(f"- black-and-white open of {S.bw_open[0]:g}-{S.bw_open[1]:g} s" + (f", ending at {be:.1f} s" if be is not None else "")
                 + ", then the logo sting" + ("; photos framed with the striped reveal" if S.photos_framed else "")
                 + ("; one-country maps as the channel's country map" if S.popup_maps else ""))
    if S.music_where == "cold_open_only":
        L.append("- music in the cold open only")
    if M(p, "splices.json").exists():
        for c in load_json(M(p, "splices.json"))["clips"]:
            L.append(f"- the channel's clip «{c['what']}» at {c['finished_from_s']:.1f}-{c['finished_to_s']:.1f} s of the finished video "
                     "(corner logo hidden while it plays)")
    if M(p, "subtitles.json").exists() and (p.profile_montage().get("text") or {}).get("subtitles"):
        sub = load_json(M(p, "subtitles.json"))
        L.append(f"- running subtitles in the intro: {len(sub.get('cues', []))} cue(s), spelled from the approved script"
                 if sub.get("cues") else f"- running subtitles in the intro: none ({sub.get('why', '')})")
    from . import news as NEWS
    if NEWS.mode(p) and NEWS.record(p):
        rec = NEWS.record(p)
        ok = [k for k, v in rec.items() if v.get("status") == "ok"]
        L.append(f"- documented news as screenshots of their public pages: {len(ok)} of {len(rec)} shot")
        for k, v in rec.items():
            if v.get("status") != "ok":
                L.append(f"  - {k} not shown as news ({v.get('status')}): {v.get('why', '')}")
    if M(p, "popups.json").exists():
        pp = load_json(M(p, "popups.json"))
        L.append(f"- one continuous presenter shot, no punch-ins; {len(pp['placed'])} pop-ups beside him ({pp['home_side']} side, never over his face)")
        for x in pp.get("left_out", []):
            L.append(f"  - pop-up «{x['said']}» left out: {x['why']}")
    if S.text_sfx == "paper":
        L.append("- a paper sound (made in code) when on-screen text appears, in place of the pop")
    from . import general as GEN, learning
    if GEN.bar_on(p):
        L.append("- labels and re-hooks in the channel's caption bar (v13: green box, a grey second line, typed in)")
    r = GEN.rules(p)
    if r and M(p, "edl.json").exists():          # «عام»: v13's style measured on the cut list as rendered
        m = GEN.measure(p, load_json(M(p, "edl.json")))
        L.append(f"- real pictures {m['real_share'] * 100:.0f} % of the B-roll time (at least {r['real_min'] * 100:.0f} %): "
                 f"graphics {m['graphic_share'] * 100:.0f} %, drawn images {m['ai_share'] * 100:.0f} %"
                 + ("" if m["real_share"] + 1e-9 >= r["real_min"] else " — UNDER the channel's share"))
        sub = learning.subjects(p, load_json(M(p, "edl.json"))["total_frames"] / 24)
        if sub:
            L.append("- biggest subjects: " + ", ".join(f"«{k}» {v * 100:.0f} %" for k, v in sub.items())
                     + f" (none over {r['subject_max'] * 100:.0f} % of the running time)")
        if m["files_over"]:
            L.append("- files shown more than twice or within 60 s: " + "; ".join(f"{k} at {v}" for k, v in m["files_over"].items()))
    lr = learning.report_lines(p)
    if lr:
        L += [""] + ["#" + x if x.startswith("## ") else x for x in lr]
    ph = ["music level under the voice: the engine's value (" + ("the brain's sound plan" if p.montage == "presenter" else "-11.6 dB")
          + ")", "sound effects' levels: the engine's values (montage/mix.py)"]
    if M(p, "splices.json").exists():
        ph.append("the channel clips' sound: set to the narration mix's loudness, true peak under -1.5 dBTP")
    L += ["", "### Placeholder values (the channel has not given these yet)", ""] + [f"- {x}" for x in ph]
    return L

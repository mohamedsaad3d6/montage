"""The Result screen's data (web panel plan 1.6, phase 4), made from a finished project's own files, so older projects
show too without running anything again; report.write also keeps it as output/<video>_report.json.

  data(p) -> {ready, videos, video, report, credits, duration_s, stats, mix, watch, decisions, checklist, sections, approved}
    stats      length, shots, pictures (moving), music cues, sound effects; script words lost (cut report, when known)
    mix        the share of each material type over the B-roll shots as rendered, with the design's names (owner's
               decision 7a: stock -> تكميلي, drawn -> قصة مرسومة, our graphics -> خريطة / أرقام / جرافيك by what they
               draw, archive -> أرشيف, news -> خبر موثّق), and the shot strip (each shot's time and type)
    watch      «اتفرّج على دول الأول» with timecodes: look (a picture) or listen (the sound): word cards, frozen or dark
               shots, text outside the frame, repeated pictures, on-screen words late on their word, likely narrator
               retakes, long silences, and every self-check that did not pass (no time when it has none)
    decisions  «قرارات اتاخدت لوحدها» that have real other options on record: each shot's picture (the candidates it
               did not choose, and its why), each drawn image's variant, and step-by-step questions (their options)
    checklist  the credit lines for the description, the YouTube «altered or synthetic content» box (drawn images or
               generated music), the end screen as the profile sets it, and the final approval
    sections   today's report sections: the channel profile and its placeholder values, documented news shown / not
               shown, the narration's likely retakes and silences covered, what «عام» learned and applied
  approve(p, video, by) -> output/approved.json (the owner's final approval of one version)
"""
import re
import time
from pathlib import Path

from ..core.io import load_json, save_json

FPS = 24
DESIGN = {"stock": ("تكميلي", "Stock"), "archive": ("أرشيف", "Archive"), "news": ("خبر موثّق", "Documented news"),
          "ai": ("قصة مرسومة", "Drawn"), "map": ("خريطة", "Map"), "numbers": ("أرقام", "Numbers"), "graphic": ("جرافيك", "Graphic"),
          "own": ("كليباتك", "Your clips"), "card": ("كارت كلام", "Word card")}


def M(p, *a):
    return p.work.joinpath("montage", *a)


def videos(p):
    """the finished videos, newest version last (the cut's own files when the output is the cut only)"""
    cut_only = p.opt("output", "montage") == "cut"
    out = []
    for f in sorted(p.output.glob("*.mp4")) if p.output.exists() else []:
        m = re.search(r"_v(\d+)\.mp4$", f.name)
        if not m or "preview" in f.name or (f.name.startswith("cut_v") != cut_only):
            continue
        st = f.stat()
        out.append({"name": f.name, "version": int(m.group(1)), "bytes": st.st_size,
                    "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))})
    return sorted(out, key=lambda v: v["version"])


def scene_kinds(p):
    """our graphics by what they draw: a map, numbers, or another graphic"""
    from .general import restyle
    f = p.decisions / "graphics" / "scenes.json"
    out = {}
    for sc in (restyle(p, load_json(f)["decision"]) if f.exists() else []):
        types = {i.get("type") for i in sc.get("items", [])}
        out[sc["name"]] = "map" if types & {"map", "pin", "route"} else "numbers" if types & {"counter", "bar", "wave"} else "graphic"
    return out


def material(s, kinds):
    from .report import material as base
    t = base(s)
    if t == "graphic":
        return kinds.get(s.get("scene"), "graphic")
    return t


def mix(p, edl):
    kinds = scene_kinds(p)
    strip, n = [], {}
    for s in edl["shots"]:
        t = material(s, kinds) if s["kind"] != "presenter" else "presenter"
        if t is None:
            t = "presenter"
        strip.append({"t0": round(s["f0"] / FPS, 2), "t1": round(s["f1"] / FPS, 2), "type": t})
        if t != "presenter":
            n[t] = n.get(t, 0) + (s["f1"] - s["f0"])
    tot = max(1, sum(n.values()))
    share = [{"type": k, "ar": DESIGN[k][0], "en": DESIGN[k][1], "share": round(v / tot, 3)} for k, v in sorted(n.items(), key=lambda kv: -kv[1])]
    return {"share": share, "strip": strip, "presenter_share": round(sum(x["t1"] - x["t0"] for x in strip if x["type"] == "presenter")
                                                                     / max(1e-6, edl["total_frames"] / FPS), 3)}


def watch(p, edl, sc):
    """«اتفرّج على دول الأول»: [{t, kind look|listen, ar, en}] in time order (no time last)"""
    from .report import measure
    out = []
    for s in edl["shots"]:
        if s["kind"] == "gfx" and str(s.get("scene", "")).startswith("card_"):
            out.append({"t": s["f0"] / FPS, "kind": "look", "ar": "كارت كلام: مالقيناش صورة للجملة دي", "en": "A word card: no picture was found for this phrase"})
    for k, ar, en in (("frozen_shots", "لقطة شكلها واقفة", "A shot that looks frozen"), ("empty_shots", "لقطة غامقة أو فاضية", "A dark or empty shot")):
        for x in sc.get(k) or []:
            out.append({"t": x.get("t"), "kind": "look", "ar": f"{ar} ({x.get('what', '')})", "en": f"{en} ({x.get('what', '')})"})
    for x in sc.get("text_outside_safe") or []:
        out.append({"t": None, "kind": "look", "ar": f"كلام قريب من حافة الكادر ({x.get('graphic')})", "en": f"Text near the frame's edge ({x.get('graphic')})"})
    from . import screen_text as ST               # owner's answers 5a and 4a of 19 Oct 2026
    for x in ST.from_transcript(p, edl):
        out.append({"t": x["t"], "kind": "look", "ar": f"كلام على الشاشة من التفريغ (مفيش سكريبت معتمد): «{x['text']}» — راجع الإملاء",
                    "en": f"On-screen words from the transcription (no approved script): «{x['text']}» — check the spelling"})
    for n, lines in ST.outside_band(p).items():
        out.append({"t": None, "kind": "look", "ar": f"كلام خارج حدود الكارت ({n})", "en": f"Text outside its card ({n})"})
    for f, ts in measure(edl)["repeated_files"].items():
        for t in ts[1:]:
            out.append({"t": t, "kind": "look", "ar": f"صورة متكررة ({f}، أول مرة {ts[0]:.0f} ث)", "en": f"A repeated picture ({f}, first at {ts[0]:.0f} s)"})
    for r in ((sc.get("on_its_word") or {}).get("not_on_word") or []):
        out.append({"t": r.get("word_s"), "kind": "look", "ar": f"«{r.get('text')}» مش على كلمتها", "en": f"«{r.get('text')}» is not on its word"})
    from . import voice_check as VC
    d = VC.asr(p) if p.mode == "voice_only" else None
    if d:
        for r in VC.retakes(d["words"], d.get("segments", [])):
            out.append({"t": r["again_s"], "kind": "listen", "ar": f"إعادة محتملة من المذيع: «{r['again']}»", "en": f"A likely narrator retake: «{r['again']}»"})
        for a, b in VC.silences(d["words"]):
            out.append({"t": a, "kind": "listen", "ar": f"سكوت {b - a:.0f} ثانية في الصوت", "en": f"{b - a:.0f} s of silence in the narration"})
    named = {"frozen_shots", "empty_shots", "text_outside_safe", "shots", "on_its_word"}
    for k, v in sc.items():
        if k not in named and isinstance(v, dict) and v.get("ok") is False:
            out.append({"t": None, "kind": "listen" if k in ("voice", "level", "music", "sfx") else "look",
                        "ar": f"المراجعة الذاتية «{k}» مانجحتش", "en": f"The self-check «{k}» did not pass"})
    if (sc.get("on_its_word") or {}).get("ok") is False and not (sc["on_its_word"].get("not_on_word")):
        out.append({"t": None, "kind": "look", "ar": "المراجعة الذاتية «on_its_word» مانجحتش", "en": "The self-check «on_its_word» did not pass"})
    for x in out:
        x["t"] = None if x["t"] is None else round(float(x["t"]), 2)
    return sorted(out, key=lambda x: (x["t"] is None, x["t"] or 0))


def decisions(p):
    """«قرارات اتاخدت لوحدها» with their other options, as the decision records keep them"""
    out = []
    cand = load_json(M(p, "candidates.json")).get("by_shot", {}) if M(p, "candidates.json").exists() else {}
    span = None
    try:
        from .phrases import Plan
        from .steps import decision, words
        d = decision(p, "montage", "shots")
        if d:
            P = Plan(d, words(p), load_json(M(p, "edl.json"))["total_frames"] / FPS)
            span = P.span
    except Exception:  # noqa: BLE001  (no times without the plan and its words: the decisions still show)
        span = None
    for f in sorted(p.decisions.glob("sources/assets_*.json")):
        if ".replaced_" in f.name:
            continue
        for x in load_json(f)["decision"].get("picks", []):
            cs = cand.get(str(x["shot"])) or []
            if not cs:
                continue
            n = x.get("n") or 0
            chosen = cs[n - 1]["about"][:120] if 0 < n <= len(cs) else "لا شيء (كارت كلام) / none (a word card)"
            others = [c["about"][:80] for i, c in enumerate(cs, 1) if i != n][:4]
            out.append({"t": round(span(x["shot"])[0], 2) if span else None, "kind": "picture", "what": f"shot {x['shot']}", "shot": x["shot"],
                        "chosen": chosen, "why": x.get("why", ""), "others": others, "of": len(cs), "ref": f"sources/{f.stem}",
                        "other_n": [i for i in range(1, len(cs) + 1) if i != n][:4]})
    ai = p.decisions / "ai" / "pick.json"
    if ai.exists():
        d = load_json(ai)["decision"]
        for k, v in (d.items() if isinstance(d, dict) else []):
            if isinstance(v, dict) and "seed" in v:
                out.append({"t": None, "kind": "ai_image", "what": k, "chosen": f"variant (seed {v['seed']})", "why": v.get("why", ""),
                            "others": ["the other drawn variants of the same prompt"], "of": None})
    for step, key, label in (("montage", "plan", "plan"), ("montage", "shots", "plan"), ("montage", "timeline", "timeline")):
        f = p.decisions / step / f"{key}.json"
        if f.exists():                      # owner's answer 1 of phase 4: the brain's own alternatives (channel profiles)
            for x in (load_json(f)["decision"] or {}).get("alternatives", []) if isinstance(load_json(f)["decision"], dict) else []:
                out.append({"t": x.get("at_s"), "kind": label, "what": x.get("what", ""), "chosen": x.get("chosen", ""), "why": x.get("why", ""),
                            "others": list(x.get("rejected", []))[:3], "of": None, "ref": f"{step}/{key}"})
    f = p.decisions / "music" / "cues.json"
    if f.exists() and isinstance(load_json(f)["decision"], list):
        for c in load_json(f)["decision"]:
            if c.get("rejected"):
                out.append({"t": None, "kind": "music", "what": c.get("name", ""), "chosen": c.get("prompt", "")[:120], "why": c.get("why", ""),
                            "others": list(c["rejected"])[:3], "of": None, "ref": "music/cues"})
    from .questions import questions, answers
    q, a = questions(p), answers(p)
    if q and (not a or a.get("mode") == "let_it_decide"):
        for x in q["questions"]:
            pick = next((o["label"] for o in x["options"] if o["key"] == x["pick"]), x["pick"])
            out.append({"t": None, "kind": "question", "what": x["question"], "chosen": pick, "why": x.get("why", ""),
                        "others": [o["label"] for o in x["options"] if o["key"] != x["pick"]], "of": len(x["options"])})
    return out


def credit_lines(p):
    f = p.output / "credits.md"
    if not f.exists():
        return None
    lines, on = [], False
    for ln in f.read_text(encoding="utf-8").splitlines():
        if ln.startswith("## "):
            on = "description" in ln.lower()
            continue
        if on and ln.startswith("- "):
            lines.append(ln[2:].strip())
    return lines


def checklist(p, edl, sc):
    ai_imgs = sum(1 for s in edl["shots"] if s["kind"] == "ai")
    cues = (sc.get("music") or {}).get("cues") or {}
    gen = [k for k, v in cues.items() if isinstance(v, dict) and v.get("generator") == "ace-step"]
    if not cues and (p.asset_dir("music")).exists():
        gen = [f.stem for f in p.asset_dir("music").glob("*.json") if not f.stem.endswith("_takes")]
    why = ([f"{ai_imgs} drawn image shot(s)"] if ai_imgs else []) + ([f"{len(gen)} music cue(s) generated (ACE-Step)"] if gen else [])
    prof = p.channel_profile() if p.profile else {}
    es = prof.get("end_screen")
    return {"credit_lines": credit_lines(p), "altered_or_synthetic": {"tick": bool(why), "why": why},
            "end_screen": {"set": bool(es), "seconds": (es or {}).get("seconds"), "video_slots": (es or {}).get("video_slots"),
                           "subscribe": (es or {}).get("subscribe"), "drawn_by_montage": False}}


def sections(p):
    """today's report sections as {title, lines}: read from the report's own writers, so the screen and the .md agree"""
    from .report import profile_lines
    from . import voice_check as VC
    md = profile_lines(p, M) + VC.report_lines(p)
    out, cur = [], None
    for ln in md:
        if ln.startswith("#"):
            cur = {"title": ln.lstrip("#").strip(), "lines": []}
            out.append(cur)
        elif ln.strip() and cur is not None:
            cur["lines"].append(ln.strip()[2:] if ln.strip().startswith("- ") else ln.strip())
    return [s for s in out if s["lines"]]


def stats(p, edl, m):
    mp = load_json(M(p, "mix_plan.json")) if M(p, "mix_plan.json").exists() else {}
    cues = len([f for f in p.asset_dir("music").glob("*.wav")]) if p.asset_dir("music").exists() else None
    return {"length_s": round(edl["total_frames"] / FPS, 1), "shots": m["shots"], "pictures": m["pictures"], "moving": m["moving_clips"],
            "music_cues": cues, "sfx": len(mp.get("sfx", [])) if mp else None,
            "words_lost": load_json(p.work / "cut_lost.json")["script_words_lost"] if (p.work / "cut_lost.json").exists() else None}


def data(p):
    from .report import measure
    vs = videos(p)
    if not vs or not M(p, "edl.json").exists():
        return {"ready": False, "videos": vs}
    edl = load_json(M(p, "edl.json"))
    sc = load_json(M(p, "selfcheck.json")) if M(p, "selfcheck.json").exists() else {}
    v = vs[-1]
    rep = p.output / (Path(v["name"]).stem + "_report.md")
    ap = p.output / "approved.json"
    return {"ready": True, "videos": vs, "video": v["name"], "report": rep.name if rep.exists() else None,
            "credits": "credits.md" if (p.output / "credits.md").exists() else None, "duration_s": round(edl["total_frames"] / FPS, 2),
            "stats": stats(p, edl, measure(edl)), "mix": mix(p, edl), "watch": watch(p, edl, sc), "decisions": decisions(p),
            "checklist": checklist(p, edl, sc), "sections": sections(p), "approved": load_json(ap) if ap.exists() else None,
            "selfcheck_ran": bool(sc), "edits": edit_rounds(p), "kept": kept_versions(p), "running": _running(p),
            "version_now": int(p.opt("version", 1))}


def _running(p):
    from ..core.runctl import lock_pid
    return bool(lock_pid(p.folder))


def kept_versions(p):
    d = p.output / "versions"
    return [load_json(f) for f in sorted(d.glob("v*/meta.json"))] if d.exists() else []


def edit_rounds(p):
    """the edit rounds, with the steps to redo named as the panel's 9 steps"""
    from ..core.summary import GROUPS
    from .edits import history
    out = []
    for r in history(p):
        r = dict(r)
        rd = r.get("redo") or {}
        if rd.get("steps"):
            r["redo_groups"] = [{"n": n, "ar": ar, "en": en} for n, (k, ar, en, names) in enumerate(GROUPS, 1) if set(names) & set(rd["steps"])]
        out.append(r)
    return out


def approve(p, video, by):
    """the owner's final approval of one finished version -> output/approved.json (a later edit starts from it)"""
    names = {v["name"]: v for v in videos(p)}
    if video not in names:
        raise ValueError("approve a finished video of this episode")
    if not (by or "").strip():
        raise ValueError("an approval carries the person's name")
    rec = {"video": video, "version": names[video]["version"], "by": by.strip(), "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    save_json(p.output / "approved.json", rec)
    return rec


__all__ = ["data", "approve", "videos"]

"""Phase 1 auto-edit: one command, every stage cached in work/.

    (the cut step of `bin/monteer run`; see monteer/steps.py)
"""
import sys
from collections import Counter

import numpy as np

from . import accuracy
from . import compare
from . import gaps
from . import script_text
from . import sync
from .align import select_takes
from .asr import transcribe
from .common import CHANNEL, EDIT_VIDEO, KEEP_OUTRO, OUT, REF_VIDEO, SR, WORK, ffprobe_duration, load_json, normalize_ar, run, save_json, tc
from .edl import build_edl, map_to_output, merge, snap_frames, subtract
from .render import render
from .silence import breath_gaps, detect_silences, frame_db, speech_seconds

MODEL = "large-v3"
PRIORITY = ["retake", "off-script", "non-speech gap", "no external audio", "breath", "silence", "no speech"]


def to_cam(words, segments):
    out = []
    for w in words:
        s, e = sync.ext_to_cam(w["s"], segments), sync.ext_to_cam(w["e"], segments)
        if s is not None and e is not None:
            out.append(dict(w, s=s, e=e))
    for i, w in enumerate(out):
        w["i"] = i
    return out


SHORT_PIECE = 0.5      # s: a kept piece shorter than this between two cuts sounds chopped (owner's fix 6)
QUIET_DB = -40.0       # a frame this quiet may be added around a short piece


def short_pieces(keep, ctc, db, fr=0.01):
    """the last pass on the keep list (a channel episode): a piece under SHORT_PIECE between two cuts is
      dropped when it holds no whole word of the literal model, or its words are said again in the next 4 s of the cut
      (a fragment of a retake); otherwise it grows into the quiet frames next to it, up to SHORT_PIECE, or stays as it is
    -> (keep, log lines)"""
    out, log = [list(k) for k in keep], []
    i = 0
    while i < len(out):
        s, e = out[i]
        if e - s >= SHORT_PIECE or i == 0 or i == len(out) - 1:
            i += 1
            continue
        whole = [w for w in ctc if w["s"] >= s - 0.02 and w["e"] <= e + 0.02]
        later = " ".join(normalize_ar(w["w"]) for w in ctc if any(a <= w["s"] < b for a, b in out[i + 1:i + 6]) and w["s"] < e + 30)
        later_words = later.split()[:12]
        mine = [normalize_ar(w["w"]) for w in whole]
        stammer = mine and all(len(m) <= 2 for m in mine) and any(x.startswith(mine[0]) for x in later_words[:2])  # «و» … «وفي ويلز»
        if not whole or stammer or (mine and all(any(m == x or (len(m) > 2 and m in x) for x in later_words) for m in mine)):
            log.append(f"dropped {s:.2f}-{e:.2f} (" + ("no whole word" if not whole else "a stammer before «" + later_words[0] + "»"
                                                     if stammer else "said again right after: " + " ".join(mine)) + ")")
            del out[i]
            continue
        need = SHORT_PIECE - (e - s)
        lo, hi = out[i - 1][1], out[i + 1][0]
        s2, e2 = s, e
        while need > 1e-6 and (s2 - fr > lo + 0.02 or e2 + fr < hi - 0.02):
            grew = False
            if e2 + fr < hi - 0.02 and db[min(len(db) - 1, int((e2) / fr))] < QUIET_DB:
                e2 += fr; need -= fr; grew = True
            if need > 1e-6 and s2 - fr > lo + 0.02 and db[max(0, int((s2 - fr) / fr))] < QUIET_DB:
                s2 -= fr; need -= fr; grew = True
            if not grew:
                break
        out[i] = [round(s2, 3), round(e2, 3)]
        log.append(f"grown {s:.2f}-{e:.2f} -> {s2:.2f}-{e2:.2f}" + ("" if e2 - s2 >= SHORT_PIECE - 1e-6 else " (no more quiet room: kept as it is)"))
        i += 1
    return snap_frames(out), log


def cut_reasons(keep, removed):
    """One reason per jump cut (gap between consecutive kept segments)."""
    cuts = []
    gaps = list(zip(keep, keep[1:]))
    for (a0, a1), (b0, b1) in gaps:
        inside = [r for r in removed if r[0] < b0 and r[1] > a1]
        reasons = sorted({r[2] for r in inside}, key=lambda x: PRIORITY.index(x) if x in PRIORITY else 99)
        reason = reasons[0] if reasons else "silence"
        detail = next((r[3] for r in inside if r[2] == reason and r[3]), "")
        cuts.append({"src_from": a1, "src_to": b0, "removed_s": b0 - a1, "reason": reason, "text": detail})
    return cuts


def unsure_list(words, sel, script, flagged):
    d = sel["decisions"]
    out = []

    def add(i0, i1, why, kept):
        out.append({"src": words[i0]["s"], "src_end": words[i1]["e"], "kept": kept, "why": why,
                    "text": " ".join(w["w"] for w in words[i0:i1 + 1])})

    # stretches of consecutive words sharing keep/type, for ad-lib and off-script checks
    i = 0
    while i < len(d):
        j = i
        while j + 1 < len(d) and d[j + 1]["keep"] == d[i]["keep"] and d[j + 1]["type"] == d[i]["type"]:
            j += 1
        n = j - i + 1
        if d[i]["type"] == "insert" and d[i]["keep"] and n >= 5 and not d[i].get("outro"):
            add(i, j, f"kept {n} words that are not in the script (ad-lib?)", True)
        if d[i]["type"] == "insert" and not d[i]["keep"] and n >= 6:
            add(i, j, f"cut {n} off-script words between takes; could be a deliberate ad-lib", False)
        i = j + 1
    # retakes where the discarded take matched the script better than the kept one, scored on
    # the same script words (the kept take may have won on switch cost or order)
    kept_score = {x["j"]: x["score"] for x in d if x["keep"] and x["j"] >= 0}
    for r in sel["runs"]:
        idx = [k for k in r["words"] if not d[k]["keep"] and d[k]["reason"].startswith("retake: ")
               and "take " in d[k]["reason"]]
        by_owner = {}
        for k in idx:
            by_owner.setdefault(d[k]["reason"].split("take ")[-1], []).append(k)
        for grp in by_owner.values():
            if len(grp) < 4:
                continue
            cut_s = float(np.mean([d[k]["score"] for k in grp]))
            kept_s = float(np.mean([kept_score.get(d[k]["j"], -0.5) for k in grp]))  # -0.5: not said
            if cut_s > kept_s + 0.15:
                add(grp[0], grp[-1], f"cut take matched the script better ({cut_s:.2f}) than the "
                                     f"kept take ({kept_s:.2f})", False)
    outro = [x["i"] for x in d if x.get("outro")]
    if outro:
        add(outro[0], min(outro[0] + 12, outro[-1]), "start of the kept channel outro (not in the script): "
            "check nothing before it is crew talk", True)
    # kept takes that match the script poorly
    for r in sel["runs"]:
        kept = [k for k in r["matched"] if d[k]["keep"]]
        if len(kept) >= 4 and r["score"] < 0.35:
            add(kept[0], kept[-1], f"kept take matches the script weakly (score {r['score']:.2f}): "
                                   "heavy ad-lib or ASR trouble", True)
    for v in flagged:
        out.append({"src": v["src"], "src_end": v["src_end"], "kept": v["verdict"] == "keep", "text": v["text"],
                    "why": f"speech-level gap the first ASR pass skipped; re-transcribed -> {v['why']}"})
    # script sentences missing from the edit
    cov = set(sel["covered_script_words"])
    sent_words = Counter(script["sent_of_word"])
    sent_cov = Counter(script["sent_of_word"][j] for j in cov)
    missing = [s for s in range(len(script["sentences"])) if sent_cov[s] < 0.5 * sent_words[s]]
    return sorted(out, key=lambda x: x["src"]), missing


def main(args=None):
    args = set(sys.argv[1:] if args is None else args)
    OUT.mkdir(exist_ok=True)
    script = script_text.build()
    info = sync.build()
    segs = info["segments"]
    cam_dur = info["cam_dur"]

    asr = transcribe(sync.EXT16, "ext", MODEL)
    words = to_cam(asr["words"], segs)
    print(f"{len(words)} transcript words on the camera timeline")

    db = frame_db()
    sel = select_takes(words, script, speech=speech_seconds(db), keep_outro=KEEP_OUTRO)
    dec = sel["decisions"]
    print("decisions:", Counter((x["type"], x["keep"]) for x in dec))

    silences = detect_silences()
    kept_words = [words[x["i"]] for x in dec if x["keep"]]
    breaths = breath_gaps(db, kept_words)
    keep_idx = [x["i"] for x in dec if x["keep"]]
    keep, removed, flagged = build_edl(words, dec, silences, breaths, db, info["cam_covered"], cam_dur,
                                       judge=lambda g: gaps.judge_all(g, words, keep_idx))
    keep_base = None
    fades = []
    if CHANNEL:                        # owner's decisions of 22 Oct 2026: the complete take, script words never lost (takes.py)
        from . import fixloop, takes
        auto = takes.complete_takes(words, sel) + takes.lost_words(words, sel)
        for f in auto:
            print(f"take fix: {f['op']} {f['spans'][0][0]:.2f}-{f['spans'][-1][1]:.2f} «{f['text'][:60]}» ({f['why']})")
        if auto:
            keep = fixloop.apply(keep, auto)
            removed = [r for r in removed if not any(r[0] >= s - 0.05 and r[1] <= e + 0.05 for f in auto if f["op"] == "keep"
                                                     for s, e in f["spans"])]
            removed = sorted(removed + [[s, e, f["reason"], f["text"]] for f in auto if f["op"] == "cut" for s, e in f["spans"]])
        save_json(WORK / "take_fixes.json", auto)
    vc = WORK / "verify_cuts.json"
    if vc.exists():  # earlier attempts found by the verification pass on the finished edit (verify.py)
        extra = load_json(vc)
        keep = snap_frames(subtract(keep, [[s, e] for s, e, _ in extra]))
        removed = sorted(removed + [[s, e, "retake", t] for s, e, t in extra])
    sf, mf = WORK / "selfcheck_fixes.json", WORK / "manual_fixes.json"
    if sf.exists() or mf.exists():  # hand decisions from the review + fixes from the self-check loop (fixloop.py)
        fx = (load_json(mf) if mf.exists() else []) + (load_json(sf) if sf.exists() else [])
        keep_base = keep
        from . import fixloop
        restore = [sp for f in fx if f["op"] == "keep" for sp in f["spans"]]
        keep = fixloop.apply(keep, fx)
        removed = [r for r in removed if not any(r[0] >= s - 0.05 and r[1] <= e + 0.05 for s, e in restore)]
        removed = sorted(removed + [[s, e, f["reason"], f["text"]] for f in fx if f["op"] == "cut"
                                    for s, e in f["spans"]])
    if CHANNEL and (WORK / "take_fixes.json").exists():   # a replaced take stays out, whatever an older self-check fix put back
        hard = [sp for f in load_json(WORK / "take_fixes.json") if f["op"] == "cut" for sp in f["spans"]]
        if hard:
            keep = snap_frames(subtract(keep, hard))
    ctc_src = WORK / "asr_ext_ctc.json"
    if ctc_src.exists() and "--no-style" not in args:  # pauses / breaths / short pieces like the reference editor (style.py)
        from . import style
        manual = load_json(mf) if mf.exists() else []
        protect = [sp for f in manual if f["op"] == "keep" and f.get("keep_pauses") for sp in f["spans"]]
        ctc = load_json(ctc_src)["words"]
        styled, _ = style.apply_style(keep, db, ctc, protect=protect, log=print, wsp=words)
        keep = style.snap(style.guard(keep, styled, ctc, db=db, wsp=words))
        if "--no-breath" not in args:  # no breath at a cut, no breathy tail on a word, none in short pauses (breath.py)
            from . import breath
            M = breath.prepare(sync.SYNC16, ctc, cache_dir=WORK, log=print)
            cleaned, brep = breath.clean(keep, M, ctc=ctc, log=print)
            keep = style.snap(style.guard(keep, cleaned, ctc, db=db, wsp=words))
            fades = [f for f in brep["soft_fades"]
                     if any(abs((s if f["side"] == "in" else e) - f["t"]) < 1e-3 for s, e in keep)]
    if CHANNEL and ctc_src.exists():   # owner's fix 6 of 22 Oct 2026: no kept piece under 0.5 s at the end
        from . import fixloop, takes
        vocab = {normalize_ar(x if isinstance(x, str) else x.get("w", "")) for x in script["words"]}
        hand = [sp for f in (load_json(mf) if mf.exists() else []) if f["op"] == "keep" for sp in f["spans"]]
        st = takes.stammers(keep, load_json(ctc_src)["words"], vocab, protect=hand)
        for f in st:
            print(f"stammer: cut {f['spans'][0][0]:.2f}-{f['spans'][0][1]:.2f} ({f['why']})")
        if st:
            keep = snap_frames(subtract(keep, [sp for f in st for sp in f["spans"]]))
            removed = sorted(removed + [[sp[0], sp[1], "retake", f["text"]] for f in st for sp in f["spans"]])
        keep, sp_log = short_pieces(keep, load_json(ctc_src)["words"], db)
        for x in sp_log:
            print("short piece:", x)
        removed = sorted(removed + [[s, e, "retake", "short piece (a fragment)"] for x in sp_log if x.startswith("dropped")
                                    for s, e in [tuple(map(float, x.split()[1].split("-")))]])
    total = sum(e - s for s, e in keep)
    cuts = cut_reasons(keep, removed)
    print(f"EDL: {len(keep)} segments, {total:.1f}s ({tc(total)}), {len(cuts)} cuts:",
          Counter(c["reason"] for c in cuts))

    unsure, missing = unsure_list(words, sel, script, flagged)
    to_out = map_to_output(keep)
    for u in unsure:
        u["out"] = float(to_out(u["src"]))

    save_json(OUT / "edl.json", {
        "fps": 24, "source_video": "المقطع قبل التعديل ... .mp4", "audio": "external mic (synced)",
        "keep": keep, "keep_before_selfcheck": keep_base or keep, "cuts": cuts, "removed_spans": removed,
        "fades": fades})
    report = {"duration_s": total, "n_segments": len(keep), "n_cuts": len(cuts),
              "cuts_by_reason": Counter(c["reason"] for c in cuts),
              "removed_s_by_reason": {r: sum(c["removed_s"] for c in cuts if c["reason"] == r)
                                      for r in set(c["reason"] for c in cuts)},
              "sync": {k: v for k, v in info.items() if k in ("segments", "cam_dur", "ext_dur", "cam_covered")},
              "unsure": unsure,
              "missing_script_sentences": [{"i": s, "text": script["sentences"][s]} for s in missing],
              "runs": [{k: r[k] for k in ("id", "j0", "j1", "score")} | {"n_words": len(r["words"]),
                        "src": words[r["words"][0]]["s"]} for r in sel["runs"]],
              "asr_seconds": asr["seconds"]}

    if "--no-render" not in args:
        out = render(keep, fades=fades)
        report["rendered_duration_s"] = ffprobe_duration(out)

    if REF_VIDEO is None:
        # no human edit: measure ASR accuracy by transcribing the auto edit itself
        if "--no-render" not in args and "--no-accuracy" not in args:
            report["asr_accuracy"] = accuracy_on_output(script)
        elif (WORK / "report_data.json").exists():  # keep the last measurement
            report["asr_accuracy"] = load_json(WORK / "report_data.json").get("asr_accuracy", {})
        save_json(WORK / "report_data.json", report)
        print("done ->", OUT)
        return

    # comparison with the human edit + ASR accuracy (reference cut used for measurement only)
    ref_asr = transcribe(sync.REF16, "ref", MODEL)
    ref_segs = compare.reconstruct(ref_asr["words"], words, force="--force-compare" in args)
    dif = compare.diff(keep, ref_segs, cam_dur)
    for key in ("auto_only", "ref_only"):
        regs = sorted(dif[key], key=lambda r: r[0] - r[1])[:15]
        dif[key] = [{"src": s, "src_end": e, "len": e - s, "out": float(to_out(s)),
                     "text": " ".join(w["w"] for w in words if w["s"] < e and w["e"] > s),
                     "our_reason": ";".join(sorted({r[2] for r in removed if r[0] < e and r[1] > s}))}
                    for s, e in regs]
    report["compare"] = {k: v for k, v in dif.items() if k != "ref_keep"}
    report["reference_duration_s"] = ffprobe_duration(compare_ref_path())

    acc = {}
    for model in [MODEL, "large-v3-turbo"]:
        try:
            ra = transcribe(sync.REF16, "ref", model)
        except Exception as ex:  # turbo is optional
            print("skip", model, ex)
            continue
        ev = accuracy.evaluate(script, ra["words"], None)
        acc[model] = {"normalized": ev["normalized"], "raw": ev["raw"], "seconds": ra["seconds"]}
        if model == MODEL:
            path, starts = accuracy.sample_diff(script, ra["words"], ev["_pairs"], ev["_excl"])
            acc["sample_windows"] = starts
    report["asr_accuracy"] = acc
    save_json(WORK / "report_data.json", report)
    print("done ->", OUT)


def accuracy_on_output(script):
    """WER/CER of the engine model on the finished edit, scored against the script (no reference edit). A channel episode
    reuses the verify pass's transcripts of that same cut (owner's fix 6 of 21 Oct 2026: transcribing it again took 37 min)"""
    reused = final_transcripts()
    if reused:
        return {m: dict({k: v for k, v in accuracy.evaluate(script, ws, None).items() if k in ("normalized", "raw")}, seconds=0,
                        reused="the verify pass's transcript of this cut") for m, ws in reused.items()}
    wav = WORK / "edit16.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", EDIT_VIDEO, "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", wav])
    acc = {}
    for model in [MODEL, "large-v3-turbo"]:
        ra = transcribe(wav, "edit", model, force=True)
        ev = accuracy.evaluate(script, ra["words"], None)
        acc[model] = {"normalized": ev["normalized"], "raw": ev["raw"], "seconds": ra["seconds"]}
    return acc


def final_transcripts():
    """{model: words} of the finished cut from the verify pass, when they are of exactly this cut list (a channel episode)"""
    from .common import PROJECT
    from .pipeline import FINAL_ASR, _draft_sig
    if not (PROJECT is not None and getattr(PROJECT, "profile", None) and FINAL_ASR and FINAL_ASR.exists()):
        return None
    d = load_json(FINAL_ASR)
    if d.get("cut") != _draft_sig(load_json(OUT / "edl.json"))["cut"] or not all(m in d.get("models", {}) for m in (MODEL, "large-v3-turbo")):
        return None
    return {m: d["models"][m] for m in (MODEL, "large-v3-turbo")}


def compare_ref_path():
    from .common import REF_VIDEO
    return REF_VIDEO


if __name__ == "__main__":
    main()

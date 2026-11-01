"""The cut's steps (talking-head projects), called by monteer/steps.py in this order:

  sync           camera + microphone on one timeline (or the video's own track when the mic is already on it)
  transcribe     whisper large-v3 words with times (shared with voice-only projects, see transcribe_voice)
  literal_words  the Egyptian wav2vec2 model's literal words (stammers and repeats stay in), run in the ml environment
  script         the script's sentences and words
  cut            the keep list: which pieces of the recording stay, with every cut's reason -> output/edl.json
                 content comes from one of two places (options.cut_content):
                   "engine" (default)  take choice by comparing the speech with the script (align.py), then the
                                       fix loop (fixloop.py) for leftover repeats and chopped words
                   "editor"            a human editor's keep list (inputs.editor_keep, a JSON file), e.g. one
                                       recovered from a published edit by learn/editor_compare
                 then, for both: the pause/breath style rules (style.py) and the breath rules (breath.py)
  cut_draft      render the cut to work/cut_draft.mp4
  cut_verify     transcribe the draft, find repeats still in it, confirm each on a short clip, cut them, redo the
                 cut and the draft (engine content only; at most options.verify_rounds rounds, default 2)
  cut_final      the finished cut: output/cut_v<version>.mp4 (never overwritten)
  cut_report     output/report.md (+ transcription accuracy measured on the finished cut)
"""
import json
import shutil
import subprocess
import sys

from ..core.io import atomic, done
from ..core.paths import ML_PY, ENGINE, tool_env
from .common import EDIT_VIDEO, OUT, PROJECT, WORK, load_json, save_json, tc

MODEL = "large-v3"
CTC = WORK / "asr_ext_ctc.json" if WORK else None
DRAFT = WORK / "cut_draft.mp4" if WORK else None


def step_sync(p):
    from . import sync
    sync.build()


def step_transcribe(p):
    from . import sync
    from .asr import transcribe
    transcribe(sync.EXT16, "ext", MODEL)


def step_literal_words(p):
    """the literal Egyptian words of the synced microphone track (ml environment, its own process)"""
    from . import sync
    if done(CTC):
        return
    subprocess.run([str(ML_PY), "-m", "monteer.cut.ctc_words", str(sync.SYNC16), str(CTC)], check=True, cwd=str(ENGINE), env=tool_env())


def step_script(p):
    from . import script_text
    script_text.build()


def step_cut(p):
    if p.opt("cut_content", "engine") == "editor":
        cut_from_editor(p)
    else:
        from . import fixloop, run
        run.main({"--no-render"})
        if p.opt("fix_loop", True):
            before = len(load_json(WORK / "selfcheck_fixes.json")) if (WORK / "selfcheck_fixes.json").exists() else 0
            _, fixes = fixloop.main()
            if len(fixes) > before:                 # the fixes are applied by the cut itself (run.py reads them)
                run.main({"--no-render"})


def cut_from_editor(p):
    """A human editor's content + the engine's style and breath rules (no take choice, no script restore).

    inputs.editor_keep (JSON): {"spans": [[source s, source e], ...]   the editor's kept pieces (source time),
                                "protect_pauses": [[s, e], ...]        spans whose pauses stay whole,
                                "slots": [{"after_src": s, "dur": d}]  black slots the editor left (e.g. a promo)}
    labels: options.labels.editor_content (the reason given to content cuts in the cut list)."""
    from . import breath, fixloop, script_text, selfcheck, style
    from .silence import frame_db
    from .sync import SYNC16
    lines = []

    def log(*a):
        s = " ".join(str(x) for x in a)
        print(s, flush=True)
        lines.append(s)

    ed = load_json(p.input("editor_keep"))
    label = p.opt("labels", {}).get("editor_content", "content (editor's choice / retake)")
    db = frame_db()
    ctc = selfcheck.with_norm(load_json(CTC)["words"])
    wsp = load_json(WORK / f"asr_ext_{MODEL}.json")["words"]
    script = script_text.build()
    last = p.opt("script_last_sentence", len(script["sentences"]) - 1)
    scr = selfcheck.script_range(script, last)[0]

    K = merge(ed["spans"])
    styled, rep_style = style.apply_style(K, db, ctc, protect=ed.get("protect_pauses", []), log=log, wsp=wsp)
    paused = style.snap(style.guard(K, styled, ctc, db=db, wsp=wsp))
    slots = [{"after": min(paused, key=lambda kv: abs(kv[1] - s["after_src"]))[1], "dur": s["dur"], "editor_after_src": s["after_src"]}
             for s in ed.get("slots", [])]
    log(f"pauses: {tc(sum(e - s for s, e in paused))} + slots, {len(paused)} pieces")

    M = breath.prepare(SYNC16, ctc, cache_dir=WORK, log=log)
    cleaned, rep = breath.clean(paused, M, ctc=ctc, log=log)
    keep = style.snap(style.guard(paused, cleaned, ctc, db=db, wsp=wsp))
    restored = [x for x in keep if x not in cleaned]
    log(f"word guard put back {len(restored)} spans")
    lost = fixloop.coverage(paused, wsp, ctc, scr) - fixloop.coverage(keep, wsp, ctc, scr)
    log(f"cut: {tc(sum(e - s for s, e in keep))} + slots, {len(keep)} pieces ({len(paused)} before the breath rules), "
        f"script words the breath rules lost: {[scr[j] for j in sorted(lost)]}")

    inserts = []
    for i in slots:              # each slot after the same piece as before the breath rules (its end may have moved)
        k4 = min(range(len(paused)), key=lambda k: abs(paused[k][1] - i["after"]))
        seg = min(keep, key=lambda kv: abs(kv[1] - paused[k4][1]) + abs(kv[0] - paused[k4][0]))
        inserts.append(dict(i, after=seg[1]))
    log("slots:", inserts)
    fades = [f for f in rep["soft_fades"] if any(abs((s if f["side"] == "in" else e) - f["t"]) < 1e-3 for s, e in keep)]
    cuts = []
    for (a0, a1), (b0, b1) in zip(keep, keep[1:]):
        ws = [w for w in ctc if w["s"] < b0 and w["e"] > a1 and style.kept_frac([[a1, b0]], w["s"], w["e"]) >= 0.5]
        cuts.append({"src_from": a1, "src_to": b0, "removed_s": b0 - a1, "reason": label if ws else "pause / breath",
                     "text": " ".join(w["w"] for w in ws)})
    save_json(OUT / "edl.json", {
        "fps": 24, "source_video": p.input("video").name, "audio": "embedded (synced external mic)" if p.input("audio") is None else "external mic (synced)",
        "keep": keep, "inserts": inserts, "fades": fades, "cuts": cuts,
        "content": "a human editor's keep list (inputs.editor_keep) + the engine's pause, breath and word-guard rules",
        "style": {"rules": {k: getattr(style, k) for k in ("CAP", "TARGET", "LEAD", "TAIL", "MIN_PIECE")}, "pauses": rep_style,
                  "breath": {"R1": rep["R1"], "R2": rep["R2"], "R3": rep["R3"], "fade_soft_s": breath.FADE_SOFT}},
        "breath_edits": rep["edits"],
        "script_words_lost_to_breath_rules": [scr[j] for j in sorted(lost)]})
    save_json(WORK / "cut_log.json", lines)


def merge(iv, gap=0.0):
    out = []
    for s, e in sorted(iv):
        if out and s <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


DRAFT_OF = WORK / "cut_draft_of.json" if WORK else None
FINAL_ASR = WORK / "asr_final.json" if WORK else None   # the finished cut's transcripts from the verify pass (the report reuses them)


def _draft_sig(e):
    """what the draft is rendered from (the keep list, inserts and fades) and the draft file as it is (size, time)"""
    import hashlib
    cut = json.dumps([e["keep"], e.get("inserts", []), e.get("fades", [])], sort_keys=True)
    st = DRAFT.stat() if DRAFT.exists() else None
    return {"cut": hashlib.sha256(cut.encode()).hexdigest()[:16], "draft": [st.st_size, st.st_mtime] if st else None}


def render_draft(e):
    """render the draft and note what it is the render of (owner, 21 Oct 2026: the verify pass changes the cut list and
    remakes the draft itself; the next run then kept re-rendering the draft and so ran the verify pass again)"""
    from .render import render
    render(e["keep"], DRAFT, inserts=e.get("inserts", ()), fades=e.get("fades", ()))
    save_json(DRAFT_OF, _draft_sig(e))


def step_cut_draft(p):
    e = load_json(OUT / "edl.json")
    if DRAFT_OF.exists() and load_json(DRAFT_OF) == _draft_sig(e):
        print("the draft is already this cut list's render (remade by the verify pass): kept as it is")
        return
    render_draft(e)


def step_cut_verify(p):
    """leftover repeats in the finished draft (engine content only); each confirmed one is cut and the draft remade"""
    if p.opt("cut_content", "engine") == "editor":
        print("editor content: the editor chose the takes; no repeat verification")
        return
    from . import run, verify
    for rnd in range(int(p.opt("verify_rounds", 2))):
        found = verify.main(DRAFT, clips=rnd == 0)
        if not found:
            break
        run.main({"--no-render"})
        render_draft(load_json(OUT / "edl.json"))
    if verify.LAST.exists():           # the last round's transcripts, less what it cut: the finished cut's own (owner's fix 6)
        save_json(FINAL_ASR, {"cut": _draft_sig(load_json(OUT / "edl.json"))["cut"], "models": load_json(verify.LAST)["models"]})


def step_cut_final(p):
    if EDIT_VIDEO.exists():
        raise SystemExit(f"{EDIT_VIDEO} exists: outputs are never overwritten; set options.version to a new number")
    with atomic(EDIT_VIDEO) as tmp:
        shutil.copy2(DRAFT, tmp)


def step_cut_report(p):
    from . import report, run, script_text
    data = load_json(WORK / "report_data.json") if (WORK / "report_data.json").exists() else {}
    if p.input("reference_edit") is None and p.opt("cut_content", "engine") == "engine":
        data["asr_accuracy"] = run.accuracy_on_output(script_text.build())
        save_json(WORK / "report_data.json", data)
        report.main()
    else:
        print("report: the reference-edit comparison is in work/report_data.json")


if __name__ == "__main__":
    print(__doc__)
    sys.exit(0)
    json  # noqa

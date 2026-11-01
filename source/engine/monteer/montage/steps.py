"""Voice-only and montage steps, registered into monteer/steps.py after the cut.

Two montages (project option "montage"):
  "phrases" (default; owner's decisions of 16 Oct 2026, replacing the sentence montage of 15 Oct): the 5b way of planning
      in the engine: every shot tied to the phrase it shows, every on-screen item and graphic element on its word, our
      graphics designed per narration (map, number, steps, headline cards, the word montage), a fast 15-20 s intro,
      transitions and effects on cuts and on-screen text, rules 18-24, no «رسم توضيحي» label. Brain decisions:
      montage/shots, sources/assets_<n> (chosen after looking at thumbnails), montage/clip_fx, ai/pick; the rest is built
      in code (montage/phrases.py, montage/steps_phrase.py, montage/build.py).
  "classic": the earlier free-form montage below (plan, music cues, sources, AI prompts and pick, clip windows, timeline,
      graphics scenes, sound plan, all decided by the brain). The same-result tests use it.
Every request is self-contained (files to read, format files, JSON schema), so the background brain answers it unattended.

Order: voice -> voice_words -> plan* -> music* -> sources* -> ai_images* -> textures -> sfx -> review* -> timeline* ->
graphics* -> parallax -> shots -> join -> mix* -> final -> selfcheck -> credits         (* = reads a judgement decision)

Judgement decisions (the brain; see core/brain.py) and what each one holds:
  montage/plan        the shot plan, block by block (what each block shows, pace, music cue, rules 18-24 used)
  music/cues          [{"name", "seconds", "prompt", "seed"?}] for the music step
  sources/assets      {"stock": [{"id", "title", "for", "source"}], "photos": [{"key", "title", "page", "licence", "author"}]}
  ai/prompts          {"key": {"prompt", "why"}}: generic scenes only, never a specific real event
  ai/pick             {"key": {"seed"}}: the image chosen for each key after looking at them
  graphics/scenes     the scene list for the renderer (see gfx/gfx.swift)
  montage/clip_fx     {"clip id": {"win": [s, e], "crop": [x, y, w], "grade", "blur"}}: after looking at the contact sheets
  montage/timeline    see montage/timeline.py
  montage/sound       see montage/mix.py
Options: options.render_window = [start s, end s] renders only that stretch (a preview or a test); the final file is then
called <output_name>_preview_<start>-<end>.mp4.
"""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from ..core import brain
from ..core.io import atomic, done, load_json, save_json
from ..core.paths import CORE_PY, ENGINE, FFMPEG, FFPROBE, ML_PY, RULES, tool_env
from ..steps import BOTH, TH, VO, Step, register

FPS = 24


def M(p, *names):
    return p.work.joinpath("montage", *names)


def V(p, *names):
    return p.work.joinpath("voice", *names)


def words(p):
    """the narration's words on the montage's timeline: the voice itself (voice-only) or the cut's output timeline"""
    if p.mode == "voice_only":
        return load_json(V(p, "asr_large-v3.json"))["words"]
    from ..cut.edl import map_to_output
    keep = load_json(p.output / "edl.json")["keep"]
    to_out = map_to_output(keep)
    kept = lambda w: any(s <= w["s"] and w["e"] <= e + 0.02 for s, e in keep)  # noqa: E731
    return [dict(w, s=float(to_out(w["s"])), e=float(to_out(w["e"]))) for w in load_json(p.work / "asr_ext_large-v3.json")["words"] if kept(w)]


def decision(p, step, key, default=None):
    f = p.decisions / step / f"{key}.json"
    return load_json(f)["decision"] if f.exists() else default


VOLATILE = {"made_at", "made_by", "seconds", "usage", "request_sha", "retried", "at", "fetched_at", "fetched_ts", "accepted_at",
            "answered_at", "why_redo"}


def content_sig(path):
    """what a read file holds, for a request's fingerprint: a decision file by its decision only; other JSON without
    times and timings; anything else by its bytes; "missing" when it does not exist"""
    import hashlib
    path = Path(path)
    if not path.exists():
        return "missing"
    if path.is_dir():
        return hashlib.sha256(json.dumps(sorted((str(f.relative_to(path)), f.stat().st_size) for f in path.rglob("*") if f.is_file())).encode()).hexdigest()[:16]
    if path.suffix == ".json":
        try:
            d = load_json(path)
            if isinstance(d, dict) and "decision" in d and "step" in d:
                d = d["decision"]

            def strip(x):
                if isinstance(x, dict):
                    return {k: strip(v) for k, v in x.items() if k not in VOLATILE}
                if isinstance(x, list):
                    return [strip(v) for v in x]
                return x
            return hashlib.sha256(json.dumps(strip(d), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        except (ValueError, OSError):
            pass
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def ask(p, step, key, what, answer_format, read=(), extra=None, schema=None, docs=(), tools=(), check=None, settle=None,
        fallback=None, once=False, repair=None):
    """the decision for step/key, or stop the run and ask for it.

    Self-contained for the background brain (Phase A of the overnight work): the request names the files to read, the
    engine files that define the answer's format (docs), the rules, a JSON schema the answer must match, and any extra
    tool it needs. check(decision) raises when the engine cannot use the answer; the brain is then asked again with the
    problem (up to 2 more times). With a person in a Claude Code session, the problem stops the run instead.
    settle(decision) -> (decision, notes): a channel episode's last resort (owner's decision of 19 Oct 2026, after the first
    real test stopped on a picture used up): when the third answer is still refused, only what breaks a rule is left out
    (a shot gets no picture, a key is not used …), said in the log and kept on the decision, and the run goes on.
    fallback: a channel episode's answer when the brain gives none it can use (owner's decision of 20 Oct 2026, after a run
    stopped on "error_max_structured_output_retries"): Claude failed after its tries, or every answer was refused and
    could not be settled. The empty answer given here (or fallback() when it is a function) goes through settle and check
    like a brain's answer, is kept on the decision ("fallback_by_engine") and said in the log, and the run goes on. Only
    requests with no fallback still stop the run (the shot plan; see NOTES.md for the list).
    once: one try only, never asked again (a cheap look; a failure goes straight to the fallback).
    repair(decision) -> (decision, notes): a channel episode's small fixes in code (owner's decision of 20 Oct 2026, after a
    plan was refused for 125 stock shots of 310, at most 124, and asking again took 35 minutes): tried on every refused
    answer before the brain is asked again; when the repaired answer passes the check, it is used, kept on the decision
    ("repaired_by_engine", with the brain's own answer) and said in the log."""
    from ..core.runner import rel
    from .questions import answers_text           # step-by-step mode: the owner's answers re-plan (montage/questions.py)
    what = what + answers_text(p, step, key)
    from .edits import edits_text, untouched_problems   # edit until satisfied: the owner's applied edits (montage/edits.py)
    et = edits_text(p, step, key)
    what = what + et
    if et and f"{step}/{key}" in ("montage/shots", "montage/plan", "montage/timeline"):
        base = check                              # owner's answer 1 of phases 5-6: shots outside the edit stay as they were

        def check(d, base=base):
            if base:
                base(d)
            probs = untouched_problems(p, step, key, d)
            if probs:
                raise ValueError("; ".join(probs))
    if p.profile and (step, key) in ALT_KEYS:      # owner's answer 1 of phase 4: the choices' rejected alternatives on record
        what, answer_format, schema = with_alternatives(what, answer_format, schema)
    if p.profile and schema:                         # a channel episode: an answer of the wrong shape goes back first
        inner, sch = check, schema

        def check(d, inner=inner, sch=sch):
            bad = shape_problems(d, sch)
            if bad:
                raise ValueError("the answer does not have the asked shape: " + "; ".join(bad))
            if inner:
                return inner(d)
    req = {"what": what, "answer_format": answer_format, "read": [rel(p, x) for x in read], "project": "paths are relative to the project folder",
           # owner's decision 2a (16 Oct 2026): the request depends on what the files it reads HOLD, not only their names, so
           # a changed plan reaches every decision that reads it (before, v5 kept Phase 1's music cues)
           "read_content": {rel(p, x): content_sig(x) for x in read},
           "rules": [f"engine/rules/{f}" for f in ("rules_01_17.md", "rules_18_24.md")], "channel": rel(p, p.channel) if p.channel else None}
    if docs:
        req["format_docs"] = list(docs)
    if schema:
        req["answer_schema"] = schema
    if tools:
        req["tools"] = list(tools)
    if extra:
        req.update(extra)
    can_fall = fallback is not None and p.profile and brain.brain_name(p) != "claude-code"
    if once and can_fall:
        req["one_try"] = True
    try:
        d = brain.decide(p, step, key, req)
    except brain.BrainUnavailable as e:
        if not can_fall:
            raise
        return fell_back(p, step, key, req, fallback, check, settle, f"no answer: {e}")
    if not check or brain.brain_name(p) == "claude-code":
        return d                    # a person answers: the engine's later steps report any problem, as before
    tries = 1 if once and can_fall else 3
    for attempt in range(tries):
        try:
            check(d)
            if attempt:                                  # keep the good answer under the plain request (no re-ask next run)
                f = p.decisions / step / f"{key}.json"
                rec = load_json(f)
                rec.update(request_sha=brain.request_sha(req), retried=attempt)
                save_json(f, rec)
            return d
        except Exception as e:  # noqa: BLE001  (any reason the engine cannot use the answer goes back to the brain)
            problem = f"{type(e).__name__}: {e}"
            if repair and p.profile and brain.brain_name(p) != "claude-code":
                fixed = repaired(p, step, key, req, d, check, repair, problem, attempt)
                if fixed is not None:
                    return fixed
            if attempt == tries - 1 and settle and p.profile and brain.brain_name(p) != "claude-code":
                fixed = settled(p, step, key, req, d, check, settle, problem)
                if fixed is not None:
                    return fixed
            if attempt == tries - 1 and can_fall:
                return fell_back(p, step, key, req, fallback, check, settle, f"every answer refused: {problem}")
            if brain.brain_name(p) == "claude-code" or attempt == 2:
                raise SystemExit(f"the decision {step}/{key} cannot be used: {problem}. Redo it (bin/monteer brain redo …) and run again")
            print(f"[brain] {step}/{key} rejected by the engine ({problem[:200]}); asking again", flush=True)
            from .learning import log_rejection
            log_rejection(p, step, key, problem)     # kept for «عام»'s learning (montage/learning.py); the request is unchanged
            brain.redo(p, step, key)
            again = dict(req, previous_problem=f"Your previous answer was rejected by the engine: {problem}\n"
                                                f"Previous answer (first 6000 characters): {json.dumps(d, ensure_ascii=False)[:6000]}")
            try:
                d = brain.decide(p, step, key, again)
            except brain.BrainUnavailable as e2:
                if not can_fall:
                    raise
                return fell_back(p, step, key, req, fallback, check, settle, f"no answer when asked again: {e2}")


def fell_back(p, step, key, req, fallback, check, settle, problem):
    """a channel episode's answer when the brain gives none it can use (ask's fallback) -> the decision; the run stops (as
    before) only when the engine cannot use even that"""
    import copy
    d = fallback() if callable(fallback) else copy.deepcopy(fallback)
    notes = []
    try:
        if settle:
            try:
                d, notes = settle(d)
            except Exception as e:  # noqa: BLE001  (the fallback is safe as it is; the last resort only fills it in)
                notes = [f"the last resort could not fill in the fallback ({type(e).__name__}: {str(e)[:120]}); used as it is"]
        if check:
            check(d)
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"the decision {step}/{key} could not be made ({problem[:300]}), and the engine's own fallback "
                         f"cannot be used ({type(e).__name__}: {e})")
    f = p.decisions / step / f"{key}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    brain.set_aside(f)                 # a refused answer stays on record (<key>.replaced_<time>.json)
    save_json(f, {"step": step, "key": key, "request_sha": brain.request_sha(req), "made_by": "engine fallback (the brain gave no usable answer)",
                  "made_at": time.strftime("%Y-%m-%d %H:%M:%S"), "decision": d,
                  "fallback_by_engine": {"problem": problem[:1000], "notes": notes}})
    print(f"[brain] {step}/{key}: Claude gave no usable answer ({problem[:200]}); the engine's safe fallback is used and the run "
          "goes on" + (": " + "; ".join(notes)[:400] if notes else ""), flush=True)
    return d


TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int, "number": (int, float)}


def shape_problems(d, schema, at="the answer", out=None):
    """where an answer does not have the shape its request's schema asks for (type, required keys, items, values) -> a few
    lines. A channel episode's answer of the wrong shape is sent back (19 Oct 2026: the clip review came back as one
    crop value, [0, 0, 0.85], instead of a clip -> settings object, and the run crashed on it)."""
    out = [] if out is None else out
    if not isinstance(schema, dict) or len(out) >= 6:
        return out
    want = schema.get("type")
    py = TYPES.get(want) if isinstance(want, str) else None
    if py and (not isinstance(d, py) or (want in ("integer", "number") and isinstance(d, bool))):
        out.append(f"{at} must be {'an' if want[0] in 'aeiou' else 'a'} {want}, not {type(d).__name__}")
        return out
    if isinstance(d, dict):
        out += [f"{at} needs \"{k}\"" for k in schema.get("required", []) if k not in d]
        props, extra = schema.get("properties", {}), schema.get("additionalProperties")
        for k, v in d.items():
            sub = props.get(k, extra if isinstance(extra, dict) else None)
            if sub:
                shape_problems(v, sub, f"{at}[{k!r}]", out)
    elif isinstance(d, list) and isinstance(schema.get("items"), dict):
        for i, v in enumerate(d[:200]):
            shape_problems(v, schema["items"], f"{at}[{i}]", out)
    return out[:6]


def repaired(p, step, key, req, d, check, repair, problem, attempt):
    """a refused answer with ask's small code fixes, when the engine can then use it -> the decision, or None (asked again)"""
    try:
        d2, notes = repair(d)
        if not notes:
            return None
        check(d2)
    except Exception:  # noqa: BLE001  (not fixable in code: the brain is asked again, as before)
        return None
    f = p.decisions / step / f"{key}.json"
    rec = load_json(f) if f.exists() else {"step": step, "key": key}
    rec.update(decision=d2, request_sha=brain.request_sha(req), retried=attempt,
               repaired_by_engine={"problem": problem[:1000], "changed": notes, "brain_answer": d})
    save_json(f, rec)
    print(f"[brain] {step}/{key}: a small overrun fixed in code instead of asking again: " + "; ".join(notes)[:600], flush=True)
    return d2


def settled(p, step, key, req, d, check, settle, problem):
    """the third refused answer with only what breaks a rule left out (ask's settle), when the engine can then use it ->
    the decision, or None (the run stops as before)"""
    try:
        d2, notes = settle(d)
        check(d2)
    except Exception as e:  # noqa: BLE001
        print(f"[brain] {step}/{key}: the engine could not settle the answer itself ({type(e).__name__}: {e})", flush=True)
        return None
    f = p.decisions / step / f"{key}.json"
    rec = load_json(f) if f.exists() else {"step": step, "key": key}
    rec.update(decision=d2, request_sha=brain.request_sha(req), retried=2,
               settled_by_engine={"problem": problem[:1000], "left_out": notes, "brain_answer": d})
    save_json(f, rec)
    print(f"[brain] {step}/{key}: refused 3 times; the engine left out what breaks the rules and goes on: "
          + "; ".join(notes)[:600], flush=True)
    return d2


# owner's answer 1 of phase 4 (channel profiles only; the classic same-result projects have none): the main requests also
# name the alternatives they rejected, so the Result screen's «قرارات اتاخدت لوحدها» can offer them («غيّرها»)
ALT_KEYS = {("montage", "plan"), ("montage", "shots"), ("montage", "timeline"), ("music", "cues")}
ALT_ITEM = {"type": "object", "required": ["what", "chosen", "rejected", "why"], "properties": {
    "what": {"type": "string"}, "at_s": {"type": "number"}, "chosen": {"type": "string"}, "why": {"type": "string"},
    "rejected": {"type": "array", "minItems": 1, "maxItems": 3, "items": {"type": "string"}}}}


def with_alternatives(what, answer_format, schema):
    if isinstance(answer_format, list):           # a list answer (the music cues): each item names its rejected options
        what += (" ALSO, for the owner's review: in each item give \"rejected\": 1-3 other moods or styles you considered "
                 "and did not take, and \"why\": one line on your choice. Nothing else in the answer changes.")
        fmt = [dict(answer_format[0], rejected=["…"], why="…")] + answer_format[1:] if answer_format else answer_format
        if schema and schema.get("type") == "array" and isinstance(schema.get("items"), dict):
            it = schema["items"]
            schema = dict(schema, items=dict(it, properties=dict(it.get("properties", {}), rejected=ALT_ITEM["properties"]["rejected"],
                                                                 why={"type": "string"})))
        return what, fmt, schema
    what += (" ALSO, for the owner's review: give \"alternatives\": 3-8 of the most important choices in this answer, each "
             "{\"what\": the choice in a few words, \"at_s\": its time in the video when it has one, \"chosen\": what you did, "
             "\"rejected\": 1-3 real alternatives you considered and did not take, \"why\": one line}. Nothing else in the "
             "answer changes.")
    fmt = dict(answer_format, alternatives=[{"what": "…", "at_s": 0, "chosen": "…", "rejected": ["…"], "why": "…"}])
    if schema and schema.get("type") == "object":
        schema = dict(schema, properties=dict(schema.get("properties", {}), alternatives={"type": "array", "maxItems": 8, "items": ALT_ITEM}))
    return what, fmt, schema


# answer schemas (checkable shapes; the engine files named in docs define the meaning)
OBJ = {"type": "object"}
NUM = {"type": "number"}
STR = {"type": "string"}
INT = {"type": "integer"}
SCHEMA_PLAN = {"type": "object", "required": ["blocks"], "properties": {"blocks": {"type": "array", "minItems": 1, "items": {
    "type": "object", "required": ["in", "out", "shows"], "properties": {
        "in": NUM, "out": NUM, "section": STR, "music": STR, "pace_s": NUM, "shows": {"type": "array", "items": STR},
        "search_stock": {"type": "array", "items": STR}, "search_photos": {"type": "array", "items": STR}, "techniques": OBJ}}}}}
SCHEMA_CUES = {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["name", "seconds", "prompt"],
                                                         "properties": {"name": STR, "seconds": NUM, "prompt": STR, "seed": {"type": "integer"}}}}
SCHEMA_SEARCH = {"type": "object", "required": ["stock", "photos"], "properties": {
    "stock": {"type": "array", "maxItems": 12, "items": {"type": "object", "required": ["query", "for"], "properties": {"query": STR, "for": STR}}},
    "photos": {"type": "array", "maxItems": 12, "items": {"type": "object", "required": ["query", "for"], "properties": {"query": STR, "for": STR}}}}}
SCHEMA_ASSETS = {"type": "object", "required": ["stock", "photos"], "properties": {
    "stock": {"type": "array", "items": {"type": "object", "required": ["id", "source", "for"], "properties": {
        "id": {"type": "integer"}, "title": STR, "for": STR, "source": {"type": "string", "enum": ["pixabay"]}}}},
    "photos": {"type": "array", "items": {"type": "object", "required": ["key", "title", "licence"], "properties": {
        "key": STR, "title": STR, "page": STR, "licence": STR, "author": STR}}}}}
SCHEMA_PROMPTS = {"type": "object", "additionalProperties": {"type": "object", "required": ["prompt"], "properties": {"prompt": STR, "why": STR}}}
SCHEMA_PICK = {"type": "object", "additionalProperties": {"type": "object", "required": ["seed"], "properties": {"seed": {"type": "integer"}, "why": STR}}}
SCHEMA_CLIPFX = {"type": "object", "additionalProperties": {"type": "object", "properties": {
    "win": {"type": "array", "items": NUM, "minItems": 2, "maxItems": 2}, "crop": {"type": "array", "items": NUM}, "grade": STR,
    "reject": {"type": "boolean"}, "why": STR}}}
SCHEMA_TIMELINE = {"type": "object", "required": ["length_s", "blocks"], "properties": {
    "length_s": NUM, "blocks": {"type": "array", "minItems": 1, "items": {"type": "array"}}, "overlays": {"type": "array", "items": STR},
    "strong_clicks": {"type": "array", "items": NUM}, "paper_photos": {"type": "array", "items": STR}, "rehook_scenes": {"type": "array", "items": STR}}}
SCHEMA_SCENES = {"type": "array", "items": {"type": "object", "required": ["name", "t_in", "t_out", "frames", "items"], "properties": {
    "name": STR, "t_in": NUM, "t_out": NUM, "frames": {"type": "integer"}, "bg": STR, "items": {"type": "array", "items": OBJ}}}}
SCHEMA_SOUND = {"type": "object", "required": ["length_s", "sections"], "properties": {
    "length_s": NUM, "music_gain_db": NUM, "sections": {"type": "array", "items": OBJ}, "stops": {"type": "array", "items": {"type": "array"}},
    "hits": {"type": "array", "items": {"type": "array"}}, "pops": {"type": "array", "items": {"type": "array"}},
    "whoosh_scenes": {"type": "array", "items": STR}, "whoosh_extra": {"type": "array", "items": {"type": "array"}}}}


def narration_length(p):
    ws = words(p)
    return ws[-1]["e"] if ws else 0


# ---------------------------------------------------------------------------------------------------- voice-only
def step_voice(p):
    """the narration as it is: 48 kHz (the mix keeps it unchanged) + 16 kHz mono for transcription"""
    src = p.input("audio") or p.input("video")
    V(p).mkdir(parents=True, exist_ok=True)
    with atomic(V(p, "audio48.wav")) as tmp:
        subprocess.run([str(FFMPEG), "-v", "error", "-y", "-i", str(src), "-map", "0:a:0", "-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s24le", str(tmp)], check=True)
    with atomic(V(p, "audio16.wav")) as tmp:
        subprocess.run([str(FFMPEG), "-v", "error", "-y", "-i", str(V(p, "audio48.wav")), "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(tmp)], check=True)


def step_voice_words(p):
    import time
    from ..cut.asr import DTW_PRESET, tokens_to_words, whisper_bin
    from ..core.paths import WHISPER_MODEL
    model = "large-v3"
    t = time.time()
    from ..core import whisper_run
    stem = V(p, f"whisper_{model}")
    # whisper's own printout goes to a file (its DTW printing repeats lines and stops early: core/whisper_run.py); the
    # run log gets its progress and one summary line
    pr = whisper_run.run([whisper_bin(), "-m", str(WHISPER_MODEL[model]), "-f", str(V(p, "audio16.wav")), "-l", "ar", "-t", "8", "-mc", "0",
                          "-ojf", "-of", str(stem), "-dtw", DTW_PRESET[model], "-nfa", "-np"], stem)
    data = json.load(open(f"{stem}.json", encoding="utf-8"))
    ws = tokens_to_words(data)
    segs = [{"s": s["offsets"]["from"] / 1000, "e": s["offsets"]["to"] / 1000, "text": s["text"].strip()} for s in data["transcription"]]
    save_json(V(p, f"asr_{model}.json"), {"model": model, "seconds": time.time() - t, "words": ws, "segments": segs})
    whisper_run.say(whisper_run.summary(data, len(ws), pr))
    from .voice_check import log_lines
    for ln in log_lines(p, ws, segs):        # likely narrator retakes and long silences (the video's report lists them)
        whisper_run.say(ln)


# ---------------------------------------------------------------------------------------------------- judgement + assets
def phrase_mode(p):
    """audio only (صوت بس): the phrase montage"""
    return p.montage == "phrases"


def presenter_mode(p):
    """with presenter (بمذيع): the classic montage with presenter shots and punch-ins, plus Ramadan's notes
    (montage/steps_presenter.py)"""
    return p.montage == "presenter"


def step_clips(p):
    """the owner's own extra clips, converted and looked at before the plan (montage/own_clips.py, decision 8b)"""
    from .own_clips import step_clips as run
    run(p, ask)


def step_plan(p):
    if phrase_mode(p):
        from . import steps_phrase
        return steps_phrase.step_plan(p, words(p), narration_length(p))
    src = V(p, "asr_large-v3.json") if p.mode == "voice_only" else p.output / "edl.json"
    L = narration_length(p)
    if popups_layout(p):               # اقتصاد احمس: one presenter shot and pop-ups beside him (montage/steps_popups.py)
        from . import steps_popups
        return steps_popups.step_plan(p, ask, words(p), L)

    def check(d):
        bl = d["blocks"]
        if bl[0]["in"] > 1 or abs(bl[-1]["out"] - L) > 2 or any(b["out"] <= b["in"] for b in bl):
            raise ValueError(f"the blocks must cover the whole narration (0 to {L:.1f} s), each with out > in")
    what = ("The shot plan for the whole video, block by block: what each block shows and from where, its pace, "
            "its music cue and the rules 18-24 it uses. Only numbers and names that are said go on screen. For each block also give "
            "English search words for free stock footage (search_stock) and for public-domain/CC archive photos (search_photos), "
            f"if it needs them. The narration is {L:.1f} s long; the blocks cover it from 0 to the end.")
    fmt = {"blocks": [{"in": "s", "out": "s", "section": "", "music": "cue", "pace_s": 3.0, "shows": ["what [source]"], "techniques": {"18": "..."},
                       "search_stock": ["oil tanker sea"], "search_photos": ["1973 oil crisis gas line"]}]}
    schema, read, docs = SCHEMA_PLAN, [src], ["monteer/montage/timeline.py", "monteer/montage/steps.py"]
    if presenter_mode(p):              # with presenter: Ramadan's notes, decisions 2-3, sentences (montage/steps_presenter.py)
        from . import steps_presenter as SPR
        W = words(p)
        read = [SPR.words_file(p, W, L), M(p, "sentences.json")]
        SPR.sentences(p, W)
        what += "\n" + SPR.plan_text(p, L)
        from . import general as GEN, learning
        what += GEN.plan_text(p, "presenter") + learning.request_text(p, "montage/plan")
        fmt = {"intro_end_s": 17.2, "mix_targets": {"base_shots": 40, "stock_max": 16, "archive_min": 6, "news_min": 0, "max_run": 3, "ai_max": 6, "why": "…"},
               "blocks": [dict(fmt["blocks"][0], material={"stock": 3, "archive": 2, "graphic": 1}),
                          {"in": "s", "out": "s", "presenter": True, "shows": ["the presenter"]}]}
        S = SPR.STR.of(p)
        if S.cold_open:                # the channel's cold open (montage/structure.py)
            fmt = dict(fmt, cold_open_end_s=262.4)
        docs = docs + ["monteer/montage/steps_presenter.py", "monteer/montage/targets.py"]
        if S.cold_open or S.clips or not S.is_default_intro:
            docs.append("monteer/montage/structure.py")
        schema = SPR.schema_plan(S)
        if GEN.rules(p):               # «عام»: real footage first, subjects (montage/general.py)
            docs.append("monteer/montage/general.py")
            fmt["blocks"][0] = dict(fmt["blocks"][0], subject="factory floor")

        def check(d):
            SPR.check_plan(p, d, L)
            extra = GEN.block_problems(p, d, L)
            if extra:
                raise ValueError("; ".join(extra[:8]))
    ask(p, "montage", "plan", what, fmt, read=read, schema=schema, docs=docs, check=check,
        repair=(lambda d: SPR.repair_plan(p, d)) if presenter_mode(p) else None)


def make_cue(c, out):
    wav = out / f"{c['name']}.wav"
    rec = out / f"{c['name']}.json"
    same = rec.exists() and load_json(rec).get("prompt") == c["prompt"] and load_json(rec).get("seconds") == c["seconds"]
    if done(wav) and same:
        print("music:", c["name"], "already made")
        return
    if done(wav):                                    # the plan's section changed: a new cue (the old one is kept aside)
        for f in (wav, rec):
            if f.exists():
                os.replace(f, f.with_name(f"{f.stem}.replaced_{time.strftime('%Y%m%d-%H%M%S')}{f.suffix}"))
    subprocess.run([str(CORE_PY), "-m", "monteer.music.music", "--seconds", str(c["seconds"]), "--out", str(wav), "--prompt", c["prompt"],
                    "--seed", str(c.get("seed", 42)), "--max-minutes", str(p_minutes(c))], check=True, cwd=str(ENGINE), env=tool_env())


def p_minutes(c):
    """ACE-Step's time limit for one cue (a hung model is stopped); twice as long when the music runs at the same time as
    other steps (phase D), which share the processor with it"""
    return (25 if c["seconds"] <= 60 else 45) * (2 if os.environ.get("MONTEER_ALONGSIDE") else 1)


def step_music(p):
    if phrase_mode(p):
        from . import steps_phrase
        out = p.asset_dir("music")
        out.mkdir(parents=True, exist_ok=True)
        return steps_phrase.step_music(p, words(p), narration_length(p), lambda c: make_cue(c, out))
    from .structure import of as structure_of
    only_cold = structure_of(p).music_where == "cold_open_only"
    if structure_of(p).music_where == "none":      # the channel has no music under the voice (اقتصاد احمس, measured)
        print("music: none for this channel (its music is in its own clips only)")
        return
    cues = ask(p, "music", "cues", "The music cues for the plan's sections (rule 22): name, length, prompt (instrumental, no vocals). "
               "Cue length at most 90 s (longer sections are looped by the mix)."
               + (" THE CHANNEL'S FIXED RULE: music in the cold open only (0 to the plan's cold_open_end_s), none in the body: "
                  "cues for the cold open's sections only." if only_cold else ""),
               [{"name": "M1_cold_open", "seconds": 90, "prompt": "...", "seed": 42}], read=[p.decisions / "montage" / "plan.json"],
               schema=SCHEMA_CUES, docs=["monteer/music/music.py", "monteer/montage/mix.py"], fallback=lambda: plan_cues(p, only_cold))
    out = p.asset_dir("music")
    out.mkdir(parents=True, exist_ok=True)
    if p.profile:                      # channel episodes: the library's downloaded tracks only, nothing generated (19 Oct 2026)
        from . import steps_phrase
        return steps_phrase.pick_music(p, cues)
    for c in cues:
        wav = out / f"{c['name']}.wav"
        if done(wav):
            print("music:", c["name"], "already made")
            continue
        subprocess.run([str(CORE_PY), "-m", "monteer.music.music", "--seconds", str(c["seconds"]), "--out", str(wav), "--prompt", c["prompt"],
                        "--seed", str(c.get("seed", 42)), "--max-minutes", "45"], check=True, cwd=str(ENGINE), env=tool_env())


def popups_layout(p):
    from .steps_popups import on
    return on(p)


def step_sources(p):
    if popups_layout(p):
        from . import steps_popups
        return steps_popups.step_sources(p, ask)
    if phrase_mode(p):
        from . import steps_phrase
        return steps_phrase.step_sources(p, words(p), narration_length(p))
    from .sources import fetch_all, search
    if brain.brain_name(p) == "claude-code":       # a person in a session chooses the ids as before (and the tests replay that)
        assets = ask(p, "sources", "assets", "The footage and archive photos the plan needs: stock clip ids (Pexels/Pixabay), archive "
                     "photos (public domain, CC0, CC BY or US federal works only; no ShareAlike, NonCommercial or NoDerivatives).",
                     {"stock": [{"id": 0, "title": "", "for": "", "source": "pexels"}], "photos": [{"key": "", "title": "File:...", "page": "", "licence": "", "author": ""}]},
                     read=[p.decisions / "montage" / "plan.json"], fallback={"stock": [], "photos": []})
        return fetch_all(p, assets)
    plan = decision(p, "montage", "plan")
    queries = search.queries_from_plan(plan, cap=not p.profile)     # a channel episode: every search word the plan asks
    if not (queries["stock"] or queries["photos"]):
        queries = ask(p, "sources", "search", "English search words for the footage and archive photos the plan needs.",
                      {"stock": [{"query": "", "for": ""}], "photos": [{"query": "", "for": ""}]},
                      read=[p.decisions / "montage" / "plan.json"], schema=SCHEMA_SEARCH, fallback={"stock": [], "photos": []})
    from .sources import magnific as _mg
    _mg.episode_reading(p, "before searching")     # owner, 22 Oct 2026: the balance read before any Magnific call of this run
    cand = search.candidates(p, queries)            # free sources only, searched in code: Pixabay API (key), the local library, free photo sources
    if presenter_mode(p):                           # no flags, no brands, unless the profile allows them (montage/place.py)
        from .place import allowed, candidate_problem
        ok = allowed(p)
        for kind, txt in (("stock", lambda c: c.get("tags", "") + " " + c.get("title", "")),
                          ("photos", lambda c: c.get("title", ""))):
            cand[kind] = {q: [c for c in v if not candidate_problem({}, txt(c), *ok)] for q, v in cand[kind].items()}
        save_json(M(p, "candidates.json"), cand)

    blocks = {}
    if p.profile and presenter_mode(p):            # owner's fix 2 of 21 Oct 2026: the picker sees each block's pictures
        blocks = search.by_block(plan, queries, cand)
        save_json(M(p, "candidates_by_block.json"), blocks)
        sheets = search.pick_sheets(blocks, cand, M(p, "pick_sheets"))
        print(f"sources: {sum(len(q.get('blocks', [])) for q in queries['stock'] + queries['photos'])} searches for "
              f"{len(blocks)} footage blocks; {len(sheets)} pick sheets", flush=True)

    def check(d):
        ok_v = {c["id"] for v in cand["stock"].values() for c in v}
        ok_p = {c["title"] for v in cand["photos"].values() for c in v}
        bad = [x["id"] for x in d["stock"] if x["id"] not in ok_v] + [x["title"] for x in d["photos"] if x["title"] not in ok_p]
        if bad:
            raise ValueError(f"these are not among the candidates: {bad[:8]}")
        if blocks:                     # a pick belongs to a block whose own searches found it
            wrong = search.wrong_block(blocks, d)
            if wrong:
                raise ValueError("these picks were not found by their block's own searches (candidates_by_block.json): pick for "
                                 "each block only from its own candidates: " + "; ".join(wrong[:10]))

    def settle(d):                     # a channel episode's last resort (ask): a pick not among the candidates is left out
        ok_v = {c["id"] for v in cand["stock"].values() for c in v}
        ok_p = {c["title"] for v in cand["photos"].values() for c in v}
        out = dict(d, stock=[x for x in d["stock"] if x["id"] in ok_v], photos=[x for x in d["photos"] if x["title"] in ok_p])
        return out, [f"{x.get('id', x.get('title'))}: not among the candidates, left out"
                     for x in d["stock"] + d["photos"] if x not in out["stock"] + out["photos"]]
    from .sources import magnific, storyblocks
    schema_assets, mg_text = SCHEMA_ASSETS, ""
    from .sources import free_archive as FA
    paid = (["magnific"] if magnific.on(p) else []) + (["storyblocks"] if storyblocks.on(p) else []) + \
        (["archive", "commons_video"] if FA.on(p) else [])         # the free archive's films (owner's fix 3)
    from .targets import video_first
    R = video_first(p)
    vf_text = (" VIDEO FIRST (this channel, owner's decision): choose video clips for at least {:.0%} of the footage, photos only "
               "for what no clip shows.".format(R["video_min"]) if R else "")
    if paid:                           # the channel's paid clips are candidates too: ids "mg<number>" / "sb<number>"
        it = SCHEMA_ASSETS["properties"]["stock"]["items"]
        schema_assets = dict(SCHEMA_ASSETS, properties=dict(SCHEMA_ASSETS["properties"], stock=dict(SCHEMA_ASSETS["properties"]["stock"], items=dict(
            it, properties=dict(it["properties"], id={"type": ["integer", "string"]}, source={"type": "string", "enum": ["pixabay"] + paid})))))
        real = [x for x in paid if x in ("magnific", "storyblocks")]
        mg_text = (((" Stock candidates with source " + " or ".join(real) + " (ids \"mg<number>\" / \"sb<number>\") are the channel's "
                     "paid clips: give their id exactly as a string and their source.") if real else
                    " Give a non-Pixabay candidate's id exactly as a string, with its source.")
                   + (" PREFER the storyblocks clips (the company's library) wherever one shows the idea." if "storyblocks" in paid else "")
                   + (" Candidates with source archive or commons_video are REAL ARCHIVE FILM of the past (Internet Archive "
                      "newsreels and US federal films, Wikimedia Commons; free, licences checked): for an archive shot, the "
                      "film of that event or time is the first choice; never use them for today." if "archive" in paid else ""))
    read_pick = [p.decisions / "montage" / "plan.json", M(p, "candidates.json")]
    if blocks:                         # each block's candidates with their pictures; a pick names the block it is for
        it = schema_assets["properties"]["stock"]["items"]
        ip = schema_assets["properties"]["photos"]["items"]
        schema_assets = dict(schema_assets, properties=dict(schema_assets["properties"],
            stock=dict(schema_assets["properties"]["stock"], items=dict(it, required=it["required"] + ["block"], properties=dict(it["properties"], block=INT))),
            photos=dict(schema_assets["properties"]["photos"], items=dict(ip, required=ip["required"] + ["block"], properties=dict(ip["properties"], block=INT)))))
        mg_text += (" DIFFERENT SUBJECTS (owner's decision): the same landmark, person or object at most 3 times in the episode, "
                    "however many clips show it.")
        mg_text += (" PICK BLOCK BY BLOCK, LOOKING AT THE PICTURES (owner's decision): candidates_by_block.json lists each footage "
                    "block of the plan (its index, in/out, what it shows) with the candidates ITS OWN searches found; "
                    "pick_sheets/block_<index>.jpg shows their preview pictures labelled with their ids (read every sheet). For "
                    "each block choose, from its own candidates only, clips whose PICTURE shows what its sentences say (read "
                    "sentences.json for the words): people when people are spoken of, the event when an event is spoken of, never "
                    "a pretty view in place of the thing said. Give each pick the \"block\" index it is for. Choose about one "
                    "clip per sentence of the block, all different.")
        read_pick += [M(p, "candidates_by_block.json"), M(p, "sentences.json")] + [sheets[k] for k in sorted(sheets, key=int)]
    assets = ask(p, "sources", "assets", "Choose the footage and archive photos the plan needs, ONLY from the candidates file (found in code "
                 "on free sources whose licences pass the gate). Prefer clips that show exactly what the block says; "
                 + ("avoid recognisable faces of private people (flags and brand logos are allowed in real footage and photos). "
                    if any(place_allowed(p)) else "avoid logos, brand names, recognisable faces of private people. ")
                 + "Photo keys: short, unique, ASCII." + mg_text + vf_text
                 + (" With presenter (Phase 2): MOVING FOOTAGE FIRST: choose video clips wherever they show the idea, photos only "
                    "for specific past events, places and documents; choose enough DIFFERENT clips that no picture repeats in a "
                    "block (one file at most twice in the video)." if presenter_mode(p) else "")
                 + (" ARCHIVE FILM FIRST (owner's decision of 22 Oct 2026): where a block asks for [archive film] of a past event, "
                    "pick the real archive films its candidates offer (source \"archive\" or \"commons_video\", a newsreel or film "
                    "of those years, listed first): a long film is cut into its scenes in code, so one film serves the whole "
                    "stretch; today's stock stands in only where no archive film fits." if (p.profile_montage().get("sources") or {}).get("archive") else ""),
                 {"stock": [{"id": 0, "title": "", "for": "", "source": "pixabay"}], "photos": [{"key": "", "title": "(a candidate's title, exactly)", "page": "", "licence": "", "author": ""}]},
                 read=read_pick, schema=schema_assets,
                 docs=["monteer/montage/sources/__init__.py"], check=check, settle=settle, fallback={"stock": [], "photos": []})
    paid_by_id = {c["id"]: c for v in cand["stock"].values() for c in v if c.get("source") in ("magnific", "storyblocks", "archive", "commons_video")}
    for it in assets.get("stock", []):             # a paid clip's page, author, plan and format for its credits record
        c = paid_by_id.get(it.get("id"))
        if c and c["source"] in ("archive", "commons_video"):      # a free archive film: what its download needs
            it.update({k: c[k] for k in ("source", "ident", "title", "licence", "page", "collection", "url", "author") if k in c})
        elif c and c["source"] == "magnific":
            it.update(source="magnific", page=c.get("page", ""), user=c.get("user", ""), premium=c.get("premium"))
        elif c:
            it.update(source="storyblocks", page=c.get("page", ""), title=c.get("title", ""), format=c.get("format", "1080p"), mb=c.get("mb"))
    by_title = {c["title"]: c for v in cand["photos"].values() for c in v}
    for it in assets.get("photos", []):            # where the chosen photo comes from (the brain names it by its title)
        c = by_title.get(it.get("title"))
        if c:
            it.update({k: c[k] for k in ("src", "id", "full", "code", "source") + (("page", "licence", "author") if c.get("src") == "commons" else ())
                       if k in c})
    magnific.episode_reading(p, "before downloads")   # the credit balance around the downloads (usage view)
    if blocks:                         # what each picked file was found for: the cut list may use it there only
        save_json(M(p, "asset_for.json"), asset_for(plan, blocks, assets))
    fetch_all(p, assets)
    if blocks:                         # an archive film cut into its scenes: each scene found for the film's blocks
        af = load_json(M(p, "asset_for.json"))
        for code, rec in list(af.items()):
            if code.startswith("S:"):
                for seg in sorted(p.asset_dir("library").glob(f"{code[2:]}_[0-9][0-9].mp4")):
                    af[f"S:{seg.stem}"] = dict(rec)
        save_json(M(p, "asset_for.json"), af)
    magnific.episode_reading(p, "episode end")


def asset_for(plan, blocks, assets):
    """each picked file's code -> the plan blocks whose own searches found it, with their time ranges (owner's fix 2 of
    21 Oct 2026: the cut list refuses a picture found for another part of the episode)"""
    out = {}
    from .sources.free_archive import _key as fa_key
    for kind, code in (("stock", lambda x: f"S:{fa_key(x)}" if x.get("source") in ("archive", "commons_video") else f"V:{x['id']}"),
                       ("photos", lambda x: f"P:{x.get('key')}")):
        for x in assets.get(kind, []):
            k = x["id"] if kind == "stock" else x["title"]
            found = sorted({int(i) for i, b in blocks.items() if k in b[kind]})
            out[code(x)] = {"blocks": found, "picked_for": x.get("block"), "for": x.get("for", ""),
                            "ranges": [[blocks[str(i)]["in"], blocks[str(i)]["out"]] for i in found]}
    return out


def step_ai_images(p):
    if popups_layout(p):               # the pop-up layout shows real pictures only (flags, maps, photos): no drawn images
        return
    from .targets import rules_of
    R = rules_of(p)
    if R and not R["ai"]:              # the channel uses no drawn images (owner's decision of 20 Oct 2026): none made or asked
        from . import steps_phrase
        if phrase_mode(p):
            step_review(p)                   # the clips are still looked at here (a rejected clip's shot is planned again)
        steps_phrase.code_decision(p, "ai", "prompts", {}, "this channel uses no drawn images (montage.footage.ai_images false)")
        steps_phrase.code_decision(p, "ai", "pick", {}, "this channel uses no drawn images")
        print("ai images: none (this channel uses no drawn images)")
        return
    if phrase_mode(p):
        from . import steps_phrase
        step_review(p)                       # look at the clips first: a rejected clip's shot gets an AI image instead
        prompts = steps_phrase.ai_prompts(p)
    else:
        prompts = ask(p, "ai", "prompts", "Prompts for AI images: generic scenes only, never a specific real event; clearly an image, "
                      "not a news photo. Keys: short ASCII names. At most 8 images (they are made on this computer's CPU)."
                      + (" With presenter (Phase 2): drawn images are stills, so only where nothing real can be filmed, at most "
                         "the plan's mix_targets ai_max; no flags, no logos." if presenter_mode(p) else ""),
                      {"KEY": {"prompt": "", "why": ""}}, read=[p.decisions / "montage" / "plan.json"], schema=SCHEMA_PROMPTS,
                      docs=["monteer/ai/images.py"], fallback={})
    if prompts:
        subprocess.run([str(ML_PY), "-m", "monteer.ai.images", str(p.folder)], check=True, cwd=str(ENGINE), env=tool_env())
    made = sorted(p.asset_dir("ai").glob("*_s*.png")) if p.asset_dir("ai").exists() else []
    if made:                                     # after looking at every image: which seed of each key is used
        seeds = {}
        for f in made:
            k, sd = f.stem.rsplit("_s", 1)
            seeds.setdefault(k, set()).add(int(sd))

        def check(d):
            bad = [k for k, v in d.items() if k not in seeds or v["seed"] not in seeds[k]]
            if bad:
                raise ValueError(f"unknown key or seed: {bad}; made: { {k: sorted(v) for k, v in seeds.items()} }")

        def settle(d):                 # a channel episode's last resort (ask): an unknown key or seed is not used
            bad = [k for k, v in d.items() if k not in seeds or v.get("seed") not in seeds[k]]
            return {k: v for k, v in d.items() if k not in bad}, [f"{k}: unknown key or seed, not used" for k in bad]
        def first():                   # a channel episode's fallback (ask): every image, its first version
            return {k: {"seed": min(v), "why": "the first version (the brain gave no usable answer)"} for k, v in seeds.items()}
        if p.profile and one_version(seeds):   # one version each: nothing to pick (owner's decision of 20 Oct 2026)
            from . import steps_phrase
            ctx = steps_phrase.pick_context(p) if phrase_mode(p) else \
                {k: {"prompt": v["prompt"], "for": v.get("why", "")} for k, v in (decision(p, "ai", "prompts", {}) or {}).items()}
            seeds = {k: v for k, v in seeds.items() if k in ctx}
            made = [f for f in made if f.stem.rsplit("_s", 1)[0] in seeds]
            steps_phrase.code_decision(p, "ai", "pick", look_at_drawn(p, "look", seeds, made, ctx),
                                       "one version of each drawn image: used unless the look (ai/look) found what must not be shown")
        elif phrase_mode(p):
            from . import steps_phrase
            ctx = steps_phrase.pick_context(p)
            made = [f for f in made if f.stem.rsplit("_s", 1)[0] in ctx]
            ask(p, "ai", "pick", "After looking at every AI image (read each file): for each key, the seed whose image SHOWS what its "
                "prompt and phrase ask for (context: the prompt and the phrase of each key). Leave a key out when neither image shows "
                "that idea, or has text, warped hands or faces, a flag, a logo or a brand name, or looks like a real news photo; for a "
                "key marked \"about Egypt\", also when it does not look like Egypt (owner's decisions of 16 Oct 2026).",
                {"KEY": {"seed": 11, "why": ""}}, read=made, schema=SCHEMA_PICK, check=check, extra={"context": ctx}, settle=settle,
                fallback=first)
        else:
            ask(p, "ai", "pick", "After looking at every AI image (read each file): the seed to use for each key (or leave a key out to not use "
                "it: anything with text, warped hands or faces, or that looks like a real news photo).",
                {"KEY": {"seed": 11, "why": ""}}, read=made, schema=SCHEMA_PICK, check=check, settle=settle, fallback=first)
    if phrase_mode(p):                                # shots still without a picture: planned again (decision 3a), then reuse
        from . import steps_phrase
        steps_phrase.replan_missing(p, ask, words(p), narration_length(p),
                                    lambda: subprocess.run([str(ML_PY), "-m", "monteer.ai.images", str(p.folder)], check=True, cwd=str(ENGINE), env=tool_env()),
                                    lambda: step_review(p))
        steps_phrase.reuse_fallback(p, ask, words(p), narration_length(p))


SCHEMA_LOOK = {"type": "object", "required": ["reject"], "properties": {"reject": {"type": "array", "items": {
    "type": "object", "required": ["key", "why"], "properties": {"key": STR, "why": STR}}}}}


def one_version(seeds):
    return bool(seeds) and all(len(v) == 1 for v in seeds.values())


def look_at_drawn(p, key, seeds, made, ctx):
    """a channel episode's drawn images, one version each (owner's decision of 20 Oct 2026, after a run stopped on the
    drawn-image pick): nothing is picked, the one version is used. Claude only looks once for what must not be shown
    (text, warped hands or faces, a flag, a logo …): one try, about a minute for up to 12 images; when it fails, every
    image is used and the log says so. -> {key: {"seed", "why"}} (ai/pick's shape)"""
    r = ask(p, "ai", key, "Look at every drawn image (read each file; the context gives each key's prompt and what it is for). Each "
            "is the only version made and is shown unless you list it here. List only the keys whose image must NOT be shown: it "
            "has text or letters, warped hands or faces, a flag, a logo or a brand name, looks like a real news photo, or plainly "
            "shows something other than its prompt; for a key marked \"about Egypt\", also when it does not look like Egypt. An "
            "empty list when every image can be shown. Answer with JSON only.",
            {"reject": [{"key": sorted(seeds)[0], "why": "…"}]}, read=made, schema=SCHEMA_LOOK, extra={"context": ctx},
            fallback={"reject": []}, once=True)
    rej = {x.get("key"): x.get("why", "") for x in r.get("reject", []) if isinstance(x, dict)}
    out = {}
    for k, v in sorted(seeds.items()):
        if k in rej:
            print(f"ai images: {k} not shown ({str(rej[k])[:120]}); its shot is planned again", flush=True)
        else:
            out[k] = {"seed": min(v), "why": "the only version"}
    print(f"ai images: {len(out)} of {len(seeds)} drawn image(s) used (one version each, no pick)", flush=True)
    return out


def step_textures(p):
    out = p.asset_dir("textures")
    if done(out / "paper.png") and done(out / "paper_overlay.png"):
        return
    subprocess.run([str(ML_PY), "-m", "monteer.montage.textures", str(out), str(p.opt("texture_seed", 73))], check=True, cwd=str(ENGINE), env=tool_env())


BEAT_SFX = ("whoosh_d", "whoosh_e", "riser_short", "tick", "projector")


def on_beat(p):
    """the channel places its effects on their moment, over speech (sound.placement "on_beat", owner's fix 8)"""
    from .structure import of as structure_of
    return bool(p.profile) and structure_of(p).placement == "on_beat"


def step_sfx(p):
    out = p.asset_dir("sfx")
    paper = paper_sfx(p)
    beat = [k for k in BEAT_SFX if on_beat(p) and not done(out / f"{k}.wav")]
    if beat and done(out / "sfx.json"):                    # the on-beat sounds, added to the effects already made
        subprocess.run([str(ML_PY), "-m", "monteer.montage.sfx", str(out), "--only"] + beat, check=True, cwd=str(ENGINE), env=tool_env())
    if done(out / "sfx.json"):
        if paper and not done(out / "paper.wav"):          # the channel's paper sound, added to the effects already made
            subprocess.run([str(ML_PY), "-m", "monteer.montage.sfx", str(out), "--only", "paper", "paper_b"], check=True, cwd=str(ENGINE),
                           env=tool_env())
        return
    subprocess.run([str(ML_PY), "-m", "monteer.montage.sfx", str(out)], check=True, cwd=str(ENGINE), env=tool_env())
    if paper:
        subprocess.run([str(ML_PY), "-m", "monteer.montage.sfx", str(out), "--only", "paper", "paper_b"], check=True, cwd=str(ENGINE),
                       env=tool_env())
    if on_beat(p):
        subprocess.run([str(ML_PY), "-m", "monteer.montage.sfx", str(out), "--only", *BEAT_SFX], check=True, cwd=str(ENGINE), env=tool_env())


def subtitles_on(p):
    from .subtitles import config
    return bool(config(p))


def paper_sfx(p):
    """the channel profile wants a paper sound on on-screen text (montage/structure.py sound.text_sfx)"""
    from .structure import of
    return of(p).text_sfx == "paper"


def step_review(p):
    """contact sheets of every downloaded clip (to choose usable windows and grades), then the clip_fx decision"""
    if popups_layout(p):               # no footage in the pop-up layout
        return
    from .review import contact_sheets
    sheets = contact_sheets(p.asset_dir("stock"), M(p, "review"))
    if (phrase_mode(p) or presenter_mode(p)) and p.asset_dir("library").exists():   # archive films and the owner's clips too
        sheets += contact_sheets(p.asset_dir("library"), M(p, "review_archive"))
    flags_ok, brands_ok = place_allowed(p)
    if flags_ok or brands_ok:                  # answer 12 of 18 Oct 2026: flags and brand logos allowed in real footage
        what = ("After looking at every clip's contact sheet (read each image): each clip's usable window in seconds "
                "(no watermarks, close-up faces of private people, black frames), optional crop and grade. Keys: the clip's id as "
                "in the sheet's file name. Set reject: true (with why) for a clip that is unusable or does not show anything worth "
                "seeing (mostly black, text or charts with foreign labels, watermarks). Flags and brand logos in the picture are "
                "allowed (owner, 18 Oct 2026).")
    else:
        what = ("After looking at every clip's contact sheet (read each image): each clip's usable window in seconds "
                "(no logos, close-up faces, brand signs, black frames), optional crop and grade. Keys: the clip's id as in the sheet's file name. "
                "Set reject: true (with why) for a clip that is unusable or does not show anything worth seeing (mostly black, text or "
                "charts with foreign labels, logos, watermarks).")
        if phrase_mode(p) or presenter_mode(p):    # owner's decisions of 16 Oct 2026 (the classic montage's request stays as it was)
            what += (" Also: no flag of any country in the window (reject a clip that shows one in every usable window), and no brand "
                     "name or logo even in part.")
    if p.profile and phrase_mode(p):   # a channel episode: only the clips not yet reviewed, a few at a time (19 Oct 2026)
        return review_new_clips(p, what)
    schema, fmt = SCHEMA_CLIPFX, {"CLIP_ID": {"win": [0.4, 9.0], "crop": [0, 0, 1], "grade": "mild"}}
    if p.profile:                      # owner's fix 9 of 21 Oct 2026: variety by subject, not only by file
        what += (" Give each clip its SUBJECT: the one main thing it shows, in 1-4 English words (a landmark, a person, an "
                 "object, a kind of place: «Big Ben», «Stormont», «Union Jack flag», «Derry aerial», «container ship»), the SAME "
                 "words for the same thing in different clips.")
        item = SCHEMA_CLIPFX["additionalProperties"]
        schema = dict(SCHEMA_CLIPFX, additionalProperties=dict(item, properties=dict(item["properties"], subject=STR)))
        fmt = {"CLIP_ID": dict(fmt["CLIP_ID"], subject="Big Ben")}
    ask(p, "montage", "clip_fx", what,
        fmt, read=sheets, schema=schema,
        docs=["monteer/montage/timeline.py", "monteer/montage/review.py", "monteer/montage/render.py"],
        # the sheets keep their names when clips are added: name the clips, so a new clip means a new review (phrase montage)
        extra={"context": {"clips": clip_ids(p)}} if phrase_mode(p) else None, fallback={})
    if presenter_mode(p):
        review_photos(p)


CLIP_BATCH = 24                         # clips per review request in a channel episode (4 sheets of 6 rows)


def review_new_clips(p, what):
    """a channel episode's clip review: the clips the review has not seen yet, CLIP_BATCH a request (each request: its
    clips' rows of three frames, about a minute of the brain), merged into the one montage/clip_fx decision the later
    steps read. Before (the first real test, 19 Oct 2026), every new clip sent all 172 clips again in one request of 33
    sheets: 6-8 min, twice an answer without JSON, once an answer of the wrong shape that stopped the run."""
    import hashlib
    from .review import contact_sheets, sheet_rows
    from .steps_phrase import code_decision
    rows = {}
    for d_, out in (("stock", "review"), ("library", "review_archive")):
        if p.asset_dir(d_).exists():
            contact_sheets(p.asset_dir(d_), M(p, out))          # makes each clip's row once (kept)
            rows.update({f.stem[4:]: f for f in M(p, out).glob("row_*.jpg")})
    have = decision(p, "montage", "clip_fx", {}) or {}
    have = have if isinstance(have, dict) else {}
    ids = [k for k in clip_ids(p) if k in rows]
    new = [k for k in ids if k not in have]
    merged = {k: v for k, v in have.items() if k in ids}
    for n0 in range(0, len(new), CLIP_BATCH):
        part = new[n0:n0 + CLIP_BATCH]
        tag = hashlib.sha256(" ".join(part).encode()).hexdigest()[:8]
        sheets = sheet_rows([rows[k] for k in part], M(p, "review_new", f"clips_{tag}"))

        def check(dd, part=part):
            bad = [k for k in dd if k not in part]
            if bad:
                raise ValueError(f"only these clips: {part}; not {bad[:6]}")

        def settle(dd, part=part):
            return {k: v for k, v in dd.items() if k in part}, [f"{k}: not one of the clips asked, left out" for k in dd if k not in part]
        got = ask(p, "montage", f"clip_fx_{tag}", what + " Answer for exactly these clips (context: clips); win in seconds "
                  "within the clip, crop [x, y, w] (the 16:9 window's left and top as shares of the frame, w its share of the width; "
                  "[0, 0, 1] = the whole frame), grade one of: mild, dark, none.",
                  {part[0]: {"win": [0.4, 9.0], "crop": [0, 0, 1], "grade": "mild"}}, read=sheets, schema=SCHEMA_CLIPFX,
                  extra={"context": {"clips": part}}, check=check, settle=settle, fallback={})
        merged.update({k: v for k, v in got.items() if k in part})
    if new or not (p.decisions / "montage" / "clip_fx.json").exists():
        code_decision(p, "montage", "clip_fx", merged, f"the clip review, {CLIP_BATCH} new clips a request (montage/clip_fx_<batch>)")
    print(f"clip review: {len(new)} new clip(s) looked at, {len(merged)} in all", flush=True)


def place_allowed(p):
    from .place import allowed
    return allowed(p)


def photo_rejects(p):
    """the archive photos rejected on sight (montage/photo_review); none when the profile allows flags and brand logos
    (answer 12 of 18 Oct 2026: an earlier rejection for a flag or a logo no longer holds)"""
    if all(place_allowed(p)):
        return {}
    return (decision(p, "montage", "photo_review", {}) or {}).get("reject", {})


def review_photos(p):
    """with presenter: the archive photos are chosen by their titles, so they are looked at here before use: numbered
    sheets of every downloaded photo; the brain rejects any that shows a flag, a logo or a brand name (owner's decisions
    of 16 Oct 2026) -> decision montage/photo_review {"reject": {key: why}}. Not asked when the profile allows both
    (answer 12 of 18 Oct 2026): this look is only for flags, logos and brand names."""
    if all(place_allowed(p)):
        return {}
    from .steps_phrase import sheet_of
    d = p.asset_dir("photos")
    keys = sorted(f.stem for f in d.glob("*.jpg")) if d.exists() else []
    if not keys:
        return {}
    sheets = []
    for n0 in range(0, len(keys), 12):
        part = keys[n0:n0 + 12]
        sheets.append(sheet_of([(d / f"{k}.jpg", k) for k in part], M(p, "review_photos", f"photos_{n0 // 12 + 1:02d}.jpg")))

    def check(dd):
        bad = [k for k in dd.get("reject", {}) if k not in keys]
        if bad:
            raise ValueError(f"unknown photo keys {bad}; the keys are {keys}")

    def settle(dd):                    # a channel episode's last resort (ask): a rejection naming no photo is dropped
        bad = [k for k in dd.get("reject", {}) if k not in keys]
        return dict(dd, reject={k: v for k, v in dd.get("reject", {}).items() if k in keys}), [f"{k}: no such photo" for k in bad]
    r = ask(p, "montage", "photo_review", "Look at every archive photo on these sheets (each labelled with its key). Reject (key: why) "
            "every photo that shows a FLAG of any country or union (also on a building or a banner), a logo or a brand name, even in "
            "part (owner's decisions of 16 Oct 2026). Keep the others. Answer with JSON only.",
            {"reject": {"KEY": "why"}}, read=sheets, extra={"context": {"photo_keys": keys}},
            schema={"type": "object", "required": ["reject"], "properties": {"reject": {"type": "object", "additionalProperties": STR}}},
            check=check, settle=settle,
            # nobody looked: the profile bans flags and logos, so no photo is shown (licence-safe and rule-safe)
            fallback=lambda: {"reject": {k: "not looked at (the brain gave no usable answer): left out" for k in keys}})
    return r.get("reject", {})


def clip_ids(p):
    out = []
    for d in ("stock", "library"):
        if p.asset_dir(d).exists():
            out += sorted(f.stem for f in p.asset_dir(d).glob("*.mp4"))
    return out


def step_timeline(p):
    if phrase_mode(p):
        from . import steps_phrase
        from .review import safe_grades
        return steps_phrase.step_timeline(p, words(p), narration_length(p), safe_grades(p, decision(p, "montage", "clip_fx", {})),
                                          decision(p, "ai", "pick", {}), M(p, "edl.json"))
    from . import timeline
    from . import graphics
    L = narration_length(p)
    wfile = V(p, "asr_large-v3.json") if p.mode == "voice_only" else p.output / "edl.json"
    if presenter_mode(p) and popups_layout(p):
        from . import steps_phrase, steps_popups
        steps_popups.step_timeline(p, words(p), L, steps_phrase.code_decision)
        return
    if presenter_mode(p):
        return step_timeline_presenter(p, L)
    have = assets_available(p)
    scenes = ask(p, "graphics", "scenes", "Our own graphics for the plan: the scene list for the renderer (cards, counters, maps, labels, "
                 "overlays). Only the episode's own words and numbers on screen. frames = round((t_out - t_in) * 24).",
                 [{"name": "", "t_in": 0, "t_out": 0, "frames": 0, "bg": "dark", "items": []}],
                 read=[p.decisions / "montage" / "plan.json", wfile], schema=SCHEMA_SCENES,
                 docs=["monteer/gfx/gfx.swift", "monteer/montage/graphics.py"], check=lambda sc: graphics.check(sc), fallback=[])
    d = ask(p, "montage", "timeline", "The cut list's blocks on the narration's timeline (see monteer/montage/timeline.py). Use only "
            f"the assets that exist (context) and the graphics scenes already decided. length_s = {L:.2f}.",
            {"length_s": 0, "blocks": [], "overlays": [], "strong_clicks": [], "paper_photos": []},
            read=[p.decisions / "montage" / "plan.json", p.decisions / "graphics" / "scenes.json", wfile], schema=SCHEMA_TIMELINE,
            docs=["monteer/montage/timeline.py"], extra={"context": have},
            check=lambda dd: timeline.build(p, dd, scenes, words(p), decision(p, "montage", "clip_fx", {}), decision(p, "ai", "pick", {})))
    timeline.build(p, d, scenes, words(p), decision(p, "montage", "clip_fx", {}), decision(p, "ai", "pick", {}), out=M(p, "edl.json"))


def step_timeline_presenter(p, L):
    """with presenter: the classic graphics and cut list (brain), checked for Ramadan's notes and decisions 2-3; B-roll
    edges snapped to sentence starts; footage changing at each sentence; transitions and the code's sound part"""
    from . import graphics, timeline
    from . import steps_presenter as SPR
    have = assets_available(p)
    W = words(p)
    plan = decision(p, "montage", "plan")
    read = [p.decisions / "montage" / "plan.json", M(p, "sentences.json"), M(p, "words.json")]
    lo, hi = SPR.TG.label_range(L)
    from . import general as GEN, learning, layout as LY
    prof = p.channel_profile() if p.profile else {}
    gfx_font = Path(prof["_folder"]) / prof["font"] if prof.get("font") else None
    said = LY.script_numbers([x["text"] for x in load_json(M(p, "sentences.json"))["sentences"]]) if p.profile else set()
    from . import gfx_policy as GP, labels as LB
    pol = GP.of(p)                     # the channel's graphics policy (owner, 22 Oct 2026); None: as before

    def check_scenes(sc):
        graphics.check(GEN.restyle(p, sc))
        SPR.check_spelling(p, sc)
        if pol:
            pr = GP.scene_problems(sc, L, pol)
            if pr:
                raise ValueError("the channel's graphics policy (montage/gfx_policy.py): " + "; ".join(pr[:12]))
        if p.profile:                  # owner's fix 7 of 21 Oct 2026: text against shapes, bars with the script's numbers
            pr = LY.problems(GEN.restyle(p, sc), gfx_font, said)
            if pr:
                raise ValueError("the graphics' layout (montage/layout.py): " + "; ".join(pr[:12]))

    def settle_scenes(sc):             # the last resort: only the scenes with a layout problem are left out (not drawn, not used)
        notes = []
        if pol:                        # and the graphics policy's: text-only cards out, re-hooks over the footage, the budget
            sc, notes = GP.settle_scenes(sc, L, pol)
        bad = set(LY.bad_scenes(GEN.restyle(p, sc), gfx_font, said))
        return [x for x in sc if x["name"] not in bad], notes + [f"scene {n} left out: its layout still breaks the rules" for n in sorted(bad)]
    scenes = ask(p, "graphics", "scenes", "Our own graphics for the plan: the scene list for the renderer (cards, counters, maps, labels, "
                 "overlays). Only the episode's own words and numbers on screen. frames = round((t_out - t_in) * 24). Video type: with "
                 f"presenter. Key-word labels (overlays on B-roll): between {lo} and {hi} in all (rule 11, about 1.3-1.8 a minute), each "
                 "starting on its word and staying about 6 s (t_out - t_in 5-7 s, owner's decision 1b); re-hooks are the narrator's own "
                 "questions. Every word on screen is spelled as in sentences.json (the approved script), never as whisper heard it in "
                 "words.json (code checks every Arabic word against the script)."
                 + (" THE INTRO HAS RUNNING SUBTITLES (the channel's): from 0 to the plan's intro_end_s the bottom of the frame "
                    "(y 860-1010) carries them, so any label or text there sits above y 820." if subtitles_on(p) else "")
                 + (" DOCUMENTED NEWS are shown only as real screenshots of their pages, made in code (scenes news_<id>): never design "
                    "a newspaper card, a masthead or a «المصدر» line, and name no scene news_…" if _news_mode(p) else "")
                 + GEN.scenes_text(p) + learning.request_text(p, "graphics/scenes") + (" " + LY.REQUEST if p.profile else "")
                 + (GP.text(L, pol) if pol else "") + (" " + LB.REQUEST if LB.of(p) else ""),
                 [{"name": "", "t_in": 0, "t_out": 0, "frames": 0, "bg": "dark", "items": []}],
                 read=read, schema=SCHEMA_SCENES,
                 docs=["monteer/gfx/gfx.swift", "monteer/montage/graphics.py"] + (["monteer/montage/general.py"] if GEN.bar_on(p) else [])
                 + (["monteer/montage/layout.py"] if p.profile else []),
                 check=check_scenes, settle=settle_scenes if p.profile else None, fallback=[])
    scenes = GEN.restyle(p, scenes)    # «عام»: its labels and re-hooks drawn as the caption bar (no change elsewhere)
    lbp = LB.of(p)
    if lbp:                            # owner, 22 Oct 2026: every label and re-hook on screen while its words are said (+ ~1 s)
        _rec0 = load_json(p.decisions / "graphics" / "scenes.json")
        if _rec0.get("brain_answer_before_retime"):      # always from the brain's own answer (a run's retiming is not a new answer)
            scenes = GEN.restyle(p, _rec0["brain_answer_before_retime"])
        said_words = LB.words_said(p)
        scenes, lnotes = LB.retime(scenes, said_words, lbp["while_said_s"])      # the brain's labels on their words first,
        if lbp.get("every_name"):                                                # then a label for each date still without one
            scenes, dnotes = LB.date_labels(scenes, load_json(M(p, "sentences.json"))["sentences"])
            scenes, more = LB.retime(scenes, said_words, lbp["while_said_s"])
            lnotes += dnotes + [x for x in more if x not in lnotes]
        from .maps import real_outlines        # and the maps drawn from the real outlines, their pins shown early
        scenes, mnotes = real_outlines(scenes)
        lnotes += mnotes
        f_sc = p.decisions / "graphics" / "scenes.json"
        rec = load_json(f_sc)
        if rec.get("decision") != scenes:
            rec.setdefault("brain_answer_before_retime", rec.get("decision"))
            rec.update(decision=scenes, retimed_by_engine=lnotes)
            save_json(f_sc, rec)
        for n_ in lnotes:
            print("labels:", n_, flush=True)
    news_ready = []
    if _news_mode(p):                  # the documented news' screenshot scenes, made in code where their line is said
        from . import news as NEWS
        news_ready = NEWS.presenter_scenes(p, W, L)
        save_json(NEWS.scenes_file(p), news_ready)
        scenes = [x for x in scenes if not x["name"].startswith("news_")] + news_ready
    st, sid = SPR.starts(p), SPR.sentence_ids(p)
    from .review import safe_grades
    fx, pick = safe_grades(p, decision(p, "montage", "clip_fx", {})), decision(p, "ai", "pick", {})
    AF = SPR.asset_for(p)              # a channel episode: what each picture was found for (owner's fix 2 of 21 Oct 2026)
    sheets = SPR.cut_sheets(p, AF) if AF else []

    def check(dd):
        d2 = SPR.snap_blocks(p, dd, L)
        edl = timeline.build(p, d2, scenes, W, fx, pick, sentences=st, sentence_ids=sid)
        probs = SPR.check_cut(p, d2, edl, L, scenes) + GEN.cut_problems(p, edl) + (GP.cut_problems(d2, edl, scenes, L, pol) if pol else [])
        if probs:
            raise ValueError("; ".join(probs))

    def repair(dd):                    # small fixes in code before asking again (owner, 20 Oct 2026; ask's repair)
        import copy
        dd, notes = copy.deepcopy(dd), []
        if pol:                        # the graphics policy: no G block held past its scene, re-hooks over the footage
            notes += GP.repair_blocks(dd, scenes, pol)
        notes += SPR.cold_open_repair(p, dd, SPR.STR.of(p), L, scenes)   # the presenter early and often (owner, 22 Oct 2026)
        sw = SPR.archive_swaps(p, dd.get("blocks", []), set(have["photos (P:<key> / PE:<key>)"]),
                               lambda bl: timeline.build(p, SPR.snap_blocks(p, dict(dd, blocks=bl), L), scenes, W, fx, pick, sentences=st, sentence_ids=sid)["shots"],
                               R=SPR.TG.rules_of(p))
        if sw:                         # a small archive shortfall: picked archive photos in place of stock clips (owner, 21 Oct 2026)
            dd["blocks"], more = sw
            notes += more
        if p.profile:                  # a clip the review rejected is left out of a block that has others (owner's fix 4)
            rej = SPR.video_rejects(p)
            for b in dd.get("blocks", []):
                if b[0] == "F":
                    keep = [a for a in b[1] if a.split("@")[0].split("|")[0].split(":", 1)[-1] not in rej]
                    if keep and len(keep) < len(b[1]):
                        notes.append(f"{', '.join(a for a in b[1] if a not in keep)}: rejected by the clip review, left out")
                        b[1] = keep
        if AF:                         # a block over one sentence only: its untagged pictures are for that sentence
            for b in dd.get("blocks", []):
                if b[0] == "F" and not any("@" in a for a in b[1]):
                    inside = [i for t, i in zip(st, sid) if b[2] - 0.2 <= t < b[3] - 0.5]
                    before = [i for t, i in zip(st, sid) if t <= b[2] + 0.2]
                    one = set(inside) | ({before[-1]} if before and not any(abs(t - b[2]) <= 0.2 for t in st) else set())
                    if len(one) == 1:
                        n = one.pop()
                        b[1] = [f"{a}@{n}" for a in b[1]]
                        notes.append(f"block {b[2]:.1f}-{b[3]:.1f} s covers sentence {n} only: its pictures tagged @{n}")
        edl = timeline.build(p, SPR.snap_blocks(p, dd, L), scenes, W, fx, pick, sentences=st, sentence_ids=sid)
        n = sum(1 for s in edl["shots"] if SPR.material_of(s) is not None)
        if "mix_targets" in dd:
            from .news import has_news as _has_news
            dd["mix_targets"], wrong = SPR.TG.computed(dd["mix_targets"], n, _has_news(p), SPR.TG.rules_of(p))
            if wrong:
                notes.append("mix_targets as computed for the cut list's own shots: " + ", ".join(wrong))
        rh = set(dd.get("rehook_scenes", []))
        t_in = {x["name"]: x.get("t_in", 0) for x in scenes}
        labels = sorted((x for x in dd.get("overlays", []) if x not in rh), key=lambda x: t_in.get(x, 0))
        over = len(labels) - SPR.TG.label_range(L)[1]
        if 0 < over <= 2 and not lbp:
            drop = set(labels[-over:])
            dd["overlays"] = [x for x in dd["overlays"] if x not in drop]
            notes += [f"key-word label {x} left out: {len(labels)} labels, at most {len(labels) - over}" for x in sorted(drop)]
        return dd, notes
    S = SPR.STR.of(p)
    schema = dict(SCHEMA_TIMELINE, required=SCHEMA_TIMELINE["required"] + ["intro_end_s", "mix_targets", "rehook_scenes"],
                  properties=dict(SCHEMA_TIMELINE["properties"], intro_end_s=NUM, mix_targets=SPR.TG.SCHEMA))
    fmt = {"length_s": 0, "intro_end_s": 0, "mix_targets": {"base_shots": 0, "stock_max": 0, "archive_min": 0, "news_min": 0, "max_run": 3, "ai_max": 0},
           "blocks": [], "overlays": [], "rehook_scenes": [], "strong_clicks": [], "paper_photos": []}
    if S.cold_open:                    # the channel's cold open: its end is part of the cut list too
        schema = dict(schema, required=schema["required"] + ["cold_open_end_s"], properties=dict(schema["properties"], cold_open_end_s=NUM))
        fmt = dict(fmt, cold_open_end_s=0)
    d = ask(p, "montage", "timeline", "The cut list's blocks on the video's timeline (see monteer/montage/timeline.py). Use only "
            f"the assets that exist (context) and the graphics scenes already decided. length_s = {L:.2f}. VIDEO TYPE: WITH "
            "PRESENTER: the presenter (punch-ins added in code) fills every stretch with no F or G block. Ramadan's notes: the "
            + SPR.timeline_note(S) +
            "block edges are moved to the nearest sentence start and footage changes at each sentence start (code). "
            + ("Key-word labels: EVERY label scene goes in overlays at its own time (code timed it to its words; over footage or "
               "the presenter alike). " if lbp else
               f"Key-word labels: overlays (not counting rehook_scenes) between {lo} and {hi}, each about 6 s and over B-roll only "
               "(put the label inside a B-roll block of at least 6 s). ") + "MOVING FOOTAGE FIRST (owner, Phase 2): in F blocks prefer V: and "
            "S: clips over P: photos and A: drawn images; FEWER REPEATS: list at least as many different assets as the block has "
            "shots; one file at most twice in the whole video, 60 s apart. "
            + SPR.TG.rule_text("presenter", SPR.TG.rules_of(p)) + GEN.timeline_text(p) + learning.request_text(p, "montage/timeline")
            + (GP.timeline_text(L, pol) if pol else "")
            + (" VIDEO FIRST (this channel): fill at least {:.0%} of the B-roll footage time with video clips (V:, S:), photos only "
               "where no clip shows the idea.".format(SPR.TG.video_first(p)["video_min"]) if SPR.TG.video_first(p) else "")
            + (" PICTURES MATCH THEIR SENTENCE (owner's decision): footage changes at each sentence start; write each F block's "
               "assets as V:<id>@<sentence i> (the \"i\" of sentences.json), one or more for EVERY sentence the block covers "
               "(a long sentence gets 2-3, shown in turn), choosing for each sentence a clip whose PICTURE shows what that sentence "
               "says: look at cut_sheets/block_<plan block>.jpg (each clip's frames, labelled with its code). asset_for.json gives "
               "the plan blocks and times each picture was found for: use a picture only there (code refuses one more than "
               f"{SPR.NEAR_PART:g} s outside them). Clips the clip review rejected are not offered." if AF else "")
            + (f" VARIETY BY SUBJECT (owner's decision): clip_fx.json gives each clip its subject; one subject at most "
               f"{SPR.SUBJECT_MAX} times in the whole video and never again within {SPR.SUBJECT_GAP:g} s, even from different "
               "files (code refuses more)." if AF else "")
            + " Each F block's assets are shown in the order listed, one per shot (in turn); "
            "V: is stock, P:/PE:/S: archive, A:/AE: ai, G scenes graphic. The same file at most twice within 75 s. Give mix_targets "
            "computed for the cut list's own B-roll shot count.",
            fmt, read=read + [p.decisions / "graphics" / "scenes.json"]
            + ([M(p, "asset_for.json"), p.decisions / "montage" / "clip_fx.json"] + sheets if AF else []), schema=schema,
            docs=["monteer/montage/timeline.py", "monteer/montage/steps_presenter.py", "monteer/montage/targets.py"],
            extra={"context": dict(have, **({"news screenshot scenes (G blocks; place each where its t_in/t_out say)": [
                {"name": x["name"], "t_in": x["t_in"], "t_out": x["t_out"]} for x in news_ready]} if news_ready else {}))}, check=check,
            repair=repair)
    if lbp:                            # every label in the cut list (code-made date labels too); over footage or the presenter
        lab_names = [x["name"] for x in scenes if LB.is_label(x) and not x["name"].startswith("rehook")]
        d = dict(d, overlays=list(dict.fromkeys(list(d.get("overlays", [])) + lab_names)))
    d2 = SPR.snap_blocks(p, d, L)
    if pol:                            # owner, 22 Oct 2026: every footage shot looked at against its sentence (shot_review.py)
        from . import shot_review as SR
        sents = load_json(M(p, "sentences.json"))["sentences"]

        def build_(dd):
            return timeline.build(p, SPR.snap_blocks(p, dd, L), scenes, W, fx, pick, sentences=st, sentence_ids=sid)

        def probs_(dd, e):             # the mix targets are bookkeeping, recomputed after the review (not a rule it breaks)
            d3 = SPR.snap_blocks(p, dd, L)
            return [x for x in SPR.check_cut(p, d3, e, L, scenes) + GP.cut_problems(d3, e, scenes, L, pol)
                    if not x.startswith("mix_targets are not computed")]
        d, rnotes = SR.review(p, d, build_, probs_, sents, ask)
        if "mix_targets" in d:
            from .news import has_news as _has_news
            n_ = sum(1 for s_ in build_(d)["shots"] if SPR.material_of(s_) is not None)
            d = dict(d, mix_targets=SPR.TG.computed(d["mix_targets"], n_, _has_news(p), SPR.TG.rules_of(p))[0])
        save_json(M(p, "shot_review.json"), rnotes)
        d2 = SPR.snap_blocks(p, d, L)
    edl = timeline.build(p, d2, scenes, W, fx, pick, sentences=st, sentence_ids=sid)
    clicks, whooshes = SPR.transitions(edl, d2, plan, S=S)
    save_json(M(p, "edl.json"), edl)
    R = SPR.TG.video_first(p)
    if R:                              # the channel's video rule on the cut list (said, never a stop)
        sh_, vp = SPR.TG.video_share(SPR.video_parts(edl["shots"]), R, "the cut list's B-roll footage")
        save_json(M(p, "video_share.json"), {"share": round(sh_, 3), "min": R["video_min"], "ok": not vp})
        print(f"video share: {sh_:.0%} of the B-roll footage time (this channel wants at least {R['video_min']:.0%})", flush=True)
    ps = {"intro_clicks": clicks, "whooshes": whooshes, "intro_end_s": d2["intro_end_s"], "timeline_snapped": d2}
    if S.cold_open:
        ps["cold_open_end_s"] = d2.get("cold_open_end_s")
    save_json(M(p, "presenter_sound.json"), ps)


def assets_available(p):
    """what the timeline may use: codes as timeline.py names them"""
    out = {"stock (V:<id>)": sorted(f.stem for f in p.asset_dir("stock").glob("*.mp4")) if p.asset_dir("stock").exists() else [],
           "photos (P:<key> / PE:<key>)": sorted(f.stem for f in p.asset_dir("photos").glob("*.jpg")) if p.asset_dir("photos").exists() else [],
           "library (S:<key>)": sorted(f.stem for f in p.asset_dir("library").glob("*.mp4")) if p.asset_dir("library").exists() else []}
    pick = decision(p, "ai", "pick", {})
    out["ai images (A:<key> / AE:<key>)"] = sorted(pick)
    if presenter_mode(p):              # photos rejected on sight (a flag, a logo, a brand) are not offered
        rej = photo_rejects(p)
        out["photos (P:<key> / PE:<key>)"] = [k for k in out["photos (P:<key> / PE:<key>)"] if k not in rej]
        out["photos rejected on sight (never use)"] = rej
        if p.profile:                  # and, in a channel episode, the clips the clip review rejected (owner's fix 4)
            from .steps_presenter import video_rejects
            vr = video_rejects(p)
            out["stock (V:<id>)"] = [k for k in out["stock (V:<id>)"] if k not in vr]
            out["library (S:<key>)"] = [k for k in out["library (S:<key>)"] if k not in vr]
            if vr:
                out["clips rejected on sight (never use)"] = vr
    return out


def window_frames(p):
    w = p.opt("render_window")
    return (int(round(w[0] * FPS)), int(round(w[1] * FPS))) if w else None


def step_graphics(p):
    from . import general as GEN, graphics
    scenes = GEN.restyle(p, decision(p, "graphics", "scenes"))     # «عام»: its caption bar (no change elsewhere)
    if _news_mode(p) and presenter_mode(p):         # the presenter type's news screenshots (montage/news.py)
        from . import news as NEWS
        if NEWS.scenes_file(p).exists():
            scenes = [x for x in scenes if not x["name"].startswith("news_")] + load_json(NEWS.scenes_file(p))
    only = None
    win = window_frames(p)
    if win:                                        # a preview renders only the graphics it shows
        edl = load_json(M(p, "edl.json"))
        sh = [s for s in edl["shots"] if s["f1"] > win[0] and s["f0"] < win[1]]
        only = {s["scene"] for s in sh if s["kind"] == "gfx"} | {o["name"] for s in sh for o in s.get("overlays", [])}
    prof = p.channel_profile()
    font = Path(prof["_folder"]) / prof["font"] if prof.get("font") else None
    if popups_layout(p) or any(x.get("art") for x in scenes):   # اقتصاد احمس (both types): waving flags and striped reveals drawn
                                                                 # frame by frame first (kept by the renderer)
        from . import popup_art
        popup_art.render([x for x in scenes if not only or x["name"] in only], M(p, "gfx", "frames"))
    graphics.render(scenes, M(p, "gfx", "frames"), font=font, only=only)


def renderer(p):
    from .render import Renderer
    ins = p.cfg.get("inputs", {}).get("insert")
    insert = {k: str(p.resolve(v)) for k, v in ins.items()} if ins else None
    return Renderer(M(p, "seg"), M(p, "gfx", "frames"), p.asset_dir("textures"), insert=insert,
                    presenter_video=p.output / f"cut_v{int(p.opt('version', 1))}.mp4")


def step_parallax(p):
    """drawn (AI) stills of the phrase montage as 2.5D camera moves (Depth Anything V2 Small, on the CPU)"""
    edl = M(p, "edl.json")
    if any(s.get("parallax") for s in load_json(edl)["shots"]):
        subprocess.run([str(ML_PY), "-m", "monteer.ai.parallax", str(edl)], check=True, cwd=str(ENGINE), env=tool_env())


def step_shots(p):
    from . import render
    edl = load_json(M(p, "edl.json"))
    win = window_frames(p)
    only = {i for i, s in enumerate(edl["shots"]) if s["f1"] > win[0] and s["f0"] < win[1]} if win else None
    probs = render.precheck(renderer(p), edl, only)          # every problem at once, before rendering (answer 5a, 19 Oct)
    if probs:
        for i, t, why in probs:
            print(f"   shot {i} at {t:.1f} s: {why}")
        raise SystemExit(f"the material of {len(probs)} shot(s) cannot be rendered (listed above); nothing was rendered")
    bad = render.segments(renderer(p), edl, M(p), only=only)
    if bad:
        raise SystemExit(f"{len(bad)} pieces failed")


def step_join(p):
    from . import render
    edl = load_json(M(p, "edl.json"))
    win = window_frames(p)
    if win:
        idx = [i for i, s in enumerate(edl["shots"]) if s["f1"] > win[0] and s["f0"] < win[1]]
        sub = {"fps": FPS, "total_frames": sum(edl["shots"][i]["nframes"] for i in idx), "shots": [edl["shots"][i] for i in idx]}
        r = renderer(p)
        tmpseg = M(p, "seg_window")
        if tmpseg.exists():
            shutil.rmtree(tmpseg)
        tmpseg.mkdir()
        for k, i in enumerate(idx):
            os.link(r.SEG / f"{i:04d}.mp4", tmpseg / f"{k:04d}.mp4")
        r.SEG = tmpseg
        render.join(r, sub, M(p, "video_window.mp4"))
        save_json(M(p, "window.json"), {"first_frame": edl["shots"][idx[0]]["f0"], "frames": sub["total_frames"], "shots": idx})
        return
    render.join(renderer(p), edl, M(p, "video.mp4"))


def cue_name(m):
    return re.sub(r"[^A-Za-z0-9_]+", "_", str(m)).strip("_")[:40]


def plan_cues(p, only_cold=False):
    """a channel episode's music cues when the brain gave none it can use (ask's fallback): one per music name in the
    plan's blocks (in the cold open only when the channel says so), its section as the mood"""
    plan = decision(p, "montage", "plan", {}) or {}
    end = plan.get("cold_open_end_s") if only_cold else None
    out = {}
    for b in plan.get("blocks", []):
        if not b.get("music") or (end is not None and b["in"] >= end):
            continue
        c = out.setdefault(cue_name(b["music"]), {"name": cue_name(b["music"]), "seconds": 0, "prompt": b.get("section") or b["music"], "seed": 42})
        c["seconds"] = max(10, min(90, round(c["seconds"] + b["out"] - b["in"])))
    return list(out.values()) or [{"name": "M1", "seconds": 90, "prompt": "calm documentary background", "seed": 42}]


def plan_sound(p, cues):
    """a channel episode's sound plan when the brain gave none it can use (ask's fallback): the plan's blocks' music
    under the voice, no stops or effects (the code's own sound parts are added after, as always)"""
    secs = []
    for b in (decision(p, "montage", "plan", {}) or {}).get("blocks", []):
        name = cue_name(b.get("music") or "")
        if name not in cues:
            continue
        if secs and secs[-1]["music"] == name and abs(secs[-1]["to"] - b["in"]) < 0.5:
            secs[-1]["to"] = b["out"]
        else:
            secs.append({"music": name, "from": b["in"], "to": b["out"]})
    return {"length_s": round(narration_length(p), 3), "music_gain_db": -11.6, "sections": secs, "stops": [], "hits": [], "pops": [],
            "whoosh_scenes": [], "whoosh_extra": []}


def step_mix(p):
    from . import mix
    if phrase_mode(p):
        d = decision(p, "montage", "sound")
    else:
        d = None
    cues = [f.stem for f in p.asset_dir("music").glob("*.wav")] if p.asset_dir("music").exists() else []
    if p.profile:                      # a channel episode's cues set aside (<name>.rejected_words_…) are not offered
        cues = [c for c in cues if "." not in c]
    from .structure import of as structure_of
    only_cold = structure_of(p).music_where == "cold_open_only"
    S_ = structure_of(p)
    if not d and S_.music_where == "none" and S_.effects == "none":   # nothing to decide: the voice alone (اقتصاد احمس, measured)
        d = {"length_s": round(narration_length(p), 3), "music_gain_db": -11.6, "sections": [], "stops": [], "hits": [], "pops": [],
             "whoosh_scenes": [], "whoosh_extra": []}
    d = d or ask(p, "montage", "sound", "The sound plan: music sections, stops before key facts, hits, pops, whooshes (see monteer/montage/mix.py). "
            f"length_s = {narration_length(p):.2f}; music cues made: {cues}."
            + (" THE CHANNEL'S FIXED RULE: music in the cold open only (0 to the plan's cold_open_end_s), none after it (code "
               "also ends it there)." if only_cold else ""),
            {"length_s": 0, "music_gain_db": -11.6, "sections": [], "stops": [], "hits": [], "pops": [], "whoosh_scenes": [], "whoosh_extra": []},
            read=[p.decisions / "montage" / "plan.json", p.decisions / "graphics" / "scenes.json",
                  V(p, "asr_large-v3.json") if p.mode == "voice_only" else M(p, "words.json") if presenter_mode(p) else p.output / "edl.json"],
            schema=SCHEMA_SOUND, docs=["monteer/montage/mix.py", "monteer/montage/sfx.py"], fallback=lambda: plan_sound(p, cues))
    if presenter_mode(p):              # the code's part: intro clicks, whooshes on transitions, pops on labels (Ramadan's notes)
        from . import steps_presenter as SPR
        d = SPR.sound_additions(p, d, load_json(M(p, "edl.json")), decision(p, "graphics", "scenes"), decision(p, "montage", "timeline"))
    from .structure import apply_to_sound           # the channel profile: music in the cold open only, dips around its clips
    d = apply_to_sound(p, d, load_json(M(p, "edl.json")))
    voice = V(p, "audio48.wav") if p.mode == "voice_only" else p.work / "cut_audio48.wav"
    if p.mode != "voice_only" and p.profile:          # the finished cut's own sound, made again for a new version's cut
        from .voice_chain import cut_voice
        cut_voice(p)
    if p.mode != "voice_only" and not done(voice):     # the finished cut's own sound, unchanged
        with atomic(voice) as tmp:
            subprocess.run([str(FFMPEG), "-v", "error", "-y", "-i", str(p.output / f"cut_v{int(p.opt('version', 1))}.mp4"), "-vn", "-ac", "2",
                            "-ar", "48000", "-c:a", "pcm_s24le", str(tmp)], check=True)
    if _camera_voice(p) and done(_clean_out(p)):    # every channel episode's voice, processed as measured (montage/voice_chain.py)
        voice = _clean_out(p)
    mix.mix(voice, words(p), load_json(M(p, "edl.json")), d, p.asset_dir("music"), p.asset_dir("sfx"), M(p, "mix.wav"), M(p, "mix_plan.json"),
            target_lufs=MIX_LUFS if p.profile else None)


MIX_LUFS = -15.0               # a channel episode's finished sound (Ramadan's episodes -14.0 to -15.7); the classic tests as before


def _camera_voice(p):
    """every channel episode's voice is processed (owner, 21 Oct 2026; the name is from when it was the camera mic only)"""
    from .voice_chain import auto_voice
    return auto_voice(p)


def _clean_out(p):
    from .voice_chain import clean_out
    return clean_out(p)


def _voice_sig(p=None):
    """the voice processing's own code and the channel's reference sound (a new reference processes the voice again)"""
    from .voice_chain import AUTO_SIG, reference
    return AUTO_SIG + "|" + json.dumps(reference(p) if p is not None else {}, sort_keys=True, ensure_ascii=False)


def out_name(p):
    slug = p.opt("output_name", "video")
    win = p.opt("render_window")
    if win:
        return p.output / f"{slug}_preview_{win[0]:g}-{win[1]:g}.mp4"
    return p.output / f"{slug}_v{int(p.opt('version', 1))}.mp4"


def step_final(p):
    from . import render
    if phrase_mode(p) and p.channel and not p.opt("render_window"):
        from . import build, steps_phrase
        build.record_variety(p, p.channel / "style_ledger.json", steps_phrase.style(p))
    win = window_frames(p)
    prof = p.channel_profile()
    overlays = [dict(o, file=str(Path(prof["_folder"]) / o["file"])) for o in prof.get("corner_overlays", [])]
    from . import structure, subtitles
    edl = load_json(M(p, "edl.json"))
    subs = []                          # the intro's running subtitles (montage/subtitles.py; the channel profile's)
    if subtitles.config(p):
        subs = subtitles.build(p, words(p), structure.anchors(p, edl).get("intro_end") or 0, M(p, "subtitles"), M(p, "subtitles.json"))
    if win:
        w = load_json(M(p, "window.json"))
        a = M(p, "mix_window.wav")
        t0, dur = w["first_frame"] / FPS, w["frames"] / FPS
        with atomic(a) as tmp:
            subprocess.run([str(FFMPEG), "-v", "error", "-y", "-ss", f"{t0:.6f}", "-t", f"{dur:.6f}", "-i", str(M(p, "mix.wav")), "-c:a", "pcm_s24le", str(tmp)], check=True)
        subs = [dict(o, **{"from": max(0.0, o["from"] - t0), "to": o["to"] - t0}) for o in subs if o["to"] > t0 and o["from"] < t0 + dur]
        render.final(M(p, "video_window.mp4"), a, out_name(p), crf=int(p.opt("crf", 20)), preset=final_preset(p), overlays=overlays + subs)
        return
    overlays += series_tag(p, prof)
    if structure.splices(p, edl):      # the channel's own clips (sting, intro clip, ad, outro): montage/structure.py
        pieces, hide = structure.assemble(p, edl, M(p, "mix.wav"), load_json(M(p, "mix_plan.json")), M(p, "mix_finished.wav"),
                                          M(p, "splices.json"))
        rows = load_json(M(p, "splices.json"))["clips"]
        overlays += [dict(o, **{"from": structure.to_finished(o["from"], rows), "to": structure.to_finished(o["to"], rows)}) for o in subs]
        render.final_spliced(M(p, "video.mp4"), M(p, "mix_finished.wav"), out_name(p), pieces, crf=int(p.opt("crf", 20)), preset=final_preset(p),
                             overlays=overlays, hide=hide)
        return
    if M(p, "splices.json").exists():                # a clip no longer applies: the self-check must not use an old record
        M(p, "splices.json").unlink()
    render.final(M(p, "video.mp4"), M(p, "mix.wav"), out_name(p), crf=int(p.opt("crf", 20)), preset=final_preset(p), overlays=overlays + subs)


def final_preset(p):
    """x264's speed for the finished video: "fast" for a channel episode (owner's decision 10 of 19 Oct 2026, about 5-8
    min less for 16 min, a slightly larger file), "medium" for the classic tests (their results stay the same)"""
    return p.opt("final_preset", "fast" if p.profile else "medium")


def final_sig(p):
    """what of the channel profile the finished video is made from (its corner overlays, clips, series tag, the ad)"""
    if not p.profile:
        return ""
    prof = p.channel_profile()
    st = ((prof.get("montage") or {}).get("structure") or {}).get("identity_clips")
    sub = (p.profile_montage().get("text") or {}).get("subtitles")
    if not (prof.get("corner_overlays") or st or p.opt("series_tag") or p.input("ad") or (sub or {}).get("intro")):
        return ""                      # nothing the profile adds (general «عام»): the step's fingerprint stays as it was
    return json.dumps([prof.get("corner_overlays"), st, p.opt("series_tag"), str(p.input("ad") or "")]
                      + ([sub, str(p.input("script") or "")] if (sub or {}).get("intro") else []), sort_keys=True, ensure_ascii=False)


def series_tag(p, prof):
    """the channel's series tag in its corner, when the episode asks for it (options.series_tag; الحدث الأخير: owner's
    answer 2 of phase 2B, an on/off option per episode)"""
    tag = ((prof.get("montage") or {}).get("assets") or {}).get("series_tag") or {}
    if not p.opt("series_tag") or not tag.get("file"):
        return []
    return [{"file": str(Path(prof["_folder"]) / tag["file"]), "x": tag["x"], "y": tag["y"], "from": 0, "to": 1e9}]


def step_selfcheck(p):
    from . import selfcheck
    if p.opt("render_window"):
        print("preview: the full self-check runs on the finished video only")
        return
    selfcheck.run(p, out_name(p))


def step_credits(p):
    from . import credits, report
    if p.opt("render_window"):
        return
    credits.write(p)
    if p.montage != "classic":          # the video's report, "Watch these first" on top (owner's decision 4a)
        out = out_name(p).with_name(out_name(p).stem + "_report.md")
        watch = report.write(p, out)
        print(f"report: {out.name}; watch these first: {len(watch)} item(s)")
        for w in watch:
            print("   -", w[:300])


# the montage code that only shapes what is made from the decisions (the cut list's pieces, our graphics, the sound, the
# reports), never what the brain is asked: a fix there no longer makes the judgement steps run again (owner's decision 6a
# of 19 Oct 2026; the first real test asked Claude again for hours after render and graphics fixes)
OUTPUT_ONLY = ("build.py", "credits.py", "graphics.py", "look.py", "mix.py", "remix.py", "render.py", "report.py", "result.py",
               "screen_text.py", "selfcheck.py", "sfx.py", "subtitles.py", "textures.py", "timeline.py")


def rules_sig(p=None):
    """must-do f of the readiness report: the rules and the montage code that writes the brain's requests, as one hash in
    the fingerprint of every judgement step, so a rule change reaches projects that already have a plan (the step runs
    again; the brain is asked again only when its request really changed, else its decision is kept). The code in
    OUTPUT_ONLY is left out (decision 6a); the steps that build from it (music, timeline, mix) also carry output_sig."""
    import hashlib
    h = hashlib.sha256()
    for f in sorted(list((ENGINE / "rules").glob("*.md")) + list((ENGINE / "monteer" / "montage").glob("*.py"))):
        if f.name in OUTPUT_ONLY:
            continue
        h.update(f.name.encode() + f.read_bytes())
    if p is not None and p.profile:     # the channel profile's montage section: a change to it reaches the judgement steps
        h.update(json.dumps(p.profile_montage(), sort_keys=True, ensure_ascii=False).encode())
    if p is not None:                   # an applied edit round (montage/edits.py): the judgement steps run again; the requests it
        from .edits import sig as edits_sig   # did not change keep their decisions (none for the classic same-result projects)
        es = edits_sig(p)
        if es:
            h.update(es.encode())
    return h.hexdigest()[:16]


def output_sig(p=None):
    """rules_sig plus the OUTPUT_ONLY code: for the steps that build their result from it (music cues, the cut list, the mix)"""
    import hashlib
    h = hashlib.sha256(rules_sig(p).encode())
    for name in OUTPUT_ONLY:
        h.update(name.encode() + (ENGINE / "monteer" / "montage" / name).read_bytes())
    return h.hexdigest()[:16]


def _dec(step, key):
    return lambda p: [p.decisions / step / f"{key}.json"]


def _own_clips(p):
    from .own_clips import clip_files
    return clip_files(p)


def _news_mode(p):
    from .news import mode
    return mode(p)


def _step_mode(p):
    from .questions import step_mode
    return step_mode(p)


def _answers(p):
    """the owner's answers (step-by-step mode): an input of the plan only where they can exist"""
    from .questions import answers_file
    f = answers_file(p)
    return [f] if _step_mode(p) or f.exists() else []


def _learns(p):
    from .learning import on
    return on(p)


def _plan_dec(p):
    return [p.decisions / "montage" / ("shots.json" if phrase_mode(p) else "plan.json")]


register("cut_report",
         Step("voice", "the narration as it is (48 kHz) + 16 kHz for transcription", (VO,), "monteer.montage.steps:step_voice",
              inputs=lambda p: [p.input("audio") or p.input("video")], outputs=lambda p: [V(p, "audio48.wav"), V(p, "audio16.wav")], adopt=True),
         Step("voice_words", "whisper large-v3: every word of the narration with its time", (VO,), "monteer.montage.steps:step_voice_words",
              inputs=lambda p: [V(p, "audio16.wav")], outputs=lambda p: [V(p, "asr_large-v3.json")], adopt=True),
         Step("clips", "your own extra clips: converted, looked at and described (judgement)", BOTH, "monteer.montage.steps:step_clips",
              inputs=_own_clips,
              outputs=lambda p: [M(p, "own_clips.json")], params=rules_sig),
         Step("news", "documented news as cropped screenshots of their public pages (channel profiles; nothing otherwise)", BOTH,
              "monteer.montage.news:step",
              inputs=lambda p: [p.folder / "script" / "news_items.json", p.folder / "script" / "facts.json"] if _news_mode(p) else [],
              outputs=lambda p: [M(p, "news", "news.json")] if _news_mode(p) and (p.folder / "script" / "news_items.json").exists() else [],
              params=lambda p: "screenshot_crop" if _news_mode(p) else None),
         Step("learn", "«عام» learns: lessons from earlier videos and the owner's words, worked out once for this video", BOTH,
              "monteer.montage.learning:step", outputs=lambda p: [M(p, "lessons.json")] if _learns(p) else [],
              params=lambda p: "learns" if _learns(p) else None),
         # version 4: the plan's instructions changed (owner's decisions of 16 Oct 2026: place, subject; then the two video
         # types, the material mix as a check, labels per rule 11); a new version makes an existing project ask again (its
         # decision is kept when the request is the same, as in the classic montage)
         Step("plan", "the shot plan (judgement): every shot tied to its phrase (audio only), or the block plan with the presenter", BOTH,
              "monteer.montage.steps:step_plan",
              version=4, inputs=lambda p: _plan_dec(p) + ([V(p, "asr_large-v3.json")] if p.mode == "voice_only" else [p.output / "edl.json"])
              + [p.folder / "script" / "lines.json", M(p, "own_clips.json"), p.folder / "project.json"]
              + ([M(p, "news", "news.json")] if _news_mode(p) else []) + ([M(p, "lessons.json")] if _learns(p) else [])
              + _answers(p), outputs=_plan_dec, params=rules_sig),
         Step("questions", "step by step: the agent's questions on the plan, and the stop for your answers (auto: nothing)", BOTH,
              "monteer.montage.questions:step", inputs=_answers, params=lambda p: "step" if _step_mode(p) else None),
         # phase D (owner's decision 9 of 19 Oct 2026): in a channel episode the music runs at the same time as the sources,
         # drawn images, graphics …; the mix waits for it. ACE-Step never runs together with the drawn images (core/heavy.py)
         Step("music", "music cues: ACE-Step + vocals check, code-made fallback; one cue at a time, resumable", BOTH, "monteer.montage.steps:step_music",
              inputs=lambda p: _plan_dec(p) if phrase_mode(p) else _dec("music", "cues")(p), params=output_sig, alongside_until="mix"),
         # owner's decision of 21 Oct 2026: every channel episode's voice (camera or separate mic, presenter or audio only) is
         # measured against the channel's reference sound and given only what it needs, at the same time as the next steps; the
         # mix waits for it and takes it; classic projects and «cut only» nothing
         Step("voice_clean", "the voice measured against the channel's reference sound and given only what it needs, -15 LUFS",
              BOTH, "monteer.montage.voice_chain:step",
              # what it is made from: the raw recording's sound (and, with presenter, the cut list: the voice is processed
              # before the cut; a new version of the same cut does not process it again)
              inputs=lambda p: ([p.output / "edl.json", p.work / "sync_ext48.wav"] if p.mode == "talking_head" else [V(p, "audio48.wav")])
              if _camera_voice(p) else [],
              outputs=lambda p: [_clean_out(p)] if _camera_voice(p) else [],
              params=lambda p: _voice_sig(p) if _camera_voice(p) else None, alongside_until="mix"),
         Step("sources", "search free sources in code, choose (judgement), download through the licence gate; provenance records", BOTH,
              "monteer.montage.steps:step_sources", inputs=lambda p: _plan_dec(p) + _dec("sources", "assets")(p), params=rules_sig),
         Step("ai_images", "AI images (generic scenes), one at a time, resumable; then the pick (judgement)", BOTH, "monteer.montage.steps:step_ai_images",
              inputs=lambda p: [p.decisions / "ai" / "prompts.json", p.decisions / "ai" / "pick.json"]
              # phrase montage: the prompts, the clip review and the reuse are made inside this step from the plan and the picks
              + ([p.decisions / "montage" / "shots.json", M(p, "picks.json")] if phrase_mode(p) else []), params=rules_sig),
         Step("textures", "paper and overlay textures, made in code", BOTH, "monteer.montage.steps:step_textures",
              outputs=lambda p: [p.asset_dir("textures") / "paper.png", p.asset_dir("textures") / "paper_overlay.png"], params=lambda p: p.opt("texture_seed", 73)),
         Step("sfx", "sound effects, made in code", BOTH, "monteer.montage.steps:step_sfx",
              outputs=lambda p: [p.asset_dir("sfx") / "sfx.json"] + ([p.asset_dir("sfx") / "paper.wav"] if paper_sfx(p) else [])
              + ([p.asset_dir("sfx") / f"{k}.wav" for k in BEAT_SFX] if on_beat(p) else []),
              params=lambda p: ("paper" if paper_sfx(p) else None) if not on_beat(p) else ("paper|on_beat" if paper_sfx(p) else "on_beat")),
         Step("review", "contact sheets of every clip; usable windows and grades (judgement)", BOTH, "monteer.montage.steps:step_review",
              inputs=_dec("montage", "clip_fx"), outputs=_dec("montage", "clip_fx"), params=rules_sig),
         Step("timeline", "the montage cut list: every shot, its source, effects and overlays", BOTH, "monteer.montage.steps:step_timeline",
              version=3, inputs=lambda p: [p.decisions / "montage" / "plan.json", M(p, "popup_pictures.json"), p.output / "edl.json",
                                           M(p, "news", "news.json")] if popups_layout(p) else
              ([p.decisions / f for f in ("montage/shots.json", "montage/clip_fx.json", "ai/pick.json")]
                                           + [M(p, "picks.json"), M(p, "style.json"), M(p, "reuse.json")] if phrase_mode(p) else
                                           [p.decisions / f for f in ("montage/timeline.json", "graphics/scenes.json", "montage/clip_fx.json", "ai/pick.json")]
                                           + ([p.decisions / "montage" / "photo_review.json"] if presenter_mode(p) else []))
              + ([V(p, "asr_large-v3.json")] if p.mode == "voice_only" else [])
              # the audio type's approved script spells the on-screen words: only when there is one (no change for the rest)
              + ([x for x in (p.folder / "script" / "lines.json", p.input("script")) if x and x.exists()] if p.mode == "voice_only" else []),
              outputs=lambda p: [M(p, "edl.json")], params=output_sig),
         Step("graphics", "our graphics: every scene's frames (one renderer), resumable", BOTH, "monteer.montage.steps:step_graphics",
              inputs=lambda p: [p.decisions / "graphics" / "scenes.json", M(p, "edl.json")], params=lambda p: p.opt("render_window")),
         Step("parallax", "drawn stills moved in depth (depth map + camera move), resumable", BOTH, "monteer.montage.steps:step_parallax",
              inputs=lambda p: [M(p, "edl.json")]),
         Step("shots", "every shot rendered to an exact-length piece, resumable", BOTH, "monteer.montage.steps:step_shots",
              inputs=lambda p: [M(p, "edl.json")], params=lambda p: p.opt("render_window")),
         Step("join", "join the pieces", BOTH, "monteer.montage.steps:step_join", inputs=lambda p: [M(p, "edl.json")], params=lambda p: p.opt("render_window")),
         Step("mix", "the sound: the voice (cleaned when it is the camera's mic) + music + effects in pauses, one fixed gain", BOTH,
              "monteer.montage.steps:step_mix",
              inputs=lambda p: [p.decisions / "montage" / "sound.json", M(p, "edl.json")]
              + ([_clean_out(p)] if _camera_voice(p) else []), outputs=lambda p: [M(p, "mix.wav"), M(p, "mix_plan.json")], params=output_sig),
         Step("final", "the finished video (never overwritten); the channel's own clips put in, its logo hidden during them",
              BOTH, "monteer.montage.steps:step_final",
              outputs=lambda p: [out_name(p)], params=lambda p: [p.opt("render_window"), p.opt("version"), p.opt("crf")]
              + ([final_sig(p)] if final_sig(p) else []), adopt=True),
         Step("selfcheck", "self-check of the finished video", BOTH, "monteer.montage.steps:step_selfcheck", inputs=lambda p: [out_name(p)]),
         Step("credits", "credits: every asset with its source and licence", BOTH, "monteer.montage.steps:step_credits", inputs=lambda p: [out_name(p)]),
         Step("observe", "this video's record for «عام»'s learning (channel profiles; nothing otherwise)", BOTH,
              "monteer.montage.learning:observe", inputs=lambda p: [out_name(p)] if p.profile else [],
              params=lambda p: p.profile or None),
         )

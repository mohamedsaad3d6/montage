"""One project's state, as data: what `bin/monteer status --json` prints and what the web panel shows (Works/output/
web_panel_plan.md, phase 1). Read-only: it never changes a project.

  summary(folder)  -> {name, type, montage, output, state, state_label, steps (the design's 9), running, waiting,
                       outputs, script (the script writer's stage, when the project has one), brain (time and API
                       equivalent of its decisions), last_log, updated}

The design's 9 steps group the engine's own steps (web_panel_plan.md 1.4). A step that does not belong to the project's
type (sync for audio only) is "not_needed"; with output "cut", steps 5-9 are "not_needed".
"""
import json
import os
import re
import time
from pathlib import Path

from .io import load_json
from .project import Project
from .runner import ALONGSIDE

GROUPS = [
    ("sync", "مزامنة الصوت مع الفيديو", "Sync audio with video", ["sync"]),
    ("transcribe", "تفريغ الكلام ومقارنته بالسكريبت", "Transcribe and compare with the script",
     ["transcribe", "literal_words", "script", "voice", "voice_words"]),
    ("cut", "التقطيع", "Cut", ["cut", "cut_verify"]),
    ("clean", "تنضيف السكوت والنَّفَس", "Clean silences and breaths", ["cut_draft", "cut_final", "cut_report"]),
    ("plan", "خطة المونتاج وأنواع الماتيريال", "Montage plan and material types", ["clips", "news", "learn", "plan", "questions"]),
    ("gather", "جمع الماتيريال: أرشيف وأخبار وصور وجرافيك", "Gather material: archive, news, photos, graphics",
     ["sources", "ai_images", "review"]),
    ("music", "توليد المزيكا والمؤثرات وفحصها", "Music and sound effects, made and checked", ["music", "sfx", "textures"]),
    ("export", "التصدير", "Export", ["timeline", "graphics", "parallax", "shots", "join", "mix", "final"]),
    ("check", "المراجعة الذاتية والتقرير", "Self-check and report", ["selfcheck", "credits", "observe"]),
]
CUT_GROUPS = {"sync", "transcribe", "cut", "clean"}
STATE_LABEL = {
    "running": ("شغّالة · خطوة {n} من ٩", "Running · step {n} of 9"),
    "waiting": ("مستنية قرار", "Waiting for a decision"),
    "waiting_you": ("مستنية إجاباتك على أسئلة الخطة", "Waiting for your answers on the plan"),
    "paused_limit": ("متوقفة مؤقتًا: وصلت لحد الاشتراك · هتكمل لوحدها {until}", "Paused: the subscription limit · resumes by itself at {until}"),
    "script_gate": ("السكريبت مستني موافقتك", "The script is waiting for your approval"),
    "failed": ("خطوة {n} فشلت", "Step {n} failed"),
    "stopped": ("وقفت عند خطوة {n}", "Stopped at step {n}"),
    "stopped_by_you": ("وقفتها انت عند خطوة {n}", "You stopped it at step {n}"),
    "done": ("جاهزة للمراجعة", "Ready to review"),
    "approved": ("اتعتمدت", "Approved"),
    "script_done": ("السكريبت اتعتمد", "Script approved"),
    "script": ("كتابة السكريبت · {stage}", "Script writer · {stage}"),
    "new": ("لسه مابدأتش", "Not started yet"),
    "start_failed": ("ماقدرش يبدأ", "Could not start"),
}
AR_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")
VIDEO_EXT = (".mp4", ".mov", ".m4v")


def lock_alive(run_dir):
    f = Path(run_dir) / "lock"
    if not f.exists():
        return False
    try:
        pid = int(f.read_text().split()[0])
        os.kill(pid, 0)
        return True
    except (ValueError, IndexError, ProcessLookupError, PermissionError, OSError):
        return False


def last_lines(path, n=40):
    if not Path(path).exists():
        return []
    with open(path, "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 64 * 1024))
        lines = f.read().decode("utf-8", "replace").splitlines()
    return [x for x in lines if x.strip()][-n:]


_ORDER = None


def step_order():
    """{step: (its place in the run, the types it is for)}, from the engine's own step list"""
    global _ORDER
    if _ORDER is None:
        from ..steps import STEPS
        _ORDER = {st.name: (i, tuple(st.modes)) for i, st in enumerate(STEPS)}
    return _ORDER


def step_state(r):
    st = (r or {}).get("status", "")
    if st == "done":
        return "done"
    if st.startswith("skipped"):
        return "not_needed"
    if st.startswith("failed"):
        return "failed"
    if st.startswith("waiting"):
        return "waiting"
    return "queued"


ENDS = (": done in", ": FAILED", ": STOPPED", ": up to date")


def running_steps(log):
    """the engine steps a running run is in: each «<step>: running —» line not yet followed by its end (two at once when
    a step runs at the same time as the main ones, fast mode phase D)"""
    now = []
    for ln in log:
        body = TS.sub("", ln)
        if body.startswith("=== "):
            now = []
            continue
        head = body.split(":", 1)[0].strip()
        if ": running —" in body:
            now = [s for s in now if s != head] + [head]
        elif any(body.startswith(head + e) for e in ENDS):
            now = [s for s in now if s != head]
    return now


# ---------------------------------------------------------------------------------------------------- what each step said
TS = re.compile(r"^\[\d\d:\d\d:\d\d\] ")
WHISPER_LINE = re.compile(r"^\[\d\d:\d\d:\d\d\.\d+ --> ")        # whisper's own printout, in logs from before it went to a file
BOOKKEEPING = {"news", "learn", "questions", "observe"}               # steps added later: missing in older runs, never "to do"
NOISE = ("$ ", "read_audio_data", "output_json", "Traceback", "  File ", "warnings.warn", "engine ", "data ", "tools ", "keys file")


def friendly(line):
    """a log line as the step's one-line detail (the brain's lines in plain words), or None for noise"""
    s = TS.sub("", line).strip()
    if not s or s.startswith(NOISE) or WHISPER_LINE.match(s):
        return None
    if s.startswith("[brain] "):
        b = s[8:]
        what = b.split(":", 1)[0]
        if "asking background Claude Code" in b:
            return f"asking the brain (Claude): {what}"
        if "answered by background Claude Code in" in b:
            secs = float(b.rsplit(" in ", 1)[1].split()[0])
            return f"the brain answered {what} in {int(secs // 60)} min {int(secs % 60)} s"
        if "rejected by the engine" in b:
            return f"the brain's answer to {what} was sent back: " + b.split("(", 1)[-1][:160]
        if "usage limit reached" in b:
            return "the subscription's limit was reached: " + b.split(";", 1)[-1].strip()
        return b[:200]
    return s[:220]


SIDE_LINE = re.compile(r"^\[([a-z_]+)\] (.*)$")       # a line of a step running alongside: "[music] music: M3 …"


def step_details(log):
    """{engine step: its latest one-line detail} from the run log (the running step's last line: e.g. "whisper: 35%"; a
    step running alongside the main ones: its own lines, which carry its name in front)"""
    out, cur, side = {}, None, set()
    for ln in log:
        body = TS.sub("", ln)
        head = body.split(":", 1)[0].strip()
        if body.startswith("=== "):
            side = set()
        m = SIDE_LINE.match(body)
        if m and m.group(1) in side:
            f = friendly(m.group(2))
            if f:
                out[m.group(1)] = f
            continue
        if ": running —" in body and ALONGSIDE in body:
            side.add(head)
            continue
        if head in side:               # the runner's own lines on it ("music: done in …"): its detail, not the main step's
            f = friendly(ln)
            if f:
                out[head] = f
            continue
        if ": running —" in body:
            cur = head
            continue
        if cur and (body.startswith(f"{cur}: done in") or body.startswith(f"{cur}: FAILED") or body.startswith(f"{cur}: STOPPED")
                    or body.startswith("=== ")):
            cur = None
            continue
        if cur:
            f = friendly(ln)
            if f:
                out[cur] = f
    return out


FAILURES = [   # (a phrase of the log, plain reason ar, en): known ways a step stops (web panel plan 1.4)
    ("cannot be used:", "العقل جاوب ٣ مرات والمحرك رفض إجابته", "The brain answered 3 times and the engine refused the answer"),
    ("the background brain needs Claude Code", "Claude Code مش متثبت أو مش مسجّل دخول", "Claude Code is not installed or not signed in"),
    ("no brain could answer", "مفيش عقل قدر يجاوب", "No brain could answer"),
    ("usage limit did not reset", "حد الاشتراك مارجعش في ٨ ساعات", "The subscription's limit did not reset within 8 hours"),
    ("No space left on device", "الديسك اتملى", "The disk is full"),
    ("not enough free disk", "الديسك اتملى", "The disk is full"),
    ("whisper stopped with exit", "التفريغ (whisper) وقف بخطأ", "The transcription (whisper) stopped with an error"),
    ("not set up (run bin/monteer setup)", "الأدوات أو النماذج ناقصة على الماك ده", "Tools or models are missing on this Mac"),
    ("No such file or directory", "ملف ناقص أو اتنقل", "A file is missing or was moved"),
    ("FileNotFoundError", "ملف ناقص أو اتنقل", "A file is missing or was moved"),
]


def failure(log, step):
    """the failed step's plain reason, what was kept, and the raw lines as details"""
    tail = log[-60:]
    text = "\n".join(tail)
    ar, en = next(((a, e) for k, a, e in FAILURES if k in text), ("الخطوة وقفت بخطأ (التفاصيل تحت)", "The step stopped with an error (details below)"))
    why = next((x.split("cannot be used:", 1)[1].split(". Redo it")[0].strip() for x in reversed(tail) if "cannot be used:" in x), "")
    return {"step": step, "reason_ar": ar, "reason_en": en, "why": why[:400],
            "saved_ar": "كل الخطوات اللي خلصت قبلها محفوظة؛ «كمّل الشغل» بيكمّل من الخطوة دي.",
            "saved_en": "Every step finished before it is kept; «Resume» continues from this step.",
            "details": [x for x in tail if x.strip()][-15:]}


def outputs(p):
    out = []
    if p.output.exists():
        for f in sorted(p.output.iterdir()):
            if f.name.startswith(".") or f.is_dir():
                continue
            kind = ("cut" if f.name.startswith("cut_v") else "video") if f.suffix.lower() in VIDEO_EXT else \
                ("report" if f.name.endswith("_report.md") or f.name == "report.md" else
                 "credits" if f.name == "credits.md" else "data" if f.suffix == ".json" else "other")
            st = f.stat()
            out.append({"name": f.name, "kind": kind, "bytes": st.st_size, "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))})
    return out


def brain_use(p):
    """what the brain did for this episode, from its decision records: decisions, brain time, tokens, API equivalent.
    Tokens: "in" is everything the brain read (the request, the files, its own earlier turns: Claude Code's input and
    cache tokens), "out" what it wrote; decisions from before tokens were recorded count in "without_tokens"."""
    n, secs, usd, t_in, t_out, no_tok = 0, 0.0, 0.0, 0, 0, 0
    if p.decisions.exists():
        for f in p.decisions.rglob("*.json"):
            if ".replaced_" in f.name or f.name.endswith(".request.json"):
                continue
            try:
                d = load_json(f)
            except (ValueError, OSError):
                continue
            u = d.get("usage") if isinstance(d, dict) else None
            if u:
                n += 1
                secs += float(u.get("seconds") or d.get("seconds") or 0)
                usd += float(u.get("api_equivalent_usd") or 0)
                if u.get("output_tokens") is None and u.get("context_tokens") is None:
                    no_tok += 1
                else:
                    t_in += int(u.get("context_tokens") or 0)
                    t_out += int(u.get("output_tokens") or 0)
    return {"decisions_by_brain": n, "brain_seconds": round(secs, 1), "api_equivalent_usd": round(usd, 2),
            "tokens_in": t_in, "tokens_out": t_out, "tokens": t_in + t_out, "without_tokens": no_tok}


def script_stage(p):
    """the script writer's stage, when the project has one (script/topic.json)"""
    sd = p.folder / "script"
    if not (sd / "topic.json").exists():
        return None
    rec = load_json(p.run / "script_record.json") if (p.run / "script_record.json").exists() else {}
    topic = load_json(sd / "topic.json")
    approved = (sd / "approved.json").exists()
    outline_ok = (sd / "outline_ok.json").exists()
    if approved:
        stage = ("الاعتماد", "Approved")
    elif any(str(v.get("status", "")).startswith("waiting") for k, v in rec.items() if k == "outline_ok"):
        stage = ("الهيكل · مستني موافقتك", "Outline · waiting for your yes")
    elif (sd / "drafts").exists() and any((sd / "drafts").glob("*.json")):
        stage = ("المسودة والمراجعة", "Draft and review")
    elif (sd / "outline.json").exists():
        stage = ("الهيكل", "Outline")
    elif (sd / "facts.json").exists():
        stage = ("البحث وبطاقات الحقائق", "Research and fact cards")
    else:
        stage = ("الموضوع", "Topic")
    return {"topic": topic.get("topic", ""), "minutes": topic.get("minutes"), "stage": stage[0], "stage_en": stage[1],
            "outline_ok": outline_ok, "approved": approved,
            "waiting_for_you": not approved and not outline_ok and (sd / "outline.json").exists()}


def summary(folder, log_lines=0):
    from . import progress as PG
    p = Project(folder)
    rec_all = load_json(p.run / "record.json") if (p.run / "record.json").exists() else {}
    started = PG.run_started(p)
    rec = PG.this_run(rec_all, started)          # only this run's states (owner, 20 Oct 2026): an older run's «done» waits
    log = last_lines(p.run / "log.txt", 400)
    details = step_details(log)
    running = lock_alive(p.run)
    now_steps = running_steps(log) if running else []
    want_cut_only = p.opt("output", "montage") == "cut"
    order = step_order()
    last_ran = max((order[s][0] for s, r in rec.items() if s in order and not str(r.get("status", "")).startswith("skipped")),
                   default=-1)
    steps = []
    for n, (key, ar, en, names) in enumerate(GROUPS, 1):
        if want_cut_only and key not in CUT_GROUPS:
            states = ["not_needed"]
        else:
            # every step of this type: one with no record yet is still to do, unless a later step already ran (then it
            # is a step added to the engine after this project went past it)
            states = []
            for s in names:
                if s not in order or p.mode not in order[s][1]:
                    continue
                if s in rec:
                    if not rec[s].get("status", "").startswith("skipped"):
                        states.append(step_state(rec[s]))
                elif order[s][0] > last_ran and not (s in BOOKKEEPING and rec):
                    states.append("queued")
            if not states:
                states = ["not_needed"] if any(s in rec for s in names) or not any(s in order for s in names) else ["queued"]
            if p.mode == "voice_only" and key in ("sync", "cut", "clean"):
                states = ["not_needed"]
        now = [s for s in now_steps if s in names]
        if now:
            st = "running"
        elif "failed" in states:
            st = "failed"
        elif "waiting" in states:
            st = "waiting"
        elif states and all(x in ("done", "not_needed") for x in states) and "done" in states:
            st = "done"
        elif states and all(x == "not_needed" for x in states):
            st = "not_needed"
        else:
            st = "queued"
        latest = next((s for s in reversed(names) if s in details and (s in now_steps or s in rec)), None)
        which = now[-1] if now else latest
        steps.append({"n": n, "key": key, "ar": ar, "en": en, "state": st, "detail": details.get(which, ""),
                      "detail_ar": PG.ar_line(details.get(which, ""), which) if which else "",
                      "seconds": round(sum(float(rec.get(s, {}).get("seconds") or 0) for s in names), 1),
                      "engine_steps": {s: rec.get(s, {}).get("status", "") for s in names if s in rec}})
    waiting = load_json(p.run / "waiting.json") if (p.run / "waiting.json").exists() else []
    outs = outputs(p)
    scr = script_stage(p)
    cur = next((s["n"] for s in steps if s["state"] in ("running", "failed", "waiting")), None)
    nxt = next((s["n"] for s in steps if s["state"] == "queued"), None)
    wait_f = next((f for f in (p.run / "brain_wait.json", p.run / "brain_wait_alongside.json") if f.exists()), None)
    brain_wait = load_json(wait_f) if running and wait_f else None
    owner_wait = bool(waiting) and all(w.get("kind") == "owner" for w in waiting)
    if (p.output / "approved.json").exists():
        state = "approved"
    elif running and brain_wait:
        state = "paused_limit"
    elif running:
        state = "running"
    elif (p.run / "start_failed.json").exists():
        state = "start_failed"
    elif any(s["state"] == "failed" for s in steps):
        state = "failed"
    elif any(s["state"] == "waiting" for s in steps) and waiting:
        state = "waiting_you" if owner_wait else "waiting"
    elif any(o["kind"] == "video" for o in outs) and steps[-1]["state"] == "done":
        state = "done"
    elif want_cut_only and steps[3]["state"] == "done":
        state = "done"
    elif scr and not rec_all:
        state = "script_done" if scr["approved"] else ("script_gate" if scr["waiting_for_you"] else "script")
    elif rec_all and nxt:
        state = "stopped_by_you" if (p.run / "stopped.json").exists() else "stopped"
    else:
        state = "new"
    n = cur or nxt or 9
    ar, en = STATE_LABEL[state]
    stage_ar, stage_en = (scr["stage"], scr["stage_en"]) if scr else ("", "")
    hm = (brain_wait or {}).get("until_hm", "")
    label = {"ar": ar.format(n=str(n).translate(AR_DIGITS), stage=stage_ar, until=hm.translate(AR_DIGITS)),
             "en": en.format(n=n, stage=stage_en, until=hm)}
    failed = next((s for s in steps if s["state"] == "failed"), None)
    failed_step = next((k for k, v in (failed or {}).get("engine_steps", {}).items() if str(v).startswith("failed")), None)
    done_n = sum(1 for s in steps if s["state"] == "done")
    todo_n = sum(1 for s in steps if s["state"] != "not_needed")
    pct, eta = round(done_n / max(1, todo_n), 3), None
    if started and rec_all and state not in ("done", "approved"):     # weighed by each step's measured time, live
        from ..steps import STEPS
        f, left = PG.estimate(p, rec, log, set(now_steps), STEPS, details)
        pct, eta = round(f, 3), (left if state == "running" else None)
    elif state in ("done", "approved"):
        pct = 1.0
    times = [Path(x).stat().st_mtime for x in (p.run / "log.txt", p.run / "record.json", p.run / "script_log.txt") if Path(x).exists()]
    out = {"folder": str(p.folder), "id": p.folder.name, "name": p.name, "type": p.mode, "type_name": p.type_name,
           "montage": p.montage, "output": p.opt("output", "montage"), "run_mode": p.opt("run_mode", "auto"),
           "version": int(p.opt("version", 1)), "instructions": p.instructions,
           "inputs": {k: (str(p.resolve(v)) if isinstance(v, str) else v) for k, v in p.cfg.get("inputs", {}).items()},
           "state": state, "state_label": label, "running": running,
           "current_step": cur, "progress": pct, "eta_s": round(eta) if eta is not None else None, "eta": PG.eta_words(eta), "steps": steps,
           "waiting": [{"step": w.get("step"), "key": w.get("key"), "why": w.get("why", ""), "kind": w.get("kind", "brain")} for w in waiting],
           "brain_wait": brain_wait, "failure": failure(log, failed_step) if state == "failed" else None,
           "approval": approval(p) if owner_wait or (p.decisions / "you" / "plan_answers.json").exists() else None,
           "outputs": outs, "script": scr, "brain": brain_use(p),
           "start_error": (load_json(p.run / "start_failed.json").get("why", "") if state == "start_failed" else ""),
           "updated": time.strftime("%Y-%m-%d %H:%M", time.localtime(max(times))) if times else None,
           "last_log": next((x for x in reversed(log) if not x.startswith("[brain]")), "")}
    if log_lines:
        out["log"] = log[-log_lines:]
    return out


def approval(p):
    from ..montage.questions import card
    try:
        return card(p)
    except (ValueError, OSError, KeyError):
        return None


def main(folder):
    print(json.dumps(summary(folder, log_lines=20), ensure_ascii=False, indent=1))

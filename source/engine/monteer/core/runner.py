"""The one command's step runner: the same steps, in the same order, every time.

For each step (monteer/steps.py) in order:
  - a step that doesn't apply to the project's mode is recorded as skipped;
  - a step whose inputs (files + settings + step version) are unchanged since its last finished run, and whose
    outputs are all present, is skipped ("up to date");
  - otherwise it runs in its own process, in its Python environment (core or ml);
  - a step that stops to wait for a judgement decision ends the run with a clear message (exit code 3);
  - a failed step ends the run; nothing after it runs.
The run record (<project>/run/record.json) is written after every step, atomically, so a crash or restart
continues from the first unfinished step. Long steps also resume inside themselves, item by item.

Steps at the same time (fast mode, phase D; owner's decision 9 of 19 Oct 2026), channel episodes only (options.parallel
false turns it off; the classic tests never): a step marked alongside_until (the music) starts in its own process at its
place and the run goes on with the next steps; the step it names (the mix) waits for it. Its output goes to the run log
with its name in front, its record is written when it ends, and its heavy model never runs together with the drawn
images' (core/heavy.py). When the main steps stop (failed, waiting) it is
stopped too, and resumes on the next run like any stopped step; when it fails, the run goes on to the step that waits
for it and stops there.
"""
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import guard
from .brain import WAITING_EXIT
from .io import load_json, save_json
from .paths import CORE_PY, ENGINE, ML_PY, tool_env
from .project import Project

BIG = 50 << 20      # files above this are fingerprinted by size + modification time instead of their content


def file_sig(p):
    p = Path(p)
    if not p.exists():
        return "missing"
    if p.is_dir():
        return [[str(c.relative_to(p)), c.stat().st_size] for c in sorted(p.rglob("*")) if c.is_file() and not c.name.startswith(".")]
    st = p.stat()
    if st.st_size > BIG:
        return f"{st.st_size}:{st.st_mtime_ns}"
    return hashlib.sha256(p.read_bytes()).hexdigest()


def rel(proj, p):
    """a path inside the project is named relative to it, so a moved or copied project keeps its run record"""
    try:
        return str(Path(p).resolve().relative_to(proj.folder))
    except ValueError:
        return str(p)


def fingerprint(step, proj):
    ins = [i for i in (step.inputs(proj) if step.inputs else []) if i is not None]
    doc = {"version": step.version, "params": step.params(proj) if step.params else None,
           "inputs": {rel(proj, p): file_sig(p) for p in ins}}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, default=str).encode()).hexdigest()[:16]


class Log:
    def __init__(self, path):
        self.f = open(path, "a", encoding="utf-8")
        self.lock = threading.Lock()

    def __call__(self, *a):
        s = f"[{time.strftime('%H:%M:%S')}] " + " ".join(str(x) for x in a)
        with self.lock:
            print(s, flush=True)
            self.f.write(s + "\n")
            self.f.flush()

    def raw(self, s):
        """a line of a step running at the same time, into the log file only"""
        with self.lock:
            self.f.write(f"[{time.strftime('%H:%M:%S')}] {s}\n")
            self.f.flush()


STEP_MAIN = "monteer.core.stepmain"
ALONGSIDE = "at the same time as the next steps"          # in its «running —» line (the panel's progress reads it)


def parallel_on(proj, stage, only):
    """steps at the same time: a channel episode's video, unless options.parallel is false or one step alone is run"""
    return stage != "script" and not only and bool(proj.profile) and proj.opt("parallel", True) is not False


class Alongside:
    """a step running at the same time as the next ones: its own process, its output into the run log
    with its name in front, its record written by a thread when it ends"""

    def __init__(self, step, proj, cmd, fp, put, log, waiting_file):
        self.step, self.proj, self.fp, self.put, self.log, self.waiting_file = step, proj, fp, put, log, waiting_file
        self.stopping = False
        self.rc = None
        self.t0 = time.time()
        # PYTHONUNBUFFERED: its lines reach the log (and the panel) as they are printed, not when it ends (19 Oct 2026)
        self.p = subprocess.Popen(cmd, cwd=str(ENGINE), env=dict(tool_env(), MONTEER_ALONGSIDE=str(waiting_file), PYTHONUNBUFFERED="1"),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.thread = threading.Thread(target=self._follow, daemon=True)
        self.thread.start()

    def _follow(self):
        name = self.step.name
        for line in iter(self.p.stdout.readline, b""):
            s = line.decode("utf-8", "replace").rstrip()
            if s:
                self.log.raw(f"[{name}] {s}")
        rc = self.p.wait()
        secs = round(time.time() - self.t0, 1)
        at = time.strftime("%Y-%m-%d %H:%M:%S")
        if self.stopping:
            self.put(name, {"status": "stopped with the main steps (resumes on the next run)", "seconds": secs, "at": at})
            self.log(f"{name}: STOPPED with the main steps after {secs} s; it resumes on the next run")
        elif rc == 0:
            # its fingerprint as it ends (a step that writes its own decision, as the music cues, looked out of date the next
            # run when it kept the one taken as it started; 21 Oct 2026)
            self.put(name, {"status": "done", "fp": fingerprint(self.step, self.proj), "seconds": secs, "at": at, "alongside": True})
            self.log(f"{name}: done in {secs} s ({ALONGSIDE})")
        elif rc == WAITING_EXIT:
            self.put(name, {"status": "waiting for a decision", "at": at})
            self.log(f"{name}: STOPPED — waiting for a decision; the run stops at the step that needs it")
        else:
            self.put(name, {"status": f"failed (exit {rc})", "seconds": secs, "at": at})
            self.log(f"{name}: FAILED after {secs} s (exit {rc}); the run goes on and stops at the step that needs it")
        self.rc = rc

    def join(self):
        self.thread.join()
        return self.rc

    def stop(self):
        """stops it and everything it started (the music generator runs in a session of its own)"""
        from .runctl import alive, tree
        if self.p.poll() is not None:
            return self.join()
        self.stopping = True
        pids, groups = tree(self.p.pid)
        groups.discard(os.getpgid(0))
        for g in groups:
            try:
                os.killpg(g, signal.SIGTERM)
            except OSError:
                pass
        for x in pids:
            try:
                os.kill(x, signal.SIGTERM)
            except OSError:
                pass
        for _ in range(60):
            if not any(alive(x) for x in pids):
                break
            time.sleep(0.25)
        else:
            for x in pids:
                try:
                    os.kill(x, signal.SIGKILL)
                except OSError:
                    pass
        return self.join()


STAGES = {"video": ("monteer.steps", "record.json", "log.txt"),
          "script": ("monteer.script.steps", "script_record.json", "script_log.txt")}


def stage_steps(stage):
    """the step list of a stage: "video" (the video: cut, montage) or "script" (the script tool, before recording)"""
    import importlib
    mod = importlib.import_module(STAGES[stage][0])
    return mod.STEPS, mod.by_name


def run(project_folder, start_from=None, only=None, until=None, stage="video"):
    STEPS, by_name = stage_steps(stage)
    _, record_name, log_name = STAGES[stage]
    guard.refuse_if_keys_inside()
    proj = Project(project_folder)
    if start_from and start_from not in by_name:
        sys.exit(f"unknown step {start_from}; steps: {', '.join(s.name for s in STEPS)}")
    with guard.Lock(proj.run / "lock"):
        awake = guard.keep_awake()
        log = Log(proj.run / log_name)
        rec_path = proj.run / record_name
        rec = load_json(rec_path) if rec_path.exists() else {}
        rec_lock = threading.Lock()

        def put(name, entry):                  # the record, written by the main steps and by a step running alongside
            with rec_lock:
                rec[name] = entry
                save_json(rec_path, rec)
        started = time.strftime("%Y-%m-%d %H:%M:%S")      # this run's start: the panel shows only this run's states (20 Oct 2026)
        if not only:                           # a one-step run (--only) is not a run of the whole video
            save_json(proj.run / f"current_{stage}_run.json", {"started": started, "pid": os.getpid()})
        kind = f"{proj.mode}: {proj.type_name}" + (f", {proj.montage} montage" if stage == "video" else "")
        log(f"=== monteer {'run' if stage == 'video' else 'script'} «{proj.name}» ({kind}) — engine {engine_version()}"
            + (f" — brain override: {os.environ['MONTEER_BRAIN']}" if os.environ.get("MONTEER_BRAIN") else ""))
        alongside = {}                         # step name -> Alongside (steps running at the same time as the main ones)
        try:
            rc = _steps(proj, STEPS, stage, start_from, only, until, rec, put, log, log_name, alongside)
        except BaseException:
            for a in alongside.values():
                a.stop()
            raise
        if rc != 0:                            # the main steps stopped: the steps alongside stop too (they resume next time)
            for name, a in alongside.items():
                if a.p.poll() is None:
                    log(f"{name}: stopping it as well (it was running {ALONGSIDE}); it resumes on the next run")
                a.stop()
        else:
            log("=== run finished")
        if awake:
            awake.terminate()
        return rc


def _join(name, a, by, rec, log, proj):
    """the step `by` waits for the step running alongside -> 0, or the exit code that stops the run"""
    if a.p.poll() is None:
        log(f"{by}: waiting for {name} ({ALONGSIDE}) to finish")
    rc = a.join()
    if rc == 0:
        return 0
    if rc == WAITING_EXIT:
        w = load_json(a.waiting_file) if Path(a.waiting_file).exists() else []
        save_json(proj.run / "waiting.json", w)
        log(f"{name}: STOPPED — waiting for {len(w)} judgement decision(s):")
        for i in w:
            log(f"   {i['step']}/{i['key']}: {i['why']} -> {i['request']}")
        log("Answer them (monteer brain answer …) and run again; the run continues from this step.")
        return WAITING_EXIT
    log(f"{by}: not started — {name} {rec.get(name, {}).get('status', 'failed')}; see {proj.run / 'log.txt'}")
    return rc or 1


def _steps(proj, STEPS, stage, start_from, only, until, rec, put, log, log_name, alongside):
    """the steps in order -> 0 when the run got to its end, else the exit code of the step that stopped it"""
    forced = False
    past_until = False
    names = [s.name for s in STEPS]
    # the output "cut only" (presenter type, owner's decision 3a): every step after the cut's report is not run
    after_cut = set(names[names.index("cut_report") + 1:]) if stage == "video" and "cut_report" in names else set()
    cut_only = stage == "video" and proj.opt("output", "montage") == "cut"
    together = parallel_on(proj, stage, only)
    for step in STEPS:
        if past_until:                 # --until STEP stops after that step, whether it ran, was up to date or was skipped
            break
        for name, a in list(alongside.items()):          # this step needs a step running alongside: it waits for it
            if a.step.alongside_until == step.name:
                r = _join(name, a, step.name, rec, log, proj)
                del alongside[name]
                if r != 0:
                    return r
        if until and step.name == until:
            past_until = True
        if start_from and step.name == start_from:
            forced = True
        if only and step.name != only:
            continue
        if proj.mode not in step.modes:
            put(step.name, {"status": "skipped: not this mode"})
            continue
        if cut_only and step.name in after_cut:
            put(step.name, {"status": "skipped: output is the cut only"})
            continue
        fp = fingerprint(step, proj)
        r = rec.get(step.name, {})
        outs = step.outputs(proj) if step.outputs else []
        if not forced and not step.always and r.get("status") == "done" and r.get("fp") == fp and all(Path(o).exists() for o in outs):
            put(step.name, dict(r, checked=time.strftime("%Y-%m-%d %H:%M:%S")))     # found up to date by this run
            log(f"{step.name}: up to date")
            continue
        if not forced and not r and outs and all(Path(o).exists() for o in outs) and step.adopt:
            put(step.name, {"status": "done", "fp": fp, "adopted": True, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
            log(f"{step.name}: outputs already present (adopted as finished)")
            continue
        py = ML_PY if step.env == "ml" else CORE_PY
        cmd = [str(py), "-m", STEP_MAIN, step.name, str(proj.folder), stage]
        if together and step.alongside_until:
            log(f"{step.name}: running — {ALONGSIDE} — {step.what}")
            alongside[step.name] = Alongside(step, proj, cmd, fp, put, log, proj.run / f"waiting_{step.name}.json")
            continue
        log(f"{step.name}: running — {step.what}")
        t0 = time.time()
        with open(proj.run / log_name, "a", encoding="utf-8") as lf:
            p = subprocess.run(cmd, cwd=str(ENGINE), env=tool_env(), stdout=lf, stderr=subprocess.STDOUT)
        secs = round(time.time() - t0, 1)
        if p.returncode == WAITING_EXIT:
            put(step.name, {"status": "waiting for a decision", "at": time.strftime("%Y-%m-%d %H:%M:%S")})
            w = load_json(proj.run / "waiting.json") if (proj.run / "waiting.json").exists() else []
            if w and all(i.get("kind") == "owner" for i in w):      # step-by-step mode: the owner's own answers
                put(step.name, dict(rec[step.name], status="waiting for your answers"))
                log(f"{step.name}: STOPPED — waiting for you: " + "; ".join(i["why"] for i in w))
                log("Answer in the panel (or with the command named above); the run continues from here.")
            else:
                log(f"{step.name}: STOPPED — waiting for {len(w)} judgement decision(s):")
                for i in w:
                    log(f"   {i['step']}/{i['key']}: {i['why']} -> {i['request']}")
                log("Answer them (monteer brain answer …) and run again; the run continues from this step.")
            return WAITING_EXIT
        if p.returncode != 0:
            put(step.name, {"status": f"failed (exit {p.returncode})", "seconds": secs, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
            log(f"{step.name}: FAILED after {secs} s (exit {p.returncode}); see {proj.run / log_name}")
            tail = (proj.run / log_name).read_text(encoding="utf-8", errors="replace").splitlines()[-5:]
            for ln in tail:
                if ln.startswith("STOP:"):
                    log(ln)
            return p.returncode
        put(step.name, {"status": "done", "fp": fingerprint(step, proj), "seconds": secs, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        log(f"{step.name}: done in {secs} s")
    for name, a in list(alongside.items()):          # --until, or no step after it that needs it: it is waited for here
        r = _join(name, a, "the end of the run", rec, log, proj)
        del alongside[name]
        if r != 0:
            return r
    return 0


def engine_version():
    try:
        return subprocess.run(["git", "-C", str(ENGINE), "describe", "--always", "--dirty"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return "?"


def status(project_folder, stage="video"):
    STEPS, _ = stage_steps(stage)
    proj = Project(project_folder)
    rec_path = proj.run / STAGES[stage][1]
    rec = load_json(rec_path) if rec_path.exists() else {}
    for s in STEPS:
        r = rec.get(s.name, {})
        print(f"{s.name:16s} {r.get('status', '-'):28s} {r.get('seconds', ''):>8} {r.get('at', '')}")

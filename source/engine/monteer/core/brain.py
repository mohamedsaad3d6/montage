"""The "brain": every judgement step goes through this one interface.

A step that needs judgement (a shot plan, which clip to use, which words a line is about, an image prompt …)
calls `decide(project, step, key, request)`. The request says what is needed, which files to read and the
shape of the answer. The answer (the decision) is saved in <project>/decisions/<step>/<key>.json together with
the fingerprint of the request, so a rerun with the same inputs repeats it exactly and never asks again.

Brains:
  claude-bg (default)    Claude Code run by the engine itself in the background (`claude -p`, restricted, read-only),
                         on the device owner's own Claude subscription: no session needs to be open
                         (core/claudebrain.py; owner's decision of 15 Oct 2026, option A).
  claude-code            A person in a Claude Code session: the run stops and writes the request next to where the decision must go
                         (<project>/decisions/<step>/<key>.request.json) and lists it in run/waiting.json.
                         Claude Code reads it, writes the decision with `monteer brain answer …`, and the run
                         is started again; it continues from that step.
  api                    Placeholder for a connected paid model (e.g. Claude via the API). It must implement
                         `answer(request) -> decision` and is chosen with project option "brain": "api".
                         Not built yet: no paid service is used. When it fails (not connected, no credit, an outage),
                         the free local model takes over SMALL requests only (marked "local_ok"); for anything larger
                         (an outline, a draft) the run stops with a clear message (report decision 1a, 15 Oct 2026).
  local                  A free local model (llama.cpp on the CPU, monteer/core/localbrain.py). A fallback only:
                         chosen with "brain": "local" or `--brain local` (then it answers everything it is given), or
                         taking over small requests from a failed api brain.
                         It answers only self-contained requests (instructions + inline inputs + answer_schema, as the
                         script tool writes them). Every decision it makes says so in made_by ("local:…"), and the
                         script tool labels it everywhere it is shown.
The brain for a run: the MONTEER_BRAIN environment variable (set by `--brain`), else the project option "brain".

A decision whose request has changed since it was made (its inputs changed) is "stale": the run stops again
and asks, unless the request is accepted unchanged with `monteer brain accept …`.
"""
import hashlib
import json
import os
import time

from .io import load_json, save_json

WAITING_EXIT = 3          # exit code of a step that stopped to wait for a decision


class NeedsDecision(Exception):
    def __init__(self, items):
        super().__init__("; ".join(f"{i['step']}/{i['key']}" for i in items))
        self.items = items


class BrainUnavailable(Exception):
    """this brain can't answer (not connected, failed, or the request needs what it can't read)"""


ROUTING = ("local_ok", "one_try")   # how it is answered (which brain may, how many tries), not what is asked: not part
                                   # of a request's fingerprint


def set_aside(dec):
    """a decision about to be replaced by a new answer is kept as <key>.replaced_<time>.json, never overwritten (19 Oct
    2026: the first real test's good clip review was lost under a broken one)"""
    if dec.exists():
        dec.rename(dec.with_name(f"{dec.stem}.replaced_{time.strftime('%Y%m%d-%H%M%S')}.json"))


def request_sha(request):
    if isinstance(request, dict):
        request = {k: v for k, v in request.items() if k not in ROUTING}
    return hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


class Brain:
    name = "base"

    def decide(self, project, step, key, request):
        raise NotImplementedError


class FileBrain(Brain):
    """claude-code: decisions are files; a missing one stops the run."""
    name = "claude-code"

    def paths(self, project, step, key):
        d = project.decisions / step
        return d / f"{key}.json", d / f"{key}.request.json"

    def decide(self, project, step, key, request):
        dec, req = self.paths(project, step, key)
        sha = request_sha(request)
        if dec.exists():
            d = load_json(dec)
            if d.get("request_sha") == sha:
                return d["decision"]
            why = "inputs changed since this decision was made"
        else:
            why = "no decision yet"
        save_json(req, dict(request, step=step, key=key, request_sha=sha, why=why,
                            answer_with=f"monteer brain answer \"{project.folder}\" {step} {key} <decision.json>"))
        raise NeedsDecision([{"step": step, "key": key, "request": str(req), "why": why}])


class ApiBrain(Brain):
    """A connected paid model answers the request directly (not built: no paid service is used yet)."""
    name = "api"

    def decide(self, project, step, key, request):
        raise BrainUnavailable("the paid API brain is not connected yet")


class LocalBrain(Brain):
    """the free local model; its decisions are stored like Claude Code's, with made_by 'local:<model>'"""
    name = "local"

    def __init__(self, fallback_from=None):
        self.fallback_from = fallback_from

    def decide(self, project, step, key, request):
        from . import localbrain
        if not localbrain.can_answer(request):
            raise BrainUnavailable(f"{step}/{key}: the local model can only answer self-contained requests")
        dec, req = FileBrain().paths(project, step, key)
        t0 = time.time()
        decision, info = localbrain.answer(request)
        rec = {"step": step, "key": key, "request_sha": request_sha(request), "made_by": f"local:{info['model']}",
               "made_at": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": round(time.time() - t0, 1), "local": info,
               "decision": decision}
        if self.fallback_from:
            rec["fallback_from"] = self.fallback_from
        set_aside(dec)
        save_json(dec, rec)
        req.unlink(missing_ok=True)
        print(f"[brain] {step}/{key}: answered by the FREE LOCAL MODEL ({info['model']}) in {rec['seconds']} s"
              + (f" — fallback: {self.fallback_from}" if self.fallback_from else ""), flush=True)
        return decision


class BackgroundBrain(Brain):
    """claude-bg: Claude Code run by the engine itself, on the device owner's own subscription (core/claudebrain.py).
    No person needs a session open. When it cannot answer (not installed, not logged in, repeated failures; a usage limit
    is waited out instead), report decision 1a applies: a small request goes to the free local model, labelled; anything
    larger stops the run with a clear message."""
    name = "claude-bg"

    def decide(self, project, step, key, request):
        from . import claudebrain
        dec, req = FileBrain().paths(project, step, key)
        model = project.opt("claude_model", "opus")
        print(f"[brain] {step}/{key}: asking background Claude Code ({model}) — {request.get('what', '')[:90]}", flush=True)
        try:
            one = isinstance(request, dict) and request.get("one_try")      # a cheap look the engine may go without
            decision, info = claudebrain.answer(request, project.folder, model=model, tries=1 if one else 3,
                                                wait_hours=0 if one else float(project.opt("usage_wait_hours", 8)))
        except RuntimeError as e:
            if isinstance(request, dict) and request.get("local_ok"):
                print(f"[brain] {step}/{key}: background Claude Code failed ({e}); the free local model takes over this small request", flush=True)
                return LocalBrain(fallback_from=f"background Claude Code failed: {e}").decide(project, step, key, request)
            raise BrainUnavailable(f"background Claude Code could not answer {step}/{key} ({e}). Check `claude auth status`, "
                                   "then run again (decisions already made are kept)")
        set_aside(dec)
        save_json(dec, {"step": step, "key": key, "request_sha": request_sha(request), "made_by": f"claude-code-bg:{info['model']}",
                        "made_at": time.strftime("%Y-%m-%d %H:%M:%S"), "seconds": info["seconds"], "usage": info, "decision": decision})
        req.unlink(missing_ok=True)
        print(f"[brain] {step}/{key}: answered by background Claude Code in {info['seconds']} s", flush=True)
        return decision


class FallbackBrain(Brain):
    """the paid API brain; when it fails, the free local model takes over SMALL requests only (report decision 1a): a request
    marked "local_ok" (search terms, choosing what to read, fact cards from a short text, fixing single lines). Anything
    larger (the outline, the draft) stops the run with a clear message; `--brain local` still forces the local model."""
    name = "api"

    def decide(self, project, step, key, request):
        try:
            return ApiBrain().decide(project, step, key, request)
        except BrainUnavailable as e:
            if not (isinstance(request, dict) and request.get("local_ok")):
                raise BrainUnavailable(
                    f"the paid brain failed ({e}). {step}/{key} ({request.get('what', '') if isinstance(request, dict) else ''}) "
                    "is too large for the free local model, which only takes over small requests (report decision 1a). "
                    "Run again when the paid brain works, or force the local model with  --brain local")
            print(f"[brain] {step}/{key}: API brain failed ({e}); the free local model takes over this small request", flush=True)
            return LocalBrain(fallback_from=f"api brain failed: {e}").decide(project, step, key, request)


DEFAULT = "claude-bg"            # owner's decision (15 Oct 2026, option A): the engine runs Claude Code itself


def brain_name(project):
    return os.environ.get("MONTEER_BRAIN") or project.opt("brain", DEFAULT)


BRAINS = {"claude-bg": BackgroundBrain, "claude-code": FileBrain, "api": FallbackBrain, "local": LocalBrain}


def get_brain(project):
    name = brain_name(project)
    if name not in BRAINS:
        raise SystemExit(f"unknown brain {name!r} ({', '.join(BRAINS)})")
    return BRAINS[name]()


def existing(project, step, key, request):
    """the stored decision record for exactly this request (whoever made it), or None"""
    dec, _ = FileBrain().paths(project, step, key)
    if dec.exists():
        d = load_json(dec)
        if d.get("request_sha") == request_sha(request):
            return d
    return None


def decide(project, step, key, request):
    d = existing(project, step, key, request)
    if d is not None:
        return d["decision"]
    return get_brain(project).decide(project, step, key, request)


def record(project, step, key):
    """the stored decision record (decision + made_by + when), or None"""
    dec, _ = FileBrain().paths(project, step, key)
    return load_json(dec) if dec.exists() else None


def answer(project, step, key, decision, made_by="claude-code"):
    """store a decision for the request currently waiting at step/key"""
    dec, req = FileBrain().paths(project, step, key)
    if not req.exists():
        raise SystemExit(f"no request is waiting at {step}/{key} (run the project first)")
    r = load_json(req)
    save_json(dec, {"step": step, "key": key, "request_sha": r["request_sha"], "made_by": made_by,
                    "made_at": time.strftime("%Y-%m-%d %H:%M:%S"), "decision": decision})
    req.unlink()
    return dec


def redo(project, step, key):
    """set a decision aside (kept as <key>.replaced_<time>.json) so the next run asks for it again"""
    dec, _ = FileBrain().paths(project, step, key)
    if not dec.exists():
        raise SystemExit(f"no decision at {step}/{key}")
    dec.rename(dec.with_name(f"{key}.replaced_{time.strftime('%Y%m%d-%H%M%S')}.json"))


def accept(project, step, key):
    """keep a stale decision as it is for the current request"""
    dec, req = FileBrain().paths(project, step, key)
    d, r = load_json(dec), load_json(req)
    d.update(request_sha=r["request_sha"], accepted_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    save_json(dec, d)
    req.unlink()

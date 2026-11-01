"""Edit until satisfied (web panel plan 2.5, phase 5): the owner's timecoded requests on a finished version become a new
version, redoing only what they touch. Every version is kept; the original decisions are never lost.

  new_round(p, requests)   requests: [{"text", "t", "t_end"?}] or a recorded alternative chosen with «غيّرها»
                           ({"alt": {"kind": "pick", "ref": "sources/assets_1", "shot": 4, "n": 2}} for a picture, or
                           {"alt": {"kind": "choice", "ref": "montage/plan", "what", "chosen", "use"}} for the brain's own
                           alternatives) -> decisions/you/edits.json, round N "preparing"
  prepare(p, n)            text requests -> one brain request edits/round_N: which of this episode's decisions change and
                           how (an instruction each), a one-line reply per request. A chosen picture alternative is a code
                           change (checked like the pick itself: in range, the file-repeat rule, not for a shot in Egypt).
                           Then WHAT WILL BE REDONE: the earliest step touched and the steps after it, and roughly how long,
                           from this episode's own step times -> round "prepared" (nothing has changed yet)
  apply(p, n)              the current version is kept in output/versions/v<N>/ (its decisions, cut list, self-check, the
                           names of its video and report); a chosen picture is put in after the picks (pick_overrides: the
                           picks' own requests and decisions stay as they were); the changed requests get
                           the owner's edit (edits_text) and the brain's previous answer to keep the rest; the version
                           goes up; the run starts. Steps whose inputs did not change are skipped, judgement requests that
                           did not change keep their decisions, and only the shots whose content changed are rendered again.
  cancel(p, n)             a prepared round is dropped (nothing was changed)
  edits_text(p, step, key) the words added to a request by the applied rounds (montage/steps.py ask); '' everywhere else (the
                           classic same-result projects never have edits)
"""
import json
import shutil
import time

from ..core.io import load_json, save_json

EDITABLE = {   # request -> (the step that asks it, what it decides)
    "montage/shots": ("plan", "the audio type's plan: every shot's type, search words, subject, place; on-screen words; our graphics; the sections' music moods"),
    "montage/plan": ("plan", "the presenter type's block plan: what each B-roll block shows, its pace and search words"),
    "graphics/scenes": ("timeline", "our graphics and labels (with presenter): their text, numbers, maps, timing"),
    "montage/timeline": ("timeline", "the cut list's blocks (with presenter): where B-roll and graphics go and which assets each shows"),
    "music/cues": ("music", "the music cues: mood and length of each section's music"),
    "montage/sound": ("mix", "the sound plan: music sections and stops, hits, pops, whooshes"),
    "ai/prompts": ("ai_images", "the drawn images' prompts"),
}
SCHEMA = {"type": "object", "required": ["changes", "replies"], "properties": {
    "changes": {"type": "array", "items": {"type": "object", "required": ["request", "instruction", "for"], "properties": {
        "request": {"type": "string"}, "instruction": {"type": "string"}, "for": {"type": "array", "items": {"type": "integer"}},
        "spans_s": {"type": "array", "items": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "number"}}}}}},
    "replies": {"type": "array", "items": {"type": "object", "required": ["n", "reply"], "properties": {
        "n": {"type": "integer"}, "reply": {"type": "string"}}}}}}


def file(p):
    return p.decisions / "you" / "edits.json"


def load(p):
    return load_json(file(p)) if file(p).exists() else {"note": "the owner's edit rounds (montage/edits.py)", "rounds": []}


def rnd(d, n):
    r = next((x for x in d["rounds"] if x["n"] == n), None)
    if not r:
        raise ValueError(f"no edit round {n}")
    return r


def editable(p):
    """{request: (step, what)} of this episode: the brain-made decisions that exist"""
    out = {}
    for k, v in EDITABLE.items():
        f = p.decisions / f"{k}.json"
        if f.exists() and not str(load_json(f).get("made_by", "")).startswith("code"):
            out[k] = v
    return out


def current_version(p):
    """the version on disk (project.json), not a value read earlier by this process"""
    return int((load_json(p.folder / "project.json").get("options") or {}).get("version", 1))


def busy(p):
    from ..core.runctl import lock_pid
    return bool(lock_pid(p.folder))


# ---------------------------------------------------------------------------------------------------- the rounds
def new_round(p, requests, by="owner"):
    from .result import videos
    if busy(p):
        raise ValueError("a run of this episode is going: wait for it to finish")
    if not videos(p):
        raise ValueError("edits start from a finished video")
    reqs = []
    for i, r in enumerate(requests, 1):
        alt = r.get("alt")
        text = (r.get("text") or "").strip()
        if not text and not alt:
            raise ValueError(f"request {i} is empty")
        reqs.append({"n": i, "text": text[:2000], "t": r.get("t"), "t_end": r.get("t_end"), "alt": alt})
    if not reqs:
        raise ValueError("write at least one request")
    d = load(p)
    if any(x["status"] in ("preparing", "prepared") for x in d["rounds"]):
        raise ValueError("an edit round is already waiting: apply it or cancel it first")
    n = max([x["n"] for x in d["rounds"]] or [0]) + 1
    d["rounds"].append({"n": n, "status": "preparing", "by": by, "made_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "version_from": current_version(p), "requests": reqs})
    save_json(file(p), d)
    return n


def context(p, reqs):
    """what is on screen and said at each request's time"""
    from .steps import M, words
    edl = load_json(M(p, "edl.json"))
    try:
        W = words(p)
    except Exception:  # noqa: BLE001
        W = []
    out = []
    for r in reqs:
        t = r.get("t")
        x = {"n": r["n"], "request": r["text"], "time_s": t}
        if t is not None:
            f = round(float(t) * 24)
            s = next((s for s in edl["shots"] if s["f0"] <= f < s["f1"]), None)
            if s:
                x["on_screen"] = {k: s.get(k) for k in ("kind", "asset", "scene") if s.get(k)}
                x["on_screen"]["shot_s"] = [round(s["f0"] / 24, 2), round(s["f1"] / 24, 2)]
                x["on_screen"]["overlays"] = [o["name"] for o in s.get("overlays", [])]
            x["said_around"] = " ".join(w["w"] for w in W if abs(w["s"] - float(t)) <= 4)
        if r.get("alt"):
            x["chosen_alternative"] = r["alt"]
        out.append(x)
    return out


def alt_text(a):
    """a brain alternative chosen with «غيّرها», as a request in words"""
    return (f"For «{a.get('what', '')}»" + (f" (at {a['at_s']:.0f} s)" if a.get("at_s") is not None else "") +
            f": use «{a.get('use', '')}» instead of «{a.get('chosen', '')}».")


def check_answer(p, d, reqs):
    ok = editable(p)
    probs = []
    ns = {r["n"] for r in reqs}
    for c in d["changes"]:
        if c["request"] not in ok:
            probs.append(f"«{c['request']}» is not one of this episode's editable decisions ({sorted(ok)})")
        if not c["instruction"].strip():
            probs.append(f"the change to {c['request']} has no instruction")
        if not set(c["for"]) <= ns:
            probs.append(f"the change to {c['request']} names requests that do not exist ({c['for']})")
        if c["request"] in TIMED and not c.get("spans_s"):
            probs.append(f"the change to {c['request']} needs spans_s: the time ranges (s) it may touch (everything outside them stays as it is)")
        for a, b in c.get("spans_s") or []:
            if not 0 <= a < b:
                probs.append(f"the change to {c['request']}: span {a}-{b} s is not a time range")
    miss = ns - {x["n"] for x in d["replies"]}
    if miss:
        probs.append(f"reply to every request (missing {sorted(miss)})")
    if probs:
        raise ValueError("; ".join(probs))


def check_pick(p, alt):
    """a chosen picture alternative, checked like the pick itself -> None or why not"""
    from . import place as PL
    from .phrases import Plan
    from .steps import M, decision, words
    f = p.decisions / f"{alt['ref']}.json"
    cand = (load_json(M(p, "candidates.json")).get("by_shot", {}) if M(p, "candidates.json").exists() else {}).get(str(alt["shot"])) or []
    if not f.exists() or not cand:
        return "that picture decision is not on record"
    if not 1 <= int(alt["n"]) <= len(cand):
        return f"candidate {alt['n']} does not exist (1-{len(cand)})"
    d = decision(p, "montage", "shots")
    shot = (d or {}).get("shots", [])[alt["shot"]] if d and alt["shot"] < len(d.get("shots", [])) else {}
    if shot.get("place") == PL.HOME:
        return "a shot about Egypt: describe the picture you want instead (only a picture that shows Egypt may go there)"
    P = Plan(d, words(p), load_json(M(p, "edl.json"))["total_frames"] / 24)
    code = lambda k, n, cs: f"{cs[n - 1]['kind']}:{cs[n - 1]['id']}" if cs and 0 < n <= len(cs) and "id" in cs[n - 1] else None  # noqa: E731
    by = load_json(M(p, "candidates.json")).get("by_shot", {})
    chosen = {}
    for g in sorted(p.decisions.glob("sources/assets_*.json")):
        if ".replaced_" not in g.name:
            chosen.update({x["shot"]: x.get("n") for x in load_json(g)["decision"].get("picks", [])})
    chosen.update(pick_overrides(p))
    uses = []
    for k, n in chosen.items():
        if k != alt["shot"] and n:
            c = code(k, n, by.get(str(k)))
            if c:
                uses.append((P.span(k)[0], c))
    mine = code(alt["shot"], int(alt["n"]), cand)
    if mine and not PL.file_ok(uses, P.span(alt["shot"])[0], mine):
        return "that picture is already shown twice, or within 60 s (the repeat rule)"
    return None


def redo(p, steps_touched, requests=()):
    """the steps from the earliest touched one to the end, and roughly how long (minutes), from this episode's own times"""
    from ..steps import STEPS
    order = [s.name for s in STEPS if p.mode in s.modes]
    if not steps_touched:
        return {"from": None, "steps": [], "minutes": [0, 0]}
    first = min(steps_touched, key=order.index)
    tail = order[order.index(first):]
    rec = load_json(p.run / "record.json") if (p.run / "record.json").exists() else {}
    secs = {s: float((rec.get(s) or {}).get("seconds") or 0) for s in tail}
    render = {"graphics", "parallax", "shots"}
    brain_s = 0.0
    for k in requests:
        f = p.decisions / f"{k}.json"
        if f.exists():
            brain_s += float((load_json(f).get("usage") or {}).get("seconds") or load_json(f).get("seconds") or 0)
    lo = brain_s + sum(v for s, v in secs.items() if s not in render and s not in ("music", "ai_images", "sources")) * 0.6 + \
        sum(secs.get(s, 0) for s in render) * 0.15
    hi = sum(secs.values()) + brain_s
    return {"from": first, "steps": [s for s in tail if s not in ("observe", "learn", "news", "questions", "check")],
            "minutes": [max(1, round(lo / 60)), max(2, round(hi / 60))]}


def prepare(p, n):
    """the round's plan: the brain's changes and replies, the code's picture changes, what will be redone"""
    d = load(p)
    r = rnd(d, n)
    if r["status"] not in ("preparing", "failed"):
        raise ValueError(f"round {n} is {r['status']}")
    texts = [dict(x, text=x["text"] or alt_text(x["alt"])) for x in r["requests"] if not (x.get("alt") or {}).get("kind") == "pick"]
    picks, replies, changes = [], [], []
    for x in r["requests"]:
        a = x.get("alt") or {}
        if a.get("kind") == "pick":
            why = check_pick(p, a)
            picks.append(dict(a, ok=why is None, why=why or ""))
            replies.append({"n": x["n"], "reply": ("هغيّر صورة اللقطة للبديل اللي اخترته." if not why else f"مش هقدر: {why}")})
    try:
        if texts:
            from .steps import ask
            ok = editable(p)
            ans = ask(p, "edits", f"round_{n}",
                      f"EDIT UNTIL SATISFIED: the owner watched version v{r['version_from']} and asks for these edits (context: each "
                      "with its time, what is on screen and said there). For each, decide which of this episode's decisions must "
                      "change (context: editable, what each decides) and write a precise instruction for re-making it: what to "
                      "change, at which shot or time, and that EVERYTHING ELSE STAYS EXACTLY AS IT IS. Change as little as "
                      "possible: prefer the latest decision (a label, a picture's search, a music cue) over re-planning. Never "
                      "break the standing rules: if an edit would, say so in its reply and make no change for it. Reply to "
                      "every request in one line of plain Egyptian Arabic, for the owner. For a change to the plan or the cut "
                      "list (montage/shots, montage/plan, montage/timeline) give spans_s: the time ranges in seconds it may touch; "
                      "code checks that everything outside them stays exactly as it was.",
                      {"changes": [{"request": "montage/shots", "instruction": "…", "for": [1], "spans_s": [[20.0, 40.0]]}], "replies": [{"n": 1, "reply": "…"}]},
                      read=[p.decisions / f"{k}.json" for k in ok], schema=SCHEMA,
                      extra={"context": {"requests": context(p, texts), "editable": {k: v[1] for k, v in ok.items()}}},
                      check=lambda dd: check_answer(p, dd, texts))
            changes, replies = ans["changes"], replies + ans["replies"]
    except Exception as e:  # noqa: BLE001  (the round says why; nothing was changed)
        from ..core.brain import NeedsDecision
        r["status"] = "failed"
        r["why"] = ("the request edits/round_%d waits for a Claude Code session" % n) if isinstance(e, NeedsDecision) else f"{type(e).__name__}: {e}"[:600]
        save_json(file(p), d)
        return r
    touched = {EDITABLE[c["request"]][0] for c in changes}
    if any(x["ok"] for x in picks):
        touched.add("sources")
    rd = redo(p, touched, [c["request"] for c in changes])
    r.update(status="prepared", prepared_at=time.strftime("%Y-%m-%d %H:%M:%S"), changes=changes, picks=picks,
             replies=sorted(replies, key=lambda x: x["n"]), redo=rd)
    r.pop("why", None)
    save_json(file(p), d)
    return r


def snapshot(p, v):
    """output/versions/v<N>/: the version's decisions, cut list, self-check, and its video's and report's names"""
    from .result import videos
    from .steps import M
    dst = p.output / "versions" / f"v{v}"
    if dst.exists():
        return dst
    (dst / "decisions").mkdir(parents=True)
    for f in p.decisions.rglob("*.json"):
        if f.name.endswith(".request.json") or ".replaced_" in f.name:
            continue
        g = dst / "decisions" / f.relative_to(p.decisions)
        g.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, g)
    for n in ("edl.json", "selfcheck.json"):
        if M(p, n).exists():
            shutil.copy2(M(p, n), dst / n)
    vid = next((x["name"] for x in reversed(videos(p)) if x["version"] == v), None)
    save_json(dst / "meta.json", {"version": v, "video": vid, "kept_at": time.strftime("%Y-%m-%d %H:%M:%S")})
    return dst


def apply(p, n, start=True):
    d = load(p)
    r = rnd(d, n)
    if r["status"] != "prepared":
        raise ValueError(f"round {n} is {r['status']}: prepare it first")
    if busy(p):
        raise ValueError("a run of this episode is going: wait for it to finish")
    v = current_version(p)
    snapshot(p, v)
    cfg = load_json(p.folder / "project.json")
    cfg.setdefault("options", {})["version"] = v + 1
    save_json(p.folder / "project.json", cfg)
    r.update(status="applied", applied_at=time.strftime("%Y-%m-%d %H:%M:%S"), version_to=v + 1)
    save_json(file(p), d)
    started = None
    if start:
        from ..core import runctl
        started = runctl.start(p.folder)
    return {"version": v + 1, "started": started}


def cancel(p, n):
    d = load(p)
    r = rnd(d, n)
    if r["status"] not in ("preparing", "prepared", "failed"):
        raise ValueError(f"round {n} is {r['status']}")
    r["status"] = "cancelled"
    save_json(file(p), d)


TIMED = {"montage/shots", "montage/plan", "montage/timeline"}
EDGE_S = 0.3                     # a shot overlapping a touched range by 0.3 s or less is outside it


def _spans(p, ref):
    """the time ranges the applied rounds may touch in this request, and the first round's version (its kept answer)"""
    rows, first = [], None
    for r in load(p)["rounds"]:
        if r["status"] != "applied":
            continue
        for c in r.get("changes", []):
            if c["request"] == ref:
                rows += [tuple(x) for x in c.get("spans_s") or []]
                first = first or r["version_from"]
    return rows, first


def _outside(a, b, spans):
    """a shot or block that does not really overlap any touched range (a shared edge does not count)"""
    if a == b:
        return all(not x <= a <= y for x, y in spans)
    return all(max(0.0, min(b, y) - max(a, x)) <= EDGE_S for x, y in spans)


def untouched_problems(p, step, key, new):
    """an edit that re-makes the plan or the cut list (owner's answer 1 of phases 5-6): every shot or block outside the
    edit's time ranges must be exactly as in the version it started from -> [problem]"""
    ref = f"{step}/{key}"
    if ref not in TIMED:
        return []
    spans, first = _spans(p, ref)
    prev_f = p.output / "versions" / f"v{first}" / "decisions" / f"{ref}.json" if first else None
    if not spans or not prev_f or not prev_f.exists():
        return []
    old = load_json(prev_f)["decision"]
    probs = []
    strip = lambda x: {k: v for k, v in x.items() if k != "alternatives"} if isinstance(x, dict) else x  # noqa: E731
    if ref == "montage/shots":
        from .phrases import Plan
        from .steps import M, words
        W = words(p)
        L = load_json(M(p, "edl.json"))["total_frames"] / 24
        P = Plan(old, W, L)
        new_by = {s["from"]: s for s in new.get("shots", [])}
        for k, s in enumerate(old.get("shots", [])):
            a, b = P.span(k)
            if _outside(a, b, spans) and strip(new_by.get(s["from"])) != strip(s):
                probs.append(f"the shot at {a:.1f}-{b:.1f} s (word {s['from']}) changed, but the edit only touches "
                             + ", ".join(f"{x:g}-{y:g} s" for x, y in spans) + ": keep it exactly as it was")
        for o in old.get("onscreen", []):
            t = W[o["at"]]["s"] if o["at"] < len(W) else None
            if t is not None and _outside(t, t, spans) and o not in new.get("onscreen", []):
                probs.append(f"the on-screen «{o['text']}» at {t:.1f} s changed, but it is outside the edit: keep it")
    else:
        if ref == "montage/plan":
            items_old, items_new = old.get("blocks", []), new.get("blocks", [])
            span = lambda x: (x["in"], x["out"])  # noqa: E731
        else:
            items_old, items_new = old.get("blocks", []), new.get("blocks", [])
            span = lambda x: (x[2], x[3]) if isinstance(x, list) and len(x) > 3 else (None, None)  # noqa: E731
        for x in items_old:
            a, b = span(x)
            if a is not None and _outside(a, b, spans) and strip(x) not in [strip(y) for y in items_new]:
                probs.append(f"the block at {a:.1f}-{b:.1f} s changed, but the edit only touches "
                             + ", ".join(f"{u:g}-{v:g} s" for u, v in spans) + ": keep it exactly as it was")
    return probs[:6]


def pick_overrides(p):
    """{shot: candidate n}: the pictures the owner chose with «غيّرها» (applied rounds, the latest wins). They are put in
    after the picks are made (montage/steps_phrase.py step_sources), so the picks' requests and decisions stay as they were"""
    out = {}
    if file(p).exists():
        for r in load(p)["rounds"]:
            if r["status"] == "applied":
                for a in r.get("picks", []):
                    if a.get("ok"):
                        out[int(a["shot"])] = int(a["n"])
    return out


def edits_text(p, step, key):
    """the applied rounds' instructions for this request, and where its previous answer is kept ('' otherwise)"""
    if not file(p).exists():
        return ""
    ref = f"{step}/{key}"
    rows = []
    for r in load(p)["rounds"]:
        if r["status"] != "applied":
            continue
        for c in r.get("changes", []):
            if c["request"] == ref:
                rows.append((r["n"], r["version_from"], c["instruction"]))
    if not rows:
        return ""
    first = rows[0][1]
    prev = p.output / "versions" / f"v{first}" / "decisions" / f"{ref}.json"
    return ("\nTHE OWNER'S EDITS (after watching the finished video; never above the standing rules). Your answer for version v"
            f"{first} is kept at {prev.relative_to(p.folder)}: start from it, make ONLY these changes, and keep everything else "
            "exactly as it was: " + " ".join(f"(round {n}) {ins}" for n, _, ins in rows))


def sig(p):
    """the applied rounds, for the judgement steps' fingerprint (montage/steps.py rules_sig): an applied edit makes them
    run again (their requests unchanged keep their decisions); None when the episode has no applied edit"""
    if not file(p).exists():
        return None
    ap = [(r["n"], r.get("version_to")) for r in load(p)["rounds"] if r["status"] == "applied"]
    return json.dumps(ap) if ap else None


def history(p):
    """the rounds for the Result screen"""
    return load(p)["rounds"]


__all__ = ["new_round", "prepare", "apply", "cancel", "edits_text", "history", "sig", "editable", "pick_overrides"]

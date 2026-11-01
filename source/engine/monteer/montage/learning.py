"""«عام» learns (phase 2G of the channel profiles; owner's answer 15 of phase 2A and the 2G brief): from the other
profiles' videos (and its own), the AI's choices and the owner's instructions; it applies what it learned by itself and
says in each video's report what it changed and why.

What is recorded (every profile, every finished video; nothing for a project without a profile):
  step "observe" (after the credits) -> AI agent/channels/general/learning/observations/<profile>__<project>.json:
    the cut measured (real pictures, graphics and drawn images over the B-roll time, files shown too often, the biggest
    subjects), the self-check's misses, the AI's answers the engine sent back (and why), the decisions set aside to be
    asked again, the searches that found no usable picture, and the owner's instructions for that episode.
  bin/monteer learn tell "<words>"  -> learning/owner.json: the owner's own instruction to «عام» (kept until forgotten).

What «عام» does with it (step "learn", before the plan; profile montage.learn.applies_by_itself):
  lessons(p) turns the records into lessons by fixed rules in code (no AI decides what is learned):
    owner     every instruction the owner gave «عام» (learn tell)                        -> the plan request(s)
    asked     the same episode instruction given for 2 or more earlier videos             -> the plan request(s)
    rejected  the same kind of answer sent back by the engine in 3 or more earlier videos -> that same request
    selfcheck the same self-check item missed in 2 or more earlier finished videos        -> the plan request(s)
    search    the same search finding no usable picture in 2 or more earlier videos       -> the audio type's plan
  at most MAX_LESSONS, the best supported first. A lesson only ADDS a reminder to a request: it never overrides the
  standing rules, the profile or the episode's own instructions, and every check stays as it is.
  They are worked out ONCE per video (work/montage/lessons.json) and kept, so a run again asks the same requests;
  `bin/monteer learn refresh "<project>"` lets that video learn again. Switches: learn.applies_by_itself false (none
  applied, still listed in the report), learn.off ["<lesson id or kind>", ...] (that lesson or kind not applied).
"""
import hashlib
import json
import re
import time

from ..core.io import load_json, save_json
from ..core.paths import CHANNELS

LEARN = CHANNELS / "general" / "learning"
OBS = LEARN / "observations"
OWNER = LEARN / "owner.json"
MAX_LESSONS = 8
RECENT = 30                    # the last 30 finished videos count
NEED = {"asked": 2, "rejected": 3, "selfcheck": 2, "search": 2}
PLAN_REQUESTS = ("montage/plan", "montage/shots")          # with presenter / audio only
LEARNABLE = PLAN_REQUESTS + ("montage/timeline", "graphics/scenes")

# what a self-check miss asks of the next plan (the self-check's own items, montage/selfcheck.py)
HINTS = {
    "rehooks": "keep a re-hook (a question to the viewer) at least every 3 minutes",
    "on_its_word": "start every on-screen word exactly on the word that says it (anchor it on that word's index)",
    "frozen_shots": "give still-looking footage and photos only short shots, and prefer clips that move",
    "empty_shots": "avoid dark or empty clips (night scenes, black frames) unless the words are about the dark",
    "text_outside_safe": "keep every on-screen text short (1-6 words) so it stays inside the frame",
    "intro": "keep the intro within its length and shot lengths exactly",
    "repeats": "use more different pictures: one file at most twice, 60 s apart, and vary the subjects",
    "presenter_type": "keep the presenter's share and the B-roll rhythm the plan asks for",
    "general_style": "keep at least the profile's share of real pictures and no subject over its share",
}


def mont(p):
    return p.profile_montage() if p is not None else {}


def conf(p):
    return mont(p).get("learn") or {}


def on(p):
    """«عام» (the profile that learns)"""
    return bool(p is not None and p.profile and conf(p).get("from"))


def lessons_file(p):
    from .steps import M
    return M(p, "lessons.json")


def norm(s):
    s = re.sub(r"«[^»]*»", "«…»", str(s))
    s = re.sub(r"\d+(\.\d+)?", "#", s)
    return re.sub(r"\s+", " ", s).strip()[:160]


def key_of(*parts):
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:8]


# ---------------------------------------------------------------------------------------------------- recorded
def log_rejection(p, step, key, problem):
    """the engine sent the AI's answer back (steps.ask): kept for learning (work only; no request changes)"""
    try:
        with open(p.run / "brain_rejections.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"request": f"{step}/{key}", "problem": str(problem)[:600], "at": time.strftime("%Y-%m-%d %H:%M:%S")},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass


def rejections(p):
    f = p.run / "brain_rejections.jsonl"
    out = []
    if f.exists():
        for ln in f.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                pass
    return out


def redone(p, auto):
    """decisions set aside to be asked again, other than the engine's own re-asks: [step/key]"""
    n_auto = {}
    for r in auto:
        n_auto[r["request"]] = n_auto.get(r["request"], 0) + 1
    out = []
    for f in sorted(p.decisions.glob("*/*.replaced_*.json")):
        req = f"{f.parent.name}/{f.name.split('.replaced_')[0]}"
        if n_auto.get(req, 0) > 0:
            n_auto[req] -= 1
        else:
            out.append(req)
    return out


def selfcheck_misses(p):
    from .steps import M
    f = M(p, "selfcheck.json")
    if not f.exists():
        return []
    out = []
    for k, v in load_json(f).items():
        if isinstance(v, dict) and v.get("ok") is False:
            out.append(k)
        elif isinstance(v, list) and v and k in ("empty_shots", "frozen_shots", "text_outside_safe"):
            out.append(k)
    return out


def search_misses(p):
    """the audio type's searches that found no usable picture (the build's fallbacks)"""
    from .steps import M, decision
    f = M(p, "build_report.json")
    if not f.exists():
        return []
    shots = (decision(p, "montage", "shots") or {}).get("shots", [])
    hf = M(p, "held_shots.json")             # a clip left out over a silence for being too short is not an empty search
    short = {int(k) for k, v in (load_json(hf) if hf.exists() else {}).items() if "too short" in v.get("result", "")}
    out = []
    for fb in load_json(f).get("fallbacks", []):
        m = re.match(r"shot (\d+)", fb)
        if m and int(m.group(1)) < len(shots) and int(m.group(1)) not in short:
            out += [q.lower() for q in shots[int(m.group(1))].get("search") or []]
    return out


def subjects(p, L):
    """the biggest subjects of the plan, as shares of the running time"""
    from . import general as GEN
    from .steps import decision, phrase_mode, words
    try:
        if phrase_mode(p):
            from .phrases import FOOTAGE, Plan
            d = decision(p, "montage", "shots")
            P = Plan(d, words(p), L)
            spans = [(s.get("subject", ""), P.span(k)[1] - P.span(k)[0]) for k, s in enumerate(d["shots"]) if s["type"] in FOOTAGE]
        else:
            d = decision(p, "montage", "plan") or {}
            spans = [(b.get("subject", ""), b["out"] - b["in"]) for b in d.get("blocks", []) if not b.get("presenter")]
    except Exception:  # noqa: BLE001  (a plan without subjects measures nothing)
        return {}
    return dict(list(GEN.subject_shares(spans, L).items())[:3])


def observe(p):
    """the step "observe": this finished video's record for «عام»'s learning (any profile; nothing without one)"""
    if not p.profile or p.opt("render_window"):       # a preview is not a finished video
        return
    from . import general as GEN
    from .steps import M
    edl = load_json(M(p, "edl.json"))
    L = edl["total_frames"] / 24
    rej = rejections(p)
    les = load_json(lessons_file(p)) if lessons_file(p).exists() else {}
    rec = {"profile": p.profile, "project": p.folder.name, "type": "presenter" if p.mode == "talking_head" else "audio",
           "observed_at": time.strftime("%Y-%m-%d %H:%M:%S"), "length_s": round(L, 1), "cut": GEN.measure(p, edl),
           "subjects": subjects(p, L), "selfcheck_misses": selfcheck_misses(p),
           "rejected": [{"request": r["request"], "problem": r["problem"]} for r in rej], "redone": redone(p, rej),
           "search_misses": search_misses(p), "instructions": p.instructions,
           "lessons_applied": [x["id"] for x in les.get("lessons", []) if x.get("applied")]}
    OBS.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^\w.-]+", "_", f"{p.profile}__{p.folder.name}")
    save_json(OBS / f"{name}.json", rec)
    print(f"learning: this video's record kept for «عام» ({OBS.name}/{name}.json): {len(rec['selfcheck_misses'])} self-check "
          f"miss(es), {len(rec['rejected'])} answer(s) sent back, real pictures {rec['cut']['real_share'] * 100:.0f} %")


def observations(exclude=None):
    if not OBS.exists():
        return []
    recs = []
    for f in OBS.glob("*.json"):
        try:
            r = load_json(f)
        except ValueError:
            continue
        if exclude and r.get("project") == exclude:
            continue
        recs.append(r)
    return sorted(recs, key=lambda r: r.get("observed_at", ""))[-RECENT:]


def owner_notes():
    return [n for n in (load_json(OWNER).get("notes", []) if OWNER.exists() else []) if n.get("active", True)]


# ---------------------------------------------------------------------------------------------------- learned
def similar(a, b):
    ta, tb = set(re.findall(r"\w+", a.lower())), set(re.findall(r"\w+", b.lower()))
    return bool(ta and tb) and len(ta & tb) / len(ta | tb) >= 0.5


def lessons(p, recs=None, notes=None):
    """[{"id", "kind", "requests", "text", "why", "evidence"}] from the records (this video's own record left out)"""
    recs = observations(exclude=p.folder.name) if recs is None else recs
    notes = owner_notes() if notes is None else notes
    out = []
    for n in notes:
        out.append({"id": f"owner:{key_of(n['text'])}", "kind": "owner", "requests": list(PLAN_REQUESTS),
                    "text": f"The owner told this channel: «{n['text']}».", "why": f"the owner's instruction to «عام» of {n.get('at', '?')}",
                    "evidence": ["bin/monteer learn tell"], "support": 99})
    asked = []                                   # the same episode instruction in 2 or more videos
    for r in recs:
        t = (r.get("instructions") or "").strip()
        if not t:
            continue
        g = next((g for g in asked if similar(g["text"], t)), None)
        if g:
            g["videos"].append(r["project"])
        else:
            asked.append({"text": t, "videos": [r["project"]]})
    for g in asked:
        if len(set(g["videos"])) >= NEED["asked"]:
            out.append({"id": f"asked:{key_of(norm(g['text']))}", "kind": "asked", "requests": list(PLAN_REQUESTS),
                        "text": f"In {len(set(g['videos']))} earlier videos the owner asked: «{g['text'][:400]}»; do the same here "
                                "unless this episode's own instructions say otherwise.",
                        "why": f"the same instruction for {len(set(g['videos']))} videos", "evidence": sorted(set(g["videos"])),
                        "support": len(set(g["videos"]))})
    rej = {}                                     # the same kind of answer sent back in 3 or more videos
    for r in recs:
        for x in r.get("rejected", []):
            if x["request"] not in LEARNABLE:
                continue
            for part in str(x["problem"]).split(";"):
                k = (x["request"], norm(part.split(": ", 1)[-1] if part.startswith(("ValueError", "KeyError")) else part))
                rej.setdefault(k, {"videos": set(), "example": re.sub(r"^\w+Error: ", "", part.strip())[:300]})["videos"].add(r["project"])
    for (req, pat), v in rej.items():
        if len(v["videos"]) >= NEED["rejected"]:
            out.append({"id": f"rejected:{req}:{key_of(pat)}", "kind": "rejected", "requests": [req],
                        "text": f"Answers to this request were sent back in {len(v['videos'])} earlier videos for: «{v['example']}»; "
                                "get this right the first time.",
                        "why": f"the engine sent this back in {len(v['videos'])} videos", "evidence": sorted(v["videos"]),
                        "support": len(v["videos"])})
    sc = {}                                      # the same self-check item missed in 2 or more finished videos
    for r in recs:
        for k in r.get("selfcheck_misses", []):
            sc.setdefault(k, set()).add(r["project"])
    for k, vids in sc.items():
        if len(vids) >= NEED["selfcheck"]:
            hint = HINTS.get(k, f"plan so that the self-check «{k}» passes")
            out.append({"id": f"selfcheck:{k}", "kind": "selfcheck", "requests": list(PLAN_REQUESTS),
                        "text": f"Earlier finished videos missed the self-check «{k}» ({len(vids)} times): {hint}.",
                        "why": f"the self-check «{k}» failed in {len(vids)} finished videos", "evidence": sorted(vids), "support": len(vids)})
    se = {}                                      # searches that found nothing usable, in 2 or more videos
    for r in recs:
        for q in r.get("search_misses", []):
            se.setdefault(q, set()).add(r["project"])
    bad = sorted((q for q, v in se.items() if len(v) >= NEED["search"]), key=lambda q: -len(se[q]))[:8]
    if bad:
        vids = sorted(set().union(*(se[q] for q in bad)))
        out.append({"id": f"search:{key_of(*bad)}", "kind": "search", "requests": ["montage/shots"],
                    "text": "These searches found no usable picture in earlier videos: " + ", ".join(f"«{q}»" for q in bad)
                            + "; for the same idea search with plainer, more common words.",
                    "why": f"{len(bad)} search(es) came back empty in 2 or more videos", "evidence": vids,
                    "support": min(len(se[q]) for q in bad)})
    out.sort(key=lambda x: (-x["support"], x["id"]))
    for x in out:
        x.pop("support", None)
    return out


def step(p):
    """the step "learn" (before the plan): «عام» works out its lessons once for this video and keeps them"""
    if not on(p):
        return
    f = lessons_file(p)
    if f.exists():
        d = load_json(f)
        print(f"learning: {sum(1 for x in d['lessons'] if x.get('applied'))} lesson(s) kept for this video (bin/monteer learn refresh to learn again)")
        return
    c = conf(p)
    off = set(c.get("off") or [])
    by_self = c.get("applies_by_itself") is not False
    ls = lessons(p)
    n = 0
    for x in ls:
        why_not = ("switched off in the profile (learn.off)" if x["id"] in off or x["kind"] in off else
                   "learn.applies_by_itself is false" if not by_self else
                   f"more than {MAX_LESSONS} lessons; the best supported are applied" if n >= MAX_LESSONS else None)
        x["applied"] = why_not is None
        if why_not:
            x["not_applied_why"] = why_not
        else:
            n += 1
    recs = observations(exclude=p.folder.name)
    save_json(f, {"note": "what «عام» learned for this video (montage/learning.py); kept until bin/monteer learn refresh",
                  "made_at": time.strftime("%Y-%m-%d %H:%M:%S"), "from_videos": len(recs),
                  "profiles_seen": sorted({r["profile"] for r in recs}), "owner_notes": len(owner_notes()), "lessons": ls})
    print(f"learning: {n} lesson(s) applied, from {len(recs)} earlier video(s) and {len(owner_notes())} owner note(s)")


def applied(p, request=None):
    if not on(p) or not lessons_file(p).exists():
        return []
    return [x for x in load_json(lessons_file(p)).get("lessons", []) if x.get("applied") and (request is None or request in x["requests"])]


def request_text(p, request):
    """the lessons for one request, as words added at its end ('' for every other profile and with none)"""
    xs = applied(p, request)
    if not xs:
        return ""
    return ("\nLESSONS THIS CHANNEL LEARNED (made in code from earlier videos and the owner's words, montage/learning.py; they "
            "never override the rules above or this episode's instructions): " + " ".join(f"({k + 1}) {x['text']}" for k, x in enumerate(xs)))


def report_lines(p):
    """the video's report: what «عام» learned and applied, why, and on what evidence"""
    if not on(p):
        return []
    if not lessons_file(p).exists():
        return ["## What «عام» learned and applied", "", "- nothing yet: the step «learn» has not run for this video", ""]
    d = load_json(lessons_file(p))
    out = ["## What «عام» learned and applied", "",
           f"From {d['from_videos']} earlier finished video(s) ({', '.join(d['profiles_seen']) or 'none yet'}) and "
           f"{d['owner_notes']} instruction(s) the owner gave «عام». A lesson only adds a reminder to a request; the rules and "
           "checks stay as they are.", ""]
    if not d["lessons"]:
        out.append("- no lesson: nothing came up often enough yet (an instruction in 2 videos, an answer sent back in 3, a "
                   "self-check missed in 2, a search empty in 2)")
    for x in d["lessons"]:
        state = "applied" if x.get("applied") else f"not applied ({x.get('not_applied_why')})"
        out.append(f"- **{x['kind']}** ({state}) — changed: added to {', '.join(x['requests'])}: {x['text']} — why: {x['why']} — "
                   f"evidence: {', '.join(x['evidence'][:6])}")
    return out + [""]


def tell(text, by="owner"):
    """the owner's instruction to «عام» (bin/monteer learn tell, or the panel's box)"""
    text = (text or "").strip()
    if not text:
        raise ValueError("write what «عام» should know")
    d = load_json(OWNER) if OWNER.exists() else {"note": "the owner's instructions to «عام» (bin/monteer learn tell)", "notes": []}
    d["notes"].append({"text": text[:1000], "at": time.strftime("%Y-%m-%d %H:%M"), "active": True, "by": by})
    LEARN.mkdir(parents=True, exist_ok=True)
    save_json(OWNER, d)
    return len(d["notes"])


def forget(n):
    d = load_json(OWNER) if OWNER.exists() else {"notes": []}
    if not 1 <= int(n) <= len(d["notes"]):
        raise ValueError(f"no note {n}")
    d["notes"][int(n) - 1]["active"] = False
    save_json(OWNER, d)


def box():
    """the panel's «عام» box: the notes, the records, the lessons a new «عام» video would get now"""
    recs = observations()
    notes = load_json(OWNER).get("notes", []) if OWNER.exists() else []
    return {"notes": [dict(x, n=k + 1) for k, x in enumerate(notes)], "records": len(recs),
            "profiles_seen": sorted({r["profile"] for r in recs}), "lessons_now": lessons(None, recs)}


# ---------------------------------------------------------------------------------------------------- bin/monteer learn
def main(argv):
    """bin/monteer learn show ["<project>"] | tell "<words>" | forget N | refresh "<project>" """
    from ..core.project import Project
    cmd = argv[0] if argv else "show"
    if cmd == "tell" and len(argv) > 1:
        n = tell(" ".join(argv[1:]), by="owner (bin/monteer learn)")
        print(f"kept: «عام» will apply it from its next video (note {n})")
        return 0
    if cmd == "forget" and len(argv) > 1:
        forget(int(argv[1]))
        print(f"note {argv[1]} is no longer applied")
        return 0
    if cmd == "refresh" and len(argv) > 1:
        p = Project(argv[1])
        if lessons_file(p).exists():
            lessons_file(p).rename(lessons_file(p).with_name(f"lessons.replaced_{time.strftime('%Y%m%d-%H%M%S')}.json"))
        print("this video learns again on its next run (its plan is asked again only if the lessons changed)")
        return 0
    if cmd == "show":
        recs = observations()
        print(f"records: {len(recs)} finished video(s) ({', '.join(sorted({r['profile'] for r in recs})) or 'none yet'}); "
              f"owner notes: {len(owner_notes())}")
        for k, n in enumerate(load_json(OWNER).get("notes", []) if OWNER.exists() else []):
            print(f"  note {k + 1}{'' if n.get('active', True) else ' (forgotten)'}: {n['text']}")
        if len(argv) > 1:
            p = Project(argv[1])
            xs = load_json(lessons_file(p))["lessons"] if lessons_file(p).exists() else lessons(p)
        else:
            xs = lessons(None, recs)          # a new video: no record of its own to leave out
        print(f"lessons a new «عام» video would get now: {len(xs)}")
        for x in xs:
            print(f"  - [{x['kind']}] {x['text']}  (why: {x['why']})")
        return 0
    print(main.__doc__)
    return 1


__all__ = ["observe", "step", "lessons", "request_text", "report_lines", "log_rejection", "applied", "on", "main"]

"""Step-by-step mode (run_mode "step"; web panel plan 2.6, built with its phase 3 on the owner's request of 18 Oct 2026):
after the plan, the brain turns the plan's real choice points into 3-6 numbered questions for the owner, each with 2-4
options, its own pick (what the plan did) and a one-line reason; the run stops until the owner answers them all at once.

  step "questions" (after "plan")   auto mode: nothing. Step mode: asks montage/questions once, then stops (waiting for
                                    "you/plan_answers", kind "owner") until the answers are in; with them it goes on.
  store(p, mode, answers, by)       the owner's answers -> decisions/you/plan_answers.json:
                                      "answers"        each question's chosen option key, or "other" with the owner's words
                                      "accept_all"     every pick is taken as the answer (the plan stays as it is)
                                      "let_it_decide"  the project switches to auto and goes on (the plan stays)
  answers_text(p, step, key)        added to the plan request (montage/plan or montage/shots) ONLY when an answer differs
                                    from the brain's pick: the plan is then asked again with the owner's choices. With
                                    no answers, or answers equal to the picks, the request is unchanged (no re-plan; the
                                    classic same-result projects never have answers).
"""
import time

from ..core.io import load_json, save_json

PLAN_KEYS = {("montage", "plan"), ("montage", "shots")}
SCHEMA = {"type": "object", "required": ["questions"], "properties": {
    "questions": {"type": "array", "minItems": 3, "maxItems": 6, "items": {"type": "object", "required": ["n", "question", "options", "pick", "why"],
        "properties": {"n": {"type": "integer"}, "question": {"type": "string"}, "why": {"type": "string"}, "pick": {"type": "string"},
                       "options": {"type": "array", "minItems": 2, "maxItems": 4, "items": {"type": "object", "required": ["key", "label"],
                                   "properties": {"key": {"type": "string"}, "label": {"type": "string"}}}}}}},
    "mix": {"type": "object"}}}


def step_mode(p):
    return p.opt("run_mode", "auto") == "step"


def answers_file(p):
    return p.decisions / "you" / "plan_answers.json"


def questions(p):
    f = p.decisions / "montage" / "questions.json"
    return load_json(f)["decision"] if f.exists() else None


def answers(p):
    f = answers_file(p)
    return load_json(f) if f.exists() else None


def plan_file(p):
    from .steps import phrase_mode
    return p.decisions / "montage" / ("shots.json" if phrase_mode(p) else "plan.json")


def check(d):
    probs = []
    ns = [q["n"] for q in d["questions"]]
    if ns != list(range(1, len(ns) + 1)):
        probs.append(f"number the questions 1..{len(ns)} in order (got {ns})")
    for q in d["questions"]:
        keys = [o["key"] for o in q["options"]]
        if len(set(keys)) != len(keys):
            probs.append(f"question {q['n']}: option keys must differ ({keys})")
        if q["pick"] not in keys:
            probs.append(f"question {q['n']}: pick «{q['pick']}» is not one of its option keys {keys}")
        if "other" in keys:
            probs.append(f"question {q['n']}: «other» is the owner's own answer, not an option key")
    if probs:
        raise ValueError("; ".join(probs))


def step(p):
    """the step "questions": in step-by-step mode, the owner's questions on the plan, and the stop for the answers"""
    if not step_mode(p):
        return
    a = answers(p)
    if a:
        print(f"questions: your answers are in ({a['mode']}); the run goes on")
        return
    from .steps import ask
    d = ask(p, "montage", "questions",
            "STEP-BY-STEP MODE: the owner wants to approve the plan before the material is gathered. From the plan you made "
            "(read it), list 3-6 numbered questions where the plan made a real choice the owner may want differently: e.g. "
            "how the video opens, how a key idea is shown (footage, archive, a map, numbers, a drawn image), the music's "
            "mood in a section, where the presenter is on screen, which country or place a passage shows. Write each "
            "question and its options in plain Egyptian Arabic, as you would ask the channel's owner; 2-4 options each, "
            "with short keys (a, b, c, d); pick = the key of what the plan did; why = one line on why you chose it. Do not "
            "ask about the standing rules (they are fixed). Also give mix: the planned share of each material type.",
            {"questions": [{"n": 1, "question": "…", "options": [{"key": "a", "label": "…"}, {"key": "b", "label": "…"}],
                            "pick": "a", "why": "…"}], "mix": {"stock": 0.3, "archive": 0.2}},
            read=[plan_file(p)], schema=SCHEMA, check=check)
    from ..core.brain import NeedsDecision
    raise NeedsDecision([{"step": "you", "key": "plan_answers", "kind": "owner", "request": None,
                          "why": f"{len(d['questions'])} question(s) on the plan, waiting for your answers"}])


def store(p, mode, given=None, by="owner"):
    """the owner's answers (the panel's approval card or bin/monteer answer) -> decisions/you/plan_answers.json"""
    q = questions(p)
    if not q:
        raise ValueError("this episode has no questions waiting")
    if mode not in ("answers", "accept_all", "let_it_decide"):
        raise ValueError("answer, accept all the recommendations, or let it decide")
    rows = []
    given = {int(k): v for k, v in (given or {}).items()}
    for x in q["questions"]:
        keys = {o["key"] for o in x["options"]}
        g = given.get(x["n"]) if mode == "answers" else {"choice": x["pick"]}
        if not g or not (g.get("choice") in keys or (g.get("choice") == "other" and (g.get("text") or "").strip())):
            raise ValueError(f"question {x['n']} has no answer (choose an option, or write your own)")
        rows.append({"n": x["n"], "choice": g["choice"], "text": (g.get("text") or "").strip()[:1000] if g["choice"] == "other" else ""})
    save_json(answers_file(p), {"mode": mode, "by": by, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "answers": rows})
    if mode == "let_it_decide":                       # the project goes on by itself from here
        cfg = load_json(p.folder / "project.json")
        cfg.setdefault("options", {})["run_mode"] = "auto"
        save_json(p.folder / "project.json", cfg)
    return rows


def answers_text(p, step, key):
    """the plan request's added words when the owner chose differently from the brain's picks ('' otherwise)"""
    if (step, key) not in PLAN_KEYS:
        return ""
    a, q = answers(p), questions(p)
    if not a or not q or a["mode"] != "answers":
        return ""
    by = {x["n"]: x for x in q["questions"]}
    changed = []
    for r in a["answers"]:
        x = by.get(r["n"])
        if not x or r["choice"] == x["pick"]:
            continue
        label = next((o["label"] for o in x["options"] if o["key"] == r["choice"]), None)
        changed.append(f"({r['n']}) {x['question']} -> " + (f"«{r['text']}» (the owner's own words)" if r["choice"] == "other" else f"«{label}»"))
    if not changed:
        return ""
    return ("\nTHE OWNER ANSWERED YOUR QUESTIONS ON THE FIRST PLAN (step-by-step mode). Make the plan again following these "
            "answers (they never override the standing rules): " + " ".join(changed))


def card(p):
    """what the panel's approval card shows: the questions, the planned mix, and the answers if any"""
    q = questions(p)
    if not q:
        return None
    return {"questions": q["questions"], "mix": q.get("mix") or {}, "answered": answers(p)}


__all__ = ["step", "store", "answers_text", "card", "step_mode", "PLAN_KEYS"]

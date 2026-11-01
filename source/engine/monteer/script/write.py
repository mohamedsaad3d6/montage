"""Steps outline* -> outline_ok (your yes, decision 10a) -> draft* (part by part) -> verify (checks + up to 2 revise* rounds).

The writer never sees an article: only fact cards (our wording + outlet + date; quotes with their exact words), the
style guide, the outline and the measures. A line that relies on facts names its cards; a line with no card is
commentary and may hold no number.
"""
import json

from ..core import brain
from ..core.brain import NeedsDecision
from ..core.io import load_json, save_json, write_text
from . import checks, style
from .common import MIX, S, TYPE_HELP, TYPES, card_brief, cards, channel_dir, latest_version, now, sha, topic
from .research import ask_all, request

TYPE_ENUM = list(TYPES)

OUTLINE_SCHEMA = {"type": "object", "required": ["title", "angle", "cold_open", "parts", "closing"], "properties": {
    "title": {"type": "string"}, "angle": {"type": "string"},
    "cold_open": {"type": "object", "required": ["idea", "cards"], "properties": {"idea": {"type": "string"},
                                                                                "cards": {"type": "array", "items": {"type": "string"}}}},
    "parts": {"type": "array", "minItems": 2, "maxItems": 7, "items": {"type": "object", "required": ["title", "goal", "cards", "words", "types"],
              "properties": {"title": {"type": "string"}, "goal": {"type": "string"},
                             "cards": {"type": "array", "items": {"type": "string"}}, "words": {"type": "integer"},
                             "types": {"type": "array", "items": {"type": "string", "enum": TYPE_ENUM}}}}},
    "closing": {"type": "string"}}}

LINE_SCHEMA = {"type": "object", "required": ["text", "type", "cards"], "properties": {
    "text": {"type": "string"}, "type": {"type": "string", "enum": TYPE_ENUM},
    "cards": {"type": "array", "items": {"type": "string"}}, "commentary": {"type": "boolean"},
    "stage": {"type": "string"},
    "names": {"type": "array", "items": {"type": "object", "required": ["ar", "latin", "say"],
                                          "properties": {"ar": {"type": "string"}, "latin": {"type": "string"}, "say": {"type": "string"}}}},
    "news": {"type": "object", "properties": {"headline": {"type": "string"}, "context": {"type": "string"},
                                              "highlight": {"type": "array", "items": {"type": "string"}}}}}}
DRAFT_SCHEMA = {"type": "object", "required": ["lines"], "properties": {"lines": {"type": "array", "minItems": 3, "items": LINE_SCHEMA}}}

RULES = (
    "FACT RULES (checked by code; a line that breaks them is sent back):\n"
    "1. Every fact, number, date and legal point must come from a card, and the line lists those card ids in 'cards'. "
    "Never state a fact that is not on a card; never invent or round a number (write it as the card does; digits).\n"
    "2. A line with no card is commentary (opinion, analogy, a question to the viewer, a transition): set commentary true; "
    "it may contain NO digits and no new facts.\n"
    "3. Your own words only: never copy a card's statement sentence as it is; never reproduce source wording.\n"
    "4. Direct quotes: only from a quote card, inside «», exactly its quote_ar, with the speaker named in the line. "
    "Other short phrases in quotation marks (2-3 words) are fine as emphasis.\n"
    "5. Each line: 1-2 spoken sentences (about 10-35 words), in the channel's Egyptian-Arabic voice.\n"
    "6. type = the picture the montage shows for the line: " + "; ".join(f"{k}: {v}" for k, v in TYPE_HELP.items())
    + f". Mix over the whole script: archive at least {int(MIX['archive_min'] * 100)}% of lines, news at least "
    f"{int(MIX['news_min'] * 100)}%, stock at most {int(MIX['stock_max'] * 100)}%, never more than {MIX['run_max']} lines "
    "of one type in a row.\n"
    "7. A 'news' line cites a news or official card and has 'news': a headline that states that card's fact in our own "
    "words (short, no invention), one context line, and 1-3 words or numbers to highlight.\n"
    "8. Foreign names: write them in Arabic in the text; list them in 'names' with the Latin spelling and how to say it "
    "(Arabic letters with vowel marks) — only the first time they appear in the episode.\n"
    "9. 'stage' (optional): a short stage direction for music or picture, the way the channel writes them, placed before the line.\n"
    "10. No links, no outlet names unless the line attributes a claim («بحسب …»).")


def writer_inputs(p):
    t = topic(p)
    w = style.for_writer(channel_dir(p))
    minutes = t.get("minutes") or w["length"]["default_minutes"]
    words = int(round(minutes * w["length"]["script_words_per_minute"], -1))
    return t, w, minutes, words


def promo_position(p):
    """channel.json promo_slot.script_position: after_part_<N> | before_last_part | end (decision 12a); None = no promo"""
    prof = p.channel_profile()
    slot = prof.get("promo_slot") or {}
    if not slot.get("use"):
        return None
    return slot.get("script_position", "before_last_part")


# ------------------------------------------------------------------------------------------------ outline*
def step_outline(p):
    t, w, minutes, words = writer_inputs(p)
    cs = cards(p)
    notes_f = S(p, "outline_notes.json")
    notes = load_json(notes_f)["notes"] if notes_f.exists() else []
    inputs = {"topic": t["topic"], "angle": t.get("angle", ""), "today": t["today"], "minutes": minutes, "target_words": words,
              "style_guide": w["guide"], "style_measures": w["measures"], "catchphrases": w["catchphrases"],
              "excerpts": [e for e in w["excerpts"] if e["move"] in ("opening", "scene", "transition", "close")][:8],
              "cards": [card_brief(c) for c in cs], "material_types": TYPE_HELP,
              "mix_targets": MIX, "promo": f"code places a promo block ({promo_position(p) or 'none: the channel profile has no promo slot'}); do not plan one"}
    key = "outline"
    if notes:
        prev = load_json(S(p, "outline.json"))
        inputs["your_notes_on_the_previous_outline"] = notes
        inputs["previous_outline"] = prev["outline"]
        key = f"outline_{len(notes) + 1}"
    instructions = (
        "Plan one episode of the channel (outline only; the full script is written later from it). Follow the style guide: "
        "a cold open (a historical scene, a striking scene or a sharp question, from the cards), then 3-6 parts with clear "
        "goals, then a closing. Give every part the card ids it will use (only ids from inputs.cards; the cold open's too), "
        "a word budget (the budgets add up to target_words) and the material types it will lean on. Use the cards that "
        "carry the story; leave out cards that do not fit. If the owner left notes on a previous outline, follow them. "
        "title and every text field in Arabic. Answer with JSON only.")
    d = brain.decide(p, "script", key, request("the outline", instructions, inputs, OUTLINE_SCHEMA, 2500))
    rec = brain.record(p, "script", key) or {}
    known = {c["id"] for c in cs}
    bad = [x for x in d["cold_open"]["cards"] + [x for pt in d["parts"] for x in pt["cards"]] if x not in known]
    out = {"outline": d, "made_by": rec.get("made_by", ""), "key": key, "made_at": now(), "target_words": words, "minutes": minutes,
           "unknown_cards": sorted(set(bad))}
    save_json(S(p, "outline.json"), out)
    write_text(S(p, "outline.md"), outline_md(out, {c["id"]: c for c in cs}))
    print(f"outline: {len(d['parts'])} parts, {sum(x['words'] for x in d['parts'])} words planned (target {words}); made by {out['made_by']}"
          + (f"; unknown card ids ignored: {bad}" if bad else ""))


def outline_md(o, byid):
    d = o["outline"]
    local = o["made_by"].startswith("local:")
    L = [f"# المخطط: {d['title']}", ""]
    if local:
        L += ["> ⚠ **كتبه نموذج محلي مجاني (جودة أقل) — راجِع كل بند.** / Written by the FREE LOCAL MODEL.", ""]
    L += [f"- **الزاوية:** {d['angle']}", f"- **الطول المستهدف:** {o['minutes']} دقيقة ≈ {o['target_words']} كلمة",
          f"- **كتبه:** {o['made_by']}", "", "## الافتتاحية", "", d["cold_open"]["idea"], ""]
    from .review import card_when
    L += [f"- [{x}] {byid[x]['statement']} — {byid[x]['outlet']} – {card_when(byid[x])}" for x in d["cold_open"]["cards"] if x in byid]
    for i, pt in enumerate(d["parts"], 1):
        L += ["", f"## الجزء {i}: {pt['title']}", "", pt["goal"], "",
              f"*{pt['words']} كلمة — الأنواع: {'، '.join(TYPES.get(x, x) for x in pt['types'])}*", ""]
        L += [f"- [{x}] {byid[x]['statement']} — {byid[x]['outlet']} – {card_when(byid[x])}" for x in pt["cards"] if x in byid]
    L += ["", "## الخاتمة", "", d["closing"], "", "---", "",
          "Yes: `bin/monteer script outline-ok \"<project>\" --name \"<you>\"` · Changes: `bin/monteer script outline-edit \"<project>\" --notes \"…\"`",
          ""]
    return "\n".join(L)


def step_outline_ok(p):
    o = load_json(S(p, "outline.json"))
    ok_f = S(p, "outline_ok.json")
    if ok_f.exists() and load_json(ok_f)["sha"] == sha(o["outline"]):
        print(f"outline approved by {load_json(ok_f)['by']}")
        return
    raise NeedsDecision([{"step": "you", "key": "outline", "request": str(S(p, "outline.md")), "kind": "owner",
                          "why": "waiting for your yes or your notes on the outline: bin/monteer script outline-ok … / outline-edit … --notes"}])


# ------------------------------------------------------------------------------------------------ draft*
def step_draft(p):
    t, w, minutes, words = writer_inputs(p)
    o = load_json(S(p, "outline.json"))
    d = o["outline"]
    cs = cards(p)
    briefs = [card_brief(c) for c in cs]
    instructions = (
        "Write ONE PART of the episode's script, line by line, in the channel's voice (follow the style guide and the "
        "excerpts; Egyptian-Arabic narration, Modern Standard Arabic only inside quotes). Use the outline's plan for this "
        "part, its word budget (±10%) and its cards; you may also use other cards from inputs.cards when they fit. The "
        "first part begins with the cold open; the last part ends with the closing. Connect to the previous and next parts "
        "naturally (no 'in this part' meta talk). Do not write a promo, a greeting or a sign-off: code adds those places.\n\n"
        + RULES + "\n\nAnswer with JSON only.")
    asks = []
    n = len(d["parts"])
    # the free local model slows down sharply with long prompts on this CPU (5.8 tokens/s short, 3.1 at 5 500 tokens,
    # 1.2 at 13 000): it gets only the cards its part plans to use (and the cold open's), not all of them
    local = brain.brain_name(p) == "local"
    for i, pt in enumerate(d["parts"], 1):
        if local:
            keep = set(pt["cards"]) | (set(d["cold_open"]["cards"]) if i == 1 else set())
            part_briefs = [b for b in briefs if b["id"] in keep]
        else:
            part_briefs = briefs
        moves = ("opening", "scene", "number", "jargon") if i == 1 else (("close", "question", "transition") if i == n else ("number", "jargon", "official_vs_hidden", "transition", "quote"))
        # what every part shares comes first and what differs comes last, so the local model reads the shared part
        # once and reuses it (llama.cpp prompt cache) instead of reading 12 000+ tokens again for every part
        inputs = {"topic": t["topic"], "today": t["today"], "style_guide": w["guide"], "style_measures": w["measures"],
                  "catchphrases": w["catchphrases"], "earlier_edits_by_the_presenter": w["earlier_edits"],
                  "outline": {"title": d["title"], "angle": d["angle"], "cold_open": d["cold_open"],
                              "parts": [{"n": k, "title": x["title"], "goal": x["goal"]} for k, x in enumerate(d["parts"], 1)],
                              "closing": d["closing"]},
                  "excerpts": [e for e in w["excerpts"] if e["move"] in moves][:8], "cards": part_briefs,
                  "this_part": dict(pt, n=i, of=n, first=i == 1, last=i == n)}
        asks.append(("script", f"draft_part{i}", request(f"draft of part {i}/{n}", instructions, inputs, DRAFT_SCHEMA, 5000)))
    answers = ask_all(p, asks)
    items, lid = [], 0
    promo = promo_position(p)
    after = int(promo.split("_")[-1]) if promo and promo.startswith("after_part_") else None
    for i, pt in enumerate(d["parts"], 1):
        rec = brain.record(p, "script", f"draft_part{i}") or {}
        if i == 2:              # the presenter's own welcome follows the cold open (style guide 2.2): a place, not text
            items.append({"kind": "stage", "text": "(⟦ترحيب المقدّم بكلماته هنا⟧)"})
        if (promo == "before_last_part" and i == n) or (after is not None and i == after + 1):
            items += promo_block()
        items.append({"kind": "part", "n": i, "text": f"(الجزء {i}: {pt['title']})"})
        for ln in answers[f"draft_part{i}"]["lines"]:
            if ln.get("stage"):
                st = ln["stage"].strip()
                items.append({"kind": "stage", "text": st if st.startswith("(") else f"({st.strip('()')})"})
            lid += 1
            items.append({"kind": "line", "id": f"L{lid:03d}", "part": i, "text": ln["text"].strip(), "type": ln["type"],
                          "cards": ln.get("cards", []), "commentary": bool(ln.get("commentary")) or not ln.get("cards"),
                          "names": ln.get("names", []), "news": ln.get("news") or None, "made_by": rec.get("made_by", ""),
                          "edited": False})
    if promo == "end":
        items += promo_block()
    dr = {"version": 1, "title": d["title"], "made_at": now(), "outline_sha": sha(d), "target_words": words, "minutes": minutes,
          "items": items, "from": "brain draft"}
    save_json(S(p, "drafts", "v1.raw.json"), dr)
    print(f"draft v1: {sum(1 for x in items if x['kind'] == 'line')} lines")


def promo_block():
    return [{"kind": "promo_start", "text": "(⟦بداية الفقرة الإعلانية — تُكتب يدويًا هنا⟧)"},
            {"kind": "promo_end", "text": "(⟦نهاية الفقرة الإعلانية⟧)"}]


# ------------------------------------------------------------------------------------------------ verify (+ revise*)
REVISE_SCHEMA = {"type": "object", "required": ["lines"], "properties": {"lines": {"type": "array", "items": {
    "type": "object", "required": ["id", "text", "type", "cards"],
    "properties": dict(LINE_SCHEMA["properties"], id={"type": "string"})}}}}


def pending_version(p):
    """the newest raw draft not yet verified"""
    v = 1
    while S(p, "drafts", f"v{v + 1}.raw.json").exists():
        v += 1
    return v


def step_verify(p):
    v = pending_version(p)
    dr = load_json(S(p, "drafts", f"v{v}.raw.json"))
    cs = {c["id"]: c for c in cards(p, only_ok=False)}
    res = checks.run(p, dr, cs)
    rounds = []
    for rnd in (1, 2):
        # lines you edited by hand are never rewritten by the brain: their problems stay in the margin for you
        bad = [x for x in dr["items"] if x["kind"] == "line" and not x.get("edited")
               and any(pr["level"] == "error" for pr in res["lines"].get(x["id"], []))]
        if not bad:
            break
        lines = [x for x in dr["items"] if x["kind"] == "line"]
        okc = [c for c in cs.values() if c["status"] == "ok"]
        context = [{"id": x["id"], "text": x["text"]} for x in lines]
        guide = style.for_writer(channel_dir(p))["guide"][:6000]
        if brain.brain_name(p) == "local":      # long prompts are very slow for the local model (see step_draft)
            o = load_json(S(p, "outline.json"))["outline"]
            parts = {x.get("part") for x in bad}
            keep = {c for x in bad for c in x["cards"]} | {c for k, pt in enumerate(o["parts"], 1) if k in parts for c in pt["cards"]}
            okc = [c for c in okc if c["id"] in keep]
            near = {i for i, x in enumerate(lines) if x in bad for i in range(i - 1, i + 2)}
            context = [{"id": x["id"], "text": x["text"]} for i, x in enumerate(lines) if i in near]
            guide = guide[:2500]
        inputs = {"lines_to_fix": [{"id": x["id"], "text": x["text"], "type": x["type"], "cards": x["cards"], "commentary": x["commentary"],
                                    "names": x.get("names", []), "news": x.get("news"),
                                    "problems": [pr["text"] for pr in res["lines"][x["id"]] if pr["level"] == "error"]} for x in bad],
                  "context": context, "cards": [card_brief(c) for c in okc], "style_guide_short": guide}
        instructions = ("Code checks found problems in these script lines. Rewrite ONLY these lines so they pass, keeping their "
                        "place in the story and the channel's voice. Fix by citing the right card, removing the unsupported "
                        "number or fact, rewording copied text, or changing the type; never invent a fact or a card id. "
                        "Return every line in lines_to_fix with its id.\n\n" + RULES + "\n\nAnswer with JSON only.")
        key = f"revise_v{v}_r{rnd}"
        d = brain.decide(p, "script", key, request(f"fix {len(bad)} lines (round {rnd})", instructions, inputs, REVISE_SCHEMA, 4000,
                                                    local_ok=len(bad) <= 8))
        rec = brain.record(p, "script", key) or {}
        fixed = {x["id"]: x for x in d["lines"]}
        for x in dr["items"]:
            if x["kind"] == "line" and x["id"] in fixed:
                f = fixed[x["id"]]
                x.update(text=f["text"].strip(), type=f["type"], cards=f.get("cards", []),
                         commentary=bool(f.get("commentary")) or not f.get("cards"), names=f.get("names", x.get("names", [])),
                         news=f.get("news") or None, revised_by=rec.get("made_by", ""))
        rounds.append({"round": rnd, "lines": len(bad), "made_by": rec.get("made_by", "")})
        res = checks.run(p, dr, cs)
    dr["revise_rounds"] = rounds
    dr["verified_at"] = now()
    save_json(S(p, "drafts", f"v{v}.json"), dr)
    save_json(S(p, "drafts", f"v{v}.checks.json"), res)
    write_text(S(p, "drafts", f"v{v}.checks.md"), checks.report_md(res, dr))
    e, wn = res["totals"]["errors"], res["totals"]["warnings"]
    print(f"draft v{v} checked: {e} errors, {wn} warnings after {len(rounds)} revise round(s); words {res['script']['words']} "
          f"(target {dr['target_words']})")

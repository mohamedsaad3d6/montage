"""The "with presenter" (بمذيع) video type: the classic montage with presenter shots and punch-ins (rule 7), plus Ramadan's
notes applied to it (owner's decision 1 of 16 Oct 2026 on Works/output/agent_readiness_report.md). The audio-only type
runs the phrase montage (steps_phrase.py); the two never share a montage.

Ramadan's notes, and where each is applied here:
  material synced to each sentence     the script's sentences aligned to the spoken words (sentences.json); every
                                       B-roll block starts and ends on a sentence start, and its pictures change at
                                       each sentence start (a long sentence gets more than one picture, cut on words)
  a fast 15-20 s intro                 B-roll and graphics only, shots of 1-3 s, ending on a sentence start between 15 and
                                       20 s (checked in code; the brain is asked again)
  clicks, effects, transitions there   a transition on every intro cut and a low click under it (code)
  normal pace after that               the presenter (with punch-ins) and B-roll blocks of 2-4 s shots (rules 7-8)
  transitions and effects on cuts and  a transition entering each B-roll block, into each graphic, at each section change
  on-screen text                       and on every second B-roll cut; a whoosh on those, a pop when a label appears
                                       (code, added to the brain's sound plan; effects start in pauses, rule 18)
Decisions 2 and 3 (montage/targets.py): key-word labels about 1.3-1.8 a minute; the material mix (over the B-roll shots,
the presenter not counted) computed by the brain as mix_targets and checked in code. The standing decisions of 16 Oct
(no flags, brands as a place, the same picture at most twice in 75 s) are checked on the cut list too; flags and brand
logos are allowed in real footage and photos when the profile says so (answer 12 of 18 Oct 2026, montage/place.py).

Brain decisions (as in the classic montage): montage/plan, music/cues, sources/assets, ai/prompts, ai/pick,
montage/clip_fx, graphics/scenes, montage/timeline, montage/sound. Each request here adds the presenter type's rules and
the files sentences.json / words.json, and the plan and the timeline are checked in code.
"""
import difflib
import re

from ..core.io import load_json, save_json
from . import place as PL
from . import structure as STR
from . import targets as TG

FPS = 24
INTRO = (15.0, 20.0)                 # the default (the channel profile may set another: montage/structure.py)
INTRO_LIMITS = (13.0, 22.0)          # when no sentence starts inside 15-20 s, the nearest one in 13-22 s


def M(p, *n):
    return p.work.joinpath("montage", *n)


# ---------------------------------------------------------------------------------------------------- sentences
def sentences(p, words):
    """the script's sentences on the cut's timeline: [{"i", "text", "s", "e", "w0", "w1"}] -> work/montage/sentences.json.
    The script's words are matched to the spoken words in order (difflib on the normalised words); a sentence starts at
    its first matched word. Sentences with no matched word (never said) are left out."""
    from ..cut.common import normalize_ar
    out_f = M(p, "sentences.json")
    sc = load_json(p.work / "script.json")
    sw = [normalize_ar(w) for w in sc["words"]]
    vw = [w.get("n") or normalize_ar(w["w"]) for w in words]
    sm = difflib.SequenceMatcher(None, sw, vw, autojunk=False)
    to_v = {}
    for a, b, n in sm.get_matching_blocks():
        for k in range(n):
            to_v[a + k] = b + k
    first, last = {}, {}
    for j, si in enumerate(sc["sent_of_word"]):
        if j in to_v:
            first.setdefault(si, to_v[j])
            last[si] = to_v[j]
    out, prev = [], -1
    for si in sorted(first):
        w0 = first[si]
        if w0 <= prev:                       # out of order (a retake or a repeated phrase): keep the earlier sentence
            continue
        out.append({"i": si, "text": sc["sentences"][si], "w0": w0})
        prev = w0
    for k, x in enumerate(out):
        x["w1"] = (out[k + 1]["w0"] - 1) if k + 1 < len(out) else len(words) - 1
        x["s"] = round(words[x["w0"]]["s"], 3) if k else 0.0
        x["e"] = round(words[out[k + 1]["w0"]]["s"], 3) if k + 1 < len(out) else round(words[-1]["e"], 3)
    save_json(out_f, {"note": "the script's sentences on the cut's timeline (s, e in seconds; w0..w1 = word indices of words.json)",
                      "matched_script_words": len(to_v), "script_words": len(sw), "spoken_words": len(vw), "sentences": out})
    return out


def words_file(p, words, L):
    ws = [{"i": i, "w": w["w"].strip(), "s": round(w["s"], 2), "e": round(w["e"], 2)} for i, w in enumerate(words)]
    save_json(M(p, "words.json"), {"length_s": round(L, 2), "words": ws})
    return M(p, "words.json")


def starts(p):
    return [x["s"] for x in load_json(M(p, "sentences.json"))["sentences"]]


def sentence_ids(p):
    """the sentences' indices ("i"), in the order of starts(p)"""
    return [x["i"] for x in load_json(M(p, "sentences.json"))["sentences"]]


# ---------------------------------------------------------------------------------------------------- pictures to sentences
NEAR_PART = 10.0              # s: a picture may stand this far outside the plan block it was found for
SUBJECT_MAX = 3               # one subject (the clip review's "subject") at most this many shots in the video
SUBJECT_GAP = 45.0            # s: and never again within this long (owner's fix 9 of 21 Oct 2026)


def subjects(p):
    """the clip review's subject of each clip (key -> lower-case words), when it gave them"""
    f = p.decisions / "montage" / "clip_fx.json"
    fx = (load_json(f).get("decision") or {}) if f.exists() else {}
    return {k: " ".join(str(v["subject"]).lower().split()) for k, v in fx.items() if isinstance(v, dict) and v.get("subject")}


def subject_problems(p, sh):
    """one subject shown too often or too soon again, whatever file shows it"""
    subj = subjects(p)
    seen, probs = {}, []
    for s in sh:
        if s["kind"] != "video" or not s.get("asset"):
            continue
        k = subj.get(s["asset"].split(":", 1)[1])
        if not k:
            continue
        t = s["f0"] / FPS
        seen.setdefault(k, []).append((t, s["asset"]))
    for k, uses in seen.items():
        if len(uses) > SUBJECT_MAX:
            probs.append(f"«{k}» is shown {len(uses)} times (at {', '.join(f'{t:.0f}' for t, _ in uses[:8])} s); at most {SUBJECT_MAX} "
                         "in the video, however many clips show it")
        close = [(a, b) for (a, fa), (b, fb) in zip(uses, uses[1:]) if b - a < SUBJECT_GAP and fa != fb]
        if close:
            probs.append(f"«{k}» again within {SUBJECT_GAP:g} s (at {', '.join(f'{a:.0f}->{b:.0f}' for a, b in close[:4])} s), from different clips")
    return probs


def asset_for(p):
    """each picked file -> the plan blocks (and their time ranges) whose own searches found it (steps.asset_for), or {}"""
    f = M(p, "asset_for.json")
    return load_json(f) if (getattr(p, "profile", None) and f.exists()) else {}


def video_rejects(p):
    """the clips the clip review rejected on sight (montage/clip_fx: "reject"), key -> why"""
    f = p.decisions / "montage" / "clip_fx.json"
    fx = (load_json(f).get("decision") or {}) if f.exists() else {}
    return {k: v.get("why", "rejected") for k, v in fx.items() if isinstance(v, dict) and v.get("reject")}


def cut_sheets(p, af):
    """one sheet per plan block: the review's frame row of each clip found for it, labelled with its code -> [sheet paths]
    (owner's fix 2 of 21 Oct 2026: the cut list sees the clips' pictures, not only their titles)"""
    from PIL import Image, ImageDraw
    rows_dir, out_dir = M(p, "review"), M(p, "cut_sheets")
    out_dir.mkdir(parents=True, exist_ok=True)
    rej = video_rejects(p)
    by_block = {}
    for code, r in af.items():
        if code[:2] in ("V:", "S:") and code[2:] not in rej:
            for b in r.get("blocks", []):
                by_block.setdefault(b, []).append(code)
    out = []
    for b, codes in sorted(by_block.items()):
        rows = []
        for code in codes:
            f = (rows_dir if code.startswith("V:") else M(p, "review_archive")) / f"row_{code[2:]}.jpg"
            if not f.exists():
                continue
            im = Image.open(f).convert("RGB")
            im = im.resize((960, int(im.height * 960 / im.width)))
            tile = Image.new("RGB", (960, im.height + 26), "black")
            tile.paste(im, (0, 26))
            ImageDraw.Draw(tile).text((8, 6), code, fill="yellow")
            rows.append(tile)
        if not rows:
            continue
        sheet = Image.new("RGB", (960, sum(r.height for r in rows)), "black")
        y = 0
        for r in rows:
            sheet.paste(r, (0, y))
            y += r.height
        path = out_dir / f"block_{int(b):02d}.jpg"
        sheet.save(path, quality=80)
        out.append(path)
    return out


def picture_problems(p, sh):
    """a channel episode's pictures on the cut list (owner's fixes 2 and 4 of 21 Oct 2026): no clip the review rejected; no
    picture found for another part of the episode; with the sentence tags, every footage shot shows a picture chosen for
    its own sentence"""
    probs = []
    if not getattr(p, "profile", None):
        return probs
    rej = video_rejects(p)
    for key in sorted({s["asset"].split(":", 1)[1] for s in sh if s["kind"] == "video" and s.get("asset")} & set(rej)):
        probs.append(f"clip {key} was rejected on sight by the clip review ({rej[key]}): do not use it")
    probs += subject_problems(p, sh)
    af = asset_for(p)
    if not af:
        return probs
    S = {x["i"]: x for x in load_json(M(p, "sentences.json"))["sentences"]}
    far, untagged = [], []
    for s in sh:
        if s["kind"] not in ("video", "photo") or not s.get("asset"):
            continue
        a, b = s["f0"] / FPS, s["f1"] / FPS
        r = af.get(s["asset"])
        if r and r.get("ranges") and not any(x0 - NEAR_PART <= (a + b) / 2 <= x1 + NEAR_PART for x0, x1 in r["ranges"]):
            far.append(f"{s['asset']} at {a:.1f} s was found for {', '.join(f'{x0:.0f}-{x1:.0f} s' for x0, x1 in r['ranges'])}")
        if not s.get("tagged"):
            n = s.get("sentence")
            words = (S.get(n) or {}).get("text", "")[:40]
            untagged.append(f"{a:.1f} s" + (f" (sentence {n} «{words}…»)" if n is not None else ""))
    if far:
        probs.append("pictures found for another part of the episode (asset_for.json; use a picture found for this part): "
                     + "; ".join(far[:8]))
    if untagged:
        probs.append(f"{len(untagged)} footage shot(s) have no picture chosen for their own sentence: write each F block's assets "
                     "as V:<id>@<sentence i> (sentences.json), one or more for every sentence the block covers: " + "; ".join(untagged[:8]))
    return probs


# ---------------------------------------------------------------------------------------------------- the plan
def own_text(p):
    """the owner's own clips (decision 8b) and the owner's words for this episode, for the plan request"""
    from .own_clips import plan_text as own
    t = own(p)
    t = (t + " In the timeline they are library footage S:<key>.\n") if t else ""
    if p.instructions:
        t += "THE OWNER'S INSTRUCTIONS FOR THIS EPISODE (follow them, unless they would break the rules): " + p.instructions + "\n"
    return t


def intro_note(S):
    """Ramadan's note (2), with the profile's fast intro (the default text is the one used before the profiles)"""
    if S.fast_open is None:
        return ("(2) NO FAST INTRO for this channel: a calm start; give intro_end_s = 0; ")
    (lo, hi), (a, b) = S.fast_open, S.fast_shot
    return (f"(2) a FAST INTRO of {lo:g}-{hi:g} s: B-roll and our graphics only (no presenter), shots of {a:g}-{b:g} s "
            f"over the hook, ending on a sentence start between {lo:g} and {hi:g} s: give intro_end_s = that sentence's s; transitions and a "
            "low click on every intro cut are added in code; " + opening_note(S))


def opening_note(S):
    """how the fast intro opens (the channel's guide); nothing when the profile does not say"""
    if S.opening == "motion":
        return ("it OPENS WITH MOTION (the channel's preferred opening): our own graphics and big fast kinetic text first, then "
                "footage; ")
    if S.opening == "timelapse":
        pat = ", then ".join(f"{n} shots of {t:g} s" for n, t in S.timelapse)
        return f"it OPENS AS A TIME-LAPSE that speeds up: {pat} (every cut on an effect); "
    return ""


def pace_note(S):
    """Ramadan's note (3): the pace after the intro (default: rule 8, as before)"""
    if S.mostly_presenter:
        return ("(3) after the intro the channel's body: MOSTLY THE PRESENTER alone; a B-roll block (12-30 s, 2-4 s shots) about "
                "once a minute or less, for what must be seen (history, places, companies, numbers); ")
    if S.body_alternation:
        a = S.body_alternation
        return ("(3) after the fast intro, the COLD OPEN and then the BODY (below); in the body the footage and the presenter "
                f"alternate: about {a:g} s of B-roll (one block, shots of 2-4 s), then about {a:g} s of the presenter, and so on "
                f"(flexible, {a * 0.5:g}-{a * 1.5:g} s each; the presenter for direct address and opinion, «يا صديقي», «أنا», «احنا»; "
                "footage for narration: history, places, companies, numbers); ")
    return ("(3) after the intro a normal pace: the presenter for direct address "
            "and opinion («يا صديقي», «أنا», «احنا»), B-roll blocks for narration (history, places, companies, numbers) of about "
            "12-30 s, once or twice a minute, with 2-4 s shots (rule 8); ")


def timeline_note(S):
    """the timeline request's words for the intro and the pace (the default text is the one used before the profiles)"""
    if S.fast_open is None:
        t = "there is no fast intro (intro_end_s = 0); "
    else:
        (lo, hi), (a, b) = S.fast_open, S.fast_shot
        t = (f"intro (0 to intro_end_s, the plan's sentence start at {lo:g}-{hi:g} s) is F/G blocks only, F blocks there with pace_s "
             f"about {(a + b) / 2:g} (shots of {a:g}-{b:g} s); ")
    if S.mostly_presenter:
        return t + ("after it mostly the presenter: B-roll blocks of about 12-30 s with pace_s 3 (shots of 2-4 s), about once a "
                    "minute or less; ")
    if S.cold_open and S.cold_alt:
        ca, al = S.cold_alt, S.body_alternation or 60
        return t + ("after it the COLD OPEN until cold_open_end_s (the plan's): F/G blocks with pace_s 3 (shots of 2-4 s), and the "
                    f"PRESENTER EARLY AND OFTEN (no block there): first at about {ca['first_s']:g} s ({ca['first_s'] - 15:g}-"
                    f"{ca['first_s'] + 30:g} s), then about every {ca['every_s']:g} s (at most {ca['every_s'] * 1.5:g} s of footage "
                    f"between two appearances, and at least {COLD_FOOTAGE_MIN:g} s: the footage stays the majority of the cold open, the "
                    f"presenter at most {COLD_PRES_MAX:.0%} of it besides his teaser), each {ca['for_s'][0]:g}-{ca['for_s'][1]:g} s, and his teaser at its end (no block "
                    f"over the last sentences before cold_open_end_s); then the BODY: one B-roll block of about {al:g} s "
                    f"({al * 0.5:g}-{al * 1.5:g} s, pace_s 3), then about {al:g} s of the presenter (no block), and so on; ")
    if S.cold_open:
        (w0, w1), _ = S.presenter_window()
        al = S.body_alternation or 60
        return t + ("after it the COLD OPEN until cold_open_end_s (the plan's): F/G blocks with pace_s 3 (shots of 2-4 s) everywhere "
                    f"except the presenter's one short appearance (about {S.presenter_for:g} s starting at {w0:g}-{w1:g} s, or about "
                    "two thirds into a shorter cold open: no block "
                    "there) and his teaser at its end (no block over the last sentences before cold_open_end_s); then the BODY: "
                    f"one B-roll block of about {al:g} s ({al * 0.5:g}-{al * 1.5:g} s, pace_s 3), then about {al:g} s of the presenter "
                    "(no block), and so on; ")
    return t + "after it B-roll blocks of about 12-30 s with pace_s 3 (shots of 2-4 s), once or twice a minute; "


def structure_text(p, S):
    """what the channel profile adds to the plan request (nothing for a profile that keeps the engine's defaults)"""
    t = ""
    if S.cold_open:
        lo, hi = S.cold_open
        (w0, w1), (d0, d1) = S.presenter_window()
        ca = S.cold_alt
        appear = (f"The presenter appears EARLY AND OFTEN inside it (owner's decision of 22 Oct 2026, like the channel's reference "
                  f"episode): first at about {ca['first_s']:g} s ({ca['first_s'] - 15:g}-{ca['first_s'] + 30:g} s), then about every "
                  f"{ca['every_s']:g} s, each time {ca['for_s'][0]:g}-{ca['for_s'][1]:g} s, for his direct address and opinion; the "
                  "rest of the cold open is B-roll (real footage first). " if ca else
                  f"The presenter appears ONCE inside it, briefly: about {S.presenter_for:g} s "
                  f"({d0:g}-{d1:g} s) starting near {S.presenter_near / 60:g}:00 ({w0:g}-{w1:g} s; about two thirds into the cold open "
                  "when the script's cold open is shorter); every other moment of the cold open is B-roll or graphics. ")
        t += (f"\nCOLD OPEN (the channel's guide, Ramadan): the first {lo / 60:g}-{hi / 60:g} minutes are a dense documentary cold "
              "open: it begins with the fast intro, then B-roll and our graphics at a fast pace (shots of 2-4 s, frequent and varied "
              f"transitions with effects, added in code). " + appear + "It ENDS on the presenter: his teaser line and his invitation to get a drink ready («حضّر "
              "مشروبك» or the like) are said on camera, and the cold open ends at the sentence start right after them: give "
              f"cold_open_end_s = that sentence's s (between {S.cold_limits[0]:.0f} and {S.cold_limits[1]:.0f} s; about "
              f"{lo:g}-{hi:g} s). The body starts there" + (", calm: fewer and softer transitions." if S.calm_body else "."))
    if S.music_where == "cold_open_only":
        t += "\nMUSIC (the channel's fixed rule): music plays in the cold open only (0 to cold_open_end_s); none in the body."
    names = [c.get("what") or c["file"] for c in S.clips]
    if names:
        t += ("\nTHE CHANNEL'S OWN CLIPS are put in by code between two sentences, the narration waiting for them: "
              + "; ".join(f"{c.get('what') or c['file']} at {c['at'].replace('_', ' ')}" for c in S.clips)
              + ". Plan the picture of the narration only; end a block on the sentence start where a clip goes.")
    return t


def news_note(p):
    """what the plan request says of documented news (the text used before the profiles, else the screenshots')"""
    from . import news as NEWS
    if not NEWS.mode(p):
        return " There are no documented news items unless the script tool made them: news_min is 0 without them."
    ok = NEWS.usable(p)
    if not ok:
        return (" Documented news are shown only as real screenshots of their pages, and none could be taken for this episode: "
                "news_min is 0; never design a newspaper card.")
    return (f" Documented news are shown only as real screenshots of their public pages, made in code: {len(ok)} ready "
            "(scenes news_<id>, placed where their line is said); never design a newspaper card, a masthead or a «المصدر» line.")


def plan_text(p, L):
    lo, hi = TG.label_range(L)
    S = STR.of(p)
    return (
        "VIDEO TYPE: WITH PRESENTER (بمذيع). The presenter is on screen wherever no B-roll or graphic block is placed (punch-ins "
        "are added in code, rule 7). Read sentences.json (the script's sentences with their times on the cut) and words.json.\n"
        "RAMADAN'S NOTES (they apply to this type): (1) the material is synced to each sentence: a B-roll block starts and ends "
        "on a sentence start (s of a sentence), and its pictures change at each sentence start, one picture per sentence idea "
        "(a long sentence gets 2-3); " + intro_note(S) + pace_note(S) + "(4) transitions and sound effects on cuts and on-screen "
        "text are added in code (rule 18: in pauses)." + structure_text(p, S) + "\n"
        f"KEY-WORD LABELS (rule 11): about 1.3-1.8 a minute, between {lo} and {hi} for this {L:.0f} s video; only words said, "
        "spelled as in sentences.json (the approved script), never as in words.json (whisper's hearing); each stays about 6 s "
        "(5-7 s, owner's decision 1b) on B-roll only, so a label needs a B-roll stretch of at least 6 s around it.\n"
        + TG.rule_text("presenter", TG.rules_of(p)) + news_note(p) + gfx_plan_text(p) + " In the plan, give each B-roll block material = {type: shot count} with the types "
        "stock, archive, ai, graphic, news; base_shots = the sum over all blocks.\n"
        + ("SEARCH WORDS PER BLOCK (owner's decision): every block with stock or archive shots gives its OWN search words, about one "
           "for every two of its footage shots, naming what its sentences speak of (the people, the event, the place, the "
           "thing; a year for an archive event): each block's clips are searched for it alone, and the cut list uses them "
           "there only.\n" if getattr(p, "profile", None) else "")
        + own_text(p) +
        "STANDING DECISIONS (rules_18_24.md): the right country (Egypt for «الحكومة» or «بلدك» when no other country is "
        "named; the named country otherwise), "
        + ("flags and brand logos allowed in real footage and photos, never in drawn images, " if any(PL.allowed(p)) else
           "no flags on screen, a brand as a place of that kind without logo or name, ")
        + "the same picture at most twice within 75 s.")


def gfx_plan_text(p):
    """the channel's graphics policy in the plan request (montage/gfx_policy.py; nothing for the other channels)"""
    from . import gfx_policy as GP
    pol = GP.of(p)
    if not pol:
        return ""
    return (f" GRAPHICS (this channel's standing rule, owner's decision of 22 Oct 2026): at most {pol['plan_max_share']:.0%} of the "
            "B-roll shots are graphic (code checks the count), and only for maps, numbers, people and comparisons; everything "
            "else is real footage: stock for today, archive (film or photos of the event) for the past. Never plan a card of a "
            "few words; a date or key word is a label over footage.")


SCHEMA_PLAN = {"type": "object", "required": ["intro_end_s", "mix_targets", "blocks"], "properties": {
    "intro_end_s": {"type": "number"}, "mix_targets": TG.SCHEMA,
    "blocks": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["in", "out", "shows"], "properties": {
        "in": {"type": "number"}, "out": {"type": "number"}, "section": {"type": "string"}, "music": {"type": "string"},
        "pace_s": {"type": "number"}, "shows": {"type": "array", "items": {"type": "string"}},
        "search_stock": {"type": "array", "items": {"type": "string"}}, "search_photos": {"type": "array", "items": {"type": "string"}},
        "techniques": {"type": "object"}, "presenter": {"type": "boolean"},
        "material": {"type": "object", "additionalProperties": {"type": "integer"}}}}}}}


def schema_plan(S):
    """the plan's answer schema: with the channel's cold open, cold_open_end_s too (else exactly SCHEMA_PLAN)"""
    if not S.cold_open:
        return SCHEMA_PLAN
    return dict(SCHEMA_PLAN, required=SCHEMA_PLAN["required"] + ["cold_open_end_s"],
                properties=dict(SCHEMA_PLAN["properties"], cold_open_end_s={"type": "number"}))


def intro_end_ok(p, t, S=None):
    S = S or STR.of(p)
    if S.fast_open is None:
        return [] if abs(t) <= 0.3 else [f"intro_end_s must be 0: this channel has no fast intro (got {t:.2f})"]
    st = starts(p)
    (a, b), (la, lb) = S.fast_open, S.fast_limits
    inside = [s for s in st if a <= s <= b]
    near = [s for s in st if la <= s <= lb]
    ok_set = inside or near
    if not any(abs(s - t) <= 0.3 for s in ok_set):
        return [f"intro_end_s {t:.2f} must be a sentence start between {a:.0f} and {b:.0f} s "
                f"(sentence starts there: {[round(s, 2) for s in ok_set] or 'none'})"]
    return []


def cold_end_ok(p, d, S):
    """the cold open's end: a sentence start in the accepted range (the channel's cold open only)"""
    if not S.cold_open:
        return []
    t = d.get("cold_open_end_s")
    if t is None:
        return ["give cold_open_end_s (the sentence start right after the presenter's teaser and «حضّر مشروبك»)"]
    lo, hi = S.cold_limits
    ok = [s for s in starts(p) if lo <= s <= hi]
    if not any(abs(s - t) <= 0.3 for s in ok):
        return [f"cold_open_end_s {t:.2f} must be a sentence start between {lo:.0f} and {hi:.0f} s (the cold open is about "
                f"{S.cold_open[0] / 60:g}-{S.cold_open[1] / 60:g} minutes)"]
    return []


def check_plan(p, d, L):
    bl = d["blocks"]
    probs = []
    if bl[0]["in"] > 1 or abs(bl[-1]["out"] - L) > 2 or any(b["out"] <= b["in"] for b in bl):
        probs.append(f"the blocks must cover the whole video (0 to {L:.1f} s), each with out > in")
    S = STR.of(p)
    probs += intro_end_ok(p, d["intro_end_s"], S)
    probs += cold_end_ok(p, d, S)
    if getattr(p, "profile", None):    # owner's fix 1 of 21 Oct 2026: every footage block brings its own search words
        bare = [f"{b['in']}-{b['out']}" for b in bl if sum(int(n) for t, n in (b.get("material") or {}).items() if t in ("stock", "archive")) > 0
                and not (b.get("search_stock") or b.get("search_photos"))]
        if bare:
            probs.append("these footage blocks have no search words of their own (search_stock / search_photos; their clips are "
                         "searched for them alone): " + ", ".join(bare[:10]))
    types = []
    for b in bl:
        for t, n in (b.get("material") or {}).items():
            if t not in TG.TYPES:
                probs.append(f"block {b['in']}-{b['out']}: unknown material type {t}")
            else:
                types += [t] * int(n)
    from .news import has_news as _has_news
    has_news = _has_news(p)     # channel profiles: only the news with a screenshot (montage/news.py)
    probs += [x for x in TG.check(types, d.get("mix_targets"), has_news, R=TG.rules_of(p)) if "in a row" not in x]   # order: on the cut list
    from . import gfx_policy as GP
    pol = GP.of(p)
    if pol:                            # the channel's graphics policy (owner, 22 Oct 2026): few graphics in the plan too
        probs += GP.plan_problems(bl, pol)
    if probs:
        raise ValueError("; ".join(probs[:12]))


def repair_plan(p, d):
    """what code fixes in a refused block plan before the brain is asked again (owner's decision of 20 Oct 2026, as the
    audio-only plan's phrases.repair): mix_targets recomputed; stock over 40% or archive under 15% by up to 3 shots ->
    that many of a block's stock shots counted as archive instead (the block with most stock first). -> (plan, [notes])"""
    import copy
    from .news import has_news as _has_news
    d, notes = copy.deepcopy(d), []
    has_news = _has_news(p)
    from . import gfx_policy as GP
    if GP.of(p):                       # extra graphic shots become footage (the channel's graphics budget)
        notes += GP.repair_plan(d["blocks"], GP.of(p))
    where, types = [], []
    for j, b in enumerate(d["blocks"]):
        for t, n in (b.get("material") or {}).items():
            where += [j] * int(n)
            types += [t] * int(n)
    by_stock = sorted(range(len(types)), key=lambda i: -int((d["blocks"][where[i]].get("material") or {}).get("stock", 0)))
    moved = {}
    R = TG.rules_of(p)
    for i in TG.repair(types, has_news, prefer=by_stock, ordered=False, R=R) or []:
        m = d["blocks"][where[i]]["material"]
        m["stock"] = int(m["stock"]) - 1
        m["archive"] = int(m.get("archive", 0)) + 1
        moved[where[i]] = moved.get(where[i], 0) + 1
    notes += [f"block {d['blocks'][j].get('in')}-{d['blocks'][j].get('out')}: {n} stock shot(s) -> archive" for j, n in moved.items()]
    if "mix_targets" in d:
        d["mix_targets"], wrong = TG.computed(d["mix_targets"], len(types), has_news, R)
        if wrong:
            notes.append("mix_targets as computed: " + ", ".join(wrong))
    if getattr(p, "profile", None):    # a footage block with no search words: its own "shows" lines become them (fix 1)
        for b in d["blocks"]:
            if sum(int(n) for t, n in (b.get("material") or {}).items() if t in ("stock", "archive")) > 0 \
                    and not (b.get("search_stock") or b.get("search_photos")):
                words = search_words(b.get("shows", []))
                if words:
                    b["search_stock"] = words
                    notes.append(f"block {b.get('in')}-{b.get('out')}: search words from what it shows: {words}")
    return d, notes


def search_words(shows):
    """a block's "shows" lines -> search words: the footage and archive lines, without their prefix and [source] tag"""
    import re
    out = []
    for x in shows:
        if "[graphic]" in x or "[presenter]" in x:
            continue
        x = re.sub(r"\[[^]]*\]", "", x)
        x = re.sub(r"^\s*(film|photo|footage|clip|video|archive)\s*:\s*", "", x, flags=re.I).strip(" ,.;")
        if x and re.search(r"[A-Za-z]", x):
            out.append(" ".join(x.split()[:7]))
    return out[:6]


# ---------------------------------------------------------------------------------------------------- the cut list
def snap_blocks(p, d, L):
    """B-roll and graphic blocks start and end on sentence starts (Ramadan: material synced to each sentence): each edge
    moves to the nearest sentence start within 1.5 s (the video's start and end stay)"""
    st = starts(p)
    out = dict(d, blocks=[])
    for el in d["blocks"]:
        if el[0] in ("F", "G"):
            el = list(el)
            for j in (2, 3):
                t = el[j]
                if 0 < t < L - 0.05:
                    near = [s for s in st if abs(s - t) <= 1.5]
                    if near:
                        el[j] = round(min(near, key=lambda s: abs(s - t)), 3)
            if el[3] <= el[2]:
                continue
        out["blocks"].append(el)
    return out


COLD_FOOTAGE_MIN = 20.0       # s of footage at least between two presenter appearances in the cold open (owner, 22 Oct 2026)
COLD_PRES_MAX = 0.35          # the presenter's share of the cold open, his teaser not counted (the reference: footage first)


def cold_open_repair(p, d, S, L, scenes=()):
    """the channel's presenter early and often in the cold open, made in code when the cut list misses it (owner, 22 Oct
    2026): a short gap between blocks (under the shortest appearance) is covered by the footage before it; where the
    presenter is missing (first near first_s, then never more than every_s x 1.5 of footage), an appearance of about 12 s
    is opened on sentence starts, cutting into a footage block (never into a graphic or a label's time when another
    sentence start nearby avoids them; a label it still covers is left out) -> notes (d changed in place)"""
    ca = S.cold_alt
    if not ca or d.get("cold_open_end_s") is None:
        return []
    notes = []
    ie, ce = d.get("intro_end_s") or 0.0, d["cold_open_end_s"]
    lo, hi = ca["for_s"]
    gap_max = ca["every_s"] * 1.5
    st = [t for t in starts(p) if ie + 0.5 < t < ce - 3]
    sc = {x["name"]: x for x in scenes}
    bl = [list(b) for b in d["blocks"] if b[0] != "INSERT"]
    bl.sort(key=lambda b: b[2])

    def pres():                        # the presenter's stretches in the cold open (nothing placed there)
        out, t = [], ie
        for b in bl:
            if b[3] <= ie or b[2] >= ce:
                continue
            if b[2] > t + 0.05:
                out.append((t, min(b[2], ce)))
            t = max(t, b[3])
        if t < ce - 0.05:
            out.append((t, ce))
        return out
    for a, b in pres():                # a sliver of presenter between two blocks: the footage before it covers it
        if b - a < lo * 0.6 and b < ce - 0.5:
            prev = next((x for x in reversed(bl) if abs(x[3] - a) < 0.06 and x[0] == "F"), None)
            if prev is not None:
                prev[3] = b
                notes.append(f"cold open: the {b - a:.1f} s of presenter at {a:.1f} s covered by the footage before it")
    labels = [(sc[n]["t_in"], sc[n]["t_out"], n) for n in d.get("overlays", []) if n in sc]
    busy = [(b[2], b[3]) for b in bl if b[0] == "G"] + [(x, y) for x, y, _ in labels]

    def open_at(target, earliest, latest):
        cands = sorted((t for t in st if earliest <= t <= latest), key=lambda t: abs(t - target))
        if not cands:
            return None

        def window(a):
            ends = [t for t in st if a + lo <= t <= a + hi]
            b = min(ends, key=lambda t: abs(t - (a + 12.0))) if ends else min(a + 12.0, ce - 1.0)
            return a, b
        free = [w for w in map(window, cands) if not any(x < w[1] and y > w[0] for x, y in busy)]
        a, b = free[0] if free else window(cands[0])
        for x, y, n in labels:
            if x < b and y > a and n in d.get("overlays", []):
                d["overlays"] = [o for o in d["overlays"] if o != n]
                notes.append(f"cold open: label {n} left out (the presenter's appearance at {a:.1f} s covers it)")
        new = []
        for blk in bl:
            if blk[3] <= a or blk[2] >= b:
                new.append(blk)
                continue
            if blk[0] == "G":
                notes.append(f"cold open: graphic {blk[1]} left out for the presenter's appearance at {a:.1f} s")
                continue
            if blk[2] < a - 1.9:
                new.append(blk[:2] + [blk[2], a] + blk[4:])
            if blk[3] > b + 1.9:
                new.append(blk[:2] + [b, blk[3]] + blk[4:])
        bl[:] = sorted(new, key=lambda x: x[2])
        notes.append(f"cold open: the presenter on screen at {a:.1f}-{b:.1f} s")
        return b
    def footage_cover(a, b):           # the footage block that ends at a takes the presenter's stretch [a, b) too
        prev = next((x for x in bl if x[0] == "F" and abs(x[3] - a) < 0.06), None)
        if prev is None:
            return False
        prev[3] = b
        return True
    f0 = ca["first_s"]
    ps0 = pres()                       # his teaser ends the cold open: no block over its last sentences (about 12 s)
    if not ps0 or abs(ps0[-1][1] - ce) > 0.5 or ps0[-1][1] - ps0[-1][0] < 3.0:
        t0 = max((t for t in starts(p) if ce - 20.0 <= t <= ce - 6.0), default=ce - 12.0, key=lambda t: -abs(t - (ce - 12.0)))
        kept = []
        for blk in bl:
            if blk[3] <= t0 or blk[2] >= ce:
                kept.append(blk)
                continue
            if blk[2] < t0 - 1.9:
                kept.append(blk[:3] + [t0] + blk[4:])
            if blk[3] > ce + 1.9:          # its part after the cold open (the body) stays
                kept.append(blk[:2] + [ce, blk[3]] + blk[4:])
        bl[:] = kept
        notes.append(f"cold open: the presenter's teaser kept free at {t0:.1f}-{ce:.1f} s")
    for a, b in pres():                # the presenter before his first moment (about f0): the footage before him goes on
        if a < f0 - 15 and b < ce - 0.5 and footage_cover(a, b):
            notes.append(f"cold open: the presenter at {a:.1f}-{b:.1f} s covered by footage (before his first moment)")
    ps = pres()
    middle = [x for x in ps if x[1] < ce - 0.5]
    if not middle or not f0 - 15 <= middle[0][0] <= f0 + 30:
        open_at(f0, max(ie + 5, f0 - 15), f0 + 30)
    for _ in range(12):                # then never more than gap_max of footage between two appearances
        ps = pres()
        prev_end, bad = ie, None
        for a, b in ps:
            if a - prev_end > gap_max:
                bad = prev_end
                break
            prev_end = b
        if bad is None:
            break
        if open_at(bad + ca["every_s"] * 0.8, bad + 15, bad + gap_max - 2) is None:
            break
    for _ in range(20):                # too little footage between two appearances: one of them goes (covered by the footage
        ps = pres()                    # before it), the later first, never the teaser, if the longest-footage rule still holds
        teaser_i = len(ps) - 1 if ps and ps[-1][1] >= ce - 0.5 else None
        changed = False
        for k in range(1, len(ps)):
            if ps[k][0] - ps[k - 1][1] >= COLD_FOOTAGE_MIN - 0.5:
                continue
            for x in (k, k - 1):
                if x == teaser_i or (x == 0 and not any(f0 - 15 <= y[0] <= f0 + 30 for y in ps[1:] if y is not ps[teaser_i or -1])):
                    continue
                before = ps[x - 1][1] if x > 0 else ie
                after = ps[x + 1][0] if x + 1 < len(ps) else ce
                if after - before <= gap_max and footage_cover(*ps[x]):
                    notes.append(f"cold open: the presenter at {ps[x][0]:.1f}-{ps[x][1]:.1f} s covered by footage (too little footage "
                                 "between two appearances)")
                    changed = True
                    break
            if changed:
                break
        if not changed:
            break
    for _ in range(20):                # still over the share: the longest appearances shortened to about 12 s
        ps = pres()
        mids = [x for x in ps if x[1] < ce - 0.5]
        teaser_s = sum(y - x for x, y in ps if x not in [m[0] for m in mids])
        share = sum(y - x for x, y in mids) / max(1e-6, ce - ie - teaser_s)
        if share <= COLD_PRES_MAX or not mids:
            break
        a, b = max(mids, key=lambda m: m[1] - m[0])
        if b - a <= lo + 0.5:
            break
        cut_at = next((t for t in sorted(st) if a + max(lo, 10.0) <= t <= b - 2.0), None)
        nxt = next((x for x in bl if x[0] == "F" and abs(x[2] - b) < 0.06), None)
        if cut_at is None or nxt is None:
            break
        nxt[2] = cut_at
        notes.append(f"cold open: the presenter at {a:.1f}-{b:.1f} s shortened to end at {cut_at:.1f} s (the footage after it starts there)")
    d["blocks"] = bl + [b for b in d["blocks"] if b[0] == "INSERT"]
    return notes


def video_parts(sh):
    """the B-roll footage on the cut list as [(seconds, "video" | "photo")] (drawn images count as photos)"""
    out = []
    for s in sh:
        if s["kind"] in ("video", "photo", "ai"):
            out.append(((s["f1"] - s["f0"]) / FPS, "video" if s["kind"] == "video" else "photo"))
    return out


def material_of(s):
    if s["kind"] in ("presenter", "black_beat", "insert"):
        return None
    if s["kind"] == "gfx":
        return "news" if s["scene"].startswith("news") else "graphic"
    if s["kind"] == "ai":
        return "ai"
    a = s.get("asset", "")
    return "stock" if a.startswith("V:") else "own" if a.startswith("S:own_") else "archive"


def archive_stretches(p):
    """each archive photo the sources step picked, with the plan's stretch it was searched for: {"P:<key>": (in s, out s)}
    (its title -> the photo search that found it -> the plan block that asked for that search)"""
    f, c = p.decisions / "sources" / "assets.json", M(p, "candidates.json")
    if not (f.exists() and c.exists()):
        return {}
    picked = (load_json(f).get("decision") or {}).get("photos") or []
    query_of = {x.get("title"): q.strip().lower() for q, v in (load_json(c).get("photos") or {}).items() for x in v}
    plan = load_json(p.decisions / "montage" / "plan.json").get("decision") or {} if (p.decisions / "montage" / "plan.json").exists() else {}
    where = {}
    for b in plan.get("blocks", []):
        for q in b.get("search_photos", []):
            where.setdefault(q.strip().lower(), (float(b.get("in", 0)), float(b.get("out", 0))))
    out = {}
    for it in picked:
        q = query_of.get(it.get("title"))
        if it.get("key") and q in where:
            out[f"P:{it['key']}"] = where[q]
    return out


NEAR_S = 15.0                 # an archive photo goes back only near the stretch it was picked for


def archive_swaps(p, blocks, have, build, limit=TG.SMALL, R=None):
    """a small archive shortfall (or stock overrun) on the cut list fixed in code (owner's decision of 21 Oct 2026: never
    ask Claude again for it): up to `limit` stock clips (V:) in F blocks give their place to archive photos the sources
    step picked for that same stretch of the plan (within NEAR_S) and the cut list does not show yet. blocks: the cut
    list's blocks; have: the photo keys that may be used; build(blocks) -> the cut list's shots.
    -> (blocks, [notes]), or None when the shortfall is bigger or no picked photo fits"""
    import copy
    from .news import has_news as _has_news
    has_news = _has_news(p)

    def short(sh):
        counted = [t for t in (material_of(s) for s in sh) if t is not None]
        want = TG.targets(len(counted), has_news, R)
        return max(counted.count("stock") - want["stock_max"], want["archive_min"] - counted.count("archive"), 0)

    need = short(build(blocks))
    if need == 0 or need > limit:
        return None
    blocks = copy.deepcopy(blocks)
    used = {a for b in blocks if b[0] == "F" for a in b[1]}
    spare = {k: v for k, v in archive_stretches(p).items() if k not in used and k.split(":", 1)[1] in have}
    notes = []
    for b in sorted((b for b in blocks if b[0] == "F"), key=lambda b: b[2]):
        if not spare or len(notes) >= limit:
            break
        stock = [i for i, a in enumerate(b[1]) if a.startswith("V:")]
        fit = [k for k, (a, z) in sorted(spare.items(), key=lambda kv: abs(kv[1][0] - b[2]))
               if a - NEAR_S <= b[3] and b[2] <= z + NEAR_S]
        if not stock or not fit:
            continue
        i, k = stock[-1], fit[0]
        notes.append(f"{b[1][i]} at {b[2]:.1f}-{b[3]:.1f} s -> archive photo {k} (picked for {spare[k][0]:.0f}-{spare[k][1]:.0f} s)")
        b[1][i] = k
        del spare[k]
        if short(build(blocks)) == 0:
            return blocks, notes
    return None


LABEL_S = (5.0, 7.0)          # owner's decision 1b: a key-word label stays about 6 s in the presenter type (rule 11)


def check_cut(p, d, edl, L, scenes=None):
    """the presenter type's checks on the built cut list (the brain is asked again with the problems)"""
    probs = []
    S = STR.of(p)
    ie = d.get("intro_end_s")
    if ie is None:
        return ["give intro_end_s (the plan's intro end, a sentence start between 15 and 20 s)"]
    probs += intro_end_ok(p, ie, S)
    probs += cold_end_ok(p, d, S)
    sh = edl["shots"]
    (s0, s1), (n0, n1) = S.fast_shot_limits, S.fast_shot
    for s in sh:
        a, b = s["f0"] / FPS, s["f1"] / FPS
        if a < ie - 0.12:              # a cut lands 2 frames (0.083 s) before its word
            if s["kind"] in ("presenter", "black_beat"):
                probs.append(f"the intro (0-{ie:.1f} s) is B-roll and graphics only; the presenter is on screen at {a:.1f}-{b:.1f} s")
            elif not s0 <= b - a <= s1 and b < ie - 0.12:
                probs.append(f"intro shots last {n0:g}-{n1:g} s; {s.get('asset') or s.get('scene')} at {a:.1f}-{b:.1f} s lasts {b - a:.1f} s "
                             f"(give the intro's F blocks pace_s about {(n0 + n1) / 2:g})")
        elif s["kind"] in ("video", "photo", "ai") and not 0.9 <= b - a <= 6.5 and s is not sh[-1]:
            probs.append(f"after the intro, B-roll shots last 2-4 s (at most 6); {s.get('asset')} at {a:.1f}-{b:.1f} s lasts {b - a:.1f} s")
    probs += cold_open_problems(d, sh, S, L)
    probs += mostly_presenter_problems(d, sh, S, L)
    rh = set(d.get("rehook_scenes", []))
    labels = [n for n in d.get("overlays", []) if n not in rh and not n.startswith("ov_")]   # ov_*: data over footage (gfx_policy)
    from . import labels as LB
    lbp = LB.of(p)                     # the channel's labels: every name as said, while said (owner, 22 Oct 2026)
    if not (lbp and lbp.get("every_name")):
        probs += TG.check_labels(len(labels), L)
    for n in [x for x in d.get("overlays", []) if (x.startswith("ov_") or x in rh) and not (lbp and lbp.get("over_presenter") and x in rh)]:
        if n in {x["name"]: x for x in (scenes or [])}:
            sc_ = {x["name"]: x for x in scenes}[n]
            over = [s for s in sh if s["kind"] not in ("video", "photo", "ai") and s["f0"] / FPS < sc_["t_out"] - 0.05 and s["f1"] / FPS > sc_["t_in"] + 0.05]
            if over:
                probs.append(f"overlay {n} ({sc_['t_in']:.1f}-{sc_['t_out']:.1f} s) is not over footage all the time ({over[0]['kind']} at "
                             f"{over[0]['f0'] / FPS:.1f} s): put it inside a B-roll block")
    sc = {x["name"]: x for x in (scenes or [])}
    for n in labels:                       # decision 1b: about 6 s, on B-roll only (a presenter shot would cut it off)
        if n not in sc:
            continue
        a, b = sc[n]["t_in"], sc[n]["t_out"]
        if not lbp and not LABEL_S[0] <= b - a <= LABEL_S[1]:
            probs.append(f"label {n} stays {b - a:.1f} s; key-word labels stay about 6 s (5-7 s, rule 11)")
        over = [s for s in sh if s["kind"] in ("presenter", "black_beat") and s["f0"] / FPS < b - 0.05 and s["f1"] / FPS > a + 0.05]
        if over and not (lbp and lbp.get("over_presenter")):
            probs.append(f"label {n} ({a:.1f}-{b:.1f} s) runs over the presenter at {over[0]['f0'] / FPS:.1f} s; labels sit on B-roll only")
    from .news import has_news as _has_news
    has_news = _has_news(p)     # channel profiles: only the news with a screenshot (montage/news.py)
    probs += TG.check([material_of(s) for s in sh], d.get("mix_targets"), has_news, where="the cut list", R=TG.rules_of(p))
    probs += picture_problems(p, sh)
    from .steps import photo_rejects
    rej = photo_rejects(p)
    for key in sorted({s["asset"].split(":", 1)[1] for s in sh if s["kind"] == "photo" and s.get("asset")} & set(rej)):
        probs.append(f"photo {key} was rejected on sight ({rej[key]}): do not use it")
    from .review import BLACK_BELOW, clip_luma
    for key in sorted({s["asset"].split(":", 1)[1] for s in sh if s["kind"] == "video" and s.get("asset")}):
        lum = clip_luma(p, key)
        if lum is not None and lum < BLACK_BELOW:
            probs.append(f"clip {key} is nearly black (its mean luma is {lum:.0f} of 255): do not use it")
    uses = [(s["f0"] / FPS, "file:" + s["asset"], s["f0"]) for s in sh if s.get("asset")]
    for key, ts in PL.file_problems(uses):        # Phase 2: one picture file at most twice in the video, 60 s apart
        probs.append(f"{key[5:]} is shown at {', '.join(f'{t:.1f}' for t in ts)} s: one picture at most twice in the video, "
                     "its two showings at least 60 s apart (list more different assets in the F blocks)")
    return probs[:12]


def stretches(sh, kinds=("presenter", "black_beat")):
    """[(start s, end s)] of the contiguous presenter stretches (or of the other kinds when kinds is the B-roll set)"""
    out = []
    for s in sh:
        if s["kind"] in kinds:
            a, b = s["f0"] / FPS, s["f1"] / FPS
            if out and abs(out[-1][1] - a) < 1e-6:
                out[-1] = (out[-1][0], b)
            else:
                out.append((a, b))
    return out


def mostly_presenter_problems(d, sh, S, L):
    """the channel's body of mostly the presenter (الملفات السرية): B-roll blocks about once a minute or less"""
    if not S.mostly_presenter:
        return []
    ie = d.get("intro_end_s") or 0
    body = [(max(a, ie), b) for a, b in stretches(sh, ("video", "photo", "ai", "gfx")) if b > ie + 0.2]
    mins = max(1e-6, (L - ie) / 60)
    share = sum(b - a for a, b in body) / max(1e-6, L - ie)
    probs = []
    if len(body) / mins > 1.3:
        probs.append(f"after the intro this channel is mostly the presenter: B-roll blocks about once a minute or less; there are "
                     f"{len(body)} in {mins:.1f} min")
    if share > 0.4:
        probs.append(f"after the intro this channel is mostly the presenter: the B-roll is {share:.0%} of it (at most about 40%)")
    return probs


def cold_open_problems(d, sh, S, L):
    """the channel's cold open (Ramadan's guide): B-roll except one short presenter appearance near its middle and the
    presenter's teaser at its end; then the body's alternation of footage and presenter"""
    probs = []
    if not S.cold_open or d.get("cold_open_end_s") is None:
        return probs
    ie, ce = d.get("intro_end_s") or 0, d["cold_open_end_s"]
    (w0, w1), (d0, d1) = S.presenter_window(ce)
    pres = [(a, b) for a, b in stretches(sh) if b > ie + 0.2 and a < ce - 0.2]
    teaser = [x for x in pres if abs(x[1] - ce) <= 0.5]
    middle = [x for x in pres if x not in teaser]
    if not teaser or not 3.0 <= teaser[-1][1] - teaser[-1][0] <= 45.0:
        probs.append(f"the cold open ends on the presenter (his teaser and «حضّر مشروبك», 3-45 s, ending at cold_open_end_s {ce:.1f}): "
                     "leave the presenter on screen there (no F or G block)")
    if S.cold_alt:                     # early and often (owner, 22 Oct 2026)
        ca = S.cold_alt
        f0 = ca["first_s"]
        if not middle or not f0 - 15 <= middle[0][0] <= f0 + 30:
            probs.append(f"in the cold open the presenter first appears at about {f0:g} s ({f0 - 15:g}-{f0 + 30:g} s); "
                         f"he is first on screen at {round(middle[0][0], 1) if middle else 'no moment before the teaser'}")
        marks = [ie] + [x for ab in pres for x in ab]
        gaps = [(round(a, 1), round(b, 1)) for a, b in zip([ie] + [b for _, b in pres], [a for a, _ in pres] + [ce]) if b - a > ca["every_s"] * 1.5]
        if middle and gaps:
            probs.append(f"in the cold open the presenter comes back about every {ca['every_s']:g} s (at most {ca['every_s'] * 1.5:g} s "
                         f"of footage between two appearances); footage alone at {gaps[:4]}")
        lo_, hi_ = ca["for_s"]
        bad = [(round(a, 1), round(b, 1)) for a, b in middle if not lo_ * 0.6 <= b - a <= hi_ * 1.3]
        if bad:
            probs.append(f"each presenter appearance in the cold open lasts {lo_:g}-{hi_:g} s; these do not: {bad[:4]}")
        short = [(round(a, 1), round(b, 1)) for (_, a), (b, _) in zip(pres, pres[1:]) if b - a < COLD_FOOTAGE_MIN - 0.5]
        if short:
            probs.append(f"in the cold open the footage is the majority: at least {COLD_FOOTAGE_MIN:g} s of footage between two "
                         f"appearances of the presenter; only a short stretch at {short[:4]}")
        teaser_s = sum(b - a for a, b in teaser)
        share = sum(b - a for a, b in middle) / max(1e-6, ce - ie - teaser_s)
        if share > COLD_PRES_MAX + 0.02:
            probs.append(f"in the cold open the presenter is {share:.0%} of it besides his teaser; at most {COLD_PRES_MAX:.0%} (the "
                         "footage is the majority, like the channel's reference)")
        del marks
    elif len(middle) != 1:
        probs.append(f"inside the cold open the presenter appears exactly once besides the teaser, about {S.presenter_for:g} s near "
                     f"{S.presenter_near:.0f} s; he is on screen at {[(round(a, 1), round(b, 1)) for a, b in middle] or 'no other moment'}")
    elif not (w0 <= middle[0][0] <= w1 and d0 <= middle[0][1] - middle[0][0] <= d1):
        a, b = middle[0]
        probs.append(f"the presenter's cold-open appearance is at {a:.1f}-{b:.1f} s; it starts at {w0:.0f}-{w1:.0f} s and lasts "
                     f"{d0:g}-{d1:g} s")
    if S.body_alternation:
        lo, hi = S.body_alternation * 0.5, S.body_alternation * 1.5
        body_p = [(max(a, ce), b) for a, b in stretches(sh) if b > ce + 0.2]
        body_b = [(max(a, ce), b) for a, b in stretches(sh, ("video", "photo", "ai", "gfx")) if b > ce + 0.2]
        long_p = [(round(a, 1), round(b, 1)) for a, b in body_p if b - a > hi * 2 and b < L - 0.5]
        if long_p:
            probs.append(f"in the body the presenter and the footage alternate about every {S.body_alternation:g} s; the presenter "
                         f"stays alone at {long_p} (put a B-roll block in it)")
        share = sum(b - a for a, b in body_b) / max(1e-6, L - ce)
        if not 0.3 <= share <= 0.7:
            probs.append(f"in the body about half the time is footage (alternating with the presenter); it is {share:.0%}")
        short_b = [(round(a, 1), round(b, 1)) for a, b in body_b if b - a < lo * 0.5]
        if len(short_b) > max(2, len(body_b) // 3):
            probs.append(f"the body's B-roll comes in blocks of about {S.body_alternation:g} s ({lo:g}-{hi:g} s); many are short: {short_b[:6]}")
    return probs


def transitions(edl, d, plan, style_order=("flash", "slide", "zoom"), S=None):
    """Ramadan's notes in code: every intro cut gets a transition and a low click; after the intro a transition entering
    each B-roll block (from the presenter), into each graphic, at each section change and on every second B-roll cut;
    the presenter's own punch-ins stay hard cuts (rule 7). -> (intro clicks, whoosh times)"""
    ie = d["intro_end_s"]
    secs = []
    prev = None
    for b in plan["blocks"]:
        if b.get("section") and b.get("section") != prev and b["in"] > 0.5:
            secs.append(b["in"])
        prev = b.get("section") or prev
    order = ["zoom", "flash", "slide", "zoomflash"]
    clicks, whooshes, seen_g, run = [], [], set(), 0
    shots = edl["shots"]
    for k, s in enumerate(shots):
        if k == 0:
            continue
        t, prev_s = s["f0"] / FPS, shots[k - 1]
        broll = s["kind"] in ("video", "photo", "ai", "gfx")
        run = run + 1 if broll and prev_s["kind"] in ("video", "photo", "ai", "gfx") else 0
        if t < ie - 0.12:
            s["transition"] = order[k % len(order)]
            clicks.append(round(t, 3))
            continue
        ce = d.get("cold_open_end_s") if S is not None and S.cold_open else None
        if ce is not None and t < ce - 0.12:          # the channel's cold open: a varied transition and an effect on every cut
            s["transition"] = order[k % len(order)]
            whooshes.append([round(t, 2), "cold open cut"])
            if s["kind"] == "gfx":
                seen_g.add(s["scene"])
            continue
        if ce is not None and S.calm_body:              # the calm body: fewer, softer transitions (Ramadan's guide)
            if s["kind"] == "gfx" and s["scene"] not in seen_g:
                s["transition"] = "zoom"
            elif broll and prev_s["kind"] in ("presenter", "black_beat"):
                s["transition"] = style_order[k % len(style_order)]
                whooshes.append([round(t, 2), "into a B-roll block"])
            if s["kind"] == "gfx":
                seen_g.add(s["scene"])
            continue
        if any(abs(t - x) <= 1.6 for x in secs) and broll:
            s["transition"] = "zoomflash"
            whooshes.append([round(t, 2), "section change"])
        elif s["kind"] == "gfx" and s["scene"] not in seen_g:
            s["transition"] = "zoom"
            whooshes.append([round(t, 2), f"into {s['scene']}"])
        elif broll and prev_s["kind"] in ("presenter", "black_beat"):
            s["transition"] = style_order[k % len(style_order)]
            whooshes.append([round(t, 2), "into a B-roll block"])
        elif broll and run % 2 == 0:
            s["transition"] = style_order[k % len(style_order)]
        if s["kind"] == "gfx":
            seen_g.add(s["scene"])
    return clicks, whooshes


def sound_additions(p, d_sound, edl, scenes, tl):
    """the code's part of the sound plan, added to the brain's: intro clicks, whooshes on transitions, a pop when each
    label appears (rule 18; mix.py starts them in pauses, the intro clicks excepted)"""
    add = load_json(M(p, "presenter_sound.json"))
    out = dict(d_sound)
    out["intro_clicks"] = add["intro_clicks"]
    have_w = [x[0] for x in out.get("whoosh_extra", [])]
    out["whoosh_extra"] = list(out.get("whoosh_extra", [])) + [w for w in add["whooshes"] if all(abs(w[0] - t) > 0.4 for t in have_w)]
    sc = {x["name"]: x for x in scenes}
    have_p = [x[1] for x in out.get("pops", [])]
    pops = list(out.get("pops", []))
    for n in tl.get("overlays", []):
        if n in sc and all(abs(sc[n]["t_in"] - t) > 0.3 for t in have_p):
            pops.append([n, round(sc[n]["t_in"], 2)])
    out["pops"] = pops
    if getattr(p, "profile", None) and STR.of(p).placement == "on_beat":
        out["placement"] = "on_beat"
        out["beats"] = beats(edl, scenes, [t for _, t in out.get("hits", [])])
    return out


BEAT_GAP = 30.0               # s between two riser-into-hit beats (Ramadan's: a few in 7 minutes)
NUMBER = re.compile(r"\d{2,}|%|٪|[٠-٩]{2,}")


def beats(edl, scenes, hit_times=()):
    """the on-beat sounds tied to what is on screen (owner's fix 8 of 21 Oct 2026) -> [[t, kind, why]]:
    a riser into a hit where a date, a year or a big number first appears (and at the sound plan's hits), at most one per
    BEAT_GAP s; a counter's ticking while a number counts; a projector where archive film comes in"""
    sc = {x["name"]: x for x in scenes}
    out, seen, last = [], set(), -1e9
    sh = edl["shots"]
    cand = []
    for s in sh:
        if s["kind"] == "gfx" and s["scene"] in sc and s["scene"] not in seen:
            seen.add(s["scene"])
            x, t = sc[s["scene"]], s["f0"] / FPS
            texts = [it for it in x.get("items", []) if it.get("type") in ("text", "kwtext", "counter")]
            if any(it.get("type") == "counter" or NUMBER.search(str(it.get("text", ""))) for it in texts):
                cand.append((t, f"{s['scene']}: a date or a number appears"))
            for it in x.get("items", []):
                if it.get("type") == "counter":
                    a = t + float(it.get("t0", 0))
                    out.append([round(a, 2), "tick", f"{s['scene']}: the number counts", round(max(0.4, float(it.get("t1", 1)) - float(it.get("t0", 0))), 2)])
    cand += [(t, "a hit in the sound plan") for t in hit_times]
    for t, why in sorted(cand):
        if t - last >= BEAT_GAP:
            out.append([round(t, 2), "beat", why])
            last = t
    for k, s in enumerate(sh):
        prev = sh[k - 1] if k else None
        if s["kind"] == "video" and str(s.get("asset", "")).startswith("S:") and not str(s.get("asset")).startswith("S:own_") \
                and not (prev and str(prev.get("asset", "")).startswith("S:")):
            out.append([round(s["f0"] / FPS, 2), "projector", f"archive film {s['asset']} comes in"])
    return sorted(out)


def check_spelling(p, scenes):
    """must-do c: every Arabic word our graphics show is a word of the approved script (whisper's misspellings are not)"""
    from .scripttext import country_names_ar, not_in_script, vocabulary
    vocab = vocabulary(p)
    if not vocab:
        return
    places = country_names_ar()
    bad = []
    for sc in scenes:
        is_map = any(it.get("type") == "map" for it in sc.get("items", [])) or sc["name"].upper().startswith("MAP")
        for it in sc.get("items", []):
            for k in ("text", "label", "keyword"):
                ws = not_in_script(it.get(k), vocab, places if is_map else ())
                if ws:
                    bad.append(f"{sc['name']}: {', '.join(ws)}")
    if bad:
        raise ValueError("these words on screen are not in the approved script (spell them as in sentences.json): " + "; ".join(bad[:10]))

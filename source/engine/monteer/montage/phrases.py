"""The phrase montage's plan (owner's decisions of 16 Oct 2026 on Works/output/v6_quality_report.md): the 5b way of planning,
in the engine. The brain reads the narration's words with their times and plans the video BY MEANING: every shot is tied
to the phrase it shows (it starts on that phrase's first word), and every on-screen item is placed ON ITS WORD (the word
index where it is said). Ramadan's notes on top: a fast 15-20 s intro (shots of 1-3 s), transitions and sound effects on
cuts and on-screen text. Code checks every answer and builds the rest (montage/build.py).

Decision montage/shots:
  {"intro_end": word index where the intro ends (the first word after it; at 15-20 s),
   "sections": [{"from": word index, "title": Arabic, "music": English mood for an instrumental cue}],
   "shots": [{"from": word index (the shot starts on this word and runs to the next shot's word),
              "phrase": the Arabic words it covers, "type": stock | archive | ai | graphic | news,
              "shows": what the picture shows (English, concrete), "search": [1-2 word searches] (stock, archive),
              "ai_prompt": a generic scene (ai; also the fallback when no footage fits), "graphic": id (graphic),
              "news_item": id (news, from the script tool's news items), "motion": in | out, "history": true,
              "subject": what is seen, in 1-3 English words (footage), "place": "EGY" when the phrase is about Egypt}],
   "graphics": [{"id", "kind": map | number | steps | headline, ...}]   (see SCHEMA; every element anchored on a word)
   "onscreen": [{"kind": word | rehook | montage, "text": said words, "at": word index, "until": word index}],
   "key_facts": [word index]   (music stops before, a hit on it)}

Code checks (the brain is asked again with the problems): shots in order from word 0; a graphic never stands empty
(its first element is said within 1.2 s of the graphic appearing); the intro ends at 13-22 s on a
shot's first word; intro shots 0.9-3.3 s, later footage 0.9-6.5 s, graphics up to 13 s; every on-screen text is exactly
the words said at its anchor; numbers, map places and graphic labels are said where they are anchored; every graphic
element falls inside a shot that shows its graphic; key words and re-hooks sit on footage, not on graphics; news only from
the script's news items; at most MAX_AI drawn images.
Owner's decisions of 16 Oct 2026 on section 6 of the report (montage/place.py): a shot about Egypt or its government is
marked place "EGY" and its searches name Egypt or an Egyptian place; no search or prompt asks for a flag or a brand; the
same subject or graphic is shown at most twice within 75 s. Owner's answer 12 of 18 Oct 2026: when the profile allows
flags and brand logos in real footage (montage/place.py allowed), searches may ask for them; drawn images' prompts never.
Owner's decisions of 16 Oct 2026 on the readiness report (montage/targets.py): the material mix is a check the plan must
meet (the brain computes mix_targets from the shot count; code recomputes and checks them); key-word labels about 1.3-1.8
a minute (rule 11).
"""
import re
import statistics

from ..core.io import load_json
from ..script.text import norm, numbers
from . import place as PL
from . import targets as TG

TYPES = ["stock", "archive", "ai", "graphic", "news", "own"]       # own: the owner's extra clips (decision 8b)
FOOTAGE = ("stock", "archive", "ai", "own")
MAX_AI = 8
AI_TOTAL_MAX = 12                  # owner's decision 3a of 19 Oct 2026: drawn images in the whole episode, re-plan included
INTRO_MIN, INTRO_MAX = 15.0, 20.0
HEADLINE_GAP_S = 30.0          # owner's decision 4a (16 Oct 2026): our headline cards at most one per 30 s

ANCHOR = {"type": "object", "required": ["text", "at"], "properties": {"text": {"type": "string"}, "at": {"type": "integer"}}}
SCHEMA = {"type": "object", "required": ["intro_end", "sections", "shots", "mix_targets"], "properties": {
    "mix_targets": TG.SCHEMA,
    "intro_end": {"type": "integer"},
    "sections": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["from", "title", "music"], "properties": {
        "from": {"type": "integer"}, "title": {"type": "string"}, "music": {"type": "string"}}}},
    "shots": {"type": "array", "minItems": 1, "items": {"type": "object", "required": ["from", "type", "shows"], "properties": {
        "from": {"type": "integer"}, "phrase": {"type": "string"}, "type": {"type": "string", "enum": TYPES},
        "shows": {"type": "string"}, "search": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "ai_prompt": {"type": "string"}, "graphic": {"type": "string"}, "news_item": {"type": "string"}, "clip": {"type": "string"},
        "motion": {"type": "string", "enum": ["in", "out", ""]}, "history": {"type": "boolean"},
        "subject": {"type": "string"}, "place": {"type": "string"}}}},
    "graphics": {"type": "array", "items": {"type": "object", "required": ["id", "kind"], "properties": {
        "id": {"type": "string"}, "kind": {"type": "string", "enum": ["map", "number", "steps", "headline"]},
        "countries": {"type": "array", "items": {"type": "string"}},
        "places": {"type": "array", "items": {"type": "object", "required": ["name", "lon", "lat", "at"], "properties": {
            "name": {"type": "string"}, "lon": {"type": "number"}, "lat": {"type": "number"}, "at": {"type": "integer"}}}},
        "value": {"type": "number"}, "at": {"type": "integer"}, "label": {"type": "string"}, "unit": {"type": "string"},
        "title": ANCHOR, "items": {"type": "array", "items": ANCHOR, "maxItems": 5}, "all_at": {"type": "integer"},
        "keyword": {"type": "string"}, "headline": {"type": "string"}, "line": {"type": "string"}}}},
    "onscreen": {"type": "array", "items": {"type": "object", "required": ["kind", "text", "at"], "properties": {
        "kind": {"type": "string", "enum": ["word", "rehook", "montage"]}, "text": {"type": "string"},
        "at": {"type": "integer"}, "until": {"type": "integer"}}}},
    "key_facts": {"type": "array", "items": {"type": "integer"}}}}

# the flag and brand rule inside INSTRUCTIONS, as it stands without a profile (the earlier ban); instructions() puts the
# profile's own rule in its place (montage/place.py rule_text)
FLAGS_BANNED = ("NO FLAGS on screen, of any country: never search for or prompt a flag. A BRAND or company (an oil "
                "company, a petrol station chain, a car maker, a shop): show a place or scene of that kind (a refinery, a petrol "
                "station forecourt, a factory) without its logo or name; never put a brand name in a search or a prompt.")
# the intro and pace paragraph inside INSTRUCTIONS as it stands without a profile; instructions() puts the profile's own in
# its place (montage/structure.py)
INTRO_DEFAULT = (
    "INTRO (Ramadan's note): the first 15-20 s are a fast montage: shots of 1-3 s (about 2 s), each a different picture of "
    "what is said at that moment; intro_end = the index of the first word after the intro (a phrase start between 15 and "
    "20 s). After the intro a normal pace: footage shots of 1.5-6 s (about 2-4 s while things are listed or named), our "
    "graphics may stay up to 12 s while they build.\n")


def intro_text(S):
    """the intro and pace paragraph for this profile (INTRO_DEFAULT when it keeps the engine's defaults)"""
    if S is None or (S.is_default_intro and not S.footage_shot and not S.slow_zoom):
        return INTRO_DEFAULT
    if S.footage_shot:
        a, b = S.footage_shot
        pace = f"footage shots of {a:g}-{b:g} s (about {(a + b) / 2:g} s)"
    else:
        pace = "footage shots of 1.5-6 s (about 2-4 s while things are listed or named)"
    zoom = (" Every footage shot moves slowly: give motion = in (a slow push-in) or out (a slow pull-out), alternating, "
            "in for tension and out at the end of a thought." if S.slow_zoom else "")
    if S.fast_open is None:
        return (f"PACE (this channel): NO FAST INTRO: a slow, calm pace from the first word; intro_end = 0. {pace[0].upper() + pace[1:]}, "
                f"our graphics may stay up to 12 s while they build.{zoom}\n" + (bw_open_text(S) if S.bw_open else ""))
    (lo, hi), (fa, fb) = S.fast_open, S.fast_shot
    return (f"INTRO (this channel): the first {lo:g}-{hi:g} s are a fast documentary montage: shots of {fa:g}-{fb:g} s (about "
            f"{(fa + fb) / 2:g} s), each a different picture of what is said at that moment; intro_end = the index of the first word "
            f"after the intro (a phrase start between {lo:g} and {hi:g} s)"
            + ("; the channel's sting is put in there by code (the narration waits for it)" if S.clips and not S.cold_open else "")
            + f". After the intro a normal pace: {pace}, our graphics may stay up to 12 s while they build.{zoom}\n"
            + (cold_open_text(S) if S.cold_open else ""))


def cold_open_text(S):
    """الحدث الأخير without a presenter (owner's decision 3A of 20 Oct 2026): the cold open is montage too"""
    lo, hi = S.cold_open
    clip = any(c.get("at") == "cold_open_end" and not str(c.get("file", "")).startswith("input:") for c in S.clips)
    return (f"COLD OPEN (this channel): from the start to about {lo / 60:g}-{hi / 60:g} minutes the video is a documentary cold "
            "open that ends on the narrator's teaser and his invitation to get a drink ready («حضّر مشروبك») when the script "
            "has it; code ends it on the sentence after that line (else on a sentence break in that window)"
            + (" and puts the channel's intro clip there (the narration waits for it)" if clip else
               ", where the episode's ad goes when it has one (no intro clip: owner's decision of 21 Oct 2026)")
            + ". Start a new shot on the first word after the teaser. Music plays in the cold open only; after it the body is calm.\n")


def bw_open_text(S):
    """اقتصاد احمس without a presenter (owner's decision 6A of 20 Oct 2026): the black-and-white open, then the sting"""
    lo, hi = S.bw_open
    return (f"BLACK-AND-WHITE OPEN (this channel): the hook, the first {lo:g}-{hi:g} s, is shown in black and white; code ends it "
            "on a pause in that window and puts the channel's logo sting there (the narration waits for it), so start a new "
            "shot after each sentence there. Photos are shown framed; a map of one country is the channel's own country map.\n")


def bw_open_end(P, S):
    """where the black-and-white open of an audio-only episode ends (s), or None without one (6A): the shot start in the
    window with the longest pause before it; none when the narration is too short for it (it must leave 30 s after)"""
    if S is None or not S.bw_open:
        return None
    lo, hi = S.bw_open
    if lo > P.L - 30:
        return None
    return longest_pause_start(P, lo, min(hi, P.L - 30))


def longest_pause_start(P, lo, hi):
    """the shot start in [lo, hi] s with the longest pause before its first word (the nearest to the middle on a tie); with
    none inside, the shot start nearest to the middle"""
    W, starts = P.W, sorted({P.span(k)[0] for k in range(len(P.shots))} - {0.0})
    first = {round(P.t(s["from"]), 3): s["from"] for s in P.shots}
    inside = [t for t in starts if lo <= t <= hi and first.get(round(t, 3), 0) > 0]
    if not inside:
        return round(min(starts, key=lambda t: abs(t - (lo + hi) / 2)), 3) if starts else None
    gap = lambda t: W[first[round(t, 3)]]["s"] - W[first[round(t, 3)] - 1]["e"]          # noqa: E731
    return round(max(inside, key=lambda t: (round(gap(t), 2), -abs(t - (lo + hi) / 2))), 3)


TEASER = ("حضر", "مشروب")


def cold_open_end(P, S):
    """where the cold open of an audio-only episode ends (s), or None without one (owner's decision 3A of 20 Oct 2026): the
    first shot start after «حضّر مشروبك» when it is said in or near the window; else the shot start in the window with the
    longest pause before it. A narration too short for the window (it must leave 30 s after it): the fast intro's end."""
    if S is None or not S.cold_open:
        return None
    lo, hi = S.cold_open
    W, starts = P.W, sorted({P.span(k)[0] for k in range(len(P.shots))} - {0.0})
    if lo > P.L - 30:
        return round(P.intro_end_s, 3) if S.fast_open is not None else None
    hi = min(hi, P.L - 30)
    for i in range(len(W) - 1):
        a, b = norm(W[i]["w"]), norm(W[i + 1]["w"])
        if a.endswith(TEASER[0]) and TEASER[1] in b and lo * 0.75 <= W[i]["s"] <= hi * 1.25:
            after = [t for t in starts if t >= W[i + 1]["e"] - 0.05]
            if after and after[0] - W[i + 1]["e"] <= 15:
                return round(after[0], 3)
    return longest_pause_start(P, lo, hi)


INSTRUCTIONS = (
    "Plan the PICTURE of an Arabic YouTube narration (economics, money, geopolitics) the way a professional editor does: BY "
    "MEANING, ON THE WORDS. Read the words file (every word with its index i, start time s and the pause after it; the "
    "approved script with punctuation and line types when there is one, and its documented news items).\n"
    "SHOTS: a list in time order; each starts on a word (from = that word's index) and runs to the next shot's word. Every "
    "shot is tied to ONE phrase and shows what that phrase says: when the narrator names a thing, a person, a place or an "
    "action, the picture shows it (the government -> a government building; oil companies -> a refinery gate or tankers; "
    "your country -> the map of Egypt). Cut BEFORE the first word of a phrase, never between a word and the word that "
    "completes it («بشكل | كافي» and «كمية | النفط» are wrong cuts). The pauses help, but the narrator also pauses inside "
    "phrases: decide by meaning.\n"
    + INTRO_DEFAULT +
    "TYPES: stock (generic free footage: give 1-3 SHORT searches of 1-2 English words, e.g. \"gas station\", \"oil "
    "tanker\"; the engine searches Pixabay and shows you thumbnails later), archive (a past event, year or place: searches "
    "for public-domain photos and US federal archive films, a year helps: \"gas line 1979\"), ai (only when no footage "
    "can exist: a GENERIC scene, never a specific real event or real person; ai_prompt in English, no text in the image; "
    f"at most {MAX_AI} in the whole video), graphic (one of our own graphics, by its id in graphics), news (only an id from "
    "the documented news items). Give every stock/archive shot an ai_prompt too, as the fallback if no footage fits.\n"
    "GRAPHICS (our own, designed for this narration; each element appears exactly when its word is said, so anchor it with "
    "the word index at which that text is said): map (countries as ISO-3 codes, highlighted when the shot starts; places "
    "with name as said, lon, lat, at), number (value as said, at = the index of the word with the number, label: a few "
    "said words), steps (a row of up to 5 boxes that appear one by one as each is said, e.g. the stages of a chain; "
    "title {text, at} optional; all_at = the word where all of them light up together, optional), headline (our own "
    "newspaper-style card, no outlet name or logo, AT MOST ONE PER 30 s: headline = 2-5 words the narrator says somewhere, keyword = one word of it "
    "shown in red, line = a short line he says, optional). One graphic may be shown by several shots (it keeps building "
    "in between). Use graphics for places, numbers, lists and stages; footage for things and people.\n"
    "ON SCREEN (only words the narrator says, placed on the word): word = a key word or number in the bottom third, shown "
    "from its word for about 2 s (rule 11: about 1.3-1.8 a minute, see KEY-WORD LABELS below); rehook = the narrator's own question or tease, "
    "shown from its first word (rule 24: at least every 2.5 minutes); montage = the rule-20 word montage: one key word "
    "(e.g. «النفط») in the same spot over several quick shots and headline cards while it is repeated (at = its first "
    "saying, until = the word where it ends). text must be EXACTLY the words said starting at index at. Key words and "
    "re-hooks go on footage shots (not on graphics: put text that belongs to a graphic inside the graphic).\n"
    "PLACE (owner's decision): the channel speaks to Egyptians. When a phrase is about Egypt or the Egyptian government (also "
    "«الحكومة», «بلدك», «عندنا», «هنا» when no other country is named), set place = \"EGY\" and show EGYPT: Egyptian "
    "streets, Egyptian government buildings and places, never another country; its searches must name Egypt or an Egyptian "
    "place (\"cairo street\", \"cairo government building\", \"egypt parliament\", \"cairo traffic\"), and its ai_prompt "
    "too (\"a street in Cairo, Egypt\"). If Egypt cannot be shown, our map of Egypt or a headline card is better than "
    "another country. When the phrase is about another named country, place = its ISO-3 code and the picture shows that "
    "country. Code asks for a place on every footage shot whose words name the government, the state, Egypt or «بلدك». " + FLAGS_BANNED + "\n"
    "REPEATS (owner's decision): the same picture may repeat, but not 3 times within 75 s. Give every stock, archive and ai "
    "shot a subject: what is seen, in 1-3 plain English words (\"earth from space\", \"thinking man\", \"oil refinery\"); "
    "two shots that show the same thing get the SAME subject even if the clips differ (three different clips of the Earth "
    "are three showings of \"earth from space\"). One subject, and one graphic, at most twice in any 75 s; a third "
    "mention gets another picture of the idea (a different thing, a graphic, a headline card).\n"
    "key_facts: the word index of each big number or reveal (the music stops just before it, a hit on it). sections: "
    "where the topic changes (from = word index), a short Arabic title, an English mood for an instrumental cue; the first "
    "section starts at 0. No labels such as «رسم توضيحي» anywhere. Answer with JSON only.")


def words_file(words, L, script_lines=None, news_items=None):
    ws = []
    for i, w in enumerate(words):
        nxt = words[i + 1]["s"] if i + 1 < len(words) else L
        ws.append({"i": i, "w": w["w"].strip(), "s": round(w["s"], 2), "pause_after": round(max(0.0, nxt - w["e"]), 2)})
    return {"length_s": round(L, 2), "words": ws, "script_lines": script_lines or [],
            "news_items": [{"id": n["id"], "headline": n["headline"], "source_line": n.get("source_line", "")} for n in (news_items or [])]}


def script_hints(p):
    """the script tool's lines (with their types) and documented news items, when the project has an approved script"""
    lines = p.folder / "script" / "lines.json"
    news = p.folder / "script" / "news_items.json"
    lt = [{"text": x["text"], "type": x["type"]} for x in load_json(lines)["lines"]] if lines.exists() else []
    ni = load_json(news)["items"] if news.exists() else []
    from . import news as NEWS
    if NEWS.mode(p):                   # channel profiles: only the items with a screenshot of their page (montage/news.py)
        ok = set(NEWS.usable(p))
        ni = [x for x in ni if x["id"] in ok]
    return lt, ni


class Plan:
    """the plan with its times: shot spans, the intro's end, anchors"""

    def __init__(self, d, words, L):
        self.d, self.W, self.L = d, words, L
        self.shots = d["shots"]

    def t(self, i):
        return self.W[i]["s"]

    def span(self, k):
        a = 0.0 if k == 0 else self.t(self.shots[k]["from"])
        b = self.t(self.shots[k + 1]["from"]) if k + 1 < len(self.shots) else self.L
        return a, b

    def shot_at(self, i):
        """index of the shot during which word i is said"""
        k = 0
        for j, s in enumerate(self.shots):
            if s["from"] <= i:
                k = j
        return k

    @property
    def intro_end_s(self):
        return self.t(self.d["intro_end"]) if 0 <= self.d["intro_end"] < len(self.W) else self.L

    def said_at(self, text, i):
        want = norm(text).split()
        if not want or i < 0 or i >= len(self.W):
            return False
        got, j = [], i              # the narrator's words from i, as many as make up as many pieces: a «2.25%» is two after
        while len(got) < len(want) and j < len(self.W):     # norm («2 25%»), so it counts as two (the plan of 20 Oct 2026
            got += norm(self.W[j]["w"]).split()               # was refused for «2.25%» said right there)
            j += 1
        if got == want:
            return True
        # one joined prefix on the first word (owner's answer 1 of the first real test): «والأرجنتين» says «الأرجنتين»,
        # «للأرجنتين» (ل + ال) too
        if len(got) != len(want) or got[1:] != want[1:]:
            return False
        g, w0 = got[0], want[0]
        return (len(g) > len(w0) and g[0] in "وفبلك" and g[1:] == w0) or (w0.startswith("ال") and g == "ل" + w0[1:])

    def said_anywhere(self, text):
        return any(self.said_at(text, i) for i in range(len(self.W)))

    def number_at(self, value, i):
        txt = " ".join(w["w"] for w in self.W[max(0, i):i + 3])
        if any(abs(n["value"] - value) < 1e-9 or abs(n["scaled"] - value) < 1e-9 for n in numbers(txt)):
            return True
        from .spoken import value_at          # said in words (owner's answer 1 of the first real test); never an ordinal
        return any(abs((value_at(self.W, j) or -1) - value) < 1e-9 for j in range(max(0, i), min(len(self.W), i + 3)))


def instructions(L, has_news, own_text="", owner="", flag_rule=None, S=None, R=None):
    """the plan's request text for this narration: the fixed instructions plus decisions 2 and 3 with their numbers, the
    owner's own clips (type own, clip = its key) and the owner's words for this episode, when there are any.
    flag_rule: the profile's flag and brand rule (montage/place.py rule_text), in place of the earlier ban; S: the profile's
    structure (montage/structure.py), for its intro and pace"""
    base = INSTRUCTIONS if not flag_rule else INSTRUCTIONS.replace(FLAGS_BANNED, flag_rule + ".")
    base = base.replace(INTRO_DEFAULT, intro_text(S))
    return base + "\n" + TG.rule_text("phrases", R) + (" There are documented news items." if has_news else
                                                            " There are no documented news items: news_min is 0.") + "\n" + \
        TG.label_text(L) + "." + \
        (("\n" + own_text + " In the plan a shot on one of them is type own with clip = its key, a subject and no search.")
         if own_text else "") + \
        (("\nTHE OWNER'S INSTRUCTIONS FOR THIS EPISODE (follow them, unless they would break the rules above): " + owner) if owner else "")


def check(d, words, L, news_ids=(), iso3=None, own=None, allow=(False, False), S=None, sil=(), R=None):
    """allow: (flags, brand logos) allowed in real footage for this profile (montage/place.py allowed); S: the profile's
    structure (montage/structure.py): its intro and pace (the engine's defaults without one); sil: the narration's long
    silences (montage/voice_check.py, channel profiles only): a shot's length is counted without them"""
    from .structure import Structure
    S = S or Structure()
    fa, fb = S.fast_shot_limits
    ga, gb = (S.footage_shot[0] * 0.8, S.footage_shot[1] * 1.15) if S.footage_shot else (0.9, 6.5)
    P = Plan(d, words, L)
    n = len(words)
    probs, warn = [], []
    sh = d["shots"]
    froms = [s["from"] for s in sh]
    if froms[0] != 0 or any(b <= a for a, b in zip(froms, froms[1:])) or froms[-1] >= n:
        raise ValueError(f"shots must start at word 0 and go forward word by word (from strictly increasing, below {n}); got {froms[:40]}")
    ie = d["intro_end"]
    if S.fast_open is None:
        if ie != 0:
            probs.append(f"this channel has no fast intro: intro_end must be 0 (got {ie})")
    elif ie not in froms:
        probs.append(f"intro_end ({ie}) must be the 'from' word of a shot")
    elif not S.fast_limits[0] <= P.intro_end_s <= S.fast_limits[1]:
        probs.append(f"the intro ends at {P.intro_end_s:.1f} s (word {ie}); it must end at a phrase start between "
                     f"{S.fast_open[0]:g} and {S.fast_open[1]:g} s")
    gids = {g["id"]: g for g in d.get("graphics", [])}
    ai_n = 0
    for k, s in enumerate(sh):
        a, b = P.span(k)
        dur = b - a
        if sil:                                # one shot may hold over a long silence (owner's answer 4 of 18 Oct 2026)
            from .voice_check import quiet
            dur -= quiet(a, b, sil)
        where = f"shot {k} (word {s['from']} «{words[s['from']]['w']}», {a:.1f}-{b:.1f} s)"
        intro = S.fast_open is not None and a < P.intro_end_s - 0.05
        if intro and not fa <= dur <= fb and k + 1 < len(sh):
            probs.append(f"{where}: intro shots last {S.fast_shot[0]:g}-{S.fast_shot[1]:g} s; this one lasts {dur:.1f} s")
        elif not intro and s["type"] in FOOTAGE and not ga <= dur <= gb and k + 1 < len(sh):
            probs.append(f"{where}: footage shots after the intro last "
                         + (f"{S.footage_shot[0]:g}-{S.footage_shot[1]:g}" if S.footage_shot else "1.5-6") + f" s; this one lasts {dur:.1f} s")
        elif s["type"] in ("graphic", "news") and dur > 13.0:
            probs.append(f"{where}: a graphic shot lasts at most 12 s; this one lasts {dur:.1f} s")
        if s["type"] == "graphic" and s.get("graphic") not in gids:
            probs.append(f"{where}: graphic «{s.get('graphic')}» is not in graphics")
        if s["type"] == "news" and s.get("news_item") not in news_ids:
            probs.append(f"{where}: type news needs a news_item id from the news items ({sorted(news_ids) or 'there are none: use another type'})")
        if s["type"] == "ai":
            ai_n += 1
            if not s.get("ai_prompt"):
                probs.append(f"{where}: type ai needs ai_prompt")
        if s["type"] in ("stock", "archive") and not s.get("search"):
            probs.append(f"{where}: {s['type']} needs search words")
        if s["type"] == "own":                 # the owner's own clip (decision 8b): one of the usable ones, in the right place
            c = (own or {}).get(s.get("clip"))
            if not c:
                probs.append(f"{where}: type own needs clip = the key of one of the owner's usable clips ({sorted(own or {}) or 'there are none'})")
            elif s.get("place") == PL.HOME and c.get("place") not in ("EGY", ""):
                probs.append(f"{where}: place EGY, but the owner's clip {s['clip']} shows {c.get('place')}")
        if s["type"] in FOOTAGE and not PL.subject_key(s.get("subject", "")):
            probs.append(f"{where}: give its subject (what is seen, 1-3 English words; the same thing gets the same subject)")
        asked = " ".join(s.get("search") or []) + " " + s.get("ai_prompt", "")
        if any(allow):                         # answer 12 of 18 Oct 2026: searches may ask for them; drawn images never
            bad = PL.search_problem(" ".join(s.get("search") or []), s.get("ai_prompt", ""), *allow)
            if bad:
                probs.append(f"{where}: no flag or logo in a drawn image's prompt, and only what the profile allows in searches "
                             f"(found {', '.join(bad)})")
        elif PL.flag_in(asked) or PL.brand_in(asked):
            probs.append(f"{where}: no flag and no brand in searches or prompts (found {', '.join(PL.flag_in(asked) + PL.brand_in(asked))}); "
                         "show a place or scene of that kind")
        cue = PL.country_cue(" ".join(w["w"] for w in words[s["from"]:sh[k + 1]["from"] if k + 1 < len(sh) else n]))
        if s["type"] in FOOTAGE and cue and not s.get("place"):
            probs.append(f"{where}: its words say «{cue}»: set place to the country it means (\"EGY\" for Egypt and for the "
                         "government or the country when no other is named; else that country's ISO-3), and show that country")
        if s.get("place") and iso3 is not None and s["place"] not in iso3:
            probs.append(f"{where}: place must be an ISO-3 code (\"EGY\" for Egypt); got «{s['place']}»")
        if s.get("place") == PL.HOME and s["type"] in ("stock", "archive"):
            bad = [q for q in s.get("search") or [] if not PL.egypt_in(q) or PL.foreign_in(q)]
            if bad:
                probs.append(f"{where}: place EGY, so every search names Egypt or an Egyptian place and no other country ({bad})")
        if s.get("place") == PL.HOME and s.get("ai_prompt") and not PL.egypt_in(s["ai_prompt"]):
            probs.append(f"{where}: place EGY, so its ai_prompt sets the scene in Egypt (e.g. \"in Cairo, Egypt\")")
    if ai_n > MAX_AI:
        probs.append(f"{ai_n} ai shots; at most {MAX_AI} (the images are made on this computer's CPU): use footage or graphics")
    shown_by = {gid: [k for k, s in enumerate(sh) if s.get("graphic") == gid] for gid in gids}

    def in_graphic(gid, i, what):
        k = P.shot_at(i)
        if k not in shown_by.get(gid, []):
            probs.append(f"graphic {gid}: {what} (word {i}) is said during shot {k}, which does not show this graphic")

    for gid, g in gids.items():
        if not shown_by[gid]:
            probs.append(f"graphic {gid} is not shown by any shot")
            continue
        if g["kind"] == "map":
            for c in g.get("countries", []):
                if iso3 is not None and c not in iso3:
                    probs.append(f"graphic {gid}: unknown ISO-3 code {c}")
            for pl in g.get("places", []):
                if not P.said_at(pl["name"], pl["at"]):
                    probs.append(f"graphic {gid}: place «{pl['name']}» is not said at word {pl['at']}")
                in_graphic(gid, pl["at"], f"place «{pl['name']}»")
            if not (g.get("countries") or g.get("places")):
                probs.append(f"graphic {gid}: a map needs countries or places")
        elif g["kind"] == "number":
            if "value" not in g or "at" not in g or not P.number_at(g["value"], g["at"]):
                from .spoken import ordinal
                at = g.get("at")
                if isinstance(at, int) and 0 <= at < n and any(ordinal(w["w"]) for w in words[at:at + 2]):
                    probs.append(f"graphic {gid}: «{words[at]['w']}» at word {at} is an ordinal (the seventh, the first…), not a "
                                 "number: no number graphic for it (owner's decision); show that idea another way")
                else:
                    probs.append(f"graphic {gid}: number {g.get('value')} is not said at word {g.get('at')}")
            else:
                in_graphic(gid, g["at"], f"the number {g['value']:g}")
            if g.get("label") and not P.said_anywhere(g["label"]):
                probs.append(f"graphic {gid}: label «{g['label']}» is not said by the narrator")
        elif g["kind"] == "steps":
            for it in ([g["title"]] if g.get("title") else []) + g.get("items", []):
                if not P.said_at(it["text"], it["at"]):
                    probs.append(f"graphic {gid}: «{it['text']}» is not said at word {it['at']} (said there: "
                                 f"«{' '.join(w['w'] for w in words[it['at']:it['at'] + 4])}»)")
                else:
                    in_graphic(gid, it["at"], f"«{it['text']}»")
            if not g.get("items"):
                probs.append(f"graphic {gid}: steps needs items")
            if g.get("all_at") is not None:
                in_graphic(gid, g["all_at"], "all_at")
        elif g["kind"] == "headline":
            for f in ("headline", "line"):
                if g.get(f) and not P.said_anywhere(g[f]):
                    probs.append(f"graphic {gid}: {f} «{g[f]}» is not said by the narrator (only his words go on screen)")
            if not g.get("headline"):
                probs.append(f"graphic {gid}: headline needs its headline")
            elif len(g["headline"].split()) > 5:
                probs.append(f"graphic {gid}: a headline is at most 5 words (it must fit the card around its keyword); «{g['headline']}»")
            elif g.get("keyword") and norm(g["keyword"]) not in norm(g["headline"]).split():
                probs.append(f"graphic {gid}: keyword «{g['keyword']}» is not a word of the headline")
    uses = [(P.span(k)[0], PL.subject_use(s) if s["type"] in FOOTAGE
             else f"graphic:{s.get('graphic')}" if s["type"] == "graphic" else "", k) for k, s in enumerate(sh)]
    for key, xs in PL.repeats(uses):          # owner's decision 2: not 3 times within 75 s
        probs.append(f"{key.split(':', 1)[0]} «{key.split(':', 1)[1]}» is shown by shots {[k for _, k in xs]} at "
                     f"{', '.join(f'{t:.1f}' for t, _ in xs)} s: at most twice within 75 s; show the third idea another way")
    for gid, g in gids.items():               # a graphic must not stand empty: its first element comes soon after it appears
        if not shown_by.get(gid) or g["kind"] == "headline" or (g["kind"] == "map" and g.get("countries")):
            continue
        ats = ([g["at"]] if g["kind"] == "number" and "at" in g else []) + [pl["at"] for pl in g.get("places", [])] + \
              ([g["title"]["at"]] if g.get("title") else []) + [it["at"] for it in g.get("items", [])]
        if ats:
            a0 = P.span(shown_by[gid][0])[0]
            first = min(P.t(i) for i in ats)
            if first - a0 > 1.2:
                probs.append(f"graphic {gid} comes on screen at {a0:.1f} s but its first element is said at {first:.1f} s: "
                             "{:.1f} s of an empty graphic; start its shot nearer that word (footage until then)".format(first - a0))
    for o in d.get("onscreen", []):
        i = o["at"]
        if not P.said_at(o["text"], i):
            probs.append(f"on screen «{o['text']}» is not what is said at word {i} (said there: «{' '.join(w['w'] for w in words[i:i + 5])}»)")
            continue
        k = P.shot_at(i)
        if o["kind"] in ("word", "rehook") and sh[k]["type"] not in FOOTAGE:
            probs.append(f"on screen «{o['text']}» (word {i}) falls on shot {k}, a {sh[k]['type']}: key words and re-hooks go on footage")
        if o["kind"] == "montage":
            u = o.get("until")
            if u is None or u <= i or words[min(u, n - 1)]["s"] - words[i]["s"] > 14:
                probs.append(f"word montage «{o['text']}»: until must be a later word, at most about 12 s after word {i}")
    for i in d.get("key_facts", []):
        if not 0 <= i < n:
            probs.append(f"key fact word {i} does not exist")
    for sec in d["sections"]:
        if sec["from"] not in froms:
            probs.append(f"section «{sec['title']}» starts at word {sec['from']}, which is not a shot's first word")
    hl = headline_times(d, P)                                   # owner's decision 4a: one headline card per 30 s at most
    for a, b in zip(hl, hl[1:]):
        if b - a < HEADLINE_GAP_S:
            probs.append(f"headline cards at {a:.1f} s and {b:.1f} s are {b - a:.1f} s apart; at most one per {HEADLINE_GAP_S:.0f} s "
                         "(show the other idea with footage or another graphic)")
    probs += TG.check([s["type"] for s in sh], d.get("mix_targets"), bool(news_ids), R=R)      # owner's decision 3
    probs += TG.check_labels(sum(1 for o in d.get("onscreen", []) if o["kind"] == "word"), L)   # decision 2 (rule 11)
    if probs:
        raise ValueError("; ".join(probs[:14]) + (f" (and {len(probs) - 14} more)" if len(probs) > 14 else ""))
    return warn


HISTORY = re.compile(r"\b(1[89]\d\d|20[0-2]\d|old|historic\w*|archive\w*|vintage|history|past)\b", re.I)


NEAR = 3                       # a text said this many words from the index given is moved there (repair)


def repair(d, words, L, has_news, R=None):
    """what code fixes in a refused plan before the brain is asked again (owner's decision of 20 Oct 2026: tiny overruns
    are fixed in code, not with another 35-minute request): an on-screen text, list item or map place said up to 3 words
    from the index given -> moved to where it is said; mix_targets recomputed; stock over 40% or archive under 15% by up
    to 3 shots -> stock shots become archive (one that names a year or the past first, then latest first; never 4 of a
    type in a row); up to 2 key-word labels over rule 11's range -> the last ones left out. -> (plan, [notes]); the plan
    is then checked in full like any answer"""
    import copy
    d = copy.deepcopy(d)
    sh, notes = d["shots"], []
    P = Plan(d, words, L)
    items = [(o, "text") for o in d.get("onscreen", [])]
    for g in d.get("graphics", []):
        items += [(x, "name") for x in g.get("places", [])] if g.get("kind") == "map" else []
        items += [(x, "text") for x in ([g["title"]] if g.get("title") else []) + g.get("items", [])] if g.get("kind") == "steps" else []
    for x, f in items:
        i = x.get("at")
        if not isinstance(i, int) or not x.get(f) or P.said_at(x[f], i):
            continue
        near = next((j for dj in range(1, NEAR + 1) for j in (i - dj, i + dj) if P.said_at(x[f], j)), None)
        if near is not None:
            x["at"] = near
            notes.append(f"«{x[f]}» moved from word {i} to word {near}, where it is said")
    hist = lambda s: bool(HISTORY.search(" ".join(s.get("search") or []) + " " + s.get("shows", "")))   # noqa: E731
    prefer = sorted(range(len(sh)), key=lambda k: (not hist(sh[k]), -k))
    if R and not R["ai"]:                    # a channel with no drawn images: up to 3 ai shots become stock (their scene as search)
        ai = [k for k, s in enumerate(sh) if s["type"] == "ai"]
        if 0 < len(ai) <= TG.SMALL:
            for k in ai:
                sh[k]["type"] = "stock"
                sh[k]["search"] = sh[k].get("search") or [" ".join((sh[k].get("subject") or sh[k].get("shows", "")).split()[:3])]
                sh[k].pop("ai_prompt", None)
                notes.append(f"shot {k} ({sh[k].get('shows', '')[:40]}): ai -> stock, searching «{sh[k]['search'][0]}» (no drawn images here)")
    swap = TG.repair([s["type"] for s in sh], has_news, prefer=prefer, R=R)
    for k in swap or []:
        sh[k]["type"] = "archive"
        notes.append(f"shot {k} ({sh[k].get('shows', '')[:40]}): stock -> archive")
    if "mix_targets" in d:
        d["mix_targets"], wrong = TG.computed(d["mix_targets"], len(sh), has_news, R)
        if wrong:
            notes.append("mix_targets as computed: " + ", ".join(wrong))
    lo, hi = TG.label_range(L)
    labels = sorted((o for o in d.get("onscreen", []) if o["kind"] == "word"), key=lambda o: o["at"])
    if 0 < len(labels) - hi <= 2:
        drop = labels[hi:]
        d["onscreen"] = [o for o in d["onscreen"] if not any(o is x for x in drop)]
        notes += [f"key-word label «{o['text']}» (word {o['at']}) left out: {len(labels)} labels, at most {hi}" for o in drop]
    return d, notes


def headline_times(d, P, extra=()):
    """when each of our headline cards first comes on screen (plus `extra` times), sorted"""
    kinds = {g["id"]: g["kind"] for g in d.get("graphics", [])}
    first = {}
    for k, s in enumerate(d["shots"]):
        if s["type"] == "graphic" and kinds.get(s.get("graphic")) == "headline":
            first.setdefault(s["graphic"], P.span(k)[0])
    return sorted(list(first.values()) + list(extra))


def mix_report(d, has_news=False, R=None):
    """the plan's mix (a check the plan already met: montage/targets.py); warnings are left for a plan made before it"""
    types = [s["type"] for s in d["shots"]]
    return TG.share(types), TG.check(types, None, has_news, R=R)


def stats(P):
    d = [P.span(k)[1] - P.span(k)[0] for k in range(len(P.shots))]
    return {"shots": len(d), "median_s": round(statistics.median(d), 2) if d else 0, "max_s": round(max(d), 2) if d else 0}

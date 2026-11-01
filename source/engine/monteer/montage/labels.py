"""Key-word labels said on time (owner's decisions of 22 Oct 2026 after «المملكة المتحدة تنهار» v2: a name card on screen
only while the name is said, about 1 s more; a card for every name, group and date as it is said, the first time only;
re-hooks where their words are said; never across shots with a restart). The profile's "montage.labels":
  {"while_said_s": 1.0, "every_name": true, "over_presenter": true}   (absent: as before, rule 11's labels of about 6 s)

  of(p) -> the policy or None
  retime(scenes, words, extra) -> (scenes, notes): every label and re-hook (bg "none", not a data overlay ov_*) moved to the
      words it says (t_in = its first word's start, t_out = its last word's end + extra, at least MIN_S), its items' times
      fitted into it; one that is not said near its time is left out; a label said again later (the same words) left out
"""
import copy
import math
import re

from rapidfuzz import fuzz

FPS = 24
MIN_S = 1.2
NEAR_S, NEAR_REHOOK_S = 12.0, 40.0   # how far from the brain's time a label's (a re-hook's) words are looked for


def of(p):
    if not getattr(p, "profile", None):
        return None
    try:
        g = p.profile_montage().get("labels")
    except Exception:  # noqa: BLE001
        return None
    return dict({"while_said_s": 1.0, "every_name": True, "over_presenter": True}, **{k: v for k, v in g.items() if not k.startswith("note")}) \
        if isinstance(g, dict) and g else None


def norm(t):
    from ..cut.common import normalize_ar
    return normalize_ar(t)


def label_text(sc):
    return " ".join(str(i.get("text", "")) for i in sc.get("items", []) if i.get("type") in ("text", "kwtext", "captionbar") and i.get("text"))


def is_label(sc):
    return (sc.get("bg") or "dark") == "none" and not sc["name"].startswith(("ov_", "news_"))


def _same(a, b):
    if a.isdigit() or b.isdigit():
        return a == b
    return a == b or (len(a) > 2 and len(b) > 2 and (fuzz.ratio(a, b) >= 70 or a in b or b in a))   # «بوجسايد»/«بوكسايت»


def find_said(tokens, words, near, within=NEAR_S):
    """the words that say the label (most of its tokens in order, close together) nearest to time near -> (i0, i1) or None"""
    toks = [t for t in tokens if len(t) > 1 or t.isdigit()][:8]
    if not toks:
        return None
    need = max(1, math.ceil(0.5 * len(toks)))
    best = None
    cand = [i for i, w in enumerate(words) if abs(w["s"] - near) <= within and _same(w["n"], toks[0])] or \
           [i for i, w in enumerate(words) if abs(w["s"] - near) <= within and any(_same(w["n"], t) for t in toks)]
    for i in cand:
        j, got, last = i, 0, i
        for t in toks:
            k = next((x for x in range(j, min(len(words), j + 4)) if _same(words[x]["n"], t)), None)
            if k is not None:
                got, last, j = got + 1, k, k + 1
        if got >= need:
            score = (got, -abs(words[i]["s"] - near))
            if best is None or score > best[0]:
                best = (score, i, last)
    return (best[1], best[2]) if best else None


def fit_items(sc, d):
    for it in sc.get("items", []):
        if "t0" in it:
            it["t0"] = round(min(float(it["t0"]), max(0.0, d - 0.5)), 3)
        if "t1" in it:
            it["t1"] = round(min(float(it["t1"]), max(float(it.get("t0", 0)) + 0.2, d - 0.1)), 3)
        if "t2" in it:
            it["t2"] = round(min(float(it["t2"]), d - 0.25), 3)


def retime(scenes, words, extra=1.0):
    words = [dict(w, n=norm(w["w"])) for w in words if norm(w["w"])]
    out, notes, seen = [], [], []
    for sc in scenes:
        if not is_label(sc):
            out.append(sc)
            continue
        text = label_text(sc)
        toks = norm(text).split()
        key = " ".join(toks)
        if any(fuzz.ratio(key, k) >= 85 and re.findall(r"\d+", key) == re.findall(r"\d+", k) for k in seen):
            notes.append(f"label {sc['name']} «{text[:30]}» left out: already shown the first time it was said")
            continue
        hit = find_said(toks, words, sc["t_in"], NEAR_REHOOK_S if sc["name"].startswith("rehook") else NEAR_S)
        if hit is None:
            notes.append(f"label {sc['name']} «{text[:30]}» left out: not said near {sc['t_in']:.1f} s")
            continue
        i0, i1 = hit
        a = max(0.0, words[i0]["s"] - 0.05)
        b = max(a + MIN_S, words[i1]["e"] + extra)
        sc = copy.deepcopy(sc)
        sc["t_in"], sc["t_out"] = round(a, 3), round(b, 3)
        sc["frames"] = int(round((b - a) * FPS))
        fit_items(sc, b - a)
        seen.append(key)
        out.append(sc)
    return out, notes


def words_said(p):
    """the episode's words on the cut: montage/words.json (whisper) and the literal model's words (wav2vec2, every word it
    hears, laid on the cut through the keep list): words.json leaves gaps («الحقوق المدنية», «بارنت» were not in it)"""
    from ..core.io import load_json
    out = list(load_json(p.work / "montage" / "words.json")["words"])
    ctc_f, edl_f = p.work / "asr_ext_ctc.json", p.output / "edl.json"
    if ctc_f.exists() and edl_f.exists():
        keep, cs, t = load_json(edl_f)["keep"], [], 0.0
        for a, b in keep:
            cs.append(t)
            t += b - a
        for w in load_json(ctc_f)["words"]:
            for (a, b), c in zip(keep, cs):
                if a <= w["s"] < b:
                    out.append({"w": w["w"], "s": c + w["s"] - a, "e": c + min(w["e"], b) - a})
                    break
    return sorted(out, key=lambda w: w["s"])


REQUEST = ("KEY-WORD LABELS (this channel's standing rule, owner's decision of 22 Oct 2026): a label for EVERY person's name, "
           "group's or party's name, place name and date AS IT IS SAID, the first time only (a name said again gets none); the "
           "label shows only while its words are said and about 1 s more (code times it to the words: give t_in at the word); "
           "over footage or over the presenter alike (bg \"none\", the lower right corner, never over his face); put every "
           "label in the cut list's overlays. Re-hooks are timed to their own question the same way.")


MONTHS_AR = ("يناير", "فبراير", "مارس", "أبريل", "ابريل", "إبريل", "مايو", "يونيو", "يوليو", "أغسطس", "اغسطس", "سبتمبر", "أكتوبر",
             "اكتوبر", "نوفمبر", "ديسمبر")
DATE = re.compile(r"(?:(?:يوم\s+)?\d{1,2}\s+)?(?:" + "|".join(MONTHS_AR) + r")(?:\s+(?:سنة\s+)?\d{4})?"
                  r"|(?<![\d.,])(?:1[89]\d\d|20\d\d)(?:\s*[–-]\s*(?:1[89]\d\d|20\d\d))?(?![\d.,%])")


def dates_in(sentences):
    """every date the script says, the first time: [(text, sentence start, sentence end)] («14 أغسطس 1969», «2024–2025»)"""
    out, seen = [], set()
    for s in sentences:
        for m in DATE.finditer(s["text"]):
            t = re.sub(r"^(يوم|سنة)\s+", "", m.group(0)).replace(" سنة ", " ").strip()
            k = re.sub(r"\s+", " ", t)
            if k in seen:
                continue
            seen.add(k)
            out.append((t, s["s"], s["e"]))
    return out


def date_labels(scenes, sentences, after_s=20.0):
    """a label for every date said that no label shows yet, made in the channel's own label design (the first key-word
    label's items, its text and width changed) -> (scenes, notes)"""
    tmpl = next((x for x in scenes if is_label(x) and not x["name"].startswith("rehook") and
                 [i.get("type") for i in x.get("items", [])][:3] == ["rect", "rect", "text"]), None)
    if tmpl is None:
        return scenes, []
    have = [(x["t_in"], x["t_out"], norm(label_text(x))) for x in scenes if is_label(x)]
    out, notes = list(scenes), []
    for k, (text, s0, s1) in enumerate(dates_in(sentences), 1):
        if s0 < after_s:               # the fast intro: its running subtitles and kinetic text say it
            continue
        digits = re.findall(r"\d+", text)
        if any(a - 3 <= s1 and b + 3 >= s0 and all(d in tx for d in digits) for a, b, tx in have):
            continue
        sc = copy.deepcopy(tmpl)
        sc["name"] = f"kw_date{k:02d}"
        w = max(240, 34 * len(text) + 90)
        right = tmpl["items"][0]["x"] + tmpl["items"][0]["w"]
        it = sc["items"]
        it[0].update(x=right - w, w=w)
        it[2].update(text=text, x=round(right - w / 2 - 7), w=w - 70)
        for x in it[3:]:
            if x.get("type") == "line":
                x.update(x=right - 30, x1=right - w + 30)
        sc["t_in"], sc["t_out"] = round(s0, 3), round(s0 + 2.0, 3)
        sc["frames"] = int(round(2.0 * FPS))
        out.append(sc)
        notes.append(f"label {sc['name']} «{text}» made for a date said")
    return out, notes

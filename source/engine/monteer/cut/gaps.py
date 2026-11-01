"""Second look at long non-silent gaps inside kept takes.

Whisper (especially with no text context) tends to skip repeated phrases, so a long gap
with speech-level audio but no words is often a retake it did not write down, and
sometimes real content. Each gap is re-transcribed on its own and then:
  - no words              -> cut ("non-speech gap": noise, laugh, crew)
  - words whisper invented (a channel episode, owner's fix 5 of 22 Oct 2026): its stock phrases on noise («شكرا»,
    «ترجمة نانسي قنقر», «اشتركوا في القناة», «موسيقى» …) that the script does not have, or words the literal model
    (wav2vec2) does not hear at all in the gap and the script does not have -> cut ("non-speech gap: whisper's
    invention"). «المملكة المتحدة تنهار» kept 62 such stretches; heard as hesitations
  - repeats what follows  -> cut ("retake", ASR missed it on the first pass)
  - repeats what precedes -> keep the gap (the later take), cut the earlier attempt before it
  - anything else         -> keep, flagged as unsure
"""
from rapidfuzz import fuzz

from .asr import whisper_bin
from .common import CHANNEL, MODELS, WORK, cached, load_json, normalize_ar, run, save_json
from .sync import SYNC16

GAPS_JSON = WORK / "gap_verdicts.json"
CLIP_DIR = WORK / "gaps"


def judge_all(gaps, words, keep_idx):
    cache = load_json(GAPS_JSON) if cached(GAPS_JSON) else {}
    CLIP_DIR.mkdir(exist_ok=True)
    kept = [words[i] for i in keep_idx]
    out = []
    for g0, g1 in gaps:
        key = f"{g0:.2f}-{g1:.2f}"
        if key not in cache:
            wav = CLIP_DIR / f"{key}.wav"
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{g0 - 0.15:.3f}", "-to", f"{g1 + 0.15:.3f}",
                 "-i", SYNC16, "-c:a", "pcm_s16le", wav])
            r = __import__("subprocess").run(
                [whisper_bin(), "-m", str(MODELS / "ggml-large-v3.bin"), "-f", str(wav), "-l", "ar",
                 "-t", "8", "-nt", "-np"], capture_output=True, text=True)
            cache[key] = r.stdout.strip()
            save_json(GAPS_JSON, cache)
        text = normalize_ar(cache[key])
        after = " ".join(w["n"] for w in kept if w["s"] >= g1)[:400]
        before = " ".join(w["n"] for w in kept if w["e"] <= g0)[-400:]
        if len(text.split()) == 0:
            verdict, why = "cut", "non-speech gap"
        elif CHANNEL and invented(text, g0, g1):
            verdict, why = "cut", "non-speech gap: whisper's invention"
        elif fuzz.partial_ratio(text, after[: max(60, 3 * len(text))]) >= 75:
            verdict, why = "cut", "retake"
        elif fuzz.partial_ratio(text, before[-max(60, 3 * len(text)):]) >= 75:
            # the gap re-says the line just before it: the gap is the later take. Keep it and cut the
            # earlier attempt (last take wins), when the repeated words can be located before the gap.
            k = earlier_attempt(text, [w for w in kept if g0 - 10 <= w["e"] <= g0 + 0.05])
            if k is not None:
                out.append({"src": g0, "src_end": g1, "text": cache[key], "verdict": "keep",
                            "why": "later take of the line before it; earlier attempt cut", "cut_from": k})
                continue
            verdict, why = "cut", "retake"
        else:
            verdict, why = "keep", "untranscribed speech kept"
        out.append({"src": g0, "src_end": g1, "text": cache[key], "verdict": verdict, "why": why})
    return out


def earlier_attempt(text, before_words):
    """Start time of the longest run of words just before a gap that the gap repeats. The run must
    start on the word the gap starts with (or its second word, if the first was misheard), so no
    word that is said only once is ever cut."""
    gw = text.split()
    for k in range(len(before_words)):
        tail = [w["n"] for w in before_words[k:]]
        for off in (0, 1):
            seg = gw[off: off + len(tail)]
            if len(seg) == len(tail) and fuzz.ratio(tail[0], seg[0]) >= 70 and \
                    fuzz.ratio(" ".join(tail), " ".join(seg)) >= 75:
                return before_words[k]["s"]
    return None


# whisper's stock phrases on noise and silence (seen on the channel's episodes: subtitle credits, YouTube endings, MSA
# fillers no Egyptian script uses), normalized
INVENTED = ("ترجمه نانسي قنقر", "نانسي قنقر", "اشتركوا في القناه", "اشترك في القناه", "شكرا للمشاهده", "شكرا لكم", "شكرا",
            "موسيقى", "مرحبا", "حسنا", "نعم", "ترجمه", "تصميم", "قنقر")
_script_cache = {}


def _script_norm():
    if "t" not in _script_cache:
        from . import script_text
        sc = script_text.build()
        _script_cache["t"] = " " + " ".join(normalize_ar(x if isinstance(x, str) else x.get("text", "")) for x in sc["sentences"]) + " "
    return _script_cache["t"]


def _ctc_in(g0, g1):
    if "ctc" not in _script_cache:
        f = WORK / "asr_ext_ctc.json"
        _script_cache["ctc"] = load_json(f)["words"] if f.exists() else None
    ctc = _script_cache["ctc"]
    return None if ctc is None else [normalize_ar(w["w"]) for w in ctc if w["s"] < g1 + 0.1 and w["e"] > g0 - 0.1]


def invented(text, g0, g1):
    """a gap's whisper text that is not speech: one of its stock phrases the script does not say, or words neither the
    script nor the literal model (which hears every sound of speech, stammers included) has in the gap"""
    t, script = normalize_ar(text), _script_norm()
    if f" {t} " in script and len(t.split()) >= 2:
        return False
    if any(f" {x} " in f" {t} " for x in INVENTED) and not any(f" {x} " in script for x in INVENTED if f" {x} " in f" {t} "):
        return True
    heard = _ctc_in(g0, g1)
    if heard is None:
        return False
    ws = [w for w in t.split() if len(w) > 2]
    if not ws:
        return False
    in_script = sum(1 for w in ws if f" {w} " in script)
    in_ctc = sum(1 for w in ws if any(fuzz.ratio(w, c) >= 70 for c in heard))
    # a long gap the literal model hears almost nothing in is no speech even when whisper's word is a script word
    # («لحظة» over 7.6 s of «المملكة المتحدة تنهار»)
    return in_ctc == 0 and (in_script < len(ws) / 2 or (g1 - g0 > 1.5 and len(heard) <= (g1 - g0) / 2))

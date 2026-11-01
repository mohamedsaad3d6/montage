"""Verification pass on the finished edit: transcribe it, look for repeats that are still in it
(a phrase the first pass heard only once because whisper gave one word a long span that hid the
repeat), map them back to the raw recording and write the earlier attempts to work/verify_cuts.json.
run.py removes those spans on the next run. The spoken outro is left alone.

    (a step of `bin/monteer run`; see monteer/steps.py)
"""
import subprocess
import time
import wave
from pathlib import Path

import numpy as np
from rapidfuzz import fuzz

from . import script_text
from .align import select_takes
from .asr import transcribe, whisper_bin
from .common import CHANNEL, EDIT_VIDEO, MODELS, OUT, SR, WORK, load_json, normalize_ar, run, save_json, tc

VERIFY_CUTS = WORK / "verify_cuts.json"
REPEAT_NEAR = 12  # words


def leftover_repeats(words, stop_at):
    """Indices of output words that are earlier attempts of a phrase said again right after."""
    script = script_text.build()
    for i, w in enumerate(words):
        w["i"] = i
    d = select_takes(words, script)["decisions"]
    cut = {x["i"] for x in d if not x["keep"] and x["reason"].startswith("retake") and words[x["i"]]["s"] < stop_at}
    # a word is an earlier attempt only if it is said again within the next few words
    cut = {i for i in cut if any(fuzz.ratio(words[i]["n"], w["n"]) >= 80 for w in words[i + 1: i + 1 + REPEAT_NEAR])}
    # a short interjection between a false start and its retry ("بعد ما أيوة بعد ما") goes with it
    for i in sorted(cut):
        k = i + 1
        if k not in cut and k + 1 < len(words) and len(words[k]["n"]) <= 4 \
                and (k + 1) not in cut and any(fuzz.ratio(words[k + 1]["n"], words[g]["n"]) >= 80
                                               for g in range(i, max(i - 6, -1), -1) if g in cut):
            cut.add(k)
    return sorted(cut)


ONE_WINDOW = 28.0  # s: a clip whisper hears in one 30 s window (the clips are 7-11 s)


def clip_of(wav, o0, o1):
    """a few seconds around the spot, on their own"""
    clip = WORK / "verify_clips" / f"{o0:.2f}.wav"
    clip.parent.mkdir(exist_ok=True)
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0, o0 - 3):.3f}", "-to", f"{o1 + 4:.3f}", "-i", wav, clip])
    return clip


def seconds(clip):
    with wave.open(str(clip)) as w:
        return w.getnframes() / w.getframerate()


def clip_texts(clips):
    """whisper large-v3's text of each clip, the model loaded ONCE for all of them (owner's 2a of 21 Oct 2026: 52 clips,
    each loading the 3 GB model again, took 59 min). -mc 0: no text is carried from one clip to the next, so each clip is
    heard as on its own (one window each, nothing before it); a clip longer than one window runs on its own as before."""
    base = [whisper_bin(), "-m", str(MODELS / "ggml-large-v3.bin"), "-l", "ar", "-t", "8", "-nt", "-np"]
    texts = {}
    alone = [c for c in clips if seconds(c) > ONE_WINDOW]
    for c in alone:
        texts[c] = subprocess.run(base + ["-f", str(c)], capture_output=True, text=True).stdout
    batch = [c for c in clips if c not in texts]
    if batch:
        t0 = time.time()
        outs = [c.parent / c.stem for c in batch]                    # whisper writes <clip>.txt for each ("18.01.txt")
        cmd = base + ["-mc", "0", "-otxt"] + [x for o in outs for x in ("-of", str(o))] + [str(c) for c in batch]
        subprocess.run(cmd, capture_output=True, text=True)
        for c, o in zip(batch, outs):
            t = Path(str(o) + ".txt")
            texts[c] = t.read_text(encoding="utf-8") if t.exists() and t.stat().st_mtime >= t0 - 1 else ""
    return [texts[c] for c in clips]


MAX_SPAN = 6       # words of a suspect tried as the repeated part


def repeated_words(heard, text):
    """how many of the suspect's first words the clip has twice, close together: the words that were really said again
    (owner's fix 6 of 21 Oct 2026: the old rule asked for its first 4 words twice, so «احنا ليه؟ يبقى», heard as
    «… احنا ليه؟ يبقى احنا ليه …», was left alone, «يبقى» being said once). -> 0 when not repeated. A suspect of several words
    needs at least 2 of them repeated; a one-word suspect at least 3 letters (so «دي» said twice is not a repeat)"""
    got = normalize_ar(heard).split()
    att = normalize_ar(text).split()
    for n in range(min(len(att), MAX_SPAN), 0, -1):
        if n == 1 and (len(att) > 1 or len(att[0]) < 3):
            continue
        w = " ".join(att[:n])
        hits = [k for k in range(len(got) - n + 1) if fuzz.ratio(" ".join(got[k: k + n]), w) >= 80]
        if any(n <= h2 - h1 <= REPEAT_NEAR for h1 in hits for h2 in hits):
            return n
    return 0


def is_repeat(heard, text):
    return repeated_words(heard, text) > 0


def confirmed_all(wav, spots):
    """Re-transcribe a few seconds around each spot on its own (one model load for all) -> (the spots confirmed, cut to
    the repeated words only, and the ones left alone). spots: (o0, o1, text, word starts)"""
    clips = [clip_of(wav, sp[0], sp[1]) for sp in spots]
    out, alone = [], []
    for (o0, o1, text, ws), heard in zip(spots, clip_texts(clips)):
        n = repeated_words(heard, text)
        print(f"  clip check {tc(o0)} «{text}»: {'repeat confirmed' if n else 'not confirmed, left alone'} — {heard.strip()[:90]}")
        if n:
            if n < len(ws):            # only the words said again are cut; the rest of the suspect stays
                o1, text = ws[n], " ".join(text.split()[:n])
            out.append((o0, o1, text))
        else:
            alone.append((o0, o1, text))
    return out, alone


# ---------------------------------------------------------------------------------------------------- owner's fix 4 of 22 Oct 2026
# a channel episode: whisper on the whole edit writes an immediate repeat once («وفي ويلز وفي ويلز», «هو محتاج أكتر من مجرد
# رفض» twice were heard once), so the first round also hears the edit in short clips, each on its own, and looks for the
# script's words said twice at one place of the script (a restart, also a reworded one that shares two words). Whisper's
# clip text invents repeats too (2 of 8 on «المملكة المتحدة تنهار»), so each one is cut only when the literal model
# (wav2vec2, which writes every stammer) has its first word twice there.
CLIP_S, CLIP_HOP = 10.0, 5.0
SCRIPT_NEAR = 8          # script words: where a transcript word may sit around its aligned place
STOPW = {"و", "في", "من", "على", "ان", "اللي", "ده", "دي", "يعني", "مش", "لا", "ما", "او", "يا", "بس", "هو", "هي", "كان", "عن",
         "مع", "الى", "لو", "انه", "انا", "احنا", "كده"}


def _same(x, y):
    return x == y or (len(x) > 2 and len(y) > 2 and fuzz.ratio(x, y) >= 80)


class ScriptPlace:
    """where each moment of the edit is in the script (the whole-edit transcript aligned to the script's words)"""

    def __init__(self, words):
        import difflib
        sc = script_text.build()
        self.sw = [w for w in (normalize_ar(x if isinstance(x, str) else x.get("w", "")) for x in sc["words"]) if w]
        self.words = [w for w in words if w.get("n")]
        sm = difflib.SequenceMatcher(None, [w["n"] for w in self.words], self.sw, autojunk=False)
        self.pos = [None] * len(self.words)
        for blk in sm.get_matching_blocks():
            for k in range(blk.size):
                self.pos[blk.a + k] = blk.b + k

    def at(self, t):
        if not self.words:
            return None
        i = min(range(len(self.words)), key=lambda k: abs(self.words[k]["s"] - t))
        for d in range(40):
            for q, off in ((i - d, d), (i + d, -d)):
                if 0 <= q < len(self.words) and self.pos[q] is not None:
                    return self.pos[q] + off
        return None

    def occurrences(self, ph, q):
        m = len(ph)
        return [x for x in range(max(0, q - SCRIPT_NEAR), min(len(self.sw) - m, q + SCRIPT_NEAR) + 1)
                if all(_same(self.sw[x + k], ph[k]) for k in range(m))]

    def said_twice_there(self, ph, t1, t2):
        a, b = self.at(t1), self.at(t2)
        return a is not None and b is not None and any(x2 - x1 >= len(ph) for x1 in self.occurrences(ph, a) for x2 in self.occurrences(ph, b))


def said_again(ws, i, j):
    """a restart: what would be cut (words i..j-1) is said again right after it (at least 80 % of its words of 3 letters or
    more among the next words), so no word is lost. «أنا مش شايف إن السؤال الأهم … هتتفكك؟ أنا شايف إن السؤال هل لندن» is
    no restart: its middle is said once (owner's review of the v2 run, 22 Oct 2026: cutting it turned the meaning round)"""
    cut = [w["n"] for w in ws[i:j] if len(w["n"]) >= 3 and w["n"] not in STOPW]
    if not cut:
        return True
    after = [w["n"] for w in ws[j:j + (j - i) + 6]]
    found = sum(1 for c in cut if any(fuzz.ratio(c, a) >= 75 for a in after))
    return found >= 0.8 * len(cut)


def repeats_in(ws, place):
    """[(o0, o1, text, word starts)] the earlier attempt of each phrase of 2+ words said twice close together (not twice in
    the script at that place)"""
    out, N = [], len(ws)
    for i in range(N):
        for j in range(i + 1, min(N, i + REPEAT_NEAR + 1)):
            if not _same(ws[i]["n"], ws[j]["n"]):
                continue
            n = 0
            while i + n < j and j + n < N and _same(ws[i + n]["n"], ws[j + n]["n"]):
                n += 1
            content = [ws[i + k]["n"] for k in range(n) if ws[i + k]["n"] not in STOPW]
            if n < 2 or not content or sum(len(c) for c in content) < 4:
                continue
            ph = [ws[i + k]["n"] for k in range(n)]
            if place.said_twice_there(ph, ws[i]["s"], ws[j]["s"]):
                continue
            if not said_again(ws, i, j):
                continue
            out.append((ws[i]["s"] - 0.03, ws[j]["s"] - 0.03, " ".join(ws[i + k]["w"] for k in range(j - i)),
                        [ws[i + k]["s"] - 0.03 for k in range(j - i)]))
            break
    return out


def clip_words(wav, total):
    """the edit in CLIP_S clips every CLIP_HOP s, each heard on its own (whisper large-v3, the model loaded once) ->
    [[words with times on the edit]] per clip"""
    from .asr import tokens_to_words
    d = WORK / "verify_clips" / "pass"
    d.mkdir(parents=True, exist_ok=True)
    starts = [round(k * CLIP_HOP, 2) for k in range(int(max(0.0, total - CLIP_S) // CLIP_HOP) + 2)]
    clips = []
    for st in starts:
        c = d / f"w{st:08.2f}.wav"
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{st:.3f}", "-t", f"{CLIP_S:.3f}", "-i", wav, c])
        clips.append(c)
    t0 = time.time()
    cmd = [whisper_bin(), "-m", str(MODELS / "ggml-large-v3.bin"), "-l", "ar", "-t", "8", "-mc", "0", "-ojf", "-np",
           "-dtw", "large.v3", "-nfa"] + [x for c in clips for x in ("-of", str(c.parent / c.stem))] + [str(c) for c in clips]
    subprocess.run(cmd, capture_output=True, text=True)
    out = []
    for st, c in zip(starts, clips):
        j = c.parent / (c.stem + ".json")
        if not j.exists() or j.stat().st_mtime < t0 - 1:
            out.append([])
            continue
        ws = [dict(w, s=w["s"] + st, e=w["e"] + st) for w in tokens_to_words(load_json(j))]
        out.append([dict(w, n=normalize_ar(w["w"])) for w in ws if normalize_ar(w["w"])])
    print(f"  short clips: {len(clips)} clips of {CLIP_S:g} s heard in {time.time() - t0:.0f} s")
    return out


def literal_confirms(o0, o1, text, to_src, keep):
    """the literal model's words (camera timeline) at the spot: one of the attempt's words (3 letters or more) twice in what
    the cut keeps"""
    ctc_f = WORK / "asr_ext_ctc.json"
    if not ctc_f.exists():
        return False
    att = [w for w in normalize_ar(text).split() if w not in STOPW and len(w) >= 3][:MAX_SPAN]
    if not att:
        return False
    s0, s1 = to_src(o0) - 0.25, to_src(o1) + 1.5
    kept = [normalize_ar(w["w"]) for w in load_json(ctc_f)["words"] if s0 <= w["s"] <= s1 and any(a <= w["s"] < b for a, b in keep)]
    like = lambda a, c: fuzz.ratio(a, c) >= 75 or (len(a) > 3 and a in c) or (len(c) > 3 and c in a)      # noqa: E731
    return any(sum(1 for c in kept if like(a, c)) >= 2 for a in att)


def more_repeats(wav, words, stop_at, to_src, keep):
    """the first round's extra look (a channel episode): short clips and the script's place -> [(o0, o1, text)] confirmed"""
    place = ScriptPlace([dict(w, n=normalize_ar(w["w"])) for w in words])
    total = load_json(OUT / "edl.json")["keep"]
    total = sum(e - s for s, e in total)
    cands = []
    for ws in clip_words(wav, total):
        cands += [c + ("clip",) for c in repeats_in(ws, place)]
    cands += [c + ("whole",) for c in repeats_in(place.words, place)]
    cands = [c for c in sorted(cands) if c[0] < stop_at]
    merged = []                        # one spot: the first found, and how many clips heard it (the clips overlap by half)
    for c in cands:
        if merged and abs(c[0] - merged[-1][0][0]) < 1.0:
            merged[-1][1] += c[4] == "clip"
            continue
        merged.append([c, int(c[4] == "clip")])
    out = []
    for (o0, o1, text, _, _), heard in merged:
        lit = literal_confirms(o0, o1, text, to_src, keep)
        ok = lit or heard >= 2
        why = "the literal model has it twice" if lit else f"{heard} clips heard it on their own" if ok else "heard once, not in the literal words"
        print(f"  {'repeat confirmed' if ok else 'left alone'} {tc(o0)} «{text}» ({why})")
        if ok:
            out.append((o0, o1, text))
    return out


UNCONFIRMED = WORK / "verify_unconfirmed.json" if WORK else None
LAST = WORK / "verify_last.json" if WORK else None


def main(video=None, clips=False):
    """video: the edit to check (default: the finished cut); clips: also the short-clip and script-place look (a channel
    episode's first round)"""
    keep = load_json(OUT / "edl.json")["keep"]
    starts = np.cumsum([0] + [e - s for s, e in keep])

    def to_src(t):
        k = int(np.clip(np.searchsorted(starts, t, "right") - 1, 0, len(keep) - 1))
        return keep[k][0] + t - starts[k]

    wav = WORK / "edit16.wav"
    run(["ffmpeg", "-y", "-v", "error", "-i", video or EDIT_VIDEO, "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", wav])
    data = load_json(WORK / "report_data.json")
    outro = [u for u in data["unsure"] if u["why"].startswith("start of the kept channel outro")]
    stop_at = outro[0]["out"] if outro else 1e9
    found, heard = [], {}  # (output start, output end, text, word starts) from either transcript
    for model in ("large-v3", "large-v3-turbo"):
        words = transcribe(wav, "edit", model, force=True)["words"]
        heard[model] = words
        groups = []
        for i in leftover_repeats(words, stop_at):
            if groups and groups[-1][-1] == i - 1:
                groups[-1].append(i)
            else:
                groups.append([i])
        for g in groups:
            o0 = words[g[0]]["s"] - 0.03
            o1 = words[g[-1] + 1]["s"] - 0.03 if g[-1] + 1 < len(words) else words[g[-1]]["e"]
            found.append((o0, o1, " ".join(words[i]["w"] for i in g), [words[i]["s"] - 0.03 for i in g]))
    merged = []
    for o0, o1, t, ws in sorted(found):
        if merged and o0 <= merged[-1][1]:
            # both models found it: cut only what they agree on, so a word only one model misheard stays
            m = merged[-1]
            a, b = max(m[0], o0), min(m[1], o1)
            t2, w2 = (m[2], m[3]) if len(m[2]) <= len(t) else (t, ws)
            merged[-1] = (a, b, t2, [a] + [x for x in w2[1:] if a < x < b])
        else:
            merged.append((o0, o1, t, ws))
    # a long transcription can invent or drop a repeat: confirm each one on a short clip
    merged, alone = confirmed_all(wav, merged)
    if clips and CHANNEL:
        have = [(o0, o1) for o0, o1, _ in merged]
        merged += [x for x in more_repeats(wav, heard["large-v3"], stop_at, to_src, keep)
                   if not any(a - 0.5 <= x[0] <= b + 0.5 for a, b in have)]
        merged.sort()
    old = load_json(VERIFY_CUTS) if VERIFY_CUTS.exists() else []
    spans = []
    for o0, o1, t in merged:
        if o1 - o0 < 0.1:
            continue
        s0, s1 = to_src(o0), to_src(o1)
        spans.append([s0, s1, t])
        print(f"output {tc(o0)} (source {tc(s0)}): cut earlier attempt «{t}»")
    save_json(VERIFY_CUTS, old + spans)
    # the suspects left alone, on the raw recording's timeline (the cut report lists those still in the finished cut)
    left = load_json(UNCONFIRMED) if UNCONFIRMED.exists() else []
    have = {round(x["src"], 1) for x in left}
    left += [{"src": round(to_src(o0), 3), "src_end": round(to_src(o1), 3), "text": t} for o0, o1, t in alone if round(to_src(o0), 1) not in have]
    save_json(UNCONFIRMED, left)
    # this round's transcripts without the words it cut: the finished cut's transcript when this is the last round
    cut_out = [[o0, o1] for o0, o1, _ in merged]
    save_json(LAST, {"cut_out": cut_out, "models": {m: [w for w in ws if not any(a <= (w["s"] + w["e"]) / 2 < b for a, b in cut_out)]
                                                     for m, ws in heard.items()}})
    print(f"{len(spans)} leftover repeats; {len(old) + len(spans)} verification cuts in total")
    return spans


if __name__ == "__main__":
    main()

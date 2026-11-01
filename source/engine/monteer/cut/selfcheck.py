"""Self-check of a finished edit: transcribe it, compare it to the script and list what a viewer would
notice: leftover repeats, script lines said only partly (a bug, not a style choice), and joins that
don't flow (the speech jumps back, skips script words, or the cut lands inside a word).

    (a step of `bin/monteer run`; see monteer/steps.py)

Each finding has an output time, a type, the words involved and which ASR models saw it.
"""
import argparse
from collections import Counter

import numpy as np
from scipy.io import wavfile
from rapidfuzz import fuzz, process

from . import script_text
from .align import _NUM
from .common import CHANNEL, OUT, SR, WORK, load_json, normalize_ar, save_json, tc

MATCH = 60          # fuzzy ratio for an output word to count as a script word
REPEAT = 80         # fuzzy ratio for two output words to count as the same word
NEAR = 70           # ... or as a corrected word ("2006 ... 2016")
FILLERS = {"يعني", "اه", "ايه", "اللي", "ال", "في", "و", "يا", "ها", "ايوه", "طب", "طيب", "ف"}
PARTIAL = 0.75      # a script line with fewer of its words in the edit is said only partly
CHOP_RUN = 3        # ... or missing this many consecutive words
SKIP = 4            # a join that skips this many script words doesn't flow
LOUD_DB = -24.0     # both sides of a join louder than this: the cut lands inside speech


def script_range(script, last_sentence):
    n = sum(1 for s in script["sent_of_word"] if s <= last_sentence)
    return script["words"][:n], script["sent_of_word"][:n]


def last_sentence(script, missing):
    """the last script sentence that belongs to this recording: the last one found in it, below the project's
    options.script_end_sentence (a script file can hold several episodes; that option marks where this one ends)"""
    from .common import PROJECT
    end = PROJECT.opt("script_end_sentence", len(script["sentences"])) if PROJECT is not None else len(script["sentences"])
    return max(i for i in range(len(script["sentences"])) if i not in missing and i < end)


def ratios(a, b):
    sim = process.cdist(a, b, scorer=fuzz.ratio, workers=-1, dtype=np.uint8).astype(np.int16)
    num = [i for i, w in enumerate(a) if w in _NUM]
    if num:
        sim[num] = np.maximum(sim[num], process.cdist([_NUM[a[i]] for i in num], b, scorer=fuzz.ratio,
                                                     workers=-1, dtype=np.uint8))
    return sim


def align(out_n, scr):
    """Monotonic weighted alignment of output words to script words (each used at most once).
    Returns j for each output word (-1 = not matched) and the ratio of the match."""
    sim = ratios(out_n, scr)
    gain = np.where(sim >= MATCH, (sim - 50) / 50.0, -np.inf)
    n, m = len(out_n), len(scr)
    H = np.zeros((n + 1, m + 1), np.float32)
    B = np.zeros((n + 1, m + 1), np.int8)  # 0 diag, 1 skip output word, 2 skip script word
    for i in range(1, n + 1):
        diag = H[i - 1, :-1] + gain[i - 1]
        up = H[i - 1, 1:]
        best = np.maximum(diag, up)
        b = np.where(diag >= up, 0, 1).astype(np.int8)
        row = np.empty(m + 1, np.float32)
        row[0] = H[i - 1, 0]
        # left moves (skip script words) propagate along the row: running max
        row[1:] = best
        acc = np.maximum.accumulate(row)
        left = acc > row
        B[i, 1:] = np.where(left[1:], 2, b)
        H[i] = acc
        B[i, 0] = 1
    j_of = [-1] * n
    r_of = [0] * n
    i, j = n, m
    while i > 0 and j > 0:
        if B[i, j] == 0:
            j_of[i - 1], r_of[i - 1] = j - 1, int(sim[i - 1, j - 1])
            i, j = i - 1, j - 1
        elif B[i, j] == 1:
            i -= 1
        else:
            j -= 1
    return j_of, r_of


NUMBER_WORDS_SPOKEN = {"الفين", "الف", "الاف", "مليون", "مليار", "ميه", "مية", "مايه", "ميتين", "عشرين", "تلاتين", "ثلاثين",
                       "اربعين", "خمسين", "ستين", "سبعين", "تمانين", "ثمانين", "تسعين", "عشره", "عشر"}


def number_word(w):
    """a spoken number word (a digit or a number written out), with or without its «و»"""
    w = w[1:] if w.startswith("و") and len(w) > 3 else w
    return w.isdigit() or w in _NUM or w in NUMBER_WORDS_SPOKEN


def find_repeats(ws, j_of, scr, stop_at):
    """Phrases said twice in a row (with at most a couple of filler words between), that the script
    does not itself repeat at that place; and corrected words ('2006 ... 2016', 'وفهم وفي فهم')."""
    out, n, seen = [], len(ws), set()
    nn = [w["n"] for w in ws]

    def script_doubles(i, k, g):
        j = next((j_of[x] for x in range(i, min(n, i + 2 * k + g + 2)) if j_of[x] >= 0), -1)
        if j < 0:
            return False
        win = scr[max(0, j - 12): j + 12]
        ph = nn[i:i + k]
        hits = [a for a in range(len(win) - k + 1) if all(fuzz.ratio(win[a + t], ph[t]) >= REPEAT for t in range(k))]
        # the script says it twice close together itself ("المسألة مش حظ، المسألة مجرد")
        return any(0 < b - a <= k + g + 2 for a in hits for b in hits)

    for k in range(5, 0, -1):
        for i in range(n - 2 * k + 1):
            if ws[i]["s"] >= stop_at or any(x in seen for x in range(i, i + k)):
                continue
            for g in range(0, 3):
                b = i + k + g
                if b + k > n or any(len(nn[x]) < 2 for x in range(i, i + k)):
                    continue
                if g and not all(nn[x] in FILLERS or len(nn[x]) <= 2 for x in range(i + k, b)) \
                        and sum(len(nn[x]) for x in range(i, i + k)) < 4:
                    continue
                if not all(fuzz.ratio(nn[i + t], nn[b + t]) >= REPEAT for t in range(k)):
                    continue
                if k == 1 and g == 0 and nn[i] in FILLERS:
                    continue
                if CHANNEL and all(number_word(nn[x]) for x in range(i, i + k)):
                    continue           # a range read out: «ألفين أربعة وعشرين وألفين خمسة وعشرين» (owner's review, 22 Oct 2026)
                if script_doubles(i, k, g):
                    continue
                seen.update(range(i, b + k))
                out.append({"type": "repeat", "i0": i, "i1": b + k - 1, "cut_i0": i, "cut_i1": b - 1,
                            "text": " ".join(w["w"] for w in ws[i:b + k])})
                break
    # a word that isn't matched to the script, right before a matched word it nearly equals
    for i in range(n - 1):
        if j_of[i] >= 0 or i in seen or ws[i]["s"] >= stop_at or len(nn[i]) < 2:
            continue
        for b in range(i + 1, min(n, i + 3)):
            if j_of[b] >= 0 and NEAR <= fuzz.ratio(nn[i], nn[b]) < 100 and \
                    all(j_of[x] < 0 for x in range(i + 1, b)):
                seen.update(range(i, b + 1))
                out.append({"type": "corrected word", "i0": i, "i1": b, "cut_i0": i, "cut_i1": b - 1,
                            "text": " ".join(w["w"] for w in ws[i:b + 1])})
                break
    return out


def find_partial(models, scr, sent_of, script, src_words):
    """Script lines said only partly in the edit (union over models)."""
    matched = np.zeros(len(scr), bool)
    for ws, j_of, _ in models:
        for j in j_of:
            if j >= 0:
                matched[j] = True
    out = []
    src_n = [w["n"] for w in src_words]
    for s in sorted(set(sent_of)):
        idx = [j for j, x in enumerate(sent_of) if x == s]
        got = matched[idx]
        frac = got.mean()
        run = best = 0
        for g in got:
            run = 0 if g else run + 1
            best = max(best, run)
        tail = 0
        for g in got[::-1]:
            if g:
                break
            tail += 1
        chopped_end = 0 < tail < len(idx) and len(idx) >= 4 and all(len(scr[j]) >= 3 for j in idx[-tail:])
        if len(idx) < 2 or (frac >= PARTIAL and best < CHOP_RUN and not chopped_end) or best == 0:
            continue
        miss = [scr[j] for j, g in zip(idx, got) if not g]
        # was the missing part ever said in the raw recording?
        said = said_in_source(miss, src_n)
        # where it would be in the edit: the output time of the nearest matched word of the line
        ws, j_of, _ = models[0]
        near = [ws[i]["s"] for i, j in enumerate(j_of) if j >= 0 and sent_of[j] == s]
        if not near:
            prev = [ws[i]["e"] for i, j in enumerate(j_of) if 0 <= j < idx[0]]
            near = [prev[-1] if prev else 0.0]
        kind = "line missing" if frac == 0 else "line said partly" if frac < PARTIAL or best >= CHOP_RUN \
            else "line end chopped"
        out.append({"type": kind, "sentence": s,
                    "out": min(near), "frac": round(float(frac), 2), "missing": " ".join(miss),
                    "text": script["sentences"][s], "said_in_raw": said})
    return out


def said_in_source(miss, src_n, k=3):
    """True if a run of the missing words appears in the raw recording's transcript."""
    if not miss:
        return False
    ph = miss[:k] if len(miss) >= k else miss
    L = len(ph)
    for a in range(len(src_n) - L + 1):
        if all(fuzz.ratio(src_n[a + t], ph[t]) >= REPEAT for t in range(L)):
            return True
    return False


def find_joins(ws, j_of, joins, db_at, stop_at):
    """Joins (cut points in the output) where the speech jumps back, skips script words, or the cut
    lands inside speech."""
    out = []
    starts = [w["s"] for w in ws]
    for t in joins:
        if t >= stop_at:
            continue
        k = int(np.searchsorted(starts, t))  # first word starting after the join
        before = [i for i in range(max(0, k - 3), k) if j_of[i] >= 0 and t - ws[i]["e"] < 2.0]
        after = [i for i in range(k, min(len(ws), k + 3)) if j_of[i] >= 0 and ws[i]["s"] - t < 2.0]
        if before and after:
            jb, ja = j_of[before[-1]], j_of[after[0]]
            ctx = " ".join(w["w"] for w in ws[max(0, k - 3): k + 3])
            if ja - jb >= SKIP:
                out.append({"type": "join skips script", "out": t, "skipped": ja - jb - 1, "text": ctx})
        # a cut inside a word: loud on both sides of the join, and a word spans it
        lb, la = db_at(t - 0.03, t), db_at(t, t + 0.03)
        inside = any(w["s"] + 0.06 < t < w["e"] - 0.06 for w in ws[max(0, k - 2): k + 1])
        if lb > LOUD_DB and la > LOUD_DB and inside:
            out.append({"type": "cut inside speech", "out": t, "db": round(max(lb, la), 1),
                        "text": " ".join(w["w"] for w in ws[max(0, k - 2): k + 2])})
    return out


def find_unmatched(ws, j_of, stop_at, joins):
    """Runs of 3+ words that match no script word (leftover chatter, broken speech), not in the outro."""
    out, i, n = [], 0, len(ws)
    while i < n:
        if j_of[i] >= 0 or ws[i]["s"] >= stop_at:
            i += 1
            continue
        k = i
        while k + 1 < n and j_of[k + 1] < 0 and ws[k + 1]["s"] < stop_at:
            k += 1
        if k - i + 1 >= 3:
            at_join = any(ws[i]["s"] - 1.0 <= t <= ws[k]["e"] + 1.0 for t in joins)
            out.append({"type": "unmatched speech" + (" at a join" if at_join else ""), "i0": i, "i1": k,
                        "text": " ".join(w["w"] for w in ws[i:k + 1])})
        i = k + 1
    return out


def find_fragments(ws, j_of, joins, stop_at, near_s=0.15):
    """Broken words at a join (literal transcript): a short piece of a word right at a cut that matches
    no script word, or the start of the word that follows it ('ش| تفسير', 'بوهي| اقتصادات')."""
    out = []
    for i, w in enumerate(ws):
        if w["s"] >= stop_at or j_of[i] >= 0:
            continue
        near = [t for t in joins if w["s"] - near_s <= t <= w["e"] + near_s]
        if not near:
            continue
        nxt = ws[i + 1]["n"] if i + 1 < len(ws) else ""
        short = len(w["n"]) <= 3 and w["n"] not in FILLERS
        prefix = len(w["n"]) >= 2 and nxt.startswith(w["n"][:2]) and fuzz.ratio(w["n"], nxt) < 80
        if short or prefix:
            out.append({"type": "broken word at a join", "i0": i, "i1": i, "text": " ".join(
                x["w"] for x in ws[max(0, i - 2): i + 3]), "join": near[0]})
    return out


def find_cut_words(keep, src_db, stop_at_src):
    """Take boundaries that land inside a sounding word on the source (the kept piece starts or ends
    mid-word). Silence cuts sit in silence by construction, so only loud boundaries are flagged."""
    out = []
    starts = np.cumsum([0] + [e - s for s, e in keep])
    for k in range(len(keep) - 1):
        e, s2 = keep[k][1], keep[k + 1][0]
        if s2 - e < 0.6 or e >= stop_at_src:  # short gaps are silence/breath cuts
            continue
        end_db, start_db = src_db(e - 0.04, e), src_db(s2, s2 + 0.04)
        if end_db > LOUD_DB or start_db > LOUD_DB:
            out.append({"type": "cut inside a word", "out": float(starts[k + 1]), "out_end": float(starts[k + 1]),
                        "side": "end" if end_db > start_db else "start", "db": round(max(end_db, start_db), 1),
                        "src": e if end_db > start_db else s2, "text": ""})
    return out


def run_check(transcripts, wav, keep, script, last_sentence, src_words, stop_at, src_db=None):
    """transcripts: [(name, words)]. Whisper models check script coverage, skipped script and off-script
    speech; the literal CTC model ('ctc') checks repeats and broken words only (it spells numbers out and
    misspells too much for script checks)."""
    scr, sent_of = script_range(script, last_sentence)
    lengths = np.array([e - s for s, e in keep])
    joins = [float(x) for x in np.cumsum(lengths)[:-1]]
    sr, audio = wavfile.read(str(wav))
    audio = audio.astype(np.float32) / 32768.0

    def db_at(a, b):
        x = audio[max(0, int(a * sr)): max(int(a * sr) + 1, int(b * sr))]
        return float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9))

    models, findings = [], []
    for name, ws in transcripts:
        j_of, r_of = align([w["n"] for w in ws], scr)
        models.append((ws, j_of, name))
        for f in find_repeats(ws, j_of, scr, stop_at):
            findings.append(dict(f, model=name, out=ws[f["i0"]]["s"], out_end=ws[f["i1"]]["e"]))
        if name == "ctc":
            for f in find_fragments(ws, j_of, joins, stop_at):
                findings.append(dict(f, model=name, out=ws[f["i0"]]["s"], out_end=ws[f["i1"]]["e"]))
            continue
        for f in find_joins(ws, j_of, joins, db_at, stop_at):
            findings.append(dict(f, model=name, out_end=f["out"]))
        for f in find_unmatched(ws, j_of, stop_at, joins):
            findings.append(dict(f, model=name, out=ws[f["i0"]]["s"], out_end=ws[f["i1"]]["e"]))
    whisper = [m for m in models if m[2] != "ctc"]
    for f in find_partial(models, scr, sent_of, script, src_words):
        findings.append(dict(f, model="all", out_end=f["out"]))
    if src_db is not None:
        to_src_stop = keep[-1][1]
        starts = np.cumsum([0] + [e - s for s, e in keep])
        for k, (s0, e0) in enumerate(keep):
            if starts[k] <= stop_at <= starts[k] + e0 - s0:
                to_src_stop = s0 + stop_at - starts[k]
        for f in find_cut_words(keep, src_db, to_src_stop):
            findings.append(dict(f, model="audio"))
    # merge the same finding seen by several models
    merged = []
    for f in sorted(findings, key=lambda x: (x["type"], x["out"])):
        m = merged[-1] if merged else None
        if m and m["type"] == f["type"] and f["out"] <= m["out_end"] + 0.5 and f["model"] not in m["models"]:
            m["models"].append(f["model"])
            m["out_end"] = max(m["out_end"], f["out_end"])
            continue
        merged.append(dict(f, models=[f["model"]]))
    for m in merged:
        m.pop("model", None)
        for k, v in m.items():
            if isinstance(v, (np.floating, np.integer)):
                m[k] = v.item()
    return sorted(merged, key=lambda x: x["out"]), models


def with_norm(ws):
    """CTC transcripts carry only raw text: add the normalized form, drop empty tokens."""
    out = []
    for w in ws:
        n = w.get("n") or normalize_ar(w["w"])
        if n:
            out.append(dict(w, n=n))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("transcripts", nargs="+")
    ap.add_argument("--wav", default=str(WORK / "edit16.wav"))
    ap.add_argument("--edl", default=str(OUT / "edl.json"))
    ap.add_argument("--save", default=str(WORK / "selfcheck.json"))
    a = ap.parse_args()
    script = script_text.build()
    data = load_json(WORK / "report_data.json")
    missing = {m["i"] for m in data["missing_script_sentences"]}
    last = max(s for s in set(script["sent_of_word"]) if s not in missing or s < min(missing) + 10)
    last = last_sentence(script, missing)
    keep = load_json(a.edl)["keep"]
    src = load_json(WORK / "asr_ext_large-v3.json")["words"]
    trs = [(p.split("_")[-1].replace(".json", ""), with_norm(load_json(p)["words"])) for p in a.transcripts]
    # the kept channel outro starts after the last script line: find it from the alignment of model 1
    stop_at = 1e9
    outro = [u for u in data["unsure"] if u["why"].startswith("start of the kept channel outro")]
    if outro:
        stop_at = outro[0]["out"]
    from .silence import FRAME, frame_db
    db = frame_db()

    def src_db(t0, t1):
        x = db[int(t0 / FRAME): max(int(t0 / FRAME) + 1, int(t1 / FRAME))]
        return float(10 * np.log10(np.mean(10 ** (x / 10))))

    found, _ = run_check(trs, a.wav, keep, script, last, src, stop_at, src_db)
    save_json(a.save, found)
    print(Counter(f["type"] for f in found))
    for f in found:
        extra = f.get("missing") or f.get("skipped") or f.get("db") or ""
        print(f"{tc(f['out'])}  {f['type']:<24} {'+'.join(f['models']):<26} {f['text'][:80]}  {extra}")


if __name__ == "__main__":
    main()

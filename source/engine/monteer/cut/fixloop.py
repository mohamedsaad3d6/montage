"""Fix loop for the self-check rule: find leftover repeats, broken words at joins and chopped line endings
in the edit, fix them on the source timeline, and repeat until clean.

The inner loop works on a "virtual" edit: the source transcripts (whisper large-v3 for the script, the
literal CTC model for repeats and word boundaries) restricted to the kept spans of the EDL. That makes
each round take seconds. selfloop.py then renders the audio, transcribes it for real and checks again.

A fix is kept only if it loses no script word the edit had before (guard), so a cut can't remove
content to get rid of a repeat.

    (a step of `bin/monteer run`; see monteer/steps.py)
"""
import numpy as np
from rapidfuzz import fuzz

from . import script_text
from . import selfcheck
from .common import FPS, OUT, WORK, load_json, normalize_ar, save_json, tc
from .edl import merge, snap_frames, subtract
from .silence import FRAME, NOISE_DB, frame_db

CTC_SRC = WORK / "asr_ext_ctc.json"
FIXES = WORK / "selfcheck_fixes.json"
MANUAL = WORK / "manual_fixes.json"
PAD = 0.04          # room left before a word when a cut stops at its start
KEEP_FRAC = 0.85    # a word with less of its audio in the edit than this is broken at a join
GONE_FRAC = 0.15    # ... and with less than this it is simply cut
CHOP_LOOK = 2.0     # seconds after a kept piece where a chopped line ending is looked for
REAL_SHORT = {"ده", "دي", "دا", "في", "من", "لا", "يا", "بس", "زي", "مش", "هو", "هي", "لو", "ما", "او", "ان",
              "عن", "مع", "كل", "اه", "و", "ف", "ب", "ل", "ع", "اي", "ال", "لي", "له", "بي", "هم", "يعني"}
OFF_CAMERA = {"ايوه", "ايوا", "هايوه", "اه", "ها"}
_db = None


def db():
    global _db
    if _db is None:
        _db = frame_db()
    return _db


def quiet(t0, t1, prefer):
    """Quietest 10 ms point in [t0, t1], ties toward prefer."""
    d = db()
    i0, i1 = int(max(0, t0) / FRAME), int(max(t1, t0 + FRAME) / FRAME) + 1
    seg = d[i0:i1]
    if len(seg) == 0:
        return prefer
    dist = np.abs(np.arange(i0, i0 + len(seg)) * FRAME - prefer)
    return float((i0 + int(np.argmin(seg + dist * 4.0))) * FRAME)


def kept_frac(keep, s, e):
    if e <= s:
        return 0.0
    inside = sum(max(0.0, min(e, b) - max(s, a)) for a, b in keep)
    return inside / (e - s)


def virtual(keep, words):
    """Source words as heard in the edit: output time, kept fraction, segment index."""
    starts = np.cumsum([0] + [e - s for s, e in keep])
    out = []
    for w in words:
        f = kept_frac(keep, w["s"], w["e"])
        if f < GONE_FRAC:
            continue
        mid = max(w["s"], min(w["e"], (w["s"] + w["e"]) / 2))
        k = next((k for k, (a, b) in enumerate(keep) if a - 0.01 <= mid <= b + 0.01), None)
        if k is None:  # the kept part is at one edge of the word
            k = next(k for k, (a, b) in enumerate(keep) if a < w["e"] and b > w["s"])
        a, b = keep[k]
        o = starts[k] + max(0.0, w["s"] - a)
        out.append(dict(w, src_s=w["s"], src_e=w["e"], s=float(o), e=float(o + min(w["e"], b) - max(w["s"], a)),
                        frac=f, seg=k))
    return out


def coverage(keep, wsp, ctc, scr):
    """Script word indices the edit says (union of whisper and the literal model)."""
    cov = set()
    for words in (wsp, ctc):
        v = [w for w in virtual(keep, words) if w["frac"] >= 0.5]
        j_of, _ = selfcheck.align([w["n"] for w in v], scr)
        cov |= {j for j in j_of if j >= 0}
    return cov


def span_of(v, i0, i1):
    """Source spans covering output words i0..i1 (one span per kept segment they sit in)."""
    spans = []
    for i in range(i0, i1 + 1):
        w = v[i]
        nxt = v[i + 1] if i + 1 < len(v) else None
        s = w["src_s"] - PAD
        e = (nxt["src_s"] - PAD) if nxt is not None and nxt["seg"] == w["seg"] and i < i1 + 1 else w["src_e"] + 0.06
        if i == i1 and nxt is not None and nxt["seg"] == w["seg"]:
            e = nxt["src_s"] - PAD
        spans.append([s, e])
    return merge(spans, gap=0.05)


def propose(keep, v, scr, j_of, stop_at, src_ws):
    """Fix proposals for the virtual edit v (CTC words)."""
    props = []
    # 1) repeats: cut the earlier copy (last take wins)
    for f in selfcheck.find_repeats(v, j_of, scr, stop_at):
        alts = [(f["cut_i0"], f["cut_i1"])]
        k = f["i1"] - f["cut_i1"]  # length of the repeated phrase
        if f["cut_i1"] - f["cut_i0"] + 1 > k:  # words between the copies: fallback cuts the first copy only
            alts.append((f["cut_i0"], f["cut_i0"] + k - 1))
        props.append({"op": "cut", "alts": [span_of(v, a, b) for a, b in alts], "reason": "retake",
                      "why": f"repeat «{f['text']}»", "out": v[f["i0"]]["s"],
                      "texts": [" ".join(v[i]["w"] for i in range(a, b + 1)) for a, b in alts]})
    # 2) broken words at joins: complete a script word, or remove a fragment
    for i, w in enumerate(v):
        if w["s"] >= stop_at or w["frac"] >= KEEP_FRAC:
            continue
        if (j_of[i] >= 0 or w["frac"] >= 0.5) and len(w["n"]) >= 3:  # mostly kept: complete it, never drop it
            props.append({"op": "keep", "spans": [[w["src_s"] - PAD, w["src_e"] + 0.06]], "reason": "chopped word",
                          "why": f"word cut at a join «{w['w']}» ({w['frac']:.0%} kept): keep all of it",
                          "out": w["s"], "text": w["w"]})
        else:
            props.append({"op": "cut", "spans": [[w["src_s"] - PAD, w["src_e"] + 0.04]], "reason": "retake",
                          "why": f"piece of a word at a join «{w['w']}» ({w['frac']:.0%} kept)",
                          "out": w["s"], "text": w["w"]})
    # 3) aborted words right at a join, restarted right after ('فيان | في سنة', 'ش | تفسير')
    lengths = np.array([e - s for s, e in keep])
    joins = [float(x) for x in np.cumsum(lengths)[:-1]]
    for f in selfcheck.find_fragments(v, j_of, joins, stop_at, near_s=0.35):
        w = v[f["i0"]]
        nxt = v[f["i0"] + 1]["n"] if f["i0"] + 1 < len(v) else ""
        prefix = len(nxt) > len(w["n"]) >= 2 and nxt.startswith(w["n"])          # 'لح | لحد', 'كا | كان'
        restart = len(nxt) >= 2 and len(w["n"]) > len(nxt) and w["n"].startswith(nxt)  # 'فيان | في سنة'
        piece = len(w["n"]) <= 2 and w["n"] not in REAL_SHORT                        # 'ش', 'ه'
        if not (prefix or restart or piece):
            continue
        props.append({"op": "cut", "spans": [[w["src_s"] - PAD, w["src_e"] + 0.04]], "reason": "retake",
                      "why": f"aborted word at a join «{w['w']}» ({f['text']})", "out": w["s"], "text": w["w"]})
    # 4) off-camera words at a join ("أيوة")
    for i, w in enumerate(v):
        if w["s"] < stop_at and w["n"] in OFF_CAMERA and j_of[i] < 0:
            props.append({"op": "cut", "spans": [[w["src_s"] - PAD, w["src_e"] + 0.04]], "reason": "off-script",
                          "why": f"off-camera «{w['w']}»", "out": w["s"], "text": w["w"]})
    return props


def chopped_endings(keep, ctc, stop_src, vocab=None):
    """A kept piece that stops one word before the speaker finishes: the next source word follows with
    no pause, a pause comes right after it, and the edit doesn't say it again in the next few words
    ('بعد ما تكون | خلصت'). Keep that word: it ends the sentence (often a paraphrase of the script)."""
    d = db()
    props = []
    v = virtual(keep, ctc)
    for k in range(len(keep) - 1):
        e = keep[k][1]
        if keep[k + 1][0] - e < 0.6 or e >= stop_src:  # silence cut, or the outro
            continue
        last = [w for w in ctc if w["e"] <= e + 0.05 and w["s"] >= keep[k][0] and kept_frac(keep, w["s"], w["e"]) >= 0.85]
        nxt = [w for w in ctc if w["s"] >= e - 0.02 and kept_frac(keep, w["s"], w["e"]) < 0.5]
        if not last or not nxt:
            continue
        w = nxt[0]
        after = nxt[1] if len(nxt) > 1 else None
        pause_before = w["s"] - last[-1]["e"]
        i1 = int((w["e"] + 0.05) / FRAME)
        quiet_after = np.mean(d[i1: i1 + 40] < NOISE_DB) if i1 + 40 < len(d) else 1.0
        if pause_before > 0.5 or quiet_after < 0.75 or len(w["n"]) < 3:
            continue
        if after is not None and after["s"] - w["e"] < 0.4:
            continue
        o = [x for x in v if x["src_s"] >= keep[k + 1][0] - 0.05][:6]
        if any(fuzz.ratio(w["n"], x["n"]) >= 70 for x in o):
            continue
        if vocab is not None and o:    # a false start of the next word is no line ending («اعطاء … اعترف», owner 22 Oct 2026)
            from .takes import is_stammer
            if is_stammer(w["w"], o[0].get("w", o[0]["n"]), vocab) or (w["n"] not in vocab and fuzz.ratio(w["n"][:3], o[0]["n"][:3]) >= 66):
                continue
        props.append({"op": "keep", "spans": [[e, w["e"] + 0.08]], "reason": "line ending",
                      "why": f"sentence ends one word after the cut: keep «{w['w']}»",
                      "out": next((x["e"] for x in v if abs(x["src_e"] - last[-1]["e"]) < 0.01), 0.0), "text": w["w"]})
    return props


_sil = None


def silence_cuts():
    """The same −32 dB silence cuts the EDL uses (edl.PAD of audio left on each side)."""
    global _sil
    if _sil is None:
        from .edl import PAD as SPAD
        from .silence import detect_silences
        _sil = [[s + SPAD, e - SPAD] for s, e in detect_silences() if e is not None and e - s > 2 * SPAD + 0.02]
    return _sil


def apply(keep, fixes):
    """Restored spans get the normal silence cuts again (unless a span is kept whole on purpose, like a
    walk to camera); then cuts are removed."""
    restore = [s for f in fixes if f["op"] == "keep" for s in f["spans"]]
    whole = [s for f in fixes if f["op"] == "keep" and f.get("keep_pauses") for s in f["spans"]]
    cuts = [s for f in fixes if f["op"] == "cut" for s in f["spans"]]
    sil = [c for c in silence_cuts() if any(c[0] < b and c[1] > a for a, b in restore)
           and not any(c[0] < b and c[1] > a for a, b in whole)]
    return snap_frames(subtract(merge(keep + restore), sil + cuts))


def snap_spans(f):
    """Put cut edges on quiet points next to the word edges."""
    out = []
    for s, e in f["spans"]:
        if f["op"] == "cut":
            s = quiet(s - 0.06, s + 0.03, s)
            e = quiet(e - 0.03, e + 0.06, e)
        else:
            e = quiet(e - 0.02, e + 0.12, e)
        out.append([s, e])
    f["spans"] = out
    return f


def main(base_keep=None, rounds=6, log=print):
    script = script_text.build()
    data = load_json(WORK / "report_data.json")
    missing = {m["i"] for m in data["missing_script_sentences"]}
    last = selfcheck.last_sentence(script, missing)
    scr, sent_of = selfcheck.script_range(script, last)
    wsp = load_json(WORK / "asr_ext_large-v3.json")["words"]
    ctc = selfcheck.with_norm(load_json(CTC_SRC)["words"])
    edl = load_json(OUT / "edl.json")
    keep = base_keep or edl.get("keep_before_selfcheck") or edl["keep"]
    outro = [u for u in data["unsure"] if u["why"].startswith("start of the kept channel outro")]
    outro_src = outro[0]["src"] if outro else 1e9
    manual = load_json(MANUAL) if MANUAL.exists() else []  # hand decisions from the review, applied first
    fixes = load_json(FIXES) if FIXES.exists() else []
    tried = {(f["op"], round(f["spans"][0][0], 1)) for f in fixes}
    cur = apply(keep, manual + fixes)
    base_cov = coverage(cur, wsp, ctc, scr)
    for rnd in range(rounds):
        starts = np.cumsum([0] + [e - s for s, e in cur])
        stop_at = next((starts[k] + max(0.0, outro_src - a) for k, (a, b) in enumerate(cur) if b >= outro_src),
                       starts[-1])
        v = virtual(cur, ctc)
        j_of, _ = selfcheck.align([w["n"] for w in v], scr)
        from .common import CHANNEL
        vocab = {normalize_ar(x if isinstance(x, str) else x.get("w", "")) for x in script["words"]} if CHANNEL else None
        props = propose(cur, v, scr, j_of, stop_at, wsp) + chopped_endings(cur, ctc, outro_src, vocab)
        for p in props:
            p.setdefault("spans", p["alts"][0] if "alts" in p else None)
        props = [p for p in props if (p["op"], round(p["spans"][0][0], 1)) not in tried]
        # spans decided by hand in the review are not touched by automatic cuts
        mk = [sp for m in manual if m["op"] == "keep" for sp in m["spans"]]
        props = [p for p in props if p["op"] != "cut" or not any(
            s < b and e > a for s, e in p["spans"] for a, b in mk)]
        if not props:
            log(f"round {rnd + 1}: nothing left to fix")
            break
        added = 0
        for p in sorted(props, key=lambda p: p["out"]):
            tried.add((p["op"], round(p["spans"][0][0], 1)))
            for spans, text in zip(p.pop("alts"), p.pop("texts")) if "alts" in p else [(p["spans"], p["text"])]:
                q = snap_spans(dict(p, spans=spans, text=text))
                trial = apply(keep, manual + fixes + [q])
                cov = coverage(trial, wsp, ctc, scr)
                lost = base_cov - cov
                if not lost:
                    break
            if lost:
                log(f"  skip {tc(p['out'])} {p['why']}: would lose script words «{' '.join(scr[j] for j in sorted(lost))}»")
                continue
            fixes.append(q)
            base_cov = cov
            added += 1
            log(f"  fix  {tc(q['out'])} {q['op']:<4} {q['why']}  [cut/keep «{q['text']}»]")
        cur = apply(keep, manual + fixes)
        log(f"round {rnd + 1}: {added} fixes, edit now {tc(sum(e - s for s, e in cur))}")
        if not added:
            break
    save_json(FIXES, fixes)
    return cur, fixes


if __name__ == "__main__":
    main()

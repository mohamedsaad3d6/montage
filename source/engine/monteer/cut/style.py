"""Stage 7c: editing-style rules learned from a human editor's cut (reference episode B).

Content decisions (which words stay) come in as a keep list; this stage keeps every speech frame
exactly as that list says and re-decides only the frames between words:
  - speech is what the literal Egyptian model (wav2vec2 CTC) hears, plus clearly loud frames (whisper
    invents words in quiet spots and its word times run over pauses). Whisper only protects: a word it
    hears over clearly loud sound is never dropped (the literal model now and then misses a real word:
    «هنا», «شوفوا» on reference episode A);
  - a pause between two kept words of the same take is left whole up to CAP; a longer one is cut
    down to TARGET, keeping silence next to the words and dropping any breath / noise inside it;
  - a join between takes keeps LEAD before the first sound and TAIL after the last one;
  - no kept piece shorter than MIN_PIECE: its pads grow into the neighbouring silence first, and a
    piece that is still short and holds no whole word is dropped.

Gaps here are measured between sound edges (word frames extended over the sound that belongs to
them), not between transcript word times.
"""
import numpy as np

FRAME = 0.01
LOUD_DB = -30.0     # a frame this loud is speech even if the literal model wrote no word there
WSP_LOUD_DB = -30.0  # a whisper word counts as speech only if its loudest frame is above this
EDGE_DB = -40.0     # sound right next to a word that still belongs to it (word onset / tail)
EDGE_MAX = (0.10, 0.15)  # how far that onset / tail may reach, s
BREATH_DB = -55.0   # a non-speech sound louder than this, lasting BREATH_MIN, away from words: a breath / noise
BREATH_MIN = 0.08
NOISE_DB = -55.0    # for counting pauses that hold any sound at all
CAP = 0.25          # a natural pause up to this (between sound edges) is left whole
TARGET = 0.18       # a longer pause is cut down to this
LEAD, TAIL = 0.09, 0.08  # silence kept before the first / after the last sound at a join
# (all four measured on the reference editor's cut of reference episode B: the editor keeps every pause up to 0.2 s, never one over
#  0.3 s, cuts longer ones to a median 0.17-0.20 s, and leaves 0.08 s / 0.09 s around a join)
MIN_PIECE = 0.5
BREATH_GAP = 0.45   # a breath in a word gap (literal-model word times) longer than this is cut out
MIN_UNIT = 0.08     # shorter runs of kept speech are slivers of a cut word, not speech
NATURAL_MAX = 2.0   # two kept words this far apart (with nothing cut between) are still one take


def runs(mask):
    d = np.diff(np.concatenate([[0], mask.astype(np.int8), [0]]))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def to_mask(intervals, n):
    m = np.zeros(n, bool)
    for s, e in intervals:
        m[max(0, int(round(s / FRAME))): max(0, int(round(e / FRAME)))] = True
    return m


def loud_words(db, wsp, slack=0.15, ctc=()):
    """Whisper words with real sound under them (allowing for whisper's loose word times) that the
    literal model has no similar word for nearby: words it missed. Drops whisper's inventions in quiet
    spots, and whisper's early or late copy of a word the literal model placed itself."""
    from rapidfuzz import fuzz
    from .common import normalize_ar
    out = []
    for w in wsp or []:
        n = normalize_ar(w["w"])
        if any(c["s"] < w["e"] + 0.5 and c["e"] > w["s"] - 0.5 and fuzz.ratio(normalize_ar(c["w"]), n) >= 60
               for c in ctc):
            continue
        a, b = int((w["s"] - slack) / FRAME), int(np.ceil((w["e"] + slack) / FRAME))
        a = max(a, 0)
        if len(db[a:b]) and db[a:b].max() > WSP_LOUD_DB:
            out.append(w)
    return out


def speech_mask(db, ctc):
    """Frames that are speech: literal-model words plus their onset/tail sound, and loud frames."""
    n = len(db)
    sp = db > LOUD_DB
    for w in ctc:
        a, b = int(w["s"] / FRAME), int(np.ceil(w["e"] / FRAME))
        sp[a:b] = True
        k = a
        while k > 0 and a - k < EDGE_MAX[0] / FRAME and db[k - 1] > EDGE_DB:
            k -= 1
        sp[k:a] = True
        k = b
        while k < n and k - b < EDGE_MAX[1] / FRAME and db[k] > EDGE_DB:
            k += 1
        sp[b:k] = True
    return sp


def breath_mask(db, sp):
    """Non-speech sound (breath, lip noise, rustle) that stands apart from the words. Room tone right
    next to a word (the gate is open there) is not a breath: the reference editor keeps it as often as silence."""
    near = np.zeros(len(db), bool)
    for a, b in runs(sp):
        near[max(0, a - 4): b + 4] = True
    m = (db > BREATH_DB) & ~sp & ~near
    out = np.zeros(len(db), bool)
    for a, b in runs(m):
        if (b - a) * FRAME >= BREATH_MIN:
            out[a:b] = True
    return out


def quiet_run(db, sp, start, step, limit):
    """Non-speech, non-breath frames from `start` going `step` (+1/-1), up to `limit`.
    `sp` here is speech | breath."""
    k, out = start, 0
    while 0 <= k < len(db) and out < limit and not sp[k]:
        out += 1
        k += step
    return out


def apply_style(keep, db, ctc, protect=(), cap=CAP, target=TARGET, lead=LEAD, tail=TAIL, min_piece=MIN_PIECE,
                log=None, wsp=None):
    """keep: content keep list [[s, e]] in source seconds. protect: spans kept exactly as they are.
    Returns the new keep list and a small report."""
    n = len(db)
    K = to_mask(keep, n)
    sp = speech_mask(db, ctc)
    br = breath_mask(db, sp)
    missed = loud_words(db, wsp, ctc=ctc)
    P = to_mask(protect, n)
    units = [(a, b) for a, b in runs(sp & K) if (b - a) * FRAME >= MIN_UNIT]
    out = np.zeros(n, bool)
    rep = {"natural_whole": 0, "natural_cut": 0, "joins": 0, "breaths_removed": 0, "dropped_pieces": 0}
    T = lambda s: int(round(s / FRAME))  # noqa: E731
    stop = sp | br  # pads never reach into a word or a breath
    starts = np.array(sorted(w["s"] for w in ctc))
    ends = np.array(sorted(w["e"] for w in ctc))

    def word_gap(g0, g1):
        e = ends[ends <= g0 * FRAME + 0.15]
        s_ = starts[starts >= g1 * FRAME - 0.15]
        return (s_[0] if len(s_) else g1 * FRAME) - (e[-1] if len(e) else g0 * FRAME)
    for a, b in units:
        out[a:b] = True
    # silence before the first and after the last unit
    if units:
        a0 = units[0][0]
        out[a0 - quiet_run(db, stop, a0 - 1, -1, T(lead)): a0] = True
        b1 = units[-1][1]
        out[b1: b1 + quiet_run(db, stop, b1, 1, T(tail))] = True
    for (a1, b1), (a2, b2) in zip(units, units[1:]):
        g0, g1 = b1, a2  # the gap between sound edges
        cut_between = bool((sp[g0:g1] & ~K[g0:g1]).any()) or (g1 - g0) * FRAME > NATURAL_MAX
        has_sound = bool(br[g0:g1].any())
        if not cut_between and (g1 - g0) <= T(cap):
            out[g0:g1] = True  # a short natural pause stays whole
            if has_sound and word_gap(g0, g1) > BREATH_GAP:
                out[g0:g1] &= ~br[g0:g1]  # ... except a breath in it, if the words are far enough apart
                rep["breaths_removed"] += 1
            rep["natural_whole"] += 1
            continue
        if cut_between:
            rep["joins"] += 1
            t, l = T(tail), T(lead)
        else:
            rep["natural_cut"] += 1
            rep["breaths_removed"] += int(has_sound)
            t = T(target) // 2 + T(target) % 2
            l = T(target) // 2
        # silence next to each word, never past a breath or other sound (that goes with the cut)
        t_ok = quiet_run(db, stop, g0, 1, t)
        l_ok = quiet_run(db, stop, g1 - 1, -1, l)
        if not cut_between and t_ok + l_ok < T(target):
            # one side has a breath right at the word: give the other side the rest
            t_ok = quiet_run(db, stop, g0, 1, T(target) - l_ok)
            l_ok = quiet_run(db, stop, g1 - 1, -1, T(target) - t_ok)
        out[g0: g0 + t_ok] = True
        out[g1 - l_ok: g1] = True
    out |= P
    # minimum piece length: a short piece that doesn't hold most of a word is a stub of a cut word
    # (the reference editor drops those); one that does grows into the silence around it
    for a, b in runs(out):
        if (b - a) * FRAME >= min_piece or P[a:b].any():
            continue
        piece = [[a * FRAME, b * FRAME]]
        has_word = any(kept_frac(piece, w["s"], w["e"]) >= 0.3 for w in ctc if w["e"] > piece[0][0] and w["s"] < piece[0][1]) \
            or any(kept_frac(piece, w["s"], w["e"]) >= 0.5 for w in missed if w["e"] > piece[0][0] and w["s"] < piece[0][1])
        if not has_word:
            out[a:b] = False
            rep["dropped_pieces"] += 1
            continue
        need = T(min_piece) - (b - a)
        back = quiet_run(db, stop, a - 1, -1, need // 2 + need % 2)
        fwd = quiet_run(db, stop, b, 1, need - back)
        back += quiet_run(db, stop, a - 1 - back, -1, need - back - fwd)
        out[a - back: a] = True
        out[b: b + fwd] = True
    new = [[a * FRAME, b * FRAME] for a, b in runs(out)]
    if log:
        log(f"style: {len(units)} speech units, {rep}")
    return new, rep


def snap(keep, fps=24):
    """Round edges to video frames; drop what rounds to nothing."""
    out = []
    for s, e in keep:
        s2, e2 = round(s * fps) / fps, round(e * fps) / fps
        if e2 > s2:
            if out and s2 <= out[-1][1]:
                out[-1][1] = max(out[-1][1], e2)
            else:
                out.append([s2, e2])
    return out


def kept_frac(keep, s, e):
    if e <= s:
        return 0.0
    return sum(max(0.0, min(e, b) - max(s, a)) for a, b in keep) / (e - s)


def guard(before, after, ctc, pad=0.03, db=None, wsp=None):
    """No word lost: every word the content keep had (literal model, and whisper where the audio is
    loud) must still be in. Returns the keep list with any lost word put back (a little room each side)."""
    words = list(ctc) + (loud_words(db, wsp, ctc=ctc) if db is not None else [])
    lost = [[w["s"] - pad, w["e"] + pad] for w in words
            if kept_frac(before, w["s"], w["e"]) >= 0.5 and kept_frac(after, w["s"], w["e"]) < 0.5]
    out = []
    for s, e in sorted(after + lost):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out

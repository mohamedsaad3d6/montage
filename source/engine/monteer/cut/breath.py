"""Stage 7d: breaths at the cuts (general rules, every episode).

The reference editor's review of an earlier cut: any breath left at a join, or a breath start / end at the edge,
tires the viewer; every word should hand over cleanly to the next. Three rules, applied after the
pause rules (style.py):
  R1 never start or end a piece inside a breath: a cut that would land in a breath moves into the
     silence before it (end of a piece) or after it (start of a piece);
  R2 a breathy tail joined to a word (the exhale as a phrase ends) or a breath straight into a word
     is cut where the breath starts / ends, with a slightly longer audio fade (FADE_SOFT) there;
  R3 an audible breath in a pause inside a piece is cut out, keeping the silence around it.

Word sound vs breath comes from the episode's own audio (10 ms frames):
  word sound = inside a literal-model (CTC) word, or louder than LOUD_DB, or above WORD_DB and called
               speech by a small classifier; a short (<= ATTACHED_MAX) breath-like sound joined straight
               onto a word is the word's own aspiration (final «ه», a released consonant);
  breath     = above BREATH_DB, not word sound, called breath by the classifier, at least BREATH_MIN.
The classifier (logistic regression on level-free features: voicing, spectral shape) is trained on
each episode by itself, from its clear cases at the same loudness (-55 to -30 dB): breaths standing
apart from the words (style.breath_mask) against frames inside CTC words. On reference episode B it got 80-96 % of
breaths and 89-92 % of soft speech right on the half of the episode it wasn't trained on.
"""
import numpy as np
from scipy.io import wavfile

from . import style
FRAME = 0.01
FPS = 24
WORD_DB = -50.0
LOUD_DB = -32.0      # louder than this is speech (breaths peak around -41 dB; a loud «ش» / «ت» looks breath-like)
BREATH_DB = -58.0
BREATH_MIN = 5       # frames
ATTACHED_MAX = 6     # frames: a breath-like sound this short joined onto a word is part of the word
HOLE = 3             # frames: gaps this short inside word sound are part of it
AUDIBLE_DB = -50.0   # a breath louder than this is audible (speech is around -20 dB)
INSIDE_MIN = 5       # frames: an audible breath this long in a pause inside a piece is cut out (R3)
SEARCH = 2.0         # s: how far into a piece to look for its last / first word sound
FADE_SOFT = 0.025    # s: audio fade at an R2 cut (a hard 10 ms fade right at a word can click)
# Cuts sit on video frames (1/24 s). When a breath starts less than a frame after the word, the frame
# boundary leaves a sliver of breath: the audio fade then ends exactly where the breath starts ("at"),
# and the sliver plays as silence (pauses in this audio are digital silence anyway).


# --- features and classifier ------------------------------------------------------------------------
def features(wav):
    """db (RMS level), voicing (autocorrelation peak at 70-400 Hz), spectral centroid, flatness and the
    share of energy in 8 bands (100 Hz - 8 kHz), per 10 ms frame."""
    sr, x = wavfile.read(str(wav))
    x = x.astype(np.float32) / 32768.0
    if x.ndim == 2:
        x = x.mean(axis=1)
    hop, win = int(sr * FRAME), int(sr * 0.032)
    n = len(x) // hop
    pad = np.concatenate([np.zeros(win // 2, np.float32), x, np.zeros(win, np.float32)])
    idx = np.arange(win)[None, :] + (np.arange(n) * hop)[:, None]
    db, voi, cen, flat = (np.empty(n, np.float32) for _ in range(4))
    bands = np.empty((n, 8), np.float32)
    w = np.hanning(win).astype(np.float32)
    freqs = np.fft.rfftfreq(1024, 1 / sr)
    lo, hi = int(sr / 400), int(sr / 70)
    edges = np.searchsorted(freqs, np.geomspace(100, 8000, 9))
    for c in range(0, n, 20000):
        f = pad[idx[c:c + 20000]]
        f = f - f.mean(axis=1, keepdims=True)
        mid = x[np.minimum((np.arange(c, min(n, c + 20000)) * hop)[:, None] + np.arange(hop)[None, :], len(x) - 1)]
        db[c:c + len(f)] = 20 * np.log10(np.sqrt((mid ** 2).mean(axis=1)) + 1e-6)
        P = np.abs(np.fft.rfft(f * w, 1024, axis=1)) ** 2 + 1e-12
        cen[c:c + len(f)] = (P * freqs).sum(axis=1) / P.sum(axis=1)
        band = P[:, 4:480]  # ~60 Hz - 7.5 kHz
        flat[c:c + len(f)] = np.exp(np.log(band).mean(axis=1)) / band.mean(axis=1)
        be = np.stack([P[:, edges[i]:edges[i + 1]].sum(axis=1) for i in range(8)], axis=1)
        bands[c:c + len(f)] = 10 * np.log10(be / be.sum(axis=1, keepdims=True))
        ac = np.fft.irfft(np.abs(np.fft.rfft(f, 2048, axis=1)) ** 2, axis=1)[:, :hi + 1]
        voi[c:c + len(f)] = ac[:, lo:hi + 1].max(axis=1) / (ac[:, 0] + 1e-9)
    return {"db": db, "voi": voi, "cen": cen, "flat": flat, "bands": bands}


def _design(F):
    def sm(x):  # 50 ms context
        k = np.ones(5) / 5
        return np.convolve(x, k, mode="same") if x.ndim == 1 else np.stack([np.convolve(c, k, mode="same") for c in x.T], 1)
    X = [F["voi"], sm(F["voi"]), np.log(F["cen"] + 1), np.log(F["flat"] + 1e-4), sm(np.log(F["flat"] + 1e-4))]
    return np.column_stack(X + [F["bands"], sm(F["bands"])]).astype(np.float64)


def _fit(X, y, l2=1e-2, it=600):
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd
    w, b = np.zeros(Z.shape[1]), 0.0
    pw = len(y) / (2 * np.bincount(y.astype(int)))  # balance the classes
    sw = np.where(y == 1, pw[1], pw[0])
    for _ in range(it):
        p = 1 / (1 + np.exp(-(Z @ w + b)))
        g = (p - y) * sw
        w -= 0.5 * (Z.T @ g / len(y) + l2 * w)
        b -= 0.5 * g.mean()
    return mu, sd, w, b


def _predict(model, X):
    mu, sd, w, b = model
    return 1 / (1 + np.exp(-(((X - mu) / sd) @ w + b)))


def train_labels(F, ctc):
    """Clear examples at the same loudness: breaths standing apart from the words, and frames inside words."""
    db = F["db"]
    inw = np.zeros(len(db), bool)
    for w in ctc:
        inw[int(w["s"] / FRAME):int(np.ceil(w["e"] / FRAME))] = True
    sp = style.speech_mask(db, ctc)
    br = style.breath_mask(db, sp)
    quiet = (db > -55) & (db < -30)
    return np.where(br & quiet)[0], np.where(inw & quiet)[0]


def breath_prob(F, ctc, check=False):
    X = _design(F)
    ib, isp = train_labels(F, ctc)
    acc = None
    if check:  # train on one half of the episode, test on the other, both ways
        half = len(F["db"]) // 2
        acc = []
        for tr in (lambda i: i < half, lambda i: i >= half):
            tb, ts = ib[tr(ib)], isp[tr(isp)]
            m = _fit(np.vstack([X[tb], X[ts]]), np.r_[np.ones(len(tb)), np.zeros(len(ts))])
            pb, ps = _predict(m, X[ib[~tr(ib)]]), _predict(m, X[isp[~tr(isp)]])
            acc.append((float((pb > .5).mean()), float((ps < .5).mean())))
    m = _fit(np.vstack([X[ib], X[isp]]), np.r_[np.ones(len(ib)), np.zeros(len(isp))])
    return _predict(m, X).astype(np.float32), acc


# --- masks ---------------------------------------------------------------------------------------------
def runs(m):
    d = np.diff(np.concatenate([[0], m.astype(np.int8), [0]]))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def close_holes(m, k):
    m = m.copy()
    r = runs(m)
    for (a1, b1), (a2, b2) in zip(r, r[1:]):
        if a2 - b1 <= k:
            m[b1:a2] = True
    return m


def masks(db, ctc, p):
    """W word sound, B breath, O other sound (clicks, lip noise, gate tails), per 10 ms frame."""
    n = len(db)
    inw = np.zeros(n, bool)
    for w in ctc:
        inw[int(w["s"] / FRAME):int(np.ceil(w["e"] / FRAME))] = True
    W = inw | ((db > WORD_DB) & (p < 0.5)) | (db > LOUD_DB)
    W = close_holes(W, HOLE)
    for a, b in runs(W):  # tiny islands of "speech" that touch no word: clicks
        if b - a < 5 and not inw[a:b].any():
            W[a:b] = False
    B = (db > BREATH_DB) & ~W & (p >= 0.5)
    B = close_holes(B, 2) & ~W
    for a, b in runs(B):
        if b - a < BREATH_MIN:
            B[a:b] = False
    for a, b in runs(B):  # a short breath-like sound joined straight onto a word belongs to the word
        attached = (a > 0 and W[a - 1]) or (b < n and W[b])
        if attached and b - a <= ATTACHED_MAX:
            B[a:b] = False
            W[a:b] = True
    O = (db > BREATH_DB) & ~W & ~B
    return W, B, O


def prepare(wav, ctc, cache_dir=None, log=None):
    """Features, breath probability and masks for one episode's audio (cached in cache_dir)."""
    F = p = None
    if cache_dir is not None:
        ff, pf = cache_dir / "breath_feat.npz", cache_dir / "breath_p.npy"
        if ff.exists() and pf.exists():
            z = np.load(ff)
            F = {k: z[k] for k in z.files}
            p = np.load(pf)
    if F is None:
        F = features(wav)
        p, acc = breath_prob(F, ctc, check=True)
        if log:
            log(f"breath detector: held-out breaths / speech right: {np.round(acc, 3).tolist()}")
        if cache_dir is not None:
            np.savez(cache_dir / "breath_feat.npz", **F)
            np.save(cache_dir / "breath_p.npy", p)
    W, B, O = masks(F["db"], ctc, p)
    return {"F": F, "p": p, "db": F["db"], "W": W, "B": B, "O": O}


# --- the rules ---------------------------------------------------------------------------------------------
def _audible(B, db, a, b, min_len=2):
    a, b = max(a, 0), min(b, len(B))
    return [(x + a, y + a) for x, y in runs(B[a:b]) if y - x >= min_len and db[x + a:y + a].max() > AUDIBLE_DB]


def _bounds(lo, hi):
    """Video-frame boundaries (s) inside [lo, hi]."""
    k0, k1 = int(np.ceil(lo * FPS - 1e-6)), int(np.floor(hi * FPS + 1e-6))
    return [k / FPS for k in range(k0, k1 + 1)]


def _end_at(word_end, target):
    """A piece end on a frame boundary: the latest one in [word_end, target] (silence / before the
    breath); if there is none, the first one after word_end (a sliver of breath stays, faded)."""
    b = _bounds(word_end, target)
    if b:
        return b[-1], False
    return int(np.ceil(word_end * FPS - 1e-6)) / FPS, True


def _start_at(target, word_start):
    b = _bounds(target, word_start)
    if b:
        return b[0], False
    return int(np.floor(word_start * FPS + 1e-6)) / FPS, True


def merge_keep(keep, tol=1e-6):
    out = []
    for s, e in sorted(keep):
        if out and s - out[-1][1] <= tol:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def clean(keep, M, ctc=(), min_piece=style.MIN_PIECE, log=None):
    """Apply R1-R3 to a keep list on video frames. Returns (keep, report); report["soft_fades"] lists the
    piece edges whose audio fades over FADE_SOFT and goes silent from / until "at" (render.py `fades`),
    report["edits"] every change (rule, side, times, the word next to it)."""
    W, B, db = M["W"], M["B"], M["db"]
    T = lambda s: int(round(s / FRAME))  # noqa: E731
    words = sorted(ctc, key=lambda w: w["s"])

    def word_near(t, side):
        if side == "end":
            c = [w for w in words if w["s"] < t + 0.05 and w["e"] > t - 0.6]
            return c[-1]["w"] if c else ""
        c = [w for w in words if w["e"] > t - 0.05 and w["s"] < t + 0.6]
        return c[0]["w"] if c else ""

    edits, soft = [], []
    # R3: audible breaths in pauses inside a piece
    out = []
    for s, e in merge_keep(keep):
        i0, i1 = T(s), T(e)
        cur = s
        r = runs(W[i0:i1])
        for (a1, b1), (a2, b2) in zip(r, r[1:]):
            g0, g1 = i0 + b1, i0 + a2
            for a, b in _audible(B, db, g0, g1, INSIDE_MIN):
                t0, sl0 = _end_at(g0 * FRAME, a * FRAME)
                t1, sl1 = _start_at(b * FRAME, g1 * FRAME)
                if t1 <= t0 or t0 - cur < min_piece or e - t1 < min_piece:
                    continue
                out.append([cur, t0])
                cur = t1
                edits.append({"rule": 3, "out": t0, "in": t1, "breath_s": [a * FRAME, b * FRAME],
                              "breath_db": float(db[a:b].max())})
                if sl0:
                    soft.append({"t": t0, "side": "out", "d": FADE_SOFT, "at": a * FRAME})
                if sl1:
                    soft.append({"t": t1, "side": "in", "d": FADE_SOFT, "at": b * FRAME})
        out.append([cur, e])
    keep = merge_keep(out)
    # R1 / R2 at every join
    for k in range(len(keep) - 1):
        (s1, e1), (s2, e2) = keep[k], keep[k + 1]
        # end of piece k
        lo = max(T(s1), T(e1) - int(SEARCH / FRAME))
        w = np.where(W[lo:T(e1)])[0]
        if len(w):
            sp = lo + w[-1] + 1
            for a, b in _audible(B, db, sp, T(e1) + 30):
                if a >= T(e1):
                    break
                attached = a - sp <= 2
                rule = 2 if attached else 1
                ne, sliver = _end_at(sp * FRAME, a * FRAME)
                fade_only = ne >= e1 - 1e-6  # the cut already sits on the first frame after the word
                if fade_only:
                    ne = e1
                elif ne - s1 < min(min_piece, e1 - s1):
                    break
                keep[k][1] = ne
                edits.append({"rule": rule, "side": "end", "old": e1, "new": ne, "word_sound_end": sp * FRAME,
                              "breath_s": [a * FRAME, b * FRAME], "breath_db": float(db[a:b].max()),
                              "word": word_near(sp * FRAME, "end"), "fade_only": fade_only})
                if rule == 2 or sliver or fade_only:  # the breath sliver up to the frame plays as silence
                    soft.append({"t": ne, "side": "out", "d": FADE_SOFT, "at": min(a * FRAME, ne)})
                break
        # start of piece k+1
        hi = min(T(e2), T(s2) + int(SEARCH / FRAME))
        w = np.where(W[T(s2):hi])[0]
        if len(w):
            sp = T(s2) + w[0]
            for a, b in reversed(_audible(B, db, T(s2) - 30, sp)):
                if b <= T(s2):
                    break
                attached = sp - b <= 2
                rule = 2 if attached else 1
                ns, sliver = _start_at(b * FRAME, sp * FRAME)
                fade_only = ns <= s2 + 1e-6
                if fade_only:
                    ns = s2
                elif e2 - ns < min(min_piece, e2 - s2):
                    break
                keep[k + 1][0] = ns
                edits.append({"rule": rule, "side": "start", "old": s2, "new": ns, "word_sound_start": sp * FRAME,
                              "breath_s": [a * FRAME, b * FRAME], "breath_db": float(db[a:b].max()),
                              "word": word_near(sp * FRAME, "start"), "fade_only": fade_only})
                if rule == 2 or sliver or fade_only:
                    soft.append({"t": ns, "side": "in", "d": FADE_SOFT, "at": max(b * FRAME, ns)})
                break
    keep = [p for p in keep if p[1] - p[0] > 1e-6]
    rep = {"R1": sum(1 for x in edits if x["rule"] == 1), "R2": sum(1 for x in edits if x["rule"] == 2),
           "fade_only": sum(1 for x in edits if x.get("fade_only")),
           "R3": sum(1 for x in edits if x["rule"] == 3), "edits": edits, "soft_fades": soft}
    if log:
        log(f"breath rules: R1 {rep['R1']} cuts moved out of a breath, R2 {rep['R2']} breathy tails / lead-ins cut, "
            f"R3 {rep['R3']} breaths cut out of pauses ({rep['fade_only']} of R1/R2 only silence a sliver up to the frame)")
    return keep, rep

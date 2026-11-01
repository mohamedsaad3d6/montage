"""Stage 7a: turn word keep/cut decisions + silences + breaths into a frame-accurate EDL.

All times are camera-timeline seconds. Every removed span carries a reason so the report
can count cuts and show why.
"""
import numpy as np

from .common import FPS
from .silence import quietest_point

PAD = 0.08          # audio kept on each side of a silence/breath cut (AutoCut-style padding)
WORD_PAD = 0.12     # extra room kept around a word at a take boundary
NONSPEECH_MAX = 1.0  # a non-silent gap without words longer than this inside a take is cut + flagged


def subtract(intervals, cuts):
    """intervals minus cuts; both are lists of [s, e]."""
    out = []
    cuts = sorted(cuts)
    for s, e in intervals:
        cur = s
        for cs, ce in cuts:
            if ce <= cur or cs >= e:
                continue
            if cs > cur:
                out.append([cur, cs])
            cur = max(cur, ce)
        if cur < e:
            out.append([cur, e])
    return out


def build_edl(words, decisions, silences, breaths, db, cam_covered, cam_dur, judge=None):
    """words: transcript words in camera time (with 'i'); decisions: from align.select_takes."""
    removed = []  # [s, e, reason, detail]
    keep_idx = [d["i"] for d in decisions if d["keep"]]

    # 1) take-level keep blocks: maximal runs of consecutive kept words
    blocks = []
    for i in keep_idx:
        if blocks and blocks[-1][-1] == i - 1:
            blocks[-1].append(i)
        else:
            blocks.append([i])
    spans = []
    for bi, b in enumerate(blocks):
        first, last = words[b[0]], words[b[-1]]
        prev_end = words[b[0] - 1]["e"] if b[0] > 0 else 0.0
        next_start = words[b[-1] + 1]["s"] if b[-1] + 1 < len(words) else cam_dur
        # cut points go on the quietest frame between the neighbouring (cut) word and this block
        s = quietest_point(db, max(prev_end, first["s"] - 0.6), first["s"], first["s"] - WORD_PAD)
        e = quietest_point(db, last["e"], min(next_start, last["e"] + 0.6), last["e"] + WORD_PAD)
        spans.append([min(s, first["s"] - 0.02), max(e, last["e"] + 0.02)])
    spans = merge(spans)

    # what fell between blocks, with the dominant reason of the cut words
    take_cuts = subtract([[0.0, cam_dur]], spans)
    for s, e in take_cuts:
        inside = [d for d in decisions if not d["keep"] and words[d["i"]]["s"] < e and words[d["i"]]["e"] > s]
        if inside:
            reasons = [d["reason"].split(":")[0] for d in inside]
            reason = max(set(reasons), key=reasons.count)
            detail = " ".join(words[d["i"]]["w"] for d in inside)
        else:
            reason, detail = "no speech", ""
        removed.append([s, e, reason, detail])

    # 2) silences (AutoCut equivalent) and breaths inside kept spans
    sil_cuts = [[s + PAD, (e if e is not None else cam_dur) - PAD] for s, e in silences]
    sil_cuts = [c for c in sil_cuts if c[1] - c[0] > 0.02]
    br_cuts = [[s + PAD * 0.6, e - PAD * 0.6] for s, e, _ in breaths]
    br_cuts = [c for c in br_cuts if c[1] - c[0] > 0.1]

    # 3) long non-silent gaps between consecutive kept words (noise, laughter, untranscribed speech)
    flagged = []
    kept_words = [words[i] for i in keep_idx]
    for a, b in zip(kept_words, kept_words[1:]):
        if b["i"] == a["i"] + 1 and b["s"] - a["e"] > NONSPEECH_MAX:
            g = [a["e"] + PAD, b["s"] - PAD]
            sil_overlap = sum(max(0, min(g[1], c[1]) - max(g[0], c[0])) for c in sil_cuts)
            if sil_overlap < 0.5 * (g[1] - g[0]):
                flagged.append(g)
    # each gap gets a second ASR pass (gaps.judge_all): cut noise and missed retakes, keep speech
    verdicts = judge(flagged) if judge else [{"src": g[0], "src_end": g[1], "verdict": "cut",
                                              "why": "non-speech gap", "text": ""} for g in flagged]
    gap_noise = [[v["src"], v["src_end"]] for v in verdicts if v["verdict"] == "cut" and v["why"] != "retake"]
    gap_retake = [[v["src"], v["src_end"]] for v in verdicts if v["why"] == "retake"]
    gap_retake += [[v["cut_from"] - 0.04, v["src"]] for v in verdicts if v.get("cut_from") is not None]

    # 4) camera time with no external audio
    no_ext = subtract([[0.0, cam_dur]], cam_covered)

    keep = spans
    for cuts, why in ((sil_cuts, "silence"), (br_cuts, "breath"),
                      (gap_noise, "non-speech gap"),
                      (gap_retake, "retake"), (no_ext, "no external audio")):
        before = keep
        keep = subtract(keep, cuts)
        for s, e in cuts:
            gone = sum(max(0, min(e, ke) - max(s, ks)) for ks, ke in before)
            if gone > 0.02:
                removed.append([s, e, why, ""])

    keep = snap_frames(keep)
    return keep, sorted(removed), verdicts


def merge(iv, gap=0.0):
    out = []
    for s, e in sorted(iv):
        if out and s <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def snap_frames(keep, min_frames=3):
    """Snap to frame boundaries so audio and video cut on the same frame; merge 1-2 frame gaps,
    drop slivers shorter than `min_frames`."""
    out = []
    for s, e in keep:
        fs, fe = int(round(s * FPS)), int(round(e * FPS))
        if out and fs - out[-1][1] <= 2:
            out[-1][1] = max(out[-1][1], fe)
        elif fe - fs >= 1:
            out.append([fs, fe])
    out = [[s, e] for s, e in out if e - s >= min_frames]
    return [[s / FPS, e / FPS] for s, e in out]


def map_to_output(keep):
    """Source time -> output time for every kept span (for report timecodes)."""
    starts = np.cumsum([0] + [e - s for s, e in keep])
    def f(t):
        for (s, e), o in zip(keep, starts):
            if s <= t <= e:
                return o + (t - s)
            if t < s:
                return o
        return starts[-1]
    return f

"""Measurement only: what the listener hears at every join (cut) of an edit, in raw-audio terms.

For each join between kept piece P (ends at raw a) and the next piece Q (starts at raw b):
  tail   = kept audio after the last word sound of P, up to the cut;
  head   = kept audio before the first word sound of Q, from the cut;
  gap    = tail + head: the pause heard across the join;
  breath / other sound inside tail and head (ms, loudest dB), and whether it touches the cut;
  clipped = word sound that runs on past the cut (cut away), on either side.
Word sound: frames inside a literal-model word, frames above -50 dB that the breath classifier
calls speech (breathclf), and any frame above -32 dB; small holes closed. Breath: frames between
-58 and -32 dB that it calls breath, runs of 50 ms or more, not a short (<= 60 ms) sound joined
straight onto a word (that is the word's own aspiration). Silence: everything else (the raw is noise-gated: -120 dB in pauses).

Both edits come from the same raw audio (the reference editor's export is that audio with hard cuts, no
processing), so measuring in raw time is fair to both.

    <core python> -m monteer.learn.joins.joins --work <episode work> --edits <episode output> --editor <compare dir> --out <joins dir>

--work holds sync_ext16.wav, sync_ext48.wav and asr_ext_ctc.json; --edits holds edl_v4.json (and edl_v5.json if
made); --editor is the editor_compare folder (editor_keep.json, editor_holes.json); --out holds breath_p.npy
(breathclf) and receives joins.json and joins_table.csv.
"""
import argparse
import csv
import json
import os
from pathlib import Path

import numpy as np

from ...cut.common import load_json, tc
from . import feat
from .autocut_fit import autocut, envelope, smooth_db

FR = 0.01
WORD_DB = -50.0
LOUD_DB = -32.0  # louder than this is speech (breaths here peak around -41 dB; loud «ش» / «ت» look breath-like)
ATTACHED_MAX = 6  # frames
BREATH_DB = -58.0
BREATH_MIN = 5   # frames
HOLE = 3         # frames: gaps this short inside word sound are part of it
SEARCH = 2.0     # s: how far into a piece to look for its last / first word sound


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


def masks(F, ctc, p):
    """Word sound / breath / other sound: the engine's own detector (monteer.cut.breath), so the
    measurement and the cutting rules see the same thing."""
    from ...cut import breath
    return breath.masks(F["db"], ctc, p)


def merge_keep(keep, tol=0.02):
    out = []
    for s, e in sorted(keep):
        if out and s - out[-1][1] <= tol:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def side(W, B, O, db, lo, hi, direction):
    """Kept audio from the cut (lo or hi, by direction) back to the nearest word sound.
    direction=-1: tail of the piece before the cut, region [lo, hi) with the cut at hi.
    direction=+1: head of the piece after the cut, cut at lo."""
    i0, i1 = int(round(lo / FR)), int(round(hi / FR))
    seg = W[i0:i1]
    if direction == -1:
        idx = np.where(seg)[0]
        sp = i0 + idx[-1] + 1 if len(idx) else i0
        reg = slice(sp, i1)
    else:
        idx = np.where(seg)[0]
        sp = i0 + idx[0] if len(idx) else i1
        reg = slice(i0, sp)
    n = reg.stop - reg.start
    b, o = B[reg], O[reg]
    touch = False
    if n > 0:
        edge = slice(reg.stop - 3, reg.stop) if direction == -1 else slice(reg.start, reg.start + 3)
        touch = bool(B[edge].any())
    # each breath run: joined to the word (exhale as the phrase ends / breath into the word), at the cut,
    # and whether the breath goes on past the cut (the cut went through it, leaving a sliver)
    word_end = reg.start if direction == -1 else reg.stop
    cut = reg.stop if direction == -1 else reg.start
    br_runs = []
    for a, e in runs(b):
        a, e = a + reg.start, e + reg.start
        attached = (a - word_end <= 2) if direction == -1 else (word_end - e <= 2)
        at_cut = (cut - e <= 2) if direction == -1 else (a - cut <= 2)
        past = bool(B[cut]) if direction == -1 else bool(B[cut - 1])
        br_runs.append({"ms": int(e - a) * 10, "db": float(db[a:e].max()), "attached": bool(attached),
                        "at_cut": bool(at_cut), "cut_through": bool(at_cut and past)})
    return {"ms": n * 10, "breath_ms": int(b.sum()) * 10, "other_ms": int(o.sum()) * 10,
            "breath_db": float(db[reg][b].max()) if b.any() else None,
            "other_db": float(db[reg][o].max()) if o.any() else None,
            "breath_at_cut": touch, "found_word": len(idx) > 0, "breaths": br_runs}


def clipped(W, db, t, direction):
    """Word sound cut away right at the cut t: how long the word sound runs on past the cut (ms) and
    how loud it is, when the kept side right at the cut is word sound too."""
    i = int(round(t / FR))
    kept = W[i - 1] if direction == -1 else W[i]
    if not kept:
        return 0, None
    k, n = (i, 0) if direction == -1 else (i - 1, 0)
    step = 1 if direction == -1 else -1
    while 0 <= k < len(W) and W[k] and n < 50:
        k += step
        n += 1
    if n == 0:
        return 0, None
    reg = slice(i, i + n) if direction == -1 else slice(i - n, i)
    return n * 10, float(db[reg].max())


def measure(keep, F, W, B, O, slots=()):
    db = F["db"]
    keep = merge_keep(keep)
    out = []
    t_out = 0.0
    for k in range(len(keep) - 1):
        (s1, e1), (s2, e2) = keep[k], keep[k + 1]
        t_out += e1 - s1
        tail = side(W, B, O, db, max(s1, e1 - SEARCH), e1, -1)
        head = side(W, B, O, db, s2, min(e2, s2 + SEARCH), +1)
        ct, ct_db = clipped(W, db, e1, -1)
        ch, ch_db = clipped(W, db, s2, +1)
        out.append({"k": k, "out_time": t_out, "raw_a": e1, "raw_b": s2, "removed_s": s2 - e1,
                    "slot": any(abs(e1 - x) < 0.1 for x in slots),
                    "tail": tail, "head": head, "gap_ms": tail["ms"] + head["ms"],
                    "clip_tail_ms": ct, "clip_tail_db": ct_db, "clip_head_ms": ch, "clip_head_db": ch_db})
    return out


def muted(edl):
    """Raw spans the render plays as silence: from a fade's "at" to the piece edge (monteer.cut.render fades)."""
    out = []
    for f in edl.get("fades", []):
        if "at" in f:
            a, b = (f["at"], f["t"]) if f["side"] == "out" else (f["t"], f["at"])
            if b > a:
                out.append((a, b))
    return out


def pauses_inside(keep, W):
    """Pauses between word sounds inside kept pieces (no cut in between), ms."""
    out = []
    for s, e in merge_keep(keep):
        r = runs(W[int(round(s / FR)):int(round(e / FR))])
        out += [(a2 - b1) * 10 for (a1, b1), (a2, b2) in zip(r, r[1:])]
    return out


def pair(J1, J2, tol=0.3):
    """Same join in two edits: the removed spans overlap, or both edges within tol."""
    out = {}
    for i, j in enumerate(J1):
        best = None
        for m, h in enumerate(J2):
            ov = min(j["raw_b"], h["raw_b"]) - max(j["raw_a"], h["raw_a"])
            near = abs(j["raw_a"] - h["raw_a"]) < tol and abs(j["raw_b"] - h["raw_b"]) < tol
            if ov > 0 or near:
                d = abs(j["raw_a"] - h["raw_a"]) + abs(j["raw_b"] - h["raw_b"])
                if best is None or d < best[0]:
                    best = (d, m)
        if best:
            out[i] = best[1]
    return out


def dist(gaps):
    g = np.array(gaps)
    bins = [0, 100, 200, 300, 400, 500, 1000, 10 ** 9]
    names = ["<0.1", "0.1-0.2", "0.2-0.3", "0.3-0.4", "0.4-0.5", "0.5-1.0", ">1.0"]
    h = np.histogram(g, bins)[0]
    return {"n": len(g), "p10": float(np.percentile(g, 10)), "median": float(np.median(g)),
            "p90": float(np.percentile(g, 90)), "iqr": float(np.percentile(g, 75) - np.percentile(g, 25)),
            "sd": float(g.std()), "bins": dict(zip(names, h.tolist()))}


AUDIBLE_DB = -50.0


def kind_of(r):
    """What a breath run left at a join sounds like (None: too faint or short to matter)."""
    if r["db"] <= AUDIBLE_DB or r["ms"] < 20:
        return None
    if r["cut_through"]:
        return "breath cut through"      # the cut lands inside a breath: a sliver of it on this side
    if not r["attached"] and r["ms"] >= 50:
        return "separate breath kept"    # a breath on its own in the pause
    if r["attached"]:
        return "breath tail on word"     # the exhale / breathy decay joined to the word
    return None


def summary(J, name):
    J = [j for j in J if not j["slot"]]
    g = [j["gap_ms"] for j in J]
    br = [j for j in J if j["tail"]["breath_ms"] or j["head"]["breath_ms"]]
    br_aud = [j for j in br if max(x for x in (j["tail"]["breath_db"], j["head"]["breath_db"]) if x is not None) > -50]
    br_cut = [j for j in J if j["tail"]["breath_at_cut"] or j["head"]["breath_at_cut"]]
    oth = [j for j in J if max(j["tail"]["other_ms"], j["head"]["other_ms"]) >= 50]
    clip = [j for j in J if j["clip_tail_ms"] >= 30 or j["clip_head_ms"] >= 30]
    clip_loud = [j for j in J if (j["clip_tail_ms"] >= 30 and j["clip_tail_db"] > -40) or
                 (j["clip_head_ms"] >= 30 and j["clip_head_db"] > -40)]
    tight = [j for j in J if j["tail"]["ms"] < 30 or j["head"]["ms"] < 30]
    kinds = {k: [j for j in J if any(kind_of(r) == k for x in ("tail", "head") for r in j[x]["breaths"])]
             for k in ("separate breath kept", "breath cut through", "breath tail on word")}
    long_ = [j for j in J if j["gap_ms"] > 400]
    s = {"edit": name, "joins": len(J), "gap": dist(g),
         "tail": dist([j["tail"]["ms"] for j in J]), "head": dist([j["head"]["ms"] for j in J]),
         "breath_left": len(br), "breath_left_louder_than_-50dB": len(br_aud), "breath_cut_through": len(br_cut),
         "other_sound_50ms": len(oth), "word_clipped_30ms": len(clip), "word_clipped_loud": len(clip_loud),
         "edge_on_word_sound_<30ms_silence": len(tight), "gap_over_0.4s": len(long_)}
    s.update({k: len(v) for k, v in kinds.items()})
    return s


def main():
    ap = argparse.ArgumentParser(description="What the listener hears at every join of our v4/v5 and of the editor's cut.")
    ap.add_argument("--work", required=True, help="episode work folder (sync_ext16.wav, sync_ext48.wav, asr_ext_ctc.json)")
    ap.add_argument("--edits", required=True, help="episode output folder with edl_v4.json (edl_v5.json optional)")
    ap.add_argument("--editor", required=True, help="editor_compare folder with editor_keep.json and editor_holes.json")
    ap.add_argument("--out", required=True, help="joins folder (breath_p.npy, feat.npz); results go here")
    opt = ap.parse_args()
    WORK, OUT, D, E = Path(opt.work), Path(opt.edits), Path(opt.out), Path(opt.editor)
    F = feat.load(WORK / "sync_ext16.wav", D / "feat.npz")
    p = np.load(D / "breath_p.npy")
    ctc = load_json(WORK / "asr_ext_ctc.json")["words"]
    W, B, O = masks(F, ctc, p)
    v4 = load_json(OUT / "edl_v4.json")
    editor = load_json(E / "editor_keep.json")
    holes = load_json(E / "editor_holes.json")
    his = [[s["src_audio_s"], s["src_audio_e"]] for s in editor]
    his_slots = [max((s for s in editor if s["ed_e"] <= h["ed_s"] + 1e-6), key=lambda s: s["ed_e"])["src_audio_e"] for h in holes]
    edits = {"v4": (v4["keep"], [i["after"] for i in v4["inserts"]])}
    if os.path.exists(OUT / "edl_v5.json"):
        v5 = load_json(OUT / "edl_v5.json")
        edits["v5"] = (v5["keep"], [i["after"] for i in v5["inserts"]], muted(v5))
    edits["editor"] = (his, his_slots)
    # AutoCut on the editor's content: the editor's stated settings (-32 dB, 50 ms margins, talks over 100 ms) and the
    # margins the editor's cut actually matches (about 100 ms, autocut_fit)
    rms, _ = envelope(WORK / "sync_ext48.wav")
    lvl = smooth_db(rms, 10)
    content = merge_keep(his, 0.6)  # the editor's content: everything between the editor's pieces closer than 0.6 s is one take
    for name, m, ms in (("autocut_50ms", 0.05, 0.0), ("autocut_100ms", 0.10, 0.2)):
        sim = autocut(lvl, -32, m, m, 0.1, ms)
        inter = []
        for s, e in sim:
            for cs, ce in content:
                a, b = max(s, cs), min(e, ce)
                if b - a > 0.05:
                    inter.append([a, b])
        edits[name] = (inter, his_slots)
    res = {"joins": {}, "summary": {}, "pauses_inside": {}}
    for name, (keep, slots, *mu) in edits.items():
        if mu and mu[0]:  # audio the render silences (a breath sliver up to the frame boundary)
            Wm, Bm, Om = W.copy(), B.copy(), O.copy()
            for a, b in mu[0]:
                for m in (Wm, Bm, Om):
                    m[int(round(a / FR)):int(round(b / FR))] = False
            J = measure(keep, F, Wm, Bm, Om, slots)
        else:
            J = measure(keep, F, W, B, O, slots)
        res["joins"][name] = J
        res["summary"][name] = summary(J, name)
        pi = pauses_inside(keep, W)
        res["pauses_inside"][name] = dist(pi) if pi else None
        res["summary"][name]["raw_kept_s"] = sum(e - s for s, e in merge_keep(keep))
    pr = pair(res["joins"]["v4"], res["joins"]["editor"])
    res["pairs_v4_editor"] = {str(k): v for k, v in pr.items()}
    json.dump(res, open(D / "joins.json", "w"), indent=0, default=float)
    for name, s in res["summary"].items():
        print(json.dumps(s, default=float))
        print("   pauses inside pieces:", res["pauses_inside"][name])
    # per-join table, v4 with the editor's matching join
    Jv, Jr = res["joins"]["v4"], res["joins"]["editor"]
    with open(D / "joins_table.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(["v4_time", "his_time", "raw_cut", "v4_tail_ms", "v4_head_ms", "v4_gap_ms", "v4_breath", "v4_clip",
                     "his_tail_ms", "his_head_ms", "his_gap_ms", "his_breath", "his_clip"])
        for i, j in enumerate(Jv):
            h = Jr[pr[i]] if i in pr else None

            def br(x):
                parts = [f"{s_}:{x[s_]['breath_ms']}ms@{x[s_]['breath_db']:.0f}dB" for s_ in ("tail", "head") if x[s_]["breath_ms"]]
                return " ".join(parts)

            def cl(x):
                return " ".join(p_ for p_ in (f"tail {x['clip_tail_ms']}ms" if x["clip_tail_ms"] else "",
                                              f"head {x['clip_head_ms']}ms" if x["clip_head_ms"] else "") if p_)
            wr.writerow([tc(j["out_time"]), tc(h["out_time"]) if h else "", tc(j["raw_a"]), j["tail"]["ms"], j["head"]["ms"],
                         j["gap_ms"], br(j), cl(j)] + ([h["tail"]["ms"], h["head"]["ms"], h["gap_ms"], br(h), cl(h)] if h else []))


if __name__ == "__main__":
    main()

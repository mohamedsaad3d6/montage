"""Compare the reference editor's cut (editor_keep.json, made by refine_video) with our v2 (edl_v2.json) on the raw
timeline: overlap, words each one kept, difference regions with their words, cut points, padding, pauses, breaths and
leftover repeats.

    <core python> -m monteer.learn.editor_compare.analyze --work <episode work> --edits <episode output> --out <compare dir>

--work holds asr_ext_ctc.json, asr_ext_large-v3.json, sync_ext16.wav and script.docx; --edits holds edl_v1.json and
edl_v2.json; --out holds editor_keep.json, editor16.wav and v2a16.wav and receives analysis.json + diffs.txt.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from ...cut.common import load_json, tc
from ..episode import bind, frame_db

RES = 0.01
DUR = 1921.0   # raw recording length (s) of reference episode B; --dur for another episode


def segs_from_keep(keep):
    out, t = [], 0.0
    for a, b in keep:
        out.append({"ed_s": t, "ed_e": t + b - a, "src_s": a, "src_e": b})
        t += b - a
    return out


def mask(segs):
    m = np.zeros(int(DUR / RES) + 2, bool)
    for s in segs:
        m[int(round(s["src_s"] / RES)): int(round(s["src_e"] / RES))] = True
    return m


def runs(m):
    d = np.diff(np.concatenate([[0], m.astype(np.int8), [0]]))
    return list(zip(np.where(d == 1)[0] * RES, np.where(d == -1)[0] * RES))


def to_out(segs, t):
    for s in segs:
        if s["src_s"] - 1e-6 <= t <= s["src_e"] + 1e-6:
            return s["ed_s"] + t - s["src_s"]
    # nearest following kept point
    nxt = [s for s in segs if s["src_s"] > t]
    return min(nxt, key=lambda s: s["src_s"])["ed_s"] if nxt else None


def kept_frac(segs, s, e):
    if e <= s:
        return 0.0
    return sum(max(0.0, min(e, g["src_e"]) - max(s, g["src_s"])) for g in segs) / (e - s)


def virtual(segs, words, gone=0.15):
    out = []
    for w in words:
        f = kept_frac(segs, w["s"], w["e"])
        if f < gone:
            continue
        mid = (w["s"] + w["e"]) / 2
        g = next((g for g in segs if g["src_s"] <= mid <= g["src_e"]), None) or \
            next(g for g in segs if g["src_s"] < w["e"] and g["src_e"] > w["s"])
        o = g["ed_s"] + max(0.0, w["s"] - g["src_s"])
        out.append(dict(w, src_s=w["s"], src_e=w["e"], s=o, e=o + min(w["e"], g["src_e"]) - max(w["s"], g["src_s"]),
                        frac=f, seg=segs.index(g)))
    return out


def stats(x):
    x = np.asarray(x, float)
    if len(x) == 0:
        return {"n": 0}
    return {"n": int(len(x)), "min": round(float(x.min()), 3), "p10": round(float(np.percentile(x, 10)), 3),
            "median": round(float(np.median(x)), 3), "p90": round(float(np.percentile(x, 90)), 3),
            "max": round(float(x.max()), 3), "mean": round(float(x.mean()), 3)}


def text_in(words, s, e, minfrac=0.5):
    return " ".join(w["w"] for w in words
                    if min(e, w["e"]) - max(s, w["s"]) >= minfrac * max(w["e"] - w["s"], 0.02))


def editor_segs(path):
    """The editor's kept segments, with src_s/src_e on the editor's audio timing."""
    return [dict(s, src_s=s["src_audio_s"], src_e=s["src_audio_e"]) for s in json.load(open(path))]


def main():
    global DUR
    ap = argparse.ArgumentParser(description="Compare the reference editor's cut with our v2 on the raw timeline.")
    ap.add_argument("--work", required=True, help="episode work folder (transcripts, sync_ext16.wav, script.docx)")
    ap.add_argument("--edits", required=True, help="episode output folder with edl_v1.json / edl_v2.json")
    ap.add_argument("--out", required=True, help="comparison folder (editor_keep.json, editor16.wav, v2a16.wav); results go here")
    ap.add_argument("--script", help="script .docx (default <work>/script.docx)")
    ap.add_argument("--dur", type=float, default=DUR, help="raw recording length in seconds")
    opt = ap.parse_args()
    DUR = opt.dur
    WORK = bind(opt.work, opt.edits, opt.script)
    OUT, D = Path(opt.edits), Path(opt.out)
    from ...cut import script_text, selfcheck
    # speech is judged on what is heard: the editor's audio timing (it drifts up to ~0.1 s from the raw's picture)
    R = editor_segs(D / "editor_keep.json")
    v2 = load_json(OUT / "edl_v2.json")
    V = segs_from_keep(v2["keep"])
    v1 = segs_from_keep(load_json(OUT / "edl_v1.json")["keep"])
    ctc = selfcheck.with_norm(load_json(WORK / "asr_ext_ctc.json")["words"])
    wsp = load_json(WORK / "asr_ext_large-v3.json")["words"]
    db = frame_db(WORK / "sync_ext16.wav")
    res = {}

    # ---- 1. totals and overlap -------------------------------------------------------------
    Rm, Vm = mask(R), mask(V)
    both = Rm & Vm
    res["totals"] = {"editor_kept_s": Rm.sum() * RES, "v2_kept_s": Vm.sum() * RES, "both_s": both.sum() * RES,
                     "editor_only_s": (Rm & ~Vm).sum() * RES, "v2_only_s": (Vm & ~Rm).sum() * RES,
                     "union_s": (Rm | Vm).sum() * RES,
                     "editor_segments": len(R), "v2_segments": len(V),
                     "editor_edit_s": R[-1]["ed_e"], "v2_edit_s": V[-1]["ed_e"]}
    # speech-only overlap (frames above -45 dB in the source)
    sp = np.zeros_like(Rm)
    sp[: len(db)] = db[: len(sp)] > -45
    res["totals"].update(speech_editor_s=(Rm & sp).sum() * RES, speech_v2_s=(Vm & sp).sum() * RES,
                         speech_both_s=(Rm & Vm & sp).sum() * RES)

    # ---- 2. words: who kept what -------------------------------------------------------------
    for name, ws in (("ctc", ctc), ("whisper", wsp)):
        fr = [(kept_frac(R, w["s"], w["e"]), kept_frac(V, w["s"], w["e"])) for w in ws]
        kr = [a >= 0.5 for a, _ in fr]
        kv = [b >= 0.5 for _, b in fr]
        res[f"words_{name}"] = {"n": len(ws), "both_keep": sum(a and b for a, b in zip(kr, kv)),
                                "both_cut": sum((not a) and (not b) for a, b in zip(kr, kv)),
                                "editor_only": sum(a and not b for a, b in zip(kr, kv)),
                                "v2_only": sum(b and not a for a, b in zip(kr, kv))}

    # ---- 3. difference regions with their words ---------------------------------------------
    def regions(m, bridge=0.25):
        rs = runs(m)
        merged = []
        for s, e in rs:
            if merged and s - merged[-1][1] < bridge:
                merged[-1][1] = e
            else:
                merged.append([s, e])
        return merged

    diffs = []
    for kind, m in (("editor_cut_v2_kept", Vm & ~Rm), ("v2_cut_editor_kept", Rm & ~Vm)):
        for s, e in regions(m):
            wc = text_in(ctc, s, e)
            ww = text_in(wsp, s, e)
            if e - s < 0.04:
                continue
            pk = float(db[int(s / RES): int(e / RES)].max()) if e - s > 0 else -120
            diffs.append({"kind": kind, "src_s": s, "src_e": e, "dur": e - s, "ctc": wc, "whisper": ww,
                          "peak_db": round(pk, 1),
                          "v2_t": to_out(V, s), "editor_t": to_out(R, s), "v1_t": to_out(v1, s)})
    res["diffs"] = diffs

    # ---- 4. cut points -----------------------------------------------------------------------
    def bounds(S):
        ins = [s["src_s"] for s in S]
        outs = [s["src_e"] for s in S]
        # a "cut" is a jump in the source between consecutive output segments
        cuts = [(S[i]["src_e"], S[i + 1]["src_s"]) for i in range(len(S) - 1)]
        return ins, outs, cuts

    ri, ro, rc = bounds(R)
    vi, vo, vc = bounds(V)

    def frac_near(a, b, tol):
        b = np.array(b)
        return float(np.mean([np.min(np.abs(b - x)) <= tol for x in a])) if len(a) else 0

    cp = {}
    for tol in (0.042, 0.1, 0.25):
        cp[f"editor_in_matched_{int(tol * 1000)}ms"] = frac_near(ri, vi, tol)
        cp[f"editor_out_matched_{int(tol * 1000)}ms"] = frac_near(ro, vo, tol)
        cp[f"v2_in_matched_{int(tol * 1000)}ms"] = frac_near(vi, ri, tol)
        cp[f"v2_out_matched_{int(tol * 1000)}ms"] = frac_near(vo, ro, tol)
        both_edges = [any(abs(a - c) <= tol and abs(b - d) <= tol for c, d in vc) for a, b in rc]
        cp[f"editor_cuts_same_both_edges_{int(tol * 1000)}ms"] = float(np.mean(both_edges))
    # signed offsets of matched edges (ours - the editor's), where within 0.5 s
    def signed(a, b):
        b = np.array(b)
        d = [float(b[np.argmin(np.abs(b - x))] - x) for x in a]
        return [x for x in d if abs(x) <= 0.5]
    cp["in_offset_v2_minus_editor"] = stats(signed(ri, vi))
    cp["out_offset_v2_minus_editor"] = stats(signed(ro, vo))
    cp["editor_cut_count"] = len(rc)
    cp["v2_cut_count"] = len(vc)
    cp["editor_backward_jumps"] = [(round(a, 2), round(b, 2)) for a, b in rc if b < a - 0.05]
    cp["editor_removed_span_len"] = stats([b - a for a, b in rc if b > a])
    cp["v2_removed_span_len"] = stats([b - a for a, b in vc if b > a])
    cp["editor_seg_len"] = stats([s["src_e"] - s["src_s"] for s in R])
    cp["v2_seg_len"] = stats([s["src_e"] - s["src_s"] for s in V])
    # what the editor's removed spans contain
    def removed_kinds(cuts):
        k = {"no_words_silence": 0, "no_words_sound": 0, "words": 0}
        for a, b in cuts:
            if b <= a:
                continue
            if text_in(ctc, a, b) or text_in(wsp, a, b):
                k["words"] += 1
            elif db[int(a / RES): int(b / RES)].max() > -45:
                k["no_words_sound"] += 1
            else:
                k["no_words_silence"] += 1
        return k
    cp["editor_removed_kinds"] = removed_kinds(rc)
    cp["v2_removed_kinds"] = removed_kinds(vc)
    res["cutpoints"] = cp

    # ---- 5. padding before first / after last sound of each segment -----------------------------
    def padding(S, thr=-45.0):
        lead, tail = [], []
        for s in S:
            i0, i1 = int(round(s["src_s"] / RES)), int(round(s["src_e"] / RES))
            loud = np.where(db[i0:i1] > thr)[0]
            if len(loud) == 0:
                continue
            # only edges where the cut is in a pause (not inside a word)
            if db[max(0, i0 - 1)] <= thr and i0 > 0:
                lead.append(loud[0] * RES)
            if i1 < len(db) and db[i1] <= thr:
                tail.append((i1 - i0 - 1 - loud[-1]) * RES)
        return stats(lead), stats(tail)

    res["padding"] = {}
    for thr in (-45.0, -35.0):
        rl, rt = padding(R, thr)
        vl, vt = padding(V, thr)
        res["padding"][str(thr)] = {"editor_lead": rl, "editor_tail": rt, "v2_lead": vl, "v2_tail": vt}

    # ---- 6. pauses in the finished edits (word gaps from the literal model, same words for both) --
    script = script_text.build()
    scr = script["words"]
    sent_of = script["sent_of_word"]
    res["pauses"] = {}
    vws = {}
    for name, S in (("editor", R), ("v2", V)):
        v = [w for w in virtual(S, ctc) if w["frac"] >= 0.5]
        vws[name] = v
        j_of, _ = selfcheck.align([w["n"] for w in v], scr)
        between, inside, join_b, join_i = [], [], [], []
        for i in range(len(v) - 1):
            g = v[i + 1]["s"] - v[i]["e"]
            if g < 0:
                continue
            ja = j_of[i]
            jb = next((j_of[x] for x in range(i + 1, min(len(v), i + 4)) if j_of[x] >= 0), -1)
            if ja < 0 or jb < 0:
                continue
            is_between = sent_of[ja] != sent_of[jb]
            joined = v[i]["seg"] != v[i + 1]["seg"]
            (between if is_between else inside).append(g)
            if joined:
                (join_b if is_between else join_i).append(g)
        res["pauses"][name] = {"between_sentences": stats(between), "inside_sentence": stats(inside),
                               "between_at_cut": stats(join_b), "inside_at_cut": stats(join_i)}
    # natural pauses in the raw (for reference)
    j_src, _ = selfcheck.align([w["n"] for w in ctc], scr)
    nat_b, nat_i = [], []
    for i in range(len(ctc) - 1):
        g = ctc[i + 1]["s"] - ctc[i]["e"]
        if g < 0 or g > 3 or j_src[i] < 0 or j_src[i + 1] < 0 or j_src[i + 1] != j_src[i] + 1:
            continue
        (nat_b if sent_of[j_src[i]] != sent_of[j_src[i + 1]] else nat_i).append(g)
    res["pauses"]["raw_natural"] = {"between_sentences": stats(nat_b), "inside_sentence": stats(nat_i)}

    # silences in the finished audio itself (model-free): runs below -50 dB
    def sil_runs(path):
        from scipy.io import wavfile
        sr, x = wavfile.read(path)
        x = x.astype(np.float32) / 32768
        hop = sr // 100
        n = len(x) // hop
        d = 20 * np.log10(np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(1)) + 1e-9)
        rr = runs(d < -50)
        return [e - s for s, e in rr if e - s >= 0.03]
    res["pauses"]["audio_silence_runs"] = {"editor": stats(sil_runs(D / "editor16.wav")), "v2": stats(sil_runs(D / "v2a16.wav"))}

    # ---- 7. breaths / non-word sounds between kept words ------------------------------------------
    cover = np.zeros(len(db), bool)
    for w in ctc + wsp:
        cover[max(0, int((w["s"] - 0.06) / RES)): int((w["e"] + 0.06) / RES)] = True
    ev = [(s, e) for s, e in runs((db > -55) & ~cover) if 0.1 <= e - s <= 1.5]
    br = {"events_total": len(ev)}
    for name, S in (("editor", R), ("v2", V)):
        cnt = {"kept_full": 0, "kept_part": 0, "removed": 0}
        kept_len = []
        for s, e in ev:
            # only events that sit between two words this edit keeps (breath handling, not take removal)
            before = [w for w in ctc if w["e"] <= s + 0.01][-1:] or [None]
            after = [w for w in ctc if w["s"] >= e - 0.01][:1] or [None]
            if not before[0] or not after[0]:
                continue
            if kept_frac(S, before[0]["s"], before[0]["e"]) < 0.5 or kept_frac(S, after[0]["s"], after[0]["e"]) < 0.5:
                continue
            f = kept_frac(S, s, e)
            if f > 0.9:
                cnt["kept_full"] += 1
            elif f > 0.1:
                cnt["kept_part"] += 1
            else:
                cnt["removed"] += 1
            if f > 0.1:
                kept_len.append(f * (e - s))
        br[name] = dict(cnt, kept_len=stats(kept_len))
    br["event_len"] = stats([e - s for s, e in ev])
    br["event_peak_db"] = stats([float(db[int(s / RES): int(e / RES)].max()) for s, e in ev])
    res["breaths"] = br

    # ---- 8. leftover repeats per the self-check, in each cut ----------------------------------------
    rep = {}
    for name in ("editor", "v2"):
        v = vws[name]
        j_of, _ = selfcheck.align([w["n"] for w in v], scr)
        r = selfcheck.find_repeats(v, j_of, scr, 1e9)
        rep[name] = [{"t": tc(v[x["i0"]]["s"]), "src": round(v[x["i0"]]["src_s"], 2), "type": x["type"],
                      "text": x["text"]} for x in r]
    res["repeats"] = rep

    json.dump(res, open(D / "analysis.json", "w"), ensure_ascii=False, indent=1, default=float)
    with open(D / "diffs.txt", "w") as f:
        for d in sorted(diffs, key=lambda d: d["src_s"]):
            f.write(f"{d['kind']:<16} src {tc(d['src_s'])}-{tc(d['src_e'])} ({d['dur']:.2f}s, pk {d['peak_db']}) "
                    f"v2 {tc(d['v2_t']) if d['v2_t'] is not None else '-'} editor {tc(d['editor_t']) if d['editor_t'] is not None else '-'}"
                    f" v1 {tc(d['v1_t']) if d['v1_t'] is not None else '-'}\n"
                    f"    ctc: {d['ctc']}\n    wsp: {d['whisper']}\n")
    print(json.dumps({k: v for k, v in res.items() if k not in ("diffs", "repeats")}, ensure_ascii=False, indent=1,
                     default=float))


if __name__ == "__main__":
    main()

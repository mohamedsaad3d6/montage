"""Extra style numbers, the reference editor's cut against our v2: short pieces, long word gaps, breath handling,
agreement around each review note, and sound in the editor's export that is not the raw (added effects / music).

    <core python> -m monteer.learn.editor_compare.extra --work <episode work> --edits <episode output> --out <compare dir>

--work holds asr_ext_ctc.json, asr_ext_large-v3.json and sync_ext16.wav; --edits holds edl_v1.json / edl_v2.json;
--out holds editor_keep.json, editor_holes.json, editor48s.wav and raw48s.wav and receives extra.json.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.io import wavfile

from ...cut.common import load_json, tc
from ..episode import frame_db
from .analyze import kept_frac, runs, segs_from_keep, virtual

# the 25 review notes on reference episode B's v1 (output times of v1); --notes FILE for another set
NOTES = {1: "00:36", 2: "00:46", 3: "01:46", 4: "02:05", 5: "02:13", 6: "03:02", 7: "03:25", 8: "03:35", 9: "05:17",
         10: "05:44", 11: "06:16", 12: "06:38", 13: "07:20", 14: "07:52", 15: "08:24", 16: "08:56", 17: "09:48",
         18: "10:04", 19: "11:35", 20: "12:37", 21: "13:01", 22: "13:11", 23: "13:39", 24: "13:50", 25: "14:40"}


def main():
    ap = argparse.ArgumentParser(description="Extra style numbers: the reference editor's cut against our v2.")
    ap.add_argument("--work", required=True, help="episode work folder (transcripts, sync_ext16.wav)")
    ap.add_argument("--edits", required=True, help="episode output folder with edl_v1.json / edl_v2.json")
    ap.add_argument("--out", required=True, help="comparison folder (editor_keep.json, editor_holes.json, editor48s.wav, raw48s.wav)")
    ap.add_argument("--notes", help='JSON file {"1": "mm:ss", ...}: review notes at v1 output times (default: the built-in 25)')
    opt = ap.parse_args()
    WORK, OUT, D = Path(opt.work), Path(opt.edits), Path(opt.out)
    notes = {int(k): v for k, v in json.load(open(opt.notes)).items()} if opt.notes else NOTES

    R = [dict(s, src_s=s["src_audio_s"], src_e=s["src_audio_e"]) for s in json.load(open(D / "editor_keep.json"))]
    V = segs_from_keep(load_json(OUT / "edl_v2.json")["keep"])
    ctc = load_json(WORK / "asr_ext_ctc.json")["words"]
    holes = json.load(open(D / "editor_holes.json"))
    db = frame_db(WORK / "sync_ext16.wav")
    out = {}
    out["short_pieces"] = {n: {f"<{t}s": sum(1 for s in S if s["src_e"] - s["src_s"] < t) for t in (0.5, 0.67, 1.0)}
                           for n, S in (("editor", R), ("v2", V))}
    gaps = {}
    for name, S in (("editor", R), ("v2", V)):
        v = [w for w in virtual(S, ctc) if w["frac"] >= 0.5]
        g = [(v[i + 1]["s"] - v[i]["e"], v[i]["e"], v[i]["w"], v[i + 1]["w"], v[i]["seg"] != v[i + 1]["seg"])
             for i in range(len(v) - 1)]
        g = [x for x in g if not any(h["ed_s"] - 0.5 < x[1] < h["ed_e"] + 0.5 for h in holes)]
        gaps[name] = {f">{th}s": [sum(1 for x in g if x[0] > th), sum(1 for x in g if x[0] > th and x[4])]
                      for th in (0.4, 0.5, 0.7, 1.0)}
        gaps[name]["longest"] = [(round(x[0], 2), tc(x[1]), x[2], x[3]) for x in sorted(g, reverse=True)[:10]]
    out["word_gaps_[all,at_cut]"] = gaps
    cover = np.zeros(len(db), bool)
    wsp = load_json(WORK / "asr_ext_large-v3.json")["words"]
    for w in ctc + wsp:
        cover[max(0, int((w["s"] - 0.06) / 0.01)): int((w["e"] + 0.06) / 0.01)] = True
    ev = [(s, e) for s, e in runs((db > -55) & ~cover) if 0.1 <= e - s <= 1.5]
    br = {}
    for name, S in (("editor", R), ("v2", V)):
        rem, kept = [], []
        for s, e in ev:
            b = [w for w in ctc if w["e"] <= s + 0.01][-1:]
            a_ = [w for w in ctc if w["s"] >= e - 0.01][:1]
            if not b or not a_ or kept_frac(S, b[0]["s"], b[0]["e"]) < .5 or kept_frac(S, a_[0]["s"], a_[0]["e"]) < .5:
                continue
            f = kept_frac(S, s, e)
            x = (float(db[int(s / .01):int(e / .01)].max()), e - s, a_[0]["s"] - b[0]["e"])
            (rem if f <= 0.1 else kept).append(x)
        br[name] = {k: {"n": len(L), "median_peak_db": round(float(np.median([r[0] for r in L])), 1),
                        "median_len_s": round(float(np.median([r[1] for r in L])), 2),
                        "median_word_gap_s": round(float(np.median([r[2] for r in L])), 2)}
                    for k, L in (("removed", rem), ("kept", kept))}
    out["breaths"] = br
    # the review notes: words that differ within +-6 s
    k1 = load_json(OUT / "edl_v1.json")["keep"]

    def src_of(t):
        c = 0
        for a0, b0 in k1:
            if c <= t <= c + b0 - a0:
                return a0 + t - c
            c += b0 - a0

    Rk = [(s["src_s"], s["src_e"]) for s in R]
    Vk = load_json(OUT / "edl_v2.json")["keep"]

    def kf(keep, s, e):
        return sum(max(0, min(e, b0) - max(s, a0)) for a0, b0 in keep) / max(e - s, 1e-3)

    nt = {}
    for n, t in notes.items():
        m, s = t.split(":")
        src = src_of(int(m) * 60 + int(s))
        ws = [w for w in ctc if src - 6 <= w["s"] <= src + 6]
        nt[n] = {"src": round(src, 1),
                 "editor_only": " ".join(w["w"] for w in ws if kf(Rk, w["s"], w["e"]) >= .5 > kf(Vk, w["s"], w["e"])),
                 "v2_only": " ".join(w["w"] for w in ws if kf(Vk, w["s"], w["e"]) >= .5 > kf(Rk, w["s"], w["e"]))}
    out["notes"] = nt
    # sound in the editor's export that is not the raw at that point (added effects / music)
    sr, e = wavfile.read(D / "editor48s.wav")
    e = e.astype(np.float32).mean(1) / 32768
    sr, r = wavfile.read(D / "raw48s.wav")
    r = r.astype(np.float32).mean(1) / 32768

    def ncc(a0, b0):
        a0 = a0 - a0.mean()
        b0 = b0 - b0.mean()
        d = np.sqrt((a0 * a0).sum() * (b0 * b0).sum())
        return (a0 * b0).sum() / d if d > 1e-12 else 1.0

    bad = []
    for s in json.load(open(D / "editor_keep.json")):
        off = int(round((s["src_audio_s"] - s["ed_s"]) * 48000))
        for t in np.arange(s["ed_s"] + 0.05, s["ed_e"] - 0.15, 0.1):
            i = int(t * 48000)
            x = e[i:i + 4800]
            if 20 * np.log10(np.sqrt((x ** 2).mean()) + 1e-9) > -40 and ncc(x, r[i + off:i + off + 4800]) < 0.8:
                bad.append(round(float(t), 1))
    rr = []
    for t in bad:
        if rr and t - rr[-1][1] <= 0.25:
            rr[-1][1] = t
        else:
            rr.append([t, t])
    out["added_sound_runs"] = rr
    json.dump(out, open(D / "extra.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items()}, ensure_ascii=False, indent=1)[:6000])


if __name__ == "__main__":
    main()

"""Layer A, timing side: pauses and breaths as they are heard in a finished cut (measurement only).

    <core python> -m monteer.learn.style_study.cut_audio <name> <cut16.wav> <ctc.json> [<joins.json> | ref=<name>,<ctc.json>] --out <dir>

Most episodes of the study have no raw recording, so the editor's joins cannot be listed the way monteer.learn.joins
does. What can be measured on any finished cut, with the same masks as monteer.learn.joins / monteer.cut.breath
(word sound W, breath B, other O):
  pauses     every gap between two stretches of word sound: length distribution, long ones
  breaths    audible breath runs (peak > -50 dB, >= 50 ms): per minute, standing alone in a pause or
             stuck to a word (a breathy tail / lead-in)
  cut-off    a breath that stops or starts abruptly against digital silence (a cut through it, or the
             mic gate closing) - checked against the known joins of reference episode B
With <joins.json> (cut-time join list, reference episode B only) each pause is also marked as at a join or not.
With ref=<name>,<ctc.json> the breath detector is trained on an earlier cut of the same speaker (cached as <name>).
Writes <out>/<name>_cutaudio.json; the breath detector cache goes to <out>/cache/<name>/.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from ...cut import breath

F = breath.FRAME


def prepare_with_ref(wav, ctc, cache, ref):
    """For a cut with too few stand-alone breaths to learn from (one of our own cuts): the same speaker's detector,
    trained on a reference cut (ref = (cache dir, ctc path))."""
    F = breath.features(Path(wav))
    z = np.load(ref[0] / "breath_feat.npz")
    Fr = {k: z[k] for k in z.files}
    rc = [w for w in json.load(open(ref[1], encoding="utf-8"))["words"] if w["w"].strip()]
    ib, isp = breath.train_labels(Fr, rc)
    Xr = breath._design(Fr)
    m = breath._fit(np.vstack([Xr[ib], Xr[isp]]), np.r_[np.ones(len(ib)), np.zeros(len(isp))])
    p = breath._predict(m, breath._design(F)).astype(np.float32)
    np.savez(cache / "breath_feat.npz", **F)
    np.save(cache / "breath_p.npy", p)
    W, B, O = breath.masks(F["db"], ctc, p)
    return {"db": F["db"], "W": W, "B": B, "O": O}


def main(name, wav, ctc_path, joins_path=None, out="."):
    outdir = Path(out)
    ctc = [w for w in json.load(open(ctc_path, encoding="utf-8"))["words"] if w["w"].strip()]
    cache = outdir / "cache" / name
    cache.mkdir(parents=True, exist_ok=True)
    if joins_path and joins_path.startswith("ref="):
        rname, rctc = joins_path[4:].split(",")
        M = prepare_with_ref(wav, ctc, cache, (outdir / "cache" / rname, rctc))
        joins_path = None
    else:
        M = breath.prepare(Path(wav), ctc, cache_dir=cache, log=print)
    db, W, B = M["db"], M["W"], M["B"]
    n = len(db)
    wr = breath.runs(W)
    joins = np.array(json.load(open(joins_path))) if joins_path else None
    pauses = []
    for (a0, a1), (b0, b1) in zip(wr, wr[1:]):
        g = (b0 - a1) * F
        pz = {"t": round(a1 * F, 2), "len": round(g, 3)}
        br = [(x + a1, y + a1) for x, y in breath.runs(B[a1:b0]) if y - x >= breath.BREATH_MIN
              and db[x + a1:y + a1].max() > breath.AUDIBLE_DB]
        pz["breaths"] = len(br)
        if joins is not None:
            pz["join"] = bool(((joins >= a1 * F - 0.02) & (joins <= b0 * F + 0.02)).any())
        pauses.append(pz)
    # audible breath runs anywhere, and how they sit
    out = []
    for x, y in breath.runs(B):
        if y - x < breath.BREATH_MIN or db[x:y].max() <= breath.AUDIBLE_DB:
            continue
        before = W[max(0, x - 3):x].any()
        after = W[y:y + 3].any()
        # abrupt edge: from breath level to digital silence within one 10 ms frame
        cut_end = y < n and db[y - 1] > -60 and db[y] < -90
        cut_start = x > 0 and db[x] > -60 and db[x - 1] < -90
        rec = {"t": round(x * F, 2), "len": round((y - x) * F, 2), "peak": round(float(db[x:y].max()), 1),
               "attached": bool(before or after), "abrupt_end": bool(cut_end), "abrupt_start": bool(cut_start)}
        if joins is not None:
            rec["at_join"] = bool((np.abs(joins - y * F) < 0.05).any() or (np.abs(joins - x * F) < 0.05).any())
        out.append(rec)
    L = np.array([p["len"] for p in pauses])
    mins = n * F / 60
    real = L[L >= 0.05]  # gaps under 50 ms are inside the flow of speech
    res = {"name": name, "minutes": round(mins, 2), "words": len(ctc),
           "pauses": len(real), "pauses_per_min": round(len(real) / mins, 1),
           "pause_median": round(float(np.median(real)), 3),
           "pause_p10_p90": [round(float(x), 3) for x in np.percentile(real, [10, 90])],
           "pause_p75": round(float(np.percentile(real, 75)), 3),
           "pause_sd_under_1s": round(float(real[real < 1].std()), 3),
           "pauses_over_0_4": int((L > 0.4).sum()), "pauses_over_0_5": int((L > 0.5).sum()),
           "pauses_over_0_7": int((L > 0.7).sum()), "pauses_over_1_0": int((L > 1.0).sum()),
           "breaths": len(out), "breaths_per_min": round(len(out) / mins, 2),
           "breaths_alone": sum(1 for b in out if not b["attached"]),
           "breaths_attached": sum(1 for b in out if b["attached"]),
           "breaths_abrupt": sum(1 for b in out if b["abrupt_end"] or b["abrupt_start"]),
           "long_pauses": [p for p in pauses if p["len"] > 0.4],
           "breath_list": out}
    if joins is not None:
        jp = [p for p in pauses if p.get("join") and p["len"] >= 0.05]
        res["join_pauses"] = len(jp)
        res["join_pause_median"] = round(float(np.median([p["len"] for p in jp])), 3)
        ab = [b for b in out if b["abrupt_end"] or b["abrupt_start"]]
        res["abrupt_breaths_at_join"] = sum(1 for b in ab if b["at_join"])
    json.dump(res, open(outdir / f"{name}_cutaudio.json", "w"), indent=1)
    print({k: v for k, v in res.items() if k not in ("breath_list", "long_pauses")})


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Pauses and breaths as heard in a finished cut.")
    ap.add_argument("name", help="name of this cut (output file prefix and cache folder)")
    ap.add_argument("wav", help="the cut's audio, 16 kHz mono")
    ap.add_argument("ctc", help="CTC words of the cut (monteer.cut.ctc_words output)")
    ap.add_argument("joins", nargs="?", help="JSON list of join times in the cut, or ref=<name>,<ctc.json>")
    ap.add_argument("--out", required=True, help="folder for <name>_cutaudio.json and the breath cache")
    opt = ap.parse_args()
    main(opt.name, opt.wav, opt.ctc, opt.joins, opt.out)

"""Score keep lists against the reference editor's cut (editor_keep.json), all in raw time.

    <core python> -m monteer.learn.editor_compare.score --work <episode work> --edits <episode output> --out <compare dir>

Versions scored: v2, rules-only (v2 content + style rules, <work>/v3/rules_only_keep.json), v3, v4, v5 (edl_vN.json in
--edits; a missing one is skipped) and the editor's own cut (style numbers). --work holds asr_ext_ctc.json,
asr_ext_large-v3.json and sync_ext16.wav; --out holds editor_keep.json and extra.json (review notes, from extra) and
receives scores.json.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from ...cut.common import load_json, tc
from ..episode import frame_db
from .analyze import kept_frac, mask, runs, segs_from_keep, stats, virtual

RES = 0.01


def keep_of(segs):
    return [[s["src_s"], s["src_e"]] for s in segs]


def score(X, R, ctc, wsp, db, notes_src, breath_events):
    """X, R: segment lists with src_s/src_e (R = the reference editor's cut)."""
    out = {}
    Xm, Rm = mask(X), mask(R)
    both = (Xm & Rm).sum() * RES
    out["kept_s"] = Xm.sum() * RES
    out["his_kept_we_keep"] = both / (Rm.sum() * RES)
    out["our_kept_he_keeps"] = both / (Xm.sum() * RES)
    out["overlap_jaccard"] = both / ((Xm | Rm).sum() * RES)
    for name, ws in (("ctc", ctc), ("whisper", wsp)):
        a = [kept_frac(X, w["s"], w["e"]) >= 0.5 for w in ws]
        b = [kept_frac(R, w["s"], w["e"]) >= 0.5 for w in ws]
        out[f"word_agreement_{name}"] = float(np.mean([x == y for x, y in zip(a, b)]))
        out[f"words_we_cut_he_kept_{name}"] = int(sum(y and not x for x, y in zip(a, b)))
        out[f"words_we_kept_he_cut_{name}"] = int(sum(x and not y for x, y in zip(a, b)))
    ri, ro = [s["src_s"] for s in R], [s["src_e"] for s in R]
    xi, xo = [s["src_s"] for s in X], [s["src_e"] for s in X]
    rc = [(R[i]["src_e"], R[i + 1]["src_s"]) for i in range(len(R) - 1)]
    xc = [(X[i]["src_e"], X[i + 1]["src_s"]) for i in range(len(X) - 1)]

    def near(a, b, tol):
        b = np.array(b)
        return float(np.mean([np.min(np.abs(b - x)) <= tol for x in a]))

    for tol, lab in ((1 / 24, "1frame"), (0.1, "100ms")):
        out[f"his_in_matched_{lab}"] = near(ri, xi, tol)
        out[f"his_out_matched_{lab}"] = near(ro, xo, tol)
        out[f"his_cuts_both_edges_{lab}"] = float(np.mean([any(abs(a - c) <= tol and abs(b - d) <= tol for c, d in xc)
                                                           for a, b in rc]))
        out[f"our_cuts_both_edges_{lab}"] = float(np.mean([any(abs(a - c) <= tol and abs(b - d) <= tol for c, d in rc)
                                                           for a, b in xc]))
    out["pieces"] = len(X)
    out["cuts"] = len(xc)
    out["pieces_under_0.5s"] = sum(1 for s in X if s["src_e"] - s["src_s"] < 0.5)
    # word gaps in the finished edit (literal-model word times, same measure as analyze)
    v = [w for w in virtual(X, ctc) if w["frac"] >= 0.5]
    g = np.array([v[i + 1]["s"] - v[i]["e"] for i in range(len(v) - 1)])
    out["gaps_over_0.4s"] = int((g > 0.4).sum())
    out["gaps_over_0.5s"] = int((g > 0.5).sum())
    out["gaps_over_0.7s"] = int((g > 0.7).sum())
    out["longest_gaps"] = [(round(float(x), 2), tc(v[i]["s"])) for i, x in sorted(enumerate(g), key=lambda t: -t[1])[:5]]
    # breaths between two kept words: share removed
    rem = kept = 0
    for s, e, wb, wa in breath_events:
        if kept_frac(X, wb["s"], wb["e"]) < 0.5 or kept_frac(X, wa["s"], wa["e"]) < 0.5:
            continue
        if kept_frac(X, s, e) <= 0.1:
            rem += 1
        else:
            kept += 1
    out["breaths_removed"] = rem
    out["breaths_kept"] = kept
    out["breath_removed_share"] = rem / max(1, rem + kept)
    # the review notes: same words as the editor within +-6 s
    same = 0
    diffs = {}
    for n, src in notes_src.items():
        ws = [w for w in ctc if src - 6 <= w["s"] <= src + 6]
        d = [w["w"] for w in ws if (kept_frac(X, w["s"], w["e"]) >= .5) != (kept_frac(R, w["s"], w["e"]) >= .5)]
        same += not d
        if d:
            diffs[n] = " ".join(d)
    out["notes_same_as_editor"] = same
    out["notes_differ"] = diffs
    return out


def main():
    ap = argparse.ArgumentParser(description="Score our keep lists against the reference editor's cut.")
    ap.add_argument("--work", required=True, help="episode work folder (transcripts, sync_ext16.wav, v3/rules_only_keep.json)")
    ap.add_argument("--edits", required=True, help="episode output folder with edl_v2.json ... edl_v5.json")
    ap.add_argument("--out", required=True, help="comparison folder with editor_keep.json (+ extra.json); scores.json goes here")
    opt = ap.parse_args()
    WORK, OUT, D = Path(opt.work), Path(opt.edits), Path(opt.out)
    ctc = load_json(WORK / "asr_ext_ctc.json")["words"]
    wsp = load_json(WORK / "asr_ext_large-v3.json")["words"]
    db = frame_db(WORK / "sync_ext16.wav")
    R = [dict(s, src_s=s["src_audio_s"], src_e=s["src_audio_e"]) for s in json.load(open(D / "editor_keep.json"))]
    notes_src = ({int(k): v["src"] for k, v in json.load(open(D / "extra.json"))["notes"].items()}
                 if (D / "extra.json").exists() else {})
    # breath-like events (same definition as analyze)
    cover = np.zeros(len(db), bool)
    for w in ctc + wsp:
        cover[max(0, int((w["s"] - 0.06) / RES)): int((w["e"] + 0.06) / RES)] = True
    ev = []
    cs = sorted(ctc, key=lambda w: w["s"])
    for s, e in runs((db > -55) & ~cover):
        if 0.1 <= e - s <= 1.5:
            b = [w for w in cs if w["e"] <= s + 0.01][-1:]
            a = [w for w in cs if w["s"] >= e - 0.01][:1]
            if b and a:
                ev.append((s, e, b[0], a[0]))
    files = {"v2": OUT / "edl_v2.json", "rules_only": WORK / "v3" / "rules_only_keep.json", "v3": OUT / "edl_v3.json",
             "v4": OUT / "edl_v4.json", "v5": OUT / "edl_v5.json"}
    versions = {}
    for k, f in files.items():
        if f.exists():
            versions[k] = segs_from_keep(load_json(f)["keep"])
        else:
            print("skipped (missing):", f)
    versions["editor"] = R
    res = {k: score(X, R, ctc, wsp, db, notes_src, ev) for k, X in versions.items()}
    json.dump(res, open(D / "scores.json", "w"), ensure_ascii=False, indent=1, default=float)
    first = next(iter(versions))
    keys = [k for k in res[first] if not isinstance(res[first][k], (list, dict))]
    print(f"{'':32}" + "".join(f"{k:>12}" for k in versions))
    for k in keys:
        print(f"{k:32}" + "".join(f"{res[v][k]:>12.3f}" if isinstance(res[v][k], float) else f"{res[v][k]:>12}"
                                  for v in versions))
    for v in versions:
        print(v, "longest gaps", res[v]["longest_gaps"], "notes differ", list(res[v]["notes_differ"]))


if __name__ == "__main__":
    main()

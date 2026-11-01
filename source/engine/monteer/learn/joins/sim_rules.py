"""Measurement only: what would candidate join rules change on v4? (No render; v4 itself is untouched.)

Applies each candidate to a copy of v4's keep list and re-measures with joins:
  R1 never cut inside a breath: move the cut to the silence before the breath (end of a piece) or
     after it (start of a piece);
  R2 breathy tail / lead-in on a word: cut where the breath starts (ends), next to the word;
  R3 audible breath in a pause inside a piece: cut it out, keep the silence around it.
Same detector before and after, so this shows what the rules would do by that detector's own
account; it can't show breaths the detector misses.

    <core python> -m monteer.learn.joins.sim_rules --work <episode work> --edits <episode output> --out <joins dir>

--work holds sync_ext16.wav and asr_ext_ctc.json; --edits holds edl_v4.json; --out holds breath_p.npy (breathclf) and
receives sim_rules.json.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from ...cut.common import load_json
from . import feat
from . import joins as J

FR = 0.01
KEEP_ATTACHED = 0  # frames of a breathy tail / lead-in kept next to the word (4 = 40 ms only turns it into a cut-through breath)


def audible(B, db, a, b):
    return [(x + a, y + a) for x, y in J.runs(B[a:b]) if y - x >= 2 and db[x + a:y + a].max() > J.AUDIBLE_DB]


def fix_joins(keep, W, B, db, r1=True, r2=True):
    keep = [list(p) for p in J.merge_keep(keep)]
    for k in range(len(keep) - 1):
        e1, s2 = int(round(keep[k][1] / FR)), int(round(keep[k + 1][0] / FR))
        # end of piece k: last word sound before the cut
        lo = max(int(round(keep[k][0] / FR)), e1 - 200)
        w = np.where(W[lo:e1])[0]
        if len(w):
            sp = lo + w[-1] + 1
            for a, b in audible(B, db, sp, min(len(B), e1 + 30)):
                if a >= e1:
                    break
                attached = a - sp <= 2
                if attached and r2:
                    e1 = min(e1, sp + KEEP_ATTACHED)
                elif not attached and r1:
                    e1 = min(e1, a)
                break
        # start of piece k+1: first word sound after the cut
        hi = min(int(round(keep[k + 1][1] / FR)), s2 + 200)
        w = np.where(W[s2:hi])[0]
        if len(w):
            sp = s2 + w[0]
            for a, b in reversed(audible(B, db, max(0, s2 - 30), sp)):
                if b <= s2:
                    break
                attached = sp - b <= 2
                if attached and r2:
                    s2 = max(s2, sp - KEEP_ATTACHED)
                elif not attached and r1:
                    s2 = max(s2, b)
                break
        keep[k][1], keep[k + 1][0] = e1 * FR, s2 * FR
    return [p for p in keep if p[1] - p[0] > 0.02]


def fix_inside(keep, W, B, db):
    """R3: cut audible breaths (>= 50 ms) out of pauses inside pieces."""
    out = []
    for s, e in J.merge_keep(keep):
        i0, i1 = int(round(s / FR)), int(round(e / FR))
        cuts = []
        r = J.runs(W[i0:i1])
        for (a1, b1), (a2, b2) in zip(r, r[1:]):
            g0, g1 = i0 + b1, i0 + a2
            for a, b in audible(B, db, g0, g1):
                if b - a >= 5:
                    cuts.append((a, b))
        cur = i0
        for a, b in cuts:
            out.append([cur * FR, a * FR])
            cur = b
        out.append([cur * FR, i1 * FR])
    return [p for p in out if p[1] - p[0] > 0.02]


def inside_breaths(keep, W, B, db):
    n = 0
    for s, e in J.merge_keep(keep):
        i0, i1 = int(round(s / FR)), int(round(e / FR))
        r = J.runs(W[i0:i1])
        for (a1, b1), (a2, b2) in zip(r, r[1:]):
            n += any(b - a >= 5 for a, b in audible(B, db, i0 + b1, i0 + a2))
    return n


def main():
    ap = argparse.ArgumentParser(description="What would candidate join rules change on v4? (measurement only)")
    ap.add_argument("--work", required=True, help="episode work folder (sync_ext16.wav, asr_ext_ctc.json)")
    ap.add_argument("--edits", required=True, help="episode output folder with edl_v4.json")
    ap.add_argument("--out", required=True, help="joins folder (breath_p.npy, feat.npz); sim_rules.json goes here")
    opt = ap.parse_args()
    WORK, D = Path(opt.work), Path(opt.out)
    F = feat.load(WORK / "sync_ext16.wav", D / "feat.npz")
    p = np.load(D / "breath_p.npy")
    ctc = load_json(WORK / "asr_ext_ctc.json")["words"]
    W, B, O = J.masks(F, ctc, p)
    db = F["db"]
    v4 = load_json(Path(opt.edits) / "edl_v4.json")
    slots = [i["after"] for i in v4["inserts"]]
    base = v4["keep"]
    variants = {
        "v4 as is": base,
        "R1": fix_joins(base, W, B, db, True, False),
        "R1+R2": fix_joins(base, W, B, db, True, True),
        "R1+R2+R3": fix_joins(fix_inside(base, W, B, db), W, B, db, True, True),
    }
    res = {}
    for name, keep in variants.items():
        js = J.measure(keep, F, W, B, O, slots)
        s = J.summary(js, name)
        s["inside_pause_breaths"] = inside_breaths(keep, W, B, db)
        s["raw_kept_s"] = sum(e - a for a, e in J.merge_keep(keep))
        res[name] = s
        print(f"{name:10} joins {s['joins']:4}  breath in pause {s['separate breath kept']:2}  cut through {s['breath cut through']:2}  "
              f"tail/lead-in {s['breath tail on word']:2}  inside-pause breaths {s['inside_pause_breaths']:2}  clipped {s['word_clipped_loud']:2}  "
              f"on-word {s['edge_on_word_sound_<30ms_silence']:3}  gap median {s['gap']['median']:.0f} p10 {s['gap']['p10']:.0f} p90 {s['gap']['p90']:.0f} sd {s['gap']['sd']:.0f}  "
              f"kept {s['raw_kept_s']:.1f}s")
    json.dump(res, open(D / "sim_rules.json", "w"), indent=1, default=float)


if __name__ == "__main__":
    main()

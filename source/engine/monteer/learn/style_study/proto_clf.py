"""Presenter on screen? A lighting-independent check for published videos without a cut to compare with.

The presenter shots of one episode are all the same locked-off studio picture, at one of a few zoom
levels. So: (1) among 60 frames spread over the video, find the group that match each other after a
zoom (registration score >= 0.7) - that is the studio; (2) every 2 fps frame is compared with up to 8
of those studio frames (zoom either way); a score >= 0.6 means the presenter is on screen.
Checked on the pair folders where the truth is known (video.json from pair_video).

    <core python> -m monteer.learn.style_study.proto_clf ID [ID ...] --channel <channel dir> --pairs <pairs dir> --out <dir>

Writes <channel dir>/feat/<id>/presenter_reg.npy (score per 2 fps frame) and <out>/proto_clf.json (kept and extended
across runs). --pair NAME=ID says which published video belongs to which pair folder.
"""
import argparse
import json
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from . import reg

FEAT = PAIRS_DIR = None   # set from the command line
SC = [1.0, 1.15, 1.32, 1.52, 1.75, 2.0]
# YouTube id of a published video -> its pair folder (--pair NAME=ID replaces)
PAIRS = {"xEv4jVhApaA": "p2", "vtNubor__8Y": "p3", "kSiA3ksTYKk": "p4"}
_G = _P = None


def both(a, b):
    """Zoom-tolerant score either way round (either frame may be the wider one)."""
    s1 = reg.match(a, b, scales=SC)[0]
    if s1 >= 0.7:
        return s1
    return max(s1, reg.match(b, a, scales=SC)[0])


def _init(g, protos):
    global _G, _P
    _G, _P = g, protos


def _score(i):
    best = 0.0
    for j in _P:
        if abs(i - j) <= 1:
            return 1.0
        best = max(best, both(_G[i], _G[j]))
        if best >= 0.75:
            break
    return best


def run(vid, pool_n=6):
    g = np.load(FEAT / vid / "g2.npy")
    n = len(g)
    samp = np.linspace(0, n - 1, 60).astype(int)
    samp = [k for k in samp if g[k, reg.TOP:].std() > 8]   # skip black / flat frames
    m = len(samp)
    A = np.zeros((m, m))
    pairs = [(a, b) for a in range(m) for b in range(a + 1, m)]
    with Pool(pool_n, initializer=_init, initargs=(g, [])) as pool:
        res = pool.starmap(_pair, [(samp[a], samp[b]) for a, b in pairs])
    for (a, b), r in zip(pairs, res):
        A[a, b] = A[b, a] = r
    deg = (A >= 0.7).sum(1)
    core = [samp[k] for k in np.argsort(-deg) if deg[k] >= max(3, 0.15 * m)]
    protos = core[:8]
    if not protos:
        np.save(FEAT / vid / "presenter_reg.npy", np.zeros(n, np.float32))
        return {"protos": 0, "presenter_pct": 0.0}
    with Pool(pool_n, initializer=_init, initargs=(g, protos)) as pool:
        sc = np.array(pool.map(_score, range(n), chunksize=40), np.float32)
    # second pass: more studio frames, spread over the video, for the frames still unmatched
    conf = np.flatnonzero(sc >= 0.8)
    if len(conf) > 12:
        more = [int(k) for k in conf[np.linspace(0, len(conf) - 1, 10).astype(int)] if k not in protos]
        low = [int(i) for i in np.flatnonzero(sc < 0.6)]
        with Pool(pool_n, initializer=_init, initargs=(g, more)) as pool:
            sc2 = pool.map(_score, low, chunksize=40)
        sc[low] = np.maximum(sc[low], sc2)
        protos = protos + more
    np.save(FEAT / vid / "presenter_reg.npy", sc)
    return {"protos": len(protos), "presenter_pct": round(float((sc >= 0.6).mean() * 100), 1)}


def _pair(a, b):
    return both(_G[a], _G[b])


def main(ids, out_dir):
    outdir = Path(out_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    out = json.load(open(outdir / "proto_clf.json")) if (outdir / "proto_clf.json").exists() else {}
    for vid in ids:
        r = run(vid)
        if vid in PAIRS:
            p = PAIRS[vid]
            rows = json.load(open(PAIRS_DIR / p / "video.json"))["rows"]
            y = np.array([1 if x["kind"] in ("presenter", "partial") else 0 if x["kind"] == "insert" else -1
                          for x in rows])
            sc = np.load(FEAT / vid / "presenter_reg.npy")
            k = min(len(y), len(sc))
            ok = y[:k] >= 0
            r["acc_vs_truth"] = round(float(((sc[:k] >= 0.6) == (y[:k] == 1))[ok].mean()), 3)
            r["presenter_true_pct"] = round(float((y[:k][ok] == 1).mean() * 100), 1)
        out[vid] = r
        print(vid, r, flush=True)
        json.dump(out, open(outdir / "proto_clf.json", "w"), indent=1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Presenter on screen? Studio-frame matching for published videos.")
    ap.add_argument("ids", nargs="+", help="YouTube ids (feature folders under <channel dir>/feat)")
    ap.add_argument("--channel", required=True, help="channel download folder (feat/<id>/g2.npy)")
    ap.add_argument("--pairs", required=True, help="folder holding the pair folders (video.json), for the accuracy check")
    ap.add_argument("--out", required=True, help="folder for proto_clf.json")
    ap.add_argument("--pair", action="append", metavar="NAME=ID", help="NAME=ID: pair folder name and the YouTube id of its published video (repeat; default: the study's four pairs)")
    opt = ap.parse_args()
    FEAT, PAIRS_DIR = Path(opt.channel) / "feat", Path(opt.pairs)
    if opt.pair:
        PAIRS = {i: n for n, i in (x.split("=", 1) for x in opt.pair)}
    main(opt.ids, opt.out)

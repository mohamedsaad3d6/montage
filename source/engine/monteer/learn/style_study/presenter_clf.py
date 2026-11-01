"""Is the presenter on screen? A frame classifier for published videos that have no cut to compare with.

Trained on the episodes where the answer is known (pair_video: the cut frame is on screen or not),
checked leave-one-episode-out, then applied to every channel video.

Features per 2 fps frame (from channel_extract): a coarse colour layout, colour/brightness histograms and
an edge layout. Second stage: frames are compared with the video's own most typical presenter frames
(registration score, zoom-tolerant), which the studio background makes very telling.

    <core python> -m monteer.learn.style_study.presenter_clf --channel <channel dir> --pairs <pairs dir> --out <dir>

<pairs dir> holds the pair folders (p0, p2, ... with video.json); --pair NAME=ID says which published video belongs to
which pair folder. Writes <channel dir>/feat/<id>/presenter.npy (probability per 2 fps frame) and <out>/clf.json.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from . import reg

FEAT = PAIRS_DIR = None   # set from the command line
# pair folder -> YouTube id of its published video (--pair NAME=ID replaces)
PAIRS = {"p0": "bApzkjRm_jU", "p2": "xEv4jVhApaA", "p3": "vtNubor__8Y", "p4": "kSiA3ksTYKk"}


def features(g, c):
    n = len(g)
    c = c.astype(np.float32) / 255
    lay = c.reshape(n, 6, 3, 8, 4, 3).mean((2, 4)).reshape(n, -1)               # 6x8 colour layout
    mx, mn = c.max(-1), c.min(-1)
    sat = (mx - mn) / np.maximum(mx, 1e-3)
    lum = c.mean(-1)
    hist = np.concatenate([np.stack([np.histogram(s, 8, (0, 1))[0] for s in sat.reshape(n, -1)]),
                           np.stack([np.histogram(l, 8, (0, 1))[0] for l in lum.reshape(n, -1)])], 1) / sat[0].size
    gf = g.astype(np.float32)
    gx = np.abs(np.diff(gf, axis=2))[:, :70, :126]
    gy = np.abs(np.diff(gf, axis=1))[:, :70, :126]
    e = gx + gy
    edge = e.reshape(n, 5, 14, 9, 14).mean((2, 4)).reshape(n, -1) / 40
    return np.concatenate([lay, hist, edge, sat.mean((1, 2))[:, None], lum.std((1, 2))[:, None]], 1)


def fit(X, y, l2=1e-2, it=800):
    mu, sd = X.mean(0), X.std(0) + 1e-6
    Z = (X - mu) / sd
    w, b = np.zeros(Z.shape[1]), 0.0
    for _ in range(it):
        p = 1 / (1 + np.exp(-(Z @ w + b)))
        g = p - y
        w -= 0.1 * (Z.T @ g / len(y) + l2 * w)
        b -= 0.1 * g.mean()
    return mu, sd, w, b


def predict(m, X):
    mu, sd, w, b = m
    return 1 / (1 + np.exp(-(((X - mu) / sd) @ w + b)))


def proto_score(g, p1, k=6):
    """Best registration score of each frame against k typical presenter frames of the same video."""
    idx = np.flatnonzero(p1 > 0.9)
    if len(idx) < k:
        return np.zeros(len(g))
    # typical frames: spread over the video
    pick = idx[np.linspace(0, len(idx) - 1, k).astype(int)]
    small = g[:, ::2, ::2]
    scales = [1.0, 1.15, 1.32, 1.52, 1.75, 2.0]
    out = np.zeros(len(g))
    for i in range(len(g)):
        best = 0.0
        for j in pick:
            if abs(i - j) <= 1:
                continue
            P = np.zeros((72, 128), np.uint8)
            sc = reg.match(g[i], g[j], scales=scales)[0]
            sc2 = reg.match(g[j], g[i], scales=scales)[0]   # the other one may be the wider shot
            best = max(best, sc, sc2)
            if best > 0.8:
                break
        out[i] = best
    return out


def labels(p):
    rows = json.load(open(PAIRS_DIR / p / "video.json"))["rows"]
    y = np.array([1 if r["kind"] in ("presenter", "partial") else 0 if r["kind"] == "insert" else -1 for r in rows])
    return y


def nocolour(X):
    """Edge layout + brightness histogram only (lighting colour changes between episodes)."""
    return np.concatenate([X[:, 144 + 8:144 + 16], X[:, 160:]], 1)


def adapt(m1, X):
    """Stage 2: the video's own confident frames teach a per-video model with all features."""
    p1 = predict(m1, nocolour(X))
    pos, neg = p1 > 0.85, p1 < 0.15
    if pos.sum() < 20 or neg.sum() < 20:
        return p1, p1
    m2 = fit(X[pos | neg], pos[pos | neg].astype(float))
    return 0.5 * p1 + 0.5 * predict(m2, X), p1


FULL = True   # with p0 (purple light) in training, colour features help instead of hurting


def nocolour(X):  # noqa: F811
    return X if FULL else np.concatenate([X[:, 144 + 8:144 + 16], X[:, 160:]], 1)


def train_all(data, use):
    X = np.vstack([nocolour(data[q][0][data[q][1] >= 0]) for q in use])
    y = np.concatenate([data[q][1][data[q][1] >= 0] for q in use])
    return fit(X, y)


def main():
    global FEAT, PAIRS_DIR, PAIRS
    ap = argparse.ArgumentParser(description="Presenter-on-screen classifier for published videos.")
    ap.add_argument("--channel", required=True, help="channel download folder (feat/<id>/g2.npy, c2.npy)")
    ap.add_argument("--pairs", required=True, help="folder holding the pair folders (video.json)")
    ap.add_argument("--out", required=True, help="folder for clf.json")
    ap.add_argument("--pair", action="append", metavar="NAME=ID", help="NAME=ID: pair folder name and the YouTube id of its published video (repeat; default: the study's four pairs)")
    opt = ap.parse_args()
    FEAT, PAIRS_DIR = Path(opt.channel) / "feat", Path(opt.pairs)
    if opt.pair:
        PAIRS = dict(x.split("=", 1) for x in opt.pair)
    data = {}
    for p, vid in PAIRS.items():
        g, c = np.load(FEAT / vid / "g2.npy"), np.load(FEAT / vid / "c2.npy")
        y = labels(p)
        n = min(len(g), len(y))
        data[p] = (features(g[:n], c[:n]), y[:n])
    report = {}
    for p in PAIRS:
        m1 = train_all(data, [q for q in PAIRS if q != p])
        Xp, yp = data[p]
        pr, p1 = adapt(m1, Xp)
        ok = yp >= 0
        report[p] = {"stage1_acc": round(float(((p1 > 0.5) == yp)[ok].mean()), 3),
                     "stage2_acc": round(float(((pr > 0.5) == yp)[ok].mean()), 3),
                     "presenter_true_pct": round(float(yp[ok].mean() * 100), 1),
                     "presenter_pred_pct": round(float((pr[ok] > 0.5).mean() * 100), 1)}
        print(p, report[p], flush=True)
    m1 = train_all(data, list(PAIRS))
    for d in sorted(FEAT.iterdir()):
        if not (d / "g2.npy").exists():
            continue
        meta = json.load(open(d / "meta.json"))
        if meta.get("vertical"):
            continue
        X = features(np.load(d / "g2.npy"), np.load(d / "c2.npy"))
        pr, _ = adapt(m1, X)
        np.save(d / "presenter.npy", pr.astype(np.float32))
        report[d.name] = {"presenter_pred_pct": round(float((pr > 0.5).mean() * 100), 1)}
        print(d.name, report[d.name], flush=True)
    Path(opt.out).mkdir(parents=True, exist_ok=True)
    json.dump(report, open(Path(opt.out) / "clf.json", "w"), indent=1)


if __name__ == "__main__":
    main()

"""Speech-vs-breath score for quiet frames (logistic regression on level-free features).

Trained on clear examples at the same loudness (-55 to -30 dB), so it can't simply use level:
  breath = the breath mask of monteer.cut.style (non-speech sound standing apart from the words);
  speech = frames inside literal-model words.
Checked on the other half of the episode (trained on the first half, tested on the second, and back).

    <core python> -m monteer.learn.joins.breathclf --work <episode work> --out <joins dir>

--work holds sync_ext16.wav and asr_ext_ctc.json; writes <out>/breath_p.npy (and the feature cache <out>/feat.npz).
"""
import argparse
from pathlib import Path

import numpy as np

from ...cut import style
from ...cut.common import load_json
from . import feat


def features(F):
    def sm(x):  # 50 ms context
        k = np.ones(5) / 5
        return np.convolve(x, k, mode="same") if x.ndim == 1 else np.stack([np.convolve(c, k, mode="same") for c in x.T], 1)
    X = [F["voi"], sm(F["voi"]), np.log(F["cen"] + 1), np.log(F["flat"] + 1e-4), sm(np.log(F["flat"] + 1e-4))]
    return np.column_stack(X + [F["bands"], sm(F["bands"])]).astype(np.float64)


def fit(X, y, l2=1e-2, it=600):
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd
    w = np.zeros(Z.shape[1])
    b = 0.0
    pw = len(y) / (2 * np.bincount(y.astype(int)))  # balance the classes
    sw = np.where(y == 1, pw[1], pw[0])
    for _ in range(it):
        p = 1 / (1 + np.exp(-(Z @ w + b)))
        g = (p - y) * sw
        w -= 0.5 * (Z.T @ g / len(y) + l2 * w)
        b -= 0.5 * g.mean()
    return mu, sd, w, b


def predict(model, X):
    mu, sd, w, b = model
    return 1 / (1 + np.exp(-(((X - mu) / sd) @ w + b)))


def labels(F, ctc):
    db = F["db"]
    n = len(db)
    inw = np.zeros(n, bool)
    for w in ctc:
        inw[int(w["s"] / .01):int(np.ceil(w["e"] / .01))] = True
    sp = style.speech_mask(db, ctc)
    br = style.breath_mask(db, sp)
    quiet = (db > -55) & (db < -30)
    return np.where(br & quiet)[0], np.where(inw & quiet)[0]


def main():
    ap = argparse.ArgumentParser(description="Speech-vs-breath score for quiet frames of the raw audio.")
    ap.add_argument("--work", required=True, help="episode work folder (sync_ext16.wav, asr_ext_ctc.json)")
    ap.add_argument("--out", required=True, help="joins folder; breath_p.npy and feat.npz go here")
    opt = ap.parse_args()
    WORK, D = Path(opt.work), Path(opt.out)
    F = feat.load(WORK / "sync_ext16.wav", D / "feat.npz")
    ctc = load_json(WORK / "asr_ext_ctc.json")["words"]
    X = features(F)
    ib, isp = labels(F, ctc)
    half = len(F["db"]) // 2
    accs = []
    for tr, te in ((lambda i: i < half, lambda i: i >= half), (lambda i: i >= half, lambda i: i < half)):
        tb, ts = ib[tr(ib)], isp[tr(isp)]
        m = fit(np.vstack([X[tb], X[ts]]), np.r_[np.ones(len(tb)), np.zeros(len(ts))])
        pb, ps = predict(m, X[ib[te(ib)]]), predict(m, X[isp[te(isp)]])
        accs.append((float((pb > .5).mean()), float((ps < .5).mean())))
    print("held-out: breaths called breath, speech called speech:", np.round(accs, 3).tolist())
    m = fit(np.vstack([X[ib], X[isp]]), np.r_[np.ones(len(ib)), np.zeros(len(isp))])
    p = predict(m, X)
    np.save(D / "breath_p.npy", p.astype(np.float32))
    print("saved breath_p.npy; frames > -55 dB called breath-like:", float((p[F["db"] > -55] > .5).mean()))


if __name__ == "__main__":
    main()

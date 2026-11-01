"""Montage layer: the small extra cuts the montage makes inside the reference editor's cut (a second tightening pass).

    <core python> -m monteer.learn.style_study.fine_align <pair dir>   -> <pair dir>/fine_align.json

pair_align finds the big pieces with 2 s windows; cuts shorter than ~2 s apart blur together there.
Here every 0.1 s a 1 s window of the published audio is located in the cut near the current offset
(+-3 s), giving a dense offset track. Each step up in the offset is a removal of that much cut time.
The removed cut span is then sorted: pause / breath (quiet in the cut), or speech (word sound inside).
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from numpy.lib.stride_tricks import sliding_window_view

from . import pair_align as pa

WIN, STEP, REACH = 100, 10, 300


def main(p):
    d = Path(p)
    p = d.name
    al = json.load(open(d / "align.json"))
    _, c = wavfile.read(d / "cut16.wav")
    _, q = wavfile.read(d / "pub16.wav")
    ce = pa.env(pa.bands(c.astype(np.float32) / 32768))
    qe = pa.env(pa.bands(q.astype(np.float32) / 32768))
    cdb = ce  # speech-band level of the cut, dB
    CW = sliding_window_view(ce, WIN)
    cm, cs = CW.mean(1), CW.std(1)
    track = []
    for i in range(0, len(qe) - WIN, STEP):
        t = i / 100
        seg = min(al["segs"], key=lambda s: 0 if s["p0"] <= t < s["p1"] else min(abs(t - s["p0"]), abs(t - s["p1"])))
        if not (seg["p0"] - 3 <= t < seg["p1"] + 3):
            continue
        guess = i + int(round(seg["off"] * 100))
        if track and abs(track[-1][0] - t) < 0.15 and track[-1][2] > 0.85:
            guess = i + int(round(track[-1][1] * 100))
        lo, hi = max(0, guess - REACH), min(len(CW) - 1, guess + REACH)
        w = qe[i:i + WIN]
        if w.std() < 2 or hi <= lo:
            continue
        wz = (w - w.mean()) / w.std()
        cand = CW[lo:hi]
        ok = cs[lo:hi] > 2
        r = np.where(ok, ((cand - cm[lo:hi, None]) * wz).mean(1) / np.maximum(cs[lo:hi], 1e-3), -1)
        j = int(np.argmax(r))
        track.append((t, (lo + j - i) / 100, float(r[j])))
    tr = [x for x in track if x[2] >= 0.9]
    # steps: offset goes up by >= 40 ms between neighbouring confident points (<= 1.5 s apart)
    rem = []
    for (t0, o0, _), (t1, o1, _) in zip(tr, tr[1:]):
        if t1 - t0 <= 1.5 and 0.04 <= o1 - o0 <= 15:
            # cut span removed: it starts where the earlier window's audio ends in the cut
            a = t0 + o0 + WIN / 100      # cut time reached by the first window's end
            b = t1 + o1                  # cut time where the next window starts
            # the removal sits somewhere between: find the quietest-run edge is not needed; measure the span
            c0 = a - (o1 - o0) if b - a < (o1 - o0) else a
            span = (max(0, b - (o1 - o0)), b) if b - a < 1.2 * (o1 - o0) else (a, a + (o1 - o0))
            lv = cdb[int(span[0] * 100):int(span[1] * 100)]
            peak = float(lv.max()) if len(lv) else -120
            rem.append({"pub_t": round(t1, 2), "cut_t": round(span[0], 2), "dur": round(o1 - o0, 2),
                        "kind": "speech" if peak > cdb.max() - 25 else "pause/breath", "peak_db": round(peak, 1)})
    # merge steps that are one removal measured twice
    merged = []
    for r in rem:
        if merged and r["pub_t"] - merged[-1]["pub_t"] < 0.25:
            merged[-1]["dur"] = round(merged[-1]["dur"] + r["dur"], 2)
            if r["kind"] == "speech":
                merged[-1]["kind"] = "speech"
        else:
            merged.append(r)
    big = [r for r in merged if r["dur"] >= 3]
    small = [r for r in merged if r["dur"] < 3]
    res = {"track_points": len(track), "confident_pct": round(100 * len(tr) / max(1, len(track)), 1),
           "small_removals": len(small), "small_removed_s": round(sum(r["dur"] for r in small), 1),
           "small_pause": sum(1 for r in small if r["kind"] != "speech"),
           "small_pause_s": round(sum(r["dur"] for r in small if r["kind"] != "speech"), 1),
           "small_speech": sum(1 for r in small if r["kind"] == "speech"),
           "small_speech_s": round(sum(r["dur"] for r in small if r["kind"] == "speech"), 1),
           "small_dur_median": float(np.median([r["dur"] for r in small])) if small else None,
           "big_removals": [(r["cut_t"], r["dur"], r["kind"]) for r in big],
           "per_min_of_cut": round(len(small) / (len(ce) / 6000), 2),
           "removals": merged}
    json.dump(res, open(d / "fine_align.json", "w"), indent=1)
    print(p, {k: v for k, v in res.items() if k != "removals"})


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="The small extra cuts the montage makes inside the editor's cut.")
    ap.add_argument("pair", help="pair folder (cut16.wav, pub16.wav, align.json); fine_align.json is written there")
    main(ap.parse_args().pair)

"""Montage layer, sound side: what the published audio adds to the reference editor's cut (measurement only).

    <core python> -m monteer.learn.style_study.pair_audio <pair dir>

With the pub->cut map (<pair dir>/align.json from pair_align), every 10 ms of the published audio is compared with the cut audio:
  voice gain     published speech level minus cut speech level
  music bed      published level where the cut is digital silence (the presenter's pauses): music / ambience under the voice
  effects        short bursts well above the bed while the cut is silent (whoosh, hit, riser)
  added audio    published stretches with no cut audio (intro, promo, clips with their own sound)
Writes <pair dir>/audio.json.
"""
import argparse
import json
from pathlib import Path

import numpy as np
from scipy.io import wavfile

SR = 16000


def frame_db(x):
    f = x[: len(x) // 160 * 160].reshape(-1, 160)
    return 10 * np.log10((f ** 2).mean(1) + 1e-12)


def main(p):
    d = Path(p)
    p = d.name
    al = json.load(open(d / "align.json"))
    _, c = wavfile.read(d / "cut16.wav")
    _, q = wavfile.read(d / "pub16.wav")
    cd, qd = frame_db(c.astype(np.float32) / 32768), frame_db(q.astype(np.float32) / 32768)
    n = len(qd)
    cut_at = np.full(n, -200.0)        # cut level at the mapped time, -200 = not mapped
    for s in al["segs"]:
        a, b = int(s["p0"] * 100), min(n, int(s["p1"] * 100))
        k = int(round(s["off"] * 100))
        idx = np.arange(a, b) + k
        ok = (idx >= 0) & (idx < len(cd))
        cut_at[a:b][ok] = cd[idx[ok]]
    mapped = cut_at > -199
    speech = mapped & (cut_at > -30)
    silent = mapped & (cut_at < -80)
    gain = float(np.median(qd[speech] - cut_at[speech]))
    pub_speech = float(np.median(qd[speech]))
    # music bed: published level in the presenter's pauses, in 5 s blocks
    blocks = []
    for t0 in range(0, n, 500):
        m = silent[t0:t0 + 500]
        if m.sum() >= 20:
            blocks.append({"t": t0 / 100, "bed_db": round(float(np.median(qd[t0:t0 + 500][m])), 1)})
    beds = np.array([b["bed_db"] for b in blocks])
    with_music = beds > -60
    # music under speech: the published level of speech frames would rise if a bed were loud; instead look at
    # bed level right next to speech (within 0.3 s) vs deep in long pauses -> ducking
    near = np.zeros(n, bool)
    for i in np.flatnonzero(speech):
        near[max(0, i - 30): i + 30] = True
    bed_near = qd[silent & near]
    bed_far = qd[silent & ~near]
    # effects: while the presenter is silent, bursts >= 10 dB above the local bed, 0.1-2 s long
    fx, i = [], 0
    sil_idx = np.flatnonzero(silent)
    local_bed = np.full(n, np.nan)
    for b in blocks:
        local_bed[int(b["t"] * 100): int(b["t"] * 100) + 500] = b["bed_db"]
    hot = silent & (qd > np.nan_to_num(local_bed, nan=-90) + 10) & (qd > -45)
    k = 0
    while k < n:
        if hot[k]:
            e = k
            while e < n and (hot[e] or (e + 1 < n and hot[e + 1])):
                e += 1
            if 10 <= e - k <= 200:
                fx.append({"t": k / 100, "dur": (e - k) / 100, "peak_db": round(float(qd[k:e].max()), 1)})
            k = e
        k += 1
    # added stretches: level profile (music only? other voices?)
    added = []
    for a in al["added"]:
        seg = qd[int(a["p0"] * 100): int(a["p1"] * 100)]
        if len(seg) == 0:
            continue
        added.append(dict(a, med_db=round(float(np.median(seg)), 1), p90_db=round(float(np.percentile(seg, 90)), 1),
                          silent_pct=round(float((seg < -60).mean() * 100), 1)))
    res = {"voice_gain_db": round(gain, 1), "pub_speech_db": round(pub_speech, 1),
           "bed_blocks": blocks,
           "bed_median_db": round(float(np.median(beds)), 1) if len(beds) else None,
           "bed_below_voice_db": round(pub_speech - float(np.median(beds[with_music])), 1) if with_music.any() else None,
           "music_blocks_pct": round(float(with_music.mean() * 100), 1) if len(beds) else None,
           "bed_near_speech_db": round(float(np.median(bed_near)), 1) if len(bed_near) else None,
           "bed_long_pause_db": round(float(np.median(bed_far)), 1) if len(bed_far) else None,
           "effects": fx, "added": added}
    json.dump(res, open(d / "audio.json", "w"), indent=1)
    print(p, {k: v for k, v in res.items() if k not in ("bed_blocks", "effects", "added")},
          "effects", len(fx), "added", [(a["p0"], a["dur"], a["med_db"]) for a in added])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="What the published audio adds to the editor's cut.")
    ap.add_argument("pair", help="pair folder (cut16.wav, pub16.wav, align.json); audio.json is written there")
    main(ap.parse_args().pair)

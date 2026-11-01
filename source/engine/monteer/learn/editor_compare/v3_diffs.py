"""Every remaining difference between one of our versions (default v3) and the reference editor's cut that involves
words (raw time + both video times).

    <core python> -m monteer.learn.editor_compare.v3_diffs [VERSION] --work <episode work> --edits <episode output> --out <compare dir>

VERSION = v3 | v4 | ... (edl_<VERSION>.json in --edits). --work holds asr_ext_ctc.json, asr_ext_large-v3.json and
sync_ext16.wav; --out holds editor_keep.json and receives <VERSION>_diffs.json.
"""
import argparse
import json
from pathlib import Path

from ...cut.common import load_json, tc
from ..episode import frame_db
from .analyze import mask, runs, segs_from_keep, text_in


def vt(segs, t, inserts=()):
    for s in segs:
        if s["src_s"] - 1e-6 <= t <= s["src_e"] + 1e-6:
            o = s["ed_s"] + t - s["src_s"]
            return o + sum(i["dur"] for i in inserts if i["after"] <= t)
    nxt = [s for s in segs if s["src_s"] > t]
    return (min(nxt, key=lambda s: s["src_s"])["ed_s"] + sum(i["dur"] for i in inserts if i["after"] <= t)) if nxt else None


def main():
    ap = argparse.ArgumentParser(description="Word differences between one of our versions and the editor's cut.")
    ap.add_argument("version", nargs="?", default="v3", help="our version to compare (default v3)")
    ap.add_argument("--work", required=True, help="episode work folder (transcripts, sync_ext16.wav)")
    ap.add_argument("--edits", required=True, help="episode output folder with edl_<version>.json")
    ap.add_argument("--out", required=True, help="comparison folder with editor_keep.json; the result goes here")
    opt = ap.parse_args()
    WORK, D, VER = Path(opt.work), Path(opt.out), opt.version
    db = frame_db(WORK / "sync_ext16.wav")
    ctc = load_json(WORK / "asr_ext_ctc.json")["words"]
    wsp = load_json(WORK / "asr_ext_large-v3.json")["words"]
    R = [dict(s, src_s=s["src_audio_s"], src_e=s["src_audio_e"]) for s in json.load(open(D / "editor_keep.json"))]
    e3 = load_json(Path(opt.edits) / f"edl_{VER}.json")
    X = segs_from_keep(e3["keep"])
    ins = e3["inserts"]

    Xm, Rm = mask(X), mask(R)
    out = []
    for kind, m in (("we keep, he cut", Xm & ~Rm), ("he keeps, we cut", Rm & ~Xm)):
        merged = []
        for s, e in runs(m):
            if merged and s - merged[-1][1] < 0.25:
                merged[-1][1] = e
            else:
                merged.append([s, e])
        for s, e in merged:
            c, w = text_in(ctc, s, e), text_in(wsp, s, e)
            if not c:  # the literal model hears no word: pause / breath timing, counted separately
                continue
            out.append({"kind": kind, "src": tc(s), "dur": round(e - s, 2), "v3": tc(vt(X, s, ins)),
                        "his": tc(R[0]["ed_s"] if vt(R, s) is None else vt(R, s)),
                        "ctc": c, "whisper": w, "peak_db": round(float(db[int(s / .01):int(e / .01)].max()), 1)})
    json.dump(out, open(D / f"{VER}_diffs.json", "w"), ensure_ascii=False, indent=1)
    for d in out:
        print(f"{d['kind']:<17} raw {d['src']} +{d['dur']:.2f}s {VER} {d['v3']} his {d['his']} pk {d['peak_db']} | {d['ctc']} || {d['whisper']}")


if __name__ == "__main__":
    main()

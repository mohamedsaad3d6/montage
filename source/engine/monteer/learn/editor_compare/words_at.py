"""Print the raw transcript words in a time window with keep marks: E = the reference editor keeps it, V = our v2 does.

    <core python> -m monteer.learn.editor_compare.words_at T0 T1 --work <episode work> --edits <episode output> --out <compare dir>

T0, T1 in raw seconds. Reads <out>/editor_keep.json, <edits>/edl_v2.json, <work>/asr_ext_large-v3.json and asr_ext_ctc.json.
"""
import argparse
import json
from pathlib import Path


def kf(keep, s, e):
    return sum(max(0, min(e, b) - max(s, a)) for a, b in keep) / max(e - s, 1e-3)


def main():
    ap = argparse.ArgumentParser(description="Raw transcript words in a window, marked by who keeps them.")
    ap.add_argument("t0", type=float)
    ap.add_argument("t1", type=float)
    ap.add_argument("--work", required=True, help="episode work folder (transcripts)")
    ap.add_argument("--edits", required=True, help="episode output folder with edl_v2.json")
    ap.add_argument("--out", required=True, help="comparison folder with editor_keep.json")
    opt = ap.parse_args()
    t0, t1, WORK = opt.t0, opt.t1, Path(opt.work)
    R = [(s["src_audio_s"], s["src_audio_e"]) for s in json.load(open(Path(opt.out) / "editor_keep.json"))]
    V = json.load(open(Path(opt.edits) / "edl_v2.json"))["keep"]
    W = json.load(open(WORK / "asr_ext_large-v3.json"))["words"]
    C = json.load(open(WORK / "asr_ext_ctc.json"))["words"]

    def mark(s, e):
        return ("E" if kf(R, s, e) >= .5 else ".") + ("V" if kf(V, s, e) >= .5 else ".")

    for name, ws in (("whisper", W), ("ctc", C)):
        print("==", name)
        line = []
        for w in ws:
            if t0 <= w["s"] < t1:
                line.append(f"{w['s']:.1f}[{mark(w['s'], w['e'])}]{w['w']}")
        print("  ".join(line))
    print("E segs:", [(round(a_, 2), round(b, 2)) for a_, b in R if b > t0 and a_ < t1])
    print("V segs:", [(round(a_, 2), round(b, 2)) for a_, b in V if b > t0 and a_ < t1])


if __name__ == "__main__":
    main()

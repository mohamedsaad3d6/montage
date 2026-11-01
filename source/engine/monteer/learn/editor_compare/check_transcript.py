"""Independent check of the rebuilt keep list with transcripts: every word the literal (CTC) model hears in the
reference editor's cut is carried through editor_keep.json to the raw timeline, where the same model's raw
transcript must have the same word at that time.

    <core python> -m monteer.learn.editor_compare.check_transcript --work <episode work> --out <compare dir>

--out holds editor_keep.json and editor_ctc.json (CTC words of the editor's cut) and receives transcript_check.json;
--work holds asr_ext_ctc.json (CTC words of the raw).
"""
import argparse
import json
from pathlib import Path

from rapidfuzz import fuzz

from ...cut.common import normalize_ar, tc


def main():
    ap = argparse.ArgumentParser(description="Check the editor's keep list word by word against the raw transcript.")
    ap.add_argument("--work", required=True, help="episode work folder with asr_ext_ctc.json")
    ap.add_argument("--out", required=True, help="comparison folder with editor_keep.json / editor_ctc.json; result goes here")
    opt = ap.parse_args()
    D = Path(opt.out)
    E = json.load(open(D / "editor_keep.json"))
    W = [w for w in json.load(open(D / "editor_ctc.json"))["words"] if normalize_ar(w["w"])]
    C = [w for w in json.load(open(Path(opt.work) / "asr_ext_ctc.json"))["words"] if normalize_ar(w["w"])]
    ok, bad = 0, []
    for w in W:
        t = (w["s"] + w["e"]) / 2
        s = next((s for s in E if s["ed_s"] <= t < s["ed_e"]), None)
        if s is None:
            bad.append((w, None))
            continue
        st = s["src_audio_s"] + t - s["ed_s"]
        near = [c for c in C if c["s"] - 0.12 <= st <= c["e"] + 0.12]
        if any(fuzz.ratio(normalize_ar(c["w"]), normalize_ar(w["w"])) >= 60 for c in near):
            ok += 1
        else:
            bad.append((w, st))
    print(f"{ok} of {len(W)} words ({100 * ok / len(W):.1f}%) land on the same word in the raw")
    # runs of 2+ consecutive misses point at a wrong segment
    runs, cur = [], []
    idx = {id(w): i for i, w in enumerate(W)}
    for w, st in bad:
        if cur and idx[id(w)] == idx[id(cur[-1][0])] + 1:
            cur.append((w, st))
        else:
            if len(cur) >= 2:
                runs.append(cur)
            cur = [(w, st)]
    if len(cur) >= 2:
        runs.append(cur)
    for r in runs:
        print(f"  {tc(r[0][0]['s'])}  {' '.join(w['w'] for w, _ in r)}   (raw {tc(r[0][1]) if r[0][1] else '-'})")
    json.dump({"matched": ok, "words": len(W),
               "miss_runs": [{"ed": r[0][0]["s"], "text": " ".join(w["w"] for w, _ in r)} for r in runs]},
              open(D / "transcript_check.json", "w"), ensure_ascii=False, indent=0)


if __name__ == "__main__":
    main()

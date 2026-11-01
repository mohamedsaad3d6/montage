"""Two montage details for an episode with a cut transcript: what the montage's extra removals contain,
and whether its zoom changes land on the cut's own joins (jump cuts) or mid-shot.

    <core python> -m monteer.learn.style_study.montage_detail <pair dir> [<joins.json>]   -> <pair dir>/montage_detail.json

Needs <pair dir>/align.json, video.json and asr_cut.json. <joins.json>: the cut's join times (cut time, s); without
it the cut video's own hard cuts are used.
"""
import argparse
import json
from pathlib import Path

import numpy as np


def main(p, joins_path=None):
    d = Path(p)
    al = json.load(open(d / "align.json"))
    words = json.load(open(d / "asr_cut.json", encoding="utf-8"))["words"]
    v = json.load(open(d / "video.json"))
    rows = v["rows"]
    # removed cut spans: speech inside?
    rem = []
    for r in al["removed"]:
        ws = [w for w in words if w["s"] >= r["c0"] - 0.05 and w["e"] <= r["c1"] + 0.05]
        part = [w for w in words if w["e"] > r["c0"] and w["s"] < r["c1"]]
        rem.append({"c0": r["c0"], "dur": r["dur"], "words_inside": len(ws),
                    "text": " ".join(w["w"] for w in part), "kind": "speech" if ws else "pause/breath"})
    # joins of the cut: given, or the cut video's own hard cuts
    joins = np.array(json.load(open(joins_path))) if joins_path else np.array(v["shots_cut"]["cuts"])
    zc = []
    for a, b in zip(rows, rows[1:]):
        if a["kind"] in ("presenter", "partial") and b["kind"] in ("presenter", "partial") and abs(a["s"] - b["s"]) >= 0.1:
            tc0, tc1 = a["tc"], b["tc"]
            near = bool(((joins >= tc0 - 0.05) & (joins <= tc1 + 0.05)).any())
            # a zoom change between two presenter samples whose cut times jump = the montage cut there too
            zc.append({"t": b["t"], "tc": tc1, "at_cut_join": near})
    # chance level: share of 0.5 s windows that contain a join
    chance = float(np.mean([((joins >= t) & (joins < t + 0.6)).any() for t in np.arange(0, max(r["tc"] or 0 for r in rows), 0.5)]))
    res = {"removed": rem,
           "removed_speech_n": sum(1 for r in rem if r["kind"] == "speech"),
           "removed_speech_s": round(sum(r["dur"] for r in rem if r["kind"] == "speech"), 1),
           "removed_pause_n": sum(1 for r in rem if r["kind"] != "speech"),
           "removed_pause_s": round(sum(r["dur"] for r in rem if r["kind"] != "speech"), 1),
           "zoom_changes": len(zc), "zoom_changes_at_join_pct": round(100 * np.mean([z["at_cut_join"] for z in zc]), 1) if zc else None,
           "chance_pct": round(100 * chance, 1)}
    json.dump(res, open(d / "montage_detail.json", "w"), ensure_ascii=False, indent=1)
    print(d.name, {k: v for k, v in res.items() if k != "removed"})
    for r in rem:
        print(f"  {r['c0']:7.1f} {r['dur']:5.2f}s {r['kind']:12s} {r['text'][:90]}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="What the montage's extra removals contain; where its zoom changes land.")
    ap.add_argument("pair", help="pair folder (align.json, video.json, asr_cut.json); montage_detail.json is written there")
    ap.add_argument("joins", nargs="?", help="JSON list of the cut's join times (default: the cut video's hard cuts)")
    opt = ap.parse_args()
    main(opt.pair, opt.joins)

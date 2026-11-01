"""Measurement only: v4's joins against the reference editor's, join by join (needs joins.json from joins).

Each join gets a list of problems and a score (higher = more audible):
  breath in pause (3), word clipped (3), cut through a breath (2, or 1 if fainter than -45 dB),
  breathy tail on a word (1, or 2 if louder than -40 dB), cut right on the word (1),
  pause over 0.3 s (1) or under 0.08 s (1).
Writes compare_joins.json: v4 worse than the editor, the editor's own remaining spots, and both.

    <core python> -m monteer.learn.joins.compare_joins --out <joins dir>
"""
import argparse
import json
from pathlib import Path

from ...cut.common import tc
from .joins import AUDIBLE_DB


def problems(j):
    out = []
    for side in ("tail", "head"):
        for r in j[side]["breaths"]:
            if r["db"] <= AUDIBLE_DB or r["ms"] < 20:
                continue
            if r["cut_through"]:
                out.append((2 if r["db"] > -45 else 1, f"cut through a breath ({side}, {r['ms']} ms, {r['db']:.0f} dB)"))
            elif not r["attached"] and r["ms"] >= 50:
                out.append((3, f"breath in the pause ({side}, {r['ms']} ms, {r['db']:.0f} dB)"))
            elif r["attached"]:
                out.append((2 if r["db"] > -40 else 1, f"breathy {'tail' if side == 'tail' else 'lead-in'} on the word ({r['ms']} ms, {r['db']:.0f} dB)"))
    for side in ("tail", "head"):
        ms, d = j[f"clip_{side}_ms"], j[f"clip_{side}_db"]
        if ms >= 30 and d is not None and d > -40:
            out.append((3, f"word sound cut off ({'end' if side == 'tail' else 'start'}, {ms} ms at {d:.0f} dB)"))
        elif j[side]["ms"] < 30:
            out.append((1, f"cut right on the word ({'end' if side == 'tail' else 'start'}: {j[side]['ms']:.0f} ms of silence)"))
    if j["gap_ms"] > 300:
        out.append((1, f"long pause ({j['gap_ms'] / 1000:.2f} s)"))
    elif j["gap_ms"] < 80:
        out.append((1, f"very short pause ({j['gap_ms'] / 1000:.2f} s)"))
    return out


def main():
    ap = argparse.ArgumentParser(description="v4's joins against the reference editor's, join by join.")
    ap.add_argument("--out", required=True, help="joins folder with joins.json; compare_joins.json goes here")
    D = Path(ap.parse_args().out)
    res = json.load(open(D / "joins.json"))
    Jv, Jr = res["joins"]["v4"], res["joins"]["editor"]
    pr = {int(k): v for k, v in res["pairs_v4_editor"].items()}
    worse, his_spots, both = [], [], []
    for i, j in enumerate(Jv):
        if j["slot"]:
            continue
        pv = problems(j)
        sv = sum(s for s, _ in pv)
        h = Jr[pr[i]] if i in pr else None
        ph = problems(h) if h else []
        sh = sum(s for s, _ in ph)
        row = {"v4": tc(j["out_time"]), "his": tc(h["out_time"]) if h else "", "raw": tc(j["raw_a"]),
               "v4_gap": j["gap_ms"], "his_gap": h["gap_ms"] if h else None,
               "v4_problems": [t for _, t in pv], "his_problems": [t for _, t in ph], "v4_score": sv, "his_score": sh}
        if sv >= 2 and sv > sh:
            worse.append(row)
        elif sv >= 2 and sh >= 2:
            both.append(row)
    for k, h in enumerate(Jr):
        if h["slot"]:
            continue
        ph = problems(h)
        sh = sum(s for s, _ in ph)
        if sh >= 2:
            i = next((i for i, m in pr.items() if m == k), None)
            pv = problems(Jv[i]) if i is not None else []
            his_spots.append({"his": tc(h["out_time"]), "v4": tc(Jv[i]["out_time"]) if i is not None else "",
                              "raw": tc(h["raw_a"]), "his_gap": h["gap_ms"], "his_problems": [t for _, t in ph],
                              "his_score": sh, "v4_score": sum(s for s, _ in pv), "v4_problems": [t for _, t in pv]})
    worse.sort(key=lambda r: -(r["v4_score"] - r["his_score"]))
    his_spots.sort(key=lambda r: -r["his_score"])
    out = {"v4_worse": worse, "editor_spots": his_spots, "both": both}
    json.dump(out, open(D / "compare_joins.json", "w"), ensure_ascii=False, indent=1)
    print(f"v4 worse than the editor: {len(worse)}   the editor's own spots (score>=2): {len(his_spots)}   both: {len(both)}")
    print("-- v4 worse")
    for r in worse:
        print(f"v4 {r['v4']} his {r['his']} raw {r['raw']} [{r['v4_score']} vs {r['his_score']}] v4: {'; '.join(r['v4_problems'])} || his: {'; '.join(r['his_problems'])}")
    print("-- the editor's spots")
    for r in his_spots:
        print(f"his {r['his']} v4 {r['v4']} raw {r['raw']} [{r['his_score']} vs v4 {r['v4_score']}] his: {'; '.join(r['his_problems'])} || v4: {'; '.join(r['v4_problems'])}")


if __name__ == "__main__":
    main()

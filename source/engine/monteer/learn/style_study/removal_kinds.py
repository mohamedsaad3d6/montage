"""Sort the montage's speech removals: a repeat / restart (the same words come again within 8 s), an aside
(«القهوة», greetings), or plain content.

    <core python> -m monteer.learn.style_study.removal_kinds <pair dir>   -> <pair dir>/removal_kinds.json

Needs <pair dir>/montage_detail.json (montage_detail) and asr_cut.json.
"""
import argparse
import json
from pathlib import Path

from rapidfuzz import fuzz

from ...cut.common import normalize_ar


def main(p):
    d = Path(p)
    md = json.load(open(d / "montage_detail.json"))
    words = json.load(open(d / "asr_cut.json", encoding="utf-8"))["words"]
    out = {"repeat_or_restart": [], "other": []}
    for r in md["removed"]:
        if r["kind"] != "speech":
            continue
        rem = normalize_ar(r["text"])
        after = normalize_ar(" ".join(w["w"] for w in words if r["c0"] + r["dur"] <= w["s"] < r["c0"] + r["dur"] + 8))
        before = normalize_ar(" ".join(w["w"] for w in words if r["c0"] - 8 <= w["s"] < r["c0"]))
        rep = len(rem.split()) >= 1 and max(fuzz.partial_ratio(rem, after), fuzz.partial_ratio(rem, before)) >= 80
        out["repeat_or_restart" if rep else "other"].append((round(r["c0"], 1), r["dur"], r["text"][:70]))
    res = {k: {"n": len(v), "s": round(sum(x[1] for x in v), 1)} for k, v in out.items()}
    print(d.name, res)
    for x in out["other"][:40]:
        print("  other", x)
    json.dump({"summary": res, "items": out}, open(d / "removal_kinds.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Sort the montage's speech removals: repeat / restart, or other.")
    ap.add_argument("pair", help="pair folder (montage_detail.json, asr_cut.json); removal_kinds.json is written there")
    main(ap.parse_args().pair)

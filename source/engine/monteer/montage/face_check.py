"""Self-check for talking-head montages: no punch-in crop cuts the presenter's face. For every zoomed presenter shot,
take frames of the cut 4 per second, find the face (macOS Vision: the `faces` tool built by setup) and test that the
face box sits inside the crop with a small margin.
    <core python> -m monteer.montage.face_check "<project>" [prep|check]  -> work/montage/facecheck/result.json
"""
import json
import subprocess
import sys
from pathlib import Path

from monteer.core.paths import FACES, FFMPEG
from monteer.core.project import Project

P = Project(sys.argv[1]) if len(sys.argv) > 1 else None
FF = str(FFMPEG)
V5 = str(P.output / f"cut_v{int(P.opt('version', 1))}.mp4") if P else ""      # the finished cut the presenter shots come from
D = (P.work / "montage" / "facecheck") if P else Path(".")
HERE = (P.work / "montage") if P else Path(".")
MARGIN = 0.01   # share of the frame


def zoomed():
    edl = json.load(open(HERE / "edl.json"))
    out = []
    for s in edl["shots"]:
        if s["kind"] == "presenter" and (s["zoom"] > 1 or s.get("push_to")):
            out.append(s)
    return out


def prep():
    for i, s in enumerate(zoomed()):
        n = s["nframes"]
        subprocess.run([FF, "-v", "error", "-y", "-ss", "%.4f" % (s["cut_in"] - 0.001), "-i", V5, "-t", "%.4f" % (n / 24),
                        "-vf", "fps=4,scale=640:-2", "-q:v", "5", str(D / f"z{i:03d}_%03d.jpg")], check=True)


def check():
    segs = zoomed()
    res = subprocess.run([str(HERE / "faces")] + sorted(str(p) for p in D.glob("z*.jpg")), capture_output=True, text=True).stdout
    bad, nof, n = [], [], 0
    for line in res.splitlines():
        if line.endswith((" none", " unreadable")):
            p, v = line.rsplit(" ", 1)[0], ["none"]
        else:
            p, *v = line.rsplit(" ", 4)
        name = Path(p).stem
        i, k = int(name[1:4]), int(name[5:]) - 1
        s = segs[i]
        t = s["final_in"] + k / 4
        n += 1
        if v[0] in ("none", "unreadable"):
            nof.append({"final": round(t, 2), "file": name})
            continue
        x, y, w, h = map(float, v)
        c = s["push_to"] if s.get("push_to") else s["crop"]
        cx, cy, cw, ch = c["x"] / 1920, c["y"] / 1080, c["w"] / 1920, c["h"] / 1080
        inside = x >= cx + MARGIN and x + w <= cx + cw - MARGIN and y >= cy - 0.02 and y + h <= cy + ch - MARGIN
        if not inside and w > 0.04:
            bad.append({"final": round(t, 2), "seg": i, "face": [round(x, 3), round(y, 3), round(w, 3), round(h, 3)],
                        "crop": [round(cx, 3), round(cy, 3), round(cw, 3), round(ch, 3)], "file": name})
    json.dump({"frames_checked": n, "face_cut": bad, "no_face_found": nof}, open(D / "result.json", "w"), indent=1)
    print("checked", n, "face cut", len(bad), "no face", len(nof))


if __name__ == "__main__":
    {"prep": prep, "check": check}[sys.argv[2]]()

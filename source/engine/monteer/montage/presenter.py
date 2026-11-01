"""Presenter shots for talking-head montages (rule 7): punch-ins that hide the jump cuts.

Where the presenter is on screen (every stretch the montage plan doesn't cover with B-roll), the picture alternates between
full frame and a punch-in of 1.32 / 1.22 / 1.17x (the reference editor's most used levels) at the cut's own joins, holding
each size at least `hold` seconds; the hold is chosen so there are about 10.5 size changes per presenter-minute (the
reference editor's 9.8-11.8). A long full-frame stretch with no join (7 s or more) gets a slow push-in 1.00 -> 1.10.
Each crop is placed around the presenter's face (face boxes from the `faces` tool, macOS Vision); when the face moves too
much for a 1.22/1.32 crop, the punch-in is lowered to 1.17 so the face stays in frame.

Inputs: stretches [(s, e)] on the cut's timeline, the cut's joins (output times of its jump cuts), the cut's pieces
[{"i", "o0", "o1"}] and face boxes per piece {i: [(x, y, w, h) as shares of the frame]}.
Output: presenter shots {"cut_in", "cut_out", "zoom", "crop": {x, y, w, h} (1080p pixels) | None, "push_to": {...} | None}.
"""
import re

FPS = 24
ZOOMS = [1.32, 1.22, 1.17]
TARGET_RATE = 10.5          # size changes per presenter-minute


def fr(t):
    return round(round(t * FPS) / FPS, 4)


def read_faces(faces_txt):
    """the faces tool's output (one line per still: '<file> x y w h' or '<file> none') -> {piece: [boxes]};
    stills are named p<piece>_<k>.jpg"""
    F = {}
    for line in open(faces_txt):
        t = line.split()
        if not t or t[-1] in ("none", "unreadable") or len(t) < 5:
            continue
        p, v = " ".join(t[:-4]), t[-4:]          # the path may hold spaces ("AI agent"): the 4 numbers are the last fields
        m = re.search(r"p(\d+)_(\d)\.jpg$", p)
        if not m:
            continue
        x, y, w, h = map(float, v)
        if w < 0.05 or not 0.2 < x + w / 2 < 0.8:      # tiny or off-centre hit: not the presenter's face
            continue
        F.setdefault(int(m.group(1)), []).append((x, y, w, h))
    return F


def crop_for(a, b, s, F, pieces):
    pcs = [p for p in pieces if p["o1"] > a + 0.01 and p["o0"] < b - 0.01]
    boxes = [f for p in pcs for f in F.get(p["i"], [])]
    if not boxes:                    # a centre crop (it was None, which the renderer could not draw)
        W = H = 1 / s
        return {"x": round((1 - W) / 2 * 1920), "y": round((1 - H) / 2 * 1080), "w": round(W * 1920), "h": round(H * 1080)}, \
            "no face found: centre crop"
    x0 = min(f[0] for f in boxes)
    x1 = max(f[0] + f[2] for f in boxes)
    y0 = min(f[1] for f in boxes)
    y1 = max(f[1] + f[3] for f in boxes)
    W = H = 1 / s
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    cl = lambda v, hi: min(max(v, 0.0), hi)  # noqa: E731
    left = cl(cx - W / 2, 1 - W)
    top = cl(cy - 0.38 * H, 1 - H)
    fits = x0 >= left and x1 <= left + W and y0 >= top and y1 <= top + H
    return {"x": round(left * 1920), "y": round(top * 1080), "w": round(W * 1920), "h": round(H * 1080)}, \
        ("face inside" if fits else "face moves a lot here: check")


def punch_ins(stretches, joins, F, pieces, hold):
    plan, prev_end_zoom, zi = [], 1.0, 0
    for a, b in stretches:
        js = [j for j in joins if a + 0.4 < j < b - 1.0]     # no size change with under 1 s of the stretch left (a flicker)
        if prev_end_zoom == 1.0:
            z = ZOOMS[zi % 3]
            zi += 1
        else:
            z = 1.0
        cuts = [a]
        last = a
        for j in js:
            if j - last >= hold:
                cuts.append(j)
                last = j
        cuts.append(b)
        for k in range(len(cuts) - 1):
            if k > 0:
                if z == 1.0:
                    z = ZOOMS[zi % 3]
                    zi += 1
                else:
                    z = 1.0
            s0, s1 = cuts[k], cuts[k + 1]
            item = {"cut_in": fr(s0), "cut_out": fr(s1), "zoom": z, "at": "start of presenter stretch" if k == 0 else "jump cut",
                    "crop": None, "push_to": None}
            if z > 1.0:
                c, note = crop_for(s0, s1, z, F, pieces)
                if note.startswith("face moves") and z > 1.17:
                    c2, note2 = crop_for(s0, s1, 1.17, F, pieces)
                    if note2 == "face inside":
                        item["zoom"], c, note = 1.17, c2, "lowered to 1.17 so the face stays in frame"
                item["crop"], item["crop_note"] = c, note
            elif s1 - s0 >= 7.0:            # long hold at full frame with no join: a slow push-in
                c, note = crop_for(s0, s1, 1.10, F, pieces)
                item["push_to"], item["crop_note"] = c, note
            plan.append(item)
        prev_end_zoom = z
    return plan


def plan(stretches, joins, F, pieces):
    """the punch-in plan whose size-change rate is closest to the target; returns (shots, hold, rate)"""
    pres_s = sum(b - a for a, b in stretches) or 1.0
    best = None
    for hold in (2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0):
        pl = punch_ins(stretches, joins, F, pieces, hold)
        rate = sum(1 for p in pl if p["at"] == "jump cut") / (pres_s / 60)
        if best is None or abs(rate - TARGET_RATE) < abs(best[2] - TARGET_RATE):
            best = (pl, hold, rate)
    return best


def shots(pl):
    """presenter plan -> cut-list shots (frames on the montage timeline = the cut's timeline)"""
    out = []
    for p in pl:
        f0, f1 = int(round(p["cut_in"] * FPS)), int(round(p["cut_out"] * FPS))
        out.append({"kind": "presenter", "f0": f0, "f1": f1, "nframes": f1 - f0, "cut_in": p["cut_in"], "zoom": p["zoom"],
                    "crop": p["crop"], "push_to": p["push_to"]})
    return out


def cut_pieces(keep):
    """the cut's pieces on its output timeline: [{"i", "o0", "o1"}], and its joins (output times of the jump cuts)"""
    pieces, t = [], 0.0
    for i, (s, e) in enumerate(keep):
        pieces.append({"i": i, "o0": t, "o1": t + (e - s)})
        t += e - s
    return pieces, [p["o1"] for p in pieces[:-1]]


def face_boxes(cut_video, pieces, out_dir):
    """one still per piece (two for pieces over 4 s) -> the faces tool -> {piece: [boxes]} (cached in out_dir/faces.txt)"""
    import subprocess
    from pathlib import Path
    from ..core.paths import FACES, FFMPEG
    out_dir = Path(out_dir)
    txt = out_dir / "faces.txt"
    if not txt.exists():
        (out_dir / "frames").mkdir(parents=True, exist_ok=True)
        stills = []
        for p in pieces:
            L = p["o1"] - p["o0"]
            for k, t in enumerate([p["o0"] + L / 2] if L <= 4 else [p["o0"] + L * 0.25, p["o0"] + L * 0.75]):
                f = out_dir / "frames" / f"p{p['i']}_{k}.jpg"
                subprocess.run([str(FFMPEG), "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(cut_video), "-frames:v", "1",
                                "-vf", "scale=640:-1", "-q:v", "4", str(f)], check=True)
                stills.append(str(f))
        r = subprocess.run([str(FACES)] + stills, capture_output=True, text=True, check=True)
        tmp = out_dir / ".faces.part.txt"
        tmp.write_text(r.stdout)
        tmp.replace(txt)
    return read_faces(txt)


def fill(p, shots, total_frames, log=print):
    """talking head: every stretch not covered by B-roll/graphics becomes presenter shots with punch-ins"""
    from ..core.io import load_json
    keep = load_json(p.output / "edl.json")["keep"]
    pieces, joins = cut_pieces(keep)
    cover = sorted((s["f0"], s["f1"]) for s in shots)
    stretches, t = [], 0
    for a, b in cover:
        if a - t > 1:
            stretches.append((t / FPS, a / FPS))
        t = max(t, b)
    if total_frames - t > 1:
        stretches.append((t / FPS, total_frames / FPS))
    F = face_boxes(p.output / f"cut_v{int(p.opt('version', 1))}.mp4", pieces, p.work / "montage" / "faces")
    pl, hold, rate = plan(stretches, joins, F, pieces)
    log(f"presenter: {len(pl)} shots in {len(stretches)} stretches, hold {hold} s, {rate:.1f} size changes per presenter-minute")
    return shots_from(pl)


shots_from = shots

"""Footage against its sentence (owner's decision of 22 Oct 2026, after «المملكة المتحدة تنهار» v2: a mural for a
motorcade, a housing estate for field hospitals, roubles for «one currency»). After the cut list is made, every footage shot
(video or photo) is looked at: its middle frame on a numbered contact sheet, with the sentence said over it; the brain
(judgement, montage/shot_review) names the shots whose picture does not show what their sentence says. Each such shot is
then taken out in code, one at a time and only when every other rule still holds: its asset leaves its block when the block
has others (the block's next clip shows instead), else the block gives that sentence to the presenter. Verdicts are kept
per (asset, sentence), so a second look only asks about new pairs.

  review(p, d, build, problems, sentences, log) -> (d, notes)
"""
import copy
import hashlib
import json
import subprocess

from ..core.io import load_json, save_json
from ..core.paths import CAIRO_FONT, FFMPEG

FPS = 24
PER_SHEET = 12
SCHEMA = {"type": "object", "required": ["mismatch"], "properties": {"mismatch": {"type": "array", "items": {
    "type": "object", "required": ["n", "why"], "properties": {"n": {"type": "integer"}, "why": {"type": "string"}}}}}}


def frame_of(s, out):
    """the shot's middle frame -> out (jpg, 480 px wide)"""
    if s["kind"] == "photo":
        src, at = s["src"], None
    else:
        src, at = s["src"], float(s.get("src_in", 0)) + (s["f1"] - s["f0"]) / FPS / 2
    cmd = [str(FFMPEG), "-v", "error", "-y"] + (["-ss", f"{at:.2f}"] if at is not None else []) + ["-i", src, "-frames:v", "1",
                                                                                                   "-vf", "scale=480:-2", str(out)]
    subprocess.run(cmd, capture_output=True)
    return out.exists()


def frame_name(s):
    """a frame's file named by the shot itself (its source and the time in it), never by its number on a sheet: a second
    run numbers other shots alike and showed the first run's frames under them (22 Oct 2026)"""
    k = f"{s.get('src')}|{s.get('src_in', 0)}|{s['f1'] - s['f0']}"
    return hashlib.sha1(k.encode()).hexdigest()[:16] + ".jpg"


def sheets(p, shots, folder, frames=None):
    """numbered contact sheets of the shots' frames (kept in frames, by frame_name) -> [jpg]"""
    from PIL import Image, ImageDraw, ImageFont
    folder.mkdir(parents=True, exist_ok=True)
    frames = frames or folder
    frames.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(CAIRO_FONT), 34)
    out = []
    for k in range(0, len(shots), PER_SHEET):
        part = shots[k:k + PER_SHEET]
        sheet = Image.new("RGB", (4 * 480, 3 * 300), (20, 20, 20))
        for j, (n, s) in enumerate(part):
            f = frames / frame_name(s)
            if not f.exists() and not frame_of(s, f):
                continue
            im = Image.open(f).convert("RGB").resize((480, 270))
            x, y = (j % 4) * 480, (j // 4) * 300
            sheet.paste(im, (x, y))
            ImageDraw.Draw(sheet).text((x + 8, y + 262), f"#{n}", fill=(255, 220, 0), font=font)
        p_ = folder / f"sheet_{k // PER_SHEET + 1:02d}.jpg"
        sheet.save(p_, quality=80)
        out.append(p_)
    return out


def sentence_text(sentences, t):
    s = [x for x in sentences if x["s"] <= t + 0.15 < x["e"]]
    return s[0]["text"] if s else ""


def review(p, d, build, problems, sentences, ask, log=print):
    """d: the timeline decision (snapped); build(d) -> edl; problems(d, edl) -> [problems] -> (d, notes)"""
    folder = p.work / "montage" / "shot_review"
    vf = folder / "verdicts.json"
    verdicts = load_json(vf) if vf.exists() else {}
    notes = []
    for rnd in range(2):
        edl = build(d)
        shots = [s for s in edl["shots"] if s["kind"] in ("video", "photo")]
        listing, todo = [], []
        for n, s in enumerate(shots, 1):
            t = s["f0"] / FPS
            text = sentence_text(sentences, t)
            key = f"{s['asset']}|{text[:80]}"
            listing.append((n, s, t, text, key))
            if key not in verdicts:
                todo.append((n, s, t, text, key))
        if todo:
            imgs = sheets(p, [(n, s) for n, s, *_ in todo], folder / f"round{rnd + 1}", folder / "frames")
            info = [{"n": n, "at_s": round(t, 1), "said": text, "picture_of": (s.get("fx") or {}).get("subject", "")} for n, s, t, text, _ in todo]
            save_json(folder / f"round{rnd + 1}" / "shots.json", info)
            ans = ask(p, "montage", f"shot_review_{rnd + 1}",
                      "FOOTAGE AGAINST ITS SENTENCE (owner's decision): look at the numbered contact sheets (each frame is a "
                      "footage shot's middle; #n under it) and shots.json (what is said over each shot, in Arabic). Name ONLY the "
                      "shots whose picture clearly does not show what its sentence says: the wrong thing (a mural for a motorcade, a "
                      "housing estate for field hospitals), the wrong country, currency or army, or a picture unrelated to the "
                      "sentence. A picture of the right place or a fitting general view is fine; do not name it. Give "
                      "mismatch = [{n, why}] (an empty list when every shot fits).",
                      {"mismatch": []}, read=[folder / f"round{rnd + 1}" / "shots.json"] + imgs, schema=SCHEMA,
                      fallback={"mismatch": []}, once=True)
            bad = {m["n"]: m["why"] for m in (ans or {}).get("mismatch", [])}
            for n, s, t, text, key in todo:
                verdicts[key] = bad.get(n, "ok")
            save_json(vf, verdicts)
        wrong = [(n, s, t, text, verdicts[key]) for n, s, t, text, key in listing if verdicts.get(key, "ok") != "ok"]
        if not wrong:
            break
        base = len(problems(d, edl))
        changed = False
        for n, s, t, text, why in wrong:
            done = False
            for mode in ("asset", "stretch"):   # its clip out of the block; else its stretch to the presenter (the block's
                d2 = copy.deepcopy(d)            # other clips repeating too often was what blocked the first, 22 Oct 2026)
                if not take_out(d2, s, t, mode):
                    continue
                edl2 = build(d2)
                if len(problems(d2, edl2)) <= base:
                    d, changed, done = d2, True, True
                    notes.append(f"{t:.1f} s {s['asset']}: out ({'the presenter instead; ' if mode == 'stretch' else ''}{why[:80]})")
                    break
            if not done:
                notes.append(f"{t:.1f} s {s['asset']}: kept, taking it out breaks another rule ({why[:60]})")
        if not changed:
            break
    for x in notes:
        log("shot review: " + x)
    return d, notes


def take_out(d, s, t, mode="asset"):
    """mode "asset": the shot's asset out of its F block (another of the block's clips shows instead) when it has others;
    "stretch" (or a block of that clip alone): the shot's stretch out of the block (the presenter shows instead) -> changed"""
    from .timeline import tag_of
    for b in d.get("blocks", []):
        if b[0] != "F" or not (b[2] - 0.05 <= t < b[3]):
            continue
        same = [a for a in b[1] if tag_of(a)[0].split("|")[0] == s["asset"]]
        if mode == "asset" and same and len(b[1]) > len(same):
            b[1] = [a for a in b[1] if a not in same]
            return True
        if mode == "asset" and same:
            pass                       # the block's only clip: its stretch goes (below)
        elif mode == "asset":
            return False
        t1 = s["f1"] / FPS
        if t - b[2] < 1.0 and b[3] - t1 < 1.0:
            d["blocks"] = [x for x in d["blocks"] if x is not b]
        elif t - b[2] < 1.0:
            b[2] = round(t1, 3)
        elif b[3] - t1 < 1.0:
            b[3] = round(t, 3)
        else:
            d["blocks"].append(["F", list(b[1]), round(t1, 3), b[3]] + list(b[4:]))
            b[3] = round(t, 3)
        return True
    return False


__all__ = ["review", "json"]

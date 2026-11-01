"""Running subtitles in the intro (phase 2D of the channel profiles; owner's answer 10 of phase 2A: on for الحدث الأخير and
الملفات السرية, in the intro only, white at the bottom, spelled from the approved script). Read from the profile's
"montage" -> text.subtitles; a profile without it (general «عام») and a project with no profile get none.

  text.subtitles = {"intro": true, "style": "phrases" | "lines", "max_words": n, "max_chars": n, "size": px,
                    "weight": 100-1000, "y": px (the line's centre on a 1080p frame),
                    "outline": {"color", "width"} (optional: a thin outline around the letters)}

What is shown: only the script's words that were SAID (montage/scripttext.py Aligner: each spoken word -> the script's
spelling of it), in the narration's order, from the start to the fast intro's end (montage/structure.py). A cue breaks
at a pause in the speech (0.35 s or more), at the style's word or character limit, and never runs past the intro's end.
Each cue shows 2 frames before its first word (like a cut) and stays until the next cue, or 0.4 s after its last word.
Without an approved script there are no subtitles (the report says so): whisper's spelling is never shown.

The cues are drawn by our graphics renderer (gfx: white, weight from the profile, a soft dark shadow) as one still each,
cropped to the text, and laid over the finished video at the final step (montage/steps.py step_final), so they sit over
footage, graphics and the presenter alike. -> work/montage/subtitles.json, work/montage/subtitles/sub_NNN.png
"""
import json
from pathlib import Path

FPS = 24
LEAD = 2 / FPS
GAP_BREAK = 0.35


def config(p):
    """the profile's subtitles, or None"""
    m = p.profile_montage() if p is not None else {}
    sub = ((m.get("text") or {}).get("subtitles")) or {}
    return sub if sub.get("intro") else None


def cues(p, words, until):
    """[{"text", "from", "to", "w0", "w1"}] over 0..until s, in the script's spelling; [] without an approved script"""
    from .scripttext import Aligner
    cfg = config(p)
    if not cfg or not until:
        return []
    al = Aligner(p, words)
    if not al.active:
        return []
    maxw, maxc = int(cfg.get("max_words", 6)), int(cfg.get("max_chars", 60))
    said = [(i, al.st[al.map[i]]) for i, w in enumerate(words) if i in al.map and w["s"] < until - 0.1]
    out, cur = [], []

    def flush():
        if cur:
            out.append({"w0": cur[0][0], "w1": cur[-1][0], "text": " ".join(t for _, t in cur)})
    for k, (i, tok) in enumerate(said):
        if cur:
            prev = cur[-1][0]
            gap = words[i]["s"] - words[prev]["e"]
            too_long = len(cur) >= maxw or len(" ".join(t for _, t in cur)) + 1 + len(tok) > maxc
            if gap >= GAP_BREAK or too_long or i != prev + 1:        # i != prev + 1: a word said that the script lacks
                flush()
                cur = []
        cur.append((i, tok))
    flush()
    for k, c in enumerate(out):
        a = max(0.0, words[c["w0"]]["s"] - LEAD)
        end = words[c["w1"]]["e"] + 0.4
        if k + 1 < len(out):
            nxt = max(0.0, words[out[k + 1]["w0"]]["s"] - LEAD)
            end = nxt if nxt - words[c["w1"]]["e"] < 1.0 else min(end, nxt)
        c["from"], c["to"] = round(a, 3), round(min(end, until), 3)
    return [c for c in out if c["to"] - c["from"] >= 0.25]


def outline(cfg):
    """a thin dark outline around the letters when the profile asks for one (الملفات السرية, owner's answer 4 of 2D)"""
    o = cfg.get("outline")
    return {"stroke": o.get("color", "#000000"), "width": float(o.get("width", 4))} if o else {}


def build(p, words, until, out_dir, record):
    """draw the cues and return the overlays for the final encode: [{"file", "x", "y", "from", "to"}]"""
    import numpy as np
    from PIL import Image
    from . import graphics
    cfg = config(p)
    cs = cues(p, words, until)
    out_dir = Path(out_dir)
    if not cs:
        Path(record).write_text(json.dumps({"cues": [], "why": "no approved script" if cfg else "off for this channel"},
                                           ensure_ascii=False, indent=1), encoding="utf-8")
        return []
    size, weight, y = float(cfg.get("size", 56)), float(cfg.get("weight", 800)), float(cfg.get("y", 930))
    scenes = [{"name": f"sub_{k:03d}", "t_in": 0.0, "t_out": round(1 / FPS, 4), "frames": 1, "bg": "none",
               "items": [{"type": "text", "text": c["text"], "x": 960, "y": y, "size": size, "weight": weight, "color": "#FFFFFF",
                          "shadow": 10, "t0": -1.0, "w": 1700, **outline(cfg)}]} for k, c in enumerate(cs)]
    graphics.render(scenes, out_dir / "frames", log=lambda *a: None)
    ovs = []
    for k, c in enumerate(cs):
        im = Image.open(out_dir / "frames" / f"sub_{k:03d}" / "00000.png").convert("RGBA")
        a = np.asarray(im)[..., 3]
        ys, xs = np.nonzero(a > 4)
        x0, y0, x1, y1 = max(0, xs.min() - 4), max(0, ys.min() - 4), min(1920, xs.max() + 5), min(1080, ys.max() + 5)
        f = out_dir / f"sub_{k:03d}.png"
        im.crop((x0, y0, x1, y1)).save(f)
        c.update(file=str(f), x=int(x0), y=int(y0), w=int(x1 - x0), h=int(y1 - y0))
        ovs.append({"file": str(f), "x": int(x0), "y": int(y0), "from": c["from"], "to": c["to"]})
    Path(record).write_text(json.dumps({"note": "running subtitles in the intro, spelled from the approved script (montage/subtitles.py)",
                                        "until_s": round(until, 3), "style": cfg, "cues": cs}, ensure_ascii=False, indent=1), encoding="utf-8")
    return ovs


__all__ = ["config", "cues", "build"]

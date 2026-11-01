"""A channel's identity files rebuilt from its own published videos (phase 2B of the channel profiles, owner's answers of
18 Oct 2026: logos rebuilt from the reference videos "for now", the stings extracted from them, the intro made 24 fps).
Run by hand from the engine folder; nothing here is a step of bin/monteer run.

  logo VIDEO --box X0 Y0 X1 Y1 --out DIR [--from S] [--to S] [--frames N]
        a logo that stays still while the picture behind it changes. Frames are sampled over [from, to] and the ones
        whose background differs most are kept; a pixel that stays the same over them is the logo (alpha from how little
        it moves against how much the background moves), its colour is their median. -> DIR/logo_src.png (as found, the
        video's own size), DIR/logo_1080.png (scaled to a 1920x1080 frame, clean edges), DIR/logo.json (where it sits:
        box, corner, margins, in the source's pixels and in 1080p)
  logo VIDEO --box … --out DIR --ref S [--from S] [--to S]
        a logo that changes shape in place over a background that does NOT change (a presenter's studio): the frames
        that look like the one at --ref are the logo, the others give the background behind it
  clip VIDEO --from S --to S --out FILE.mp4
        a stretch of a video as a montage-ready piece: 1920x1080, 24 fps, H.264 with BT.709 tags, its own sound (AAC) +
        FILE.wav (48 kHz) for the mix
  conform VIDEO --out FILE.mp4      the same, the whole video (e.g. a 60 fps intro to 24 fps; no sound added)
  sheet VIDEO --out FILE.jpg [--from S] [--to S] [--n N]      a contact sheet of N frames with their times

The reference videos are small (854x480 or 640x360), so what is rebuilt is soft when scaled to 1080p: a stand-in until
the channel's own files arrive.
"""
import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from ..core.paths import FFMPEG, FFPROBE

FF, FP = str(FFMPEG), str(FFPROBE)
TAIL = "setsar=1,format=yuv420p,setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709"


def probe(f):
    out = subprocess.run([FP, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate",
                          "-show_entries", "format=duration", "-of", "json", str(f)], capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    s = j["streams"][0]
    return int(s["width"]), int(s["height"]), s["r_frame_rate"], float(j["format"]["duration"])


def grab(f, t, box=None):
    """one frame at t (rgb uint8), optionally only the box (x0, y0, x1, y1)"""
    w, h, _, _ = probe(f) if box is None else (box[2] - box[0], box[3] - box[1], 0, 0)
    vf = ["-vf", f"format=rgb24,crop={box[2] - box[0]}:{box[3] - box[1]}:{box[0]}:{box[1]}"] if box else []   # rgb first: odd sizes stay exact
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{t:.3f}", "-i", str(f), "-frames:v", "1"] + vf +
                         ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(h, w, 3) if len(raw) == w * h * 3 else None


def sample(f, box, t0, t1, n):
    ts = [t0 + (t1 - t0) * (i + 0.5) / n for i in range(n)]
    got = [(t, grab(f, t, box)) for t in ts]
    return [t for t, a in got if a is not None], np.stack([a for _, a in got if a is not None]).astype(np.float32)


def thumb(a, k=6):
    h, w = a.shape[:2]
    return a[:h - h % k, :w - w % k].reshape(k, h // k, k, w // k, 3).mean(axis=(1, 3))


def diverse(fr, most=40):
    """the frames whose picture differs most from each other (greedy: farthest first)"""
    th = np.stack([thumb(a) for a in fr])
    keep = [0]
    dist = np.abs(th - th[0]).mean(axis=(1, 2, 3))
    while len(keep) < min(most, len(fr)):
        j = int(np.argmax(dist))
        if dist[j] < 6:
            break
        keep.append(j)
        dist = np.minimum(dist, np.abs(th - th[j]).mean(axis=(1, 2, 3)))
    return keep


def clean_edges(rgb, alpha):
    """colours of half-transparent edge pixels taken from the nearest solid logo pixel (no background fringe)"""
    from scipy.ndimage import distance_transform_edt
    solid = alpha >= 0.9
    if not solid.any():
        return rgb
    _, (iy, ix) = distance_transform_edt(~solid, return_indices=True)
    return rgb[iy, ix]


def smooth_alpha(a, size):
    """graded alpha -> smooth upscale -> a narrow ramp at 0.5: clean anti-aliased edges at the target size
    (as montage/logo.py rebuilds a logo)"""
    m = Image.fromarray((a * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6))
    big = np.asarray(m.resize((size[0] * 4, size[1] * 4), Image.BICUBIC)).astype(np.float32) / 255
    r = np.clip((big - 0.5) / 0.08 + 0.5, 0, 1)
    return np.asarray(Image.fromarray((r * 255).astype(np.uint8)).resize(size, Image.LANCZOS)).astype(np.float32) / 255


def cmd_logo(a):
    from scipy.ndimage import binary_dilation, binary_fill_holes, label
    W, H, _, D = probe(a.video)
    box = tuple(a.box)
    t0, t1 = a.t_from or 0.0, a.t_to or D - 2
    ts, fr = sample(a.video, box, t0, t1, a.frames)
    if a.ref is None:                                  # still logo, changing background
        keep = diverse(fr)
        sel = fr[keep]
        med = np.median(sel, axis=0)
        dev = np.abs(sel - med).mean(axis=3)           # [n, h, w]
        spread = np.median(dev, axis=0)
        ref = np.percentile(spread, 70)                # the background's own movement (most of the box is background)
        alpha = np.clip(1 - spread / max(ref, 1e-3), 0, 1)
        alpha = np.clip((alpha - 0.35) / 0.4, 0, 1)
        how = {"method": "still logo over changing pictures", "frames_used": len(keep), "times": [round(ts[k], 1) for k in keep]}
    else:                                              # changing logo, still background
        rf = grab(a.video, a.ref, box).astype(np.float32)
        d = np.abs(fr - rf).mean(axis=(1, 2, 3))
        lo = d < np.percentile(d, 20) + 3
        hi = d > np.percentile(d, 60)
        med = np.median(fr[lo], axis=0)
        plate = np.median(fr[hi], axis=0)
        diff = np.abs(med - plate).mean(axis=2)
        alpha = np.clip((diff - 8) / 16, 0, 1)
        solid = binary_fill_holes(alpha > 0.5)
        alpha = np.where(solid & (alpha < 0.5), 1.0, alpha)
        how = {"method": "changing logo over a still background", "ref_s": a.ref, "logo_frames": int(lo.sum()),
               "background_frames": int(hi.sum())}
    lab, n = label(alpha > 0.5)
    sizes = np.bincount(lab.ravel())
    if n == 0:
        raise SystemExit("no still logo found in the box")
    # the logo is the biggest piece and every piece within a few pixels of what is kept (letters, dots); loose specks of
    # a still background (a plant, a lamp) farther away are dropped
    keep = {int(np.argmax(sizes[1:])) + 1}
    while True:
        near = binary_dilation(np.isin(lab, list(keep)), iterations=a.join_px)
        more = {int(i) for i in np.unique(lab[near]) if i and sizes[i] >= 3} - keep
        if not more:
            break
        keep |= more
    alpha = alpha * binary_dilation(np.isin(lab, list(keep)), iterations=1)
    ys, xs = np.nonzero(alpha > 0.5)
    if not len(xs):
        raise SystemExit("no still logo found in the box")
    y0, y1 = int(max(0, ys.min() - 2)), int(min(alpha.shape[0], ys.max() + 3))
    x0, x1 = int(max(0, xs.min() - 2)), int(min(alpha.shape[1], xs.max() + 3))
    rgb, al = clean_edges(med, alpha)[y0:y1, x0:x1], alpha[y0:y1, x0:x1]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.dstack([rgb, al * 255]).clip(0, 255).astype(np.uint8), "RGBA").save(out / "logo_src.png")
    s = 1080 / H
    size = (round((x1 - x0) * s), round((y1 - y0) * s))
    big_rgb = np.asarray(Image.fromarray(rgb.clip(0, 255).astype(np.uint8)).resize(size, Image.LANCZOS)).astype(np.float32)
    Image.fromarray(np.dstack([big_rgb, smooth_alpha(al, size) * 255]).clip(0, 255).astype(np.uint8), "RGBA").save(out / "logo_1080.png")
    gx0, gy0 = box[0] + x0, box[1] + y0
    gx1, gy1 = box[0] + x1, box[1] + y1
    right = (gx0 + gx1) / 2 > W / 2
    rec = {"video": str(a.video), "video_size": [W, H], "search_box": list(box), "span_s": [round(t0, 1), round(t1, 1)], **how,
           "source_px": {"x": gx0, "y": gy0, "w": gx1 - gx0, "h": gy1 - gy0},
           "corner": ("top" if gy0 < H / 2 else "bottom") + "-" + ("right" if right else "left"),
           "at_1080": {"x": round(gx0 * s), "y": round(gy0 * s), "w": size[0], "h": size[1],
                       "margin_side": round((W - gx1 if right else gx0) * s), "margin_top": round(gy0 * s),
                       "width_share": round(size[0] / 1920, 4)}}
    (out / "logo.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: rec[k] for k in ("corner", "source_px", "at_1080")}, ensure_ascii=False))


def encode(src, out, t_from=None, t_to=None, sound=True):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cut = (["-ss", f"{t_from:.3f}"] if t_from is not None else []) + (["-to", f"{t_to:.3f}"] if t_to is not None else [])
    vf = f"fps=24,scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,{TAIL}"
    tmp = out.with_name("." + out.name + ".part.mp4")
    a = ["-c:a", "aac", "-b:a", "256k", "-ar", "48000"] if sound else ["-an"]
    subprocess.run([FF, "-v", "error", "-y", "-i", str(src)] + cut + ["-vf", vf, "-c:v", "libx264", "-preset", "slow", "-crf", "14",
                    "-r", "24"] + a + ["-movflags", "+faststart", str(tmp)], check=True)
    tmp.replace(out)
    if sound:
        subprocess.run([FF, "-v", "error", "-y", "-i", str(src)] + cut + ["-vn", "-ac", "2", "-ar", "48000", "-c:a", "pcm_s24le",
                        str(out.with_suffix(".wav"))], check=True)


def cmd_sheet(a):
    W, H, _, D = probe(a.video)
    t0, t1 = a.t_from or 0.0, a.t_to or D
    n = a.n
    ts = [t0 + (t1 - t0) * (i + 0.5) / n for i in range(n)]
    tw, th = 384, round(384 * H / W)
    cols = min(n, 6)
    sheet = Image.new("RGB", (cols * tw, ((n + cols - 1) // cols) * (th + 22)), (20, 20, 20))
    d = ImageDraw.Draw(sheet)
    for i, t in enumerate(ts):
        fr = grab(a.video, t)
        if fr is None:
            continue
        x, y = (i % cols) * tw, (i // cols) * (th + 22)
        sheet.paste(Image.fromarray(fr).resize((tw, th), Image.LANCZOS), (x, y))
        d.text((x + 6, y + th + 4), f"{t:.2f} s", fill=(230, 230, 230))
    sheet.save(a.out, quality=90)


def main():
    ap = argparse.ArgumentParser(prog="channel_identity")
    sub = ap.add_subparsers(dest="cmd", required=True)
    lg = sub.add_parser("logo")
    lg.add_argument("video")
    lg.add_argument("--box", type=int, nargs=4, required=True)
    lg.add_argument("--out", required=True)
    lg.add_argument("--from", dest="t_from", type=float)
    lg.add_argument("--to", dest="t_to", type=float)
    lg.add_argument("--frames", type=int, default=160)
    lg.add_argument("--ref", type=float)
    lg.add_argument("--join-px", dest="join_px", type=int, default=14, help="pieces this close to the logo belong to it")
    for name in ("clip", "conform"):
        c = sub.add_parser(name)
        c.add_argument("video")
        c.add_argument("--out", required=True)
        if name == "clip":
            c.add_argument("--from", dest="t_from", type=float, required=True)
            c.add_argument("--to", dest="t_to", type=float, required=True)
    sh = sub.add_parser("sheet")
    sh.add_argument("video")
    sh.add_argument("--out", required=True)
    sh.add_argument("--from", dest="t_from", type=float)
    sh.add_argument("--to", dest="t_to", type=float)
    sh.add_argument("--n", type=int, default=18)
    a = ap.parse_args()
    if a.cmd == "logo":
        cmd_logo(a)
    elif a.cmd == "clip":
        encode(a.video, a.out, a.t_from, a.t_to)
    elif a.cmd == "conform":
        encode(a.video, a.out, sound=bool(subprocess.run([FP, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                                                              "-of", "csv=p=0", a.video], capture_output=True, text=True).stdout.strip()))
    elif a.cmd == "sheet":
        cmd_sheet(a)


if __name__ == "__main__":
    main()

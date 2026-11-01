"""The pop-ups of اقتصاد احمس that our graphics renderer cannot draw, made frame by frame here (phase 2F part 2; owner's
answers of 18 Oct 2026, matched to the channel's episodes v01-v03):

  flag     the public-domain flag waving gently: a travelling wave along the fly (the hoist side still), with the
           cloth's light and shade following it; a quick fade and a slight grow in, a fade out
  photo    (and news) the framed picture in the channel's tan frame, revealed by diagonal light stripes in about 0.2 s
           and leaving the same way in about 0.25 s (measured at 52.5 s and 57.7 s of v01)

The frames go where the graphics step puts every scene's frames (work/montage/gfx/frames/<scene>/%05d.png, full 1920x1080
with transparency) with the graphics step's own "done" stamp for that scene, so the step keeps them; a scene whose frames
are missing is drawn by the renderer from its plain items instead (a still flag or a framed photo).
"""
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

FPS = 24
FRAME = "#C8B48C"                 # the channel's tan photo frame (measured on v01 at 53 s)
BORDER = 16                       # px at 1080p
IN_S, OUT_S = 0.20, 0.25          # the stripes in, the stripes out
PERIOD = 46                       # the stripes' spacing, px


def ease(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


def fit(w, h, box, pad=0):
    x0, y0, x1, y1 = box
    k = min((x1 - x0 - 2 * pad) / w, (y1 - y0 - 2 * pad) / h)
    return max(1, round(w * k)), max(1, round(h * k))


def flag_frames(png, box, n):
    """[RGBA 1920x1080] of a gently waving flag in the box"""
    from scipy.ndimage import map_coordinates
    src = Image.open(png).convert("RGBA")
    A = 0.06                                            # the wave's height, a share of the flag's height
    w, h = fit(src.width, src.height * (1 + 2 * A), box)
    h0 = round(h / (1 + 2 * A))
    flag = np.asarray(src.resize((w, h0), Image.LANCZOS)).astype(np.float32)
    amp = A * h0
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    along = xx / max(1, w - 1)                          # 0 at the hoist (still), 1 at the fly
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    out = []
    for f in range(n):
        t = f / FPS
        ph = 2 * math.pi * (along * 1.15 - 1.1 * t)
        dy = amp * np.sin(ph) * along ** 0.8
        sy = yy - amp - dy                              # where each output pixel looks in the flat flag
        layers = [map_coordinates(flag[..., c], [sy, xx], order=1, mode="constant", cval=0) for c in range(4)]
        img = np.stack(layers, axis=-1)
        shade = 1 + 0.16 * np.cos(ph) * along ** 0.6    # light on the crests, shade in the troughs
        img[..., :3] = np.clip(img[..., :3] * shade[..., None], 0, 255)
        a_in, a_out = ease(t / 0.25), 1 - ease((t - (n / FPS - 0.25)) / 0.25)
        img[..., 3] *= min(a_in, a_out)
        s = 0.94 + 0.06 * ease(t / 0.35)
        im = Image.fromarray(img.astype(np.uint8), "RGBA")
        if s < 0.999:
            im = im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
        canvas = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
        sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
        sh.putalpha(im.getchannel("A").point(lambda v: int(v * 0.45)))
        sh = sh.filter(ImageFilter.GaussianBlur(10))
        px, py = round(cx - im.width / 2), round(cy - im.height / 2)
        canvas.alpha_composite(sh, (px + 6, py + 10))
        canvas.alpha_composite(im, (px, py))
        out.append(canvas)
    return out


def framed(png, box):
    """the picture in the channel's tan frame, fitted in the box -> RGBA"""
    src = Image.open(png).convert("RGB")
    w, h = fit(src.width, src.height, box, pad=BORDER + 4)
    im = Image.new("RGBA", (w + 2 * BORDER, h + 2 * BORDER), FRAME)
    im.paste(src.resize((w, h), Image.LANCZOS), (BORDER, BORDER))
    d = ImageDraw.Draw(im)
    d.rectangle([BORDER - 3, BORDER - 3, BORDER + w + 2, BORDER + h + 2], outline="#8E7A55", width=3)   # the frame's inner edge
    return im


def stripes(size, p, reverse=False):
    """the diagonal stripe mask of a reveal at progress p (0 hidden .. 1 shown): each stripe fills from its edge"""
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w]
    phase = ((xx + yy) % PERIOD) / PERIOD
    if reverse:
        phase = 1 - phase
    k = ease(p) * 1.15 - 0.075
    m = np.clip((k - phase) * 12, 0, 1)
    edge = np.clip(1 - np.abs(k - phase) * 10, 0, 1) * (0 < p < 1)   # the light on each stripe's moving edge
    return m, edge


def photo_frames(png, box, n):
    """[RGBA 1920x1080] of a framed picture revealed by stripes and leaving the same way"""
    pic = framed(png, box)
    arr = np.asarray(pic).astype(np.float32)
    x0, y0, x1, y1 = box
    px, py = round((x0 + x1) / 2 - pic.width / 2), round((y0 + y1) / 2 - pic.height / 2)
    shadow = Image.new("RGBA", pic.size, (0, 0, 0, 120)).filter(ImageFilter.GaussianBlur(1))
    out, dur = [], n / FPS
    for f in range(n):
        t = f / FPS
        if t < IN_S:
            m, edge = stripes(pic.size, t / IN_S)
        elif t > dur - OUT_S:
            m, edge = stripes(pic.size, 1 - (t - (dur - OUT_S)) / OUT_S, reverse=True)
        else:
            m, edge = np.ones(arr.shape[:2]), np.zeros(arr.shape[:2])
        img = arr.copy()
        img[..., :3] = img[..., :3] * (1 - 0.55 * edge[..., None]) + 255 * 0.55 * edge[..., None]
        img[..., 3] = 255 * np.maximum(m, 0.35 * edge)
        im = Image.fromarray(img.astype(np.uint8), "RGBA")
        canvas = Image.new("RGBA", (1920, 1080), (0, 0, 0, 0))
        if m.mean() > 0.98:
            canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(12)), (px + 8, py + 12))
        canvas.alpha_composite(im, (px, py))
        out.append(canvas)
    return out


def render(scenes, frames_dir, log=print):
    """the frames of every scene that carries "art" (flag, photo, news), with the graphics step's own stamp"""
    from .graphics import scene_sig
    frames_dir = Path(frames_dir)
    made = 0
    for sc in scenes:
        art = sc.get("art")
        if not art or art["kind"] not in ("flag", "photo", "news"):
            continue
        body = {k: v for k, v in sc.items() if k != "out"}
        sig = scene_sig(body)
        final, stamp = frames_dir / sc["name"], frames_dir / f".{sc['name']}.done"
        if final.is_dir() and stamp.exists() and stamp.read_text() == sig and len(list(final.glob("*.png"))) == sc["frames"]:
            continue
        tmp = frames_dir / f".{sc['name']}.part"
        if tmp.exists():
            import shutil
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True)
        fr = (flag_frames if art["kind"] == "flag" else photo_frames)(art["png"], tuple(art["box"]), sc["frames"])
        for i, im in enumerate(fr):
            im.save(tmp / f"{i:05d}.png", optimize=False, compress_level=3)
        if final.exists():
            import shutil
            shutil.rmtree(final)
        tmp.replace(final)
        stamp.write_text(sig)
        made += 1
    log(f"pop-up art: {made} scene(s) drawn frame by frame (waving flags, striped reveals)")


__all__ = ["render", "flag_frames", "photo_frames", "framed", "stripes"]

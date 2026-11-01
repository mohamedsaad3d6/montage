"""Rule 21 textures, made in code (no download, no licence): a warm paper background for history cards and headline
cards, and a soft paper overlay for archive photos. Film grain itself is added with ffmpeg's noise filter at render time.

    textures.main(out_dir, seed)   -> out_dir/paper.png (1920x1080 background), paper_overlay.png (grey, soft-light blend)
Runs in the ml environment (the numpy/Pillow versions that made the earlier textures). The seed varies the texture per
video (variety); seed 73 gives the texture of the earlier videos.
"""
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

W, H = 1920, 1080
rng = np.random.default_rng(73)


def reseed(seed):
    global rng
    rng = np.random.default_rng(seed)


def blur(a, r):
    return np.asarray(Image.fromarray(np.clip(a * 255, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(r))).astype(np.float32) / 255


def fibres(n=2600):
    """thin light and dark strokes, like paper fibres"""
    im = Image.new("L", (W, H), 128)
    from PIL import ImageDraw
    d = ImageDraw.Draw(im)
    for _ in range(n):
        x, y = rng.uniform(0, W), rng.uniform(0, H)
        a = rng.uniform(0, np.pi)
        L = rng.uniform(6, 40)
        v = int(128 + rng.choice([-1, 1]) * rng.uniform(6, 22))
        d.line([(x, y), (x + L * np.cos(a), y + L * np.sin(a))], fill=v, width=1)
    return np.asarray(im.filter(ImageFilter.GaussianBlur(0.6))).astype(np.float32) / 255 - 0.5


def main(OUT, seed=73):
    OUT = Path(OUT)
    reseed(seed)
    OUT.mkdir(parents=True, exist_ok=True)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    # large soft blotches + fine grain + fibres + a gentle vignette
    up = lambda gw, gh: np.asarray(Image.fromarray((rng.random((gh, gw)) * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)).astype(np.float32) / 255 - 0.5  # noqa: E731
    blot = up(10, 6)          # large soft stains
    blot2 = up(60, 34)        # smaller mottling
    fine = rng.normal(0, 1, (H, W)).astype(np.float32)
    fib = fibres()
    vig = 1 - 0.20 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    lum = (1.0 + 0.10 * blot + 0.025 * blot2 + 0.018 * fine + 0.35 * fib) * vig
    base = np.array([242, 229, 203], np.float32) / 255           # warm off-white
    warm = np.stack([np.zeros_like(blot), 0.02 * blot, 0.06 * blot], -1)   # stains a little more yellow-brown
    paper = np.clip(lum[..., None] * base[None, None, :] - warm, 0, 1)
    Image.fromarray((paper * 255).astype(np.uint8)).save(OUT / ".paper.part.png")
    # overlay for photos: mid-grey with the same structure (used with a soft-light blend, so 0.5 = no change)
    ov = np.clip(0.5 + 0.22 * blot + 0.10 * blot2 + 0.03 * fine + 0.40 * fib - 0.25 * (1 - vig), 0, 1)
    Image.fromarray((ov * 255).astype(np.uint8)).save(OUT / ".paper_overlay.part.png")
    import os
    os.replace(OUT / ".paper.part.png", OUT / "paper.png")
    os.replace(OUT / ".paper_overlay.part.png", OUT / "paper_overlay.png")
    print("written", OUT)


if __name__ == "__main__":
    import sys
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 73)

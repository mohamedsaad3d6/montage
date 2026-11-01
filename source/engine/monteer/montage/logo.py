"""A channel's logo, taken from its own published video: the logo stays fixed while the picture behind it changes, so over
many frames its pixels barely vary. Those pixels give the logo's shape; their median gives its colours. The two colour
layers (a dark/grey one and a red one) are rebuilt 4x larger with clean edges (smooth upscale of each layer's mask, then
a soft threshold), because a logo in a 720p video is only ~225x110 px. The result goes into the channel profile.

    <ml python> -m monteer.montage.logo VIDEO OUT_FOLDER X Y W H      (search box in the video's own pixels)
-> OUT_FOLDER/logo_src_crop.png (as found), logo_4x.png (rebuilt, transparent), logo_mask_debug.png
"""
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

import sys

from monteer.core.paths import FFMPEG

SRC = Path(sys.argv[1])
OUT = Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
X, Y, CW, CH = (int(v) for v in sys.argv[3:7])          # search box in the source video's pixels
raw = subprocess.run([str(FFMPEG), "-v", "error", "-i", str(SRC), "-vf", f"fps=1/4,crop={CW}:{CH}:{X}:{Y}",
                      "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
fr = np.frombuffer(raw, np.uint8).reshape(-1, CH, CW, 3).astype(np.float32)
med = np.median(fr, axis=0)
dev = np.median(np.abs(fr - med), axis=0).mean(axis=2)          # typical change of each pixel over time
still = dev < 6
r, g, b = med[..., 0], med[..., 1], med[..., 2]
red = still & (r > 140) & (r - g > 70) & (r - b > 60)
grey = still & (r < 110) & (g < 110) & (b < 110) & (np.abs(r - g) < 25)
ys, xs = np.nonzero(red | grey)
x0, x1, y0, y1 = xs.min() - 4, xs.max() + 5, ys.min() - 4, ys.max() + 5
Image.fromarray(med[y0:y1, x0:x1].astype(np.uint8)).save(OUT / "logo_src_crop.png")
dbg = np.zeros((CH, CW, 3), np.uint8); dbg[grey] = (90, 90, 90); dbg[red] = (220, 30, 40)
Image.fromarray(dbg).resize((CW * 3, CH * 3), Image.NEAREST).save(OUT / "logo_mask_debug.png")
col_red = tuple(int(v) for v in np.median(med[red], axis=0))
col_grey = tuple(int(v) for v in np.median(med[grey], axis=0))
S = 4
h, w = y1 - y0, x1 - x0


def layer(soft):
    """graded mask (0..1, anti-aliased like the source) -> 16x smooth upscale -> threshold at 0.5 with a narrow ramp
    -> down to 4x: clean, anti-aliased edges that follow the source's own sub-pixel edge"""
    m = Image.fromarray((soft[y0:y1, x0:x1] * 255).astype(np.uint8)).filter(__import__("PIL.ImageFilter", fromlist=["x"]).GaussianBlur(0.7))
    big = np.asarray(m.resize((w * 16, h * 16), Image.BICUBIC)).astype(np.float32) / 255
    a = np.clip((big - 0.5) / 0.06 + 0.5, 0, 1)
    return np.asarray(Image.fromarray((a * 255).astype(np.uint8)).resize((w * S, h * S), Image.LANCZOS)).astype(np.float32) / 255


# graded masks from the median frame: how far each pixel has moved from the background towards the logo colour
near = np.zeros_like(still)
near[max(0, y0 - 1):y1 + 1, max(0, x0 - 1):x1 + 1] = True
from scipy.ndimage import binary_dilation  # noqa: E402
zone_r = binary_dilation(red, iterations=2)
zone_g = binary_dilation(grey, iterations=2)
bg = np.median(med[~binary_dilation(red | grey, iterations=4) & near], axis=0)
rg = med[..., 0] - med[..., 1]
soft_red = np.clip((rg - (bg[0] - bg[1])) / ((col_red[0] - col_red[1]) - (bg[0] - bg[1])), 0, 1) * zone_r
lum = med.mean(axis=2)
soft_grey = np.clip((bg.mean() - lum) / (bg.mean() - np.mean(col_grey)), 0, 1) * zone_g * (rg < 60)
ar, ag = layer(soft_red), layer(soft_grey)
out = np.zeros((h * S, w * S, 4), np.float32)
for a, c in ((ag, col_grey), (ar, col_red)):
    out[..., :3] = out[..., :3] * (1 - a[..., None]) + np.array(c) * a[..., None]
    out[..., 3] = np.maximum(out[..., 3], a * 255)
Image.fromarray(out.clip(0, 255).astype(np.uint8)).save(OUT / "logo_4x.png")
print("frames", len(fr), "box", (x0 + X, y0 + Y, w, h), "red", col_red, "grey", col_grey, "out", (w * S, h * S))

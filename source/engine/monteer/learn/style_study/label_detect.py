"""The channel's key-word label: a beige paper box with dark Arabic text, bottom-right (names, places, numbers).

    <core python> -m monteer.learn.style_study.label_detect <video.mp4> <out.npy>

For every 2 fps frame, a crop of the bottom-right corner is checked for a beige box (bright, warm, low
saturation) holding dark text, with ordinary picture around it. Saves a 0/1 array per frame (usually as
<channel dir>/feat/<id>/labels.npy, read by channel_summary). Decodes the whole video (heavy).
"""
import argparse
import subprocess

import numpy as np

from ...core.paths import FFMPEG

FF = str(FFMPEG)
CW, CH = 96, 48    # crop x 0.66-0.98, y 0.62-0.95 of the frame


def crops(path):
    raw = subprocess.run([FF, "-v", "error", "-i", path, "-vf",
                          f"fps=2,crop=iw*0.32:ih*0.33:iw*0.66:ih*0.62,scale={CW}:{CH}:flags=area",
                          "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, CH, CW, 3).astype(np.int16)


def detect(X):
    R, G, B = X[..., 0], X[..., 1], X[..., 2]
    beige = (R > 200) & (G > 185) & (B > 150) & (R - B > 10) & (R - B < 70) & (R >= G - 5)
    box = beige[:, 18:38, 20:88]
    fill = box.mean((1, 2))
    # text strokes: brownish pixels inside the box rows (between beige on both sides)
    ink = ((R < 190) & (R - B > 15))[:, 22:34, 26:82]
    txt = ink.mean((1, 2))
    # the box has an edge: just left of it the picture is not beige
    left = beige[:, 18:38, 2:10].mean((1, 2))
    return ((fill > 0.45) & (txt > 0.03) & (txt < 0.35) & (left < 0.6)).astype(np.uint8)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Find the channel's key-word label in every 2 fps frame.")
    ap.add_argument("video", help="a published video (.mp4)")
    ap.add_argument("out", help="output .npy (0/1 per 2 fps frame)")
    opt = ap.parse_args()
    np.save(opt.out, detect(crops(opt.video)))

"""Per-video features for the channel study (published videos only; montage layer and pacing).

    <core python> -m monteer.learn.style_study.channel_extract <video.mp4> <out_dir>

Saves, so the downloaded video itself can be deleted afterwards:
  g2.npy      2 fps grey 128x72 frames         c2.npy  2 fps colour 32x18 frames
  diff.npy    full-rate frame difference (64x36 grey), for hard cuts / flashes
  db.npy      10 ms audio level (16 kHz mono)
  sheet_*.jpg contact sheets, one frame every 10 s, for looking at the on-screen style
  meta.json   duration, fps, size
Decodes the whole video (heavy).
"""
import argparse
import json
import subprocess
from pathlib import Path

import numpy as np

from ...core.paths import FFMPEG, FFPROBE
from . import reg

FF, FP = str(FFMPEG), str(FFPROBE)
SHEET_FONT = "/System/Library/Fonts/Supplemental/Arial.ttf"   # macOS system font for the time stamps on the sheets


def main(src, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    probe = subprocess.run([FP, "-v", "error", "-show_entries",
                            "stream=codec_type,width,height,r_frame_rate:format=duration", "-of", "json", src],
                           capture_output=True, text=True, check=True)
    meta = json.loads(probe.stdout)
    v = [s for s in meta["streams"] if s["codec_type"] == "video"][0]
    W, H = int(v["width"]), int(v["height"])
    vertical = H > W
    size = (72, 128) if vertical else (128, 72)
    np.save(out / "g2.npy", reg.frames(src, fps=2, size=size))
    np.save(out / "c2.npy", reg.frames(src, fps=2, size=(18, 32) if vertical else (32, 18), gray=False))
    G = reg.frames(src, size=(36, 64) if vertical else (64, 36)).astype(np.float32)
    np.save(out / "diff.npy", np.r_[0, np.abs(np.diff(G, axis=0)).mean((1, 2))].astype(np.float32))
    np.save(out / "mean.npy", G.mean((1, 2)).astype(np.float32))
    wav = out / "a16.wav"
    subprocess.run([FF, "-v", "error", "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000", str(wav)], check=True)
    from scipy.io import wavfile
    _, x = wavfile.read(wav)
    x = x.astype(np.float32) / 32768
    f = x[: len(x) // 160 * 160].reshape(-1, 160)
    np.save(out / "db.npy", (10 * np.log10((f ** 2).mean(1) + 1e-12)).astype(np.float32))
    tw = 180 if vertical else 240
    subprocess.run([FF, "-v", "error", "-y", "-i", src, "-vf",
                    f"fps=1/10,scale={tw}:-2,drawtext=fontfile={SHEET_FONT}:"
                    f"text='%{{pts\\:hms}}':x=3:y=3:fontsize=13:fontcolor=yellow:box=1:boxcolor=black,"
                    f"tile={'10x4' if vertical else '8x8'}", str(out / "sheet_%02d.jpg")], check=True)
    json.dump({"duration": float(meta["format"]["duration"]), "w": W, "h": H, "fps": v["r_frame_rate"],
               "vertical": vertical}, open(out / "meta.json", "w"))
    print(out.name, "done", W, H, meta["format"]["duration"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Per-video features for the channel study.")
    ap.add_argument("video", help="a published video (.mp4)")
    ap.add_argument("out", help="feature folder for this video (usually <channel dir>/feat/<id>)")
    opt = ap.parse_args()
    main(opt.video, opt.out)

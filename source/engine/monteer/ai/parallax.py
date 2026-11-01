"""Depth parallax for drawn (AI) stills: the picture moves in 2.5D, near things more than far ones (the owner's materials
decision 9: Depth Anything V2 Small, Apache-2.0; the larger sizes are non-commercial, so never those).

    <ml python> -m monteer.ai.parallax "<edl.json>"        (the parallax step runs this)
For every cut-list shot with a "parallax" target (only AI stills: real photos are never warped), it makes that file if it
is missing: an exact-length clip (the shot's frames, 24 fps, 1920x1080) of the still with a camera move:
  in   (tension, rule 23) a dolly-in, near things growing faster;
  out  (the end) the same, reversed;
  drift (default) a gentle dolly-in with a slow sideways move, near against far.
Depth maps are cached next to each image (<image>.depth.npy, float16, quarter size). The move is small (at most about 1.5% of
the width sideways; near and far zoom differ by at most 3.5%) and the depth is blurred, so edges stretch softly instead of tearing.
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from ..core.paths import FFMPEG, MODELS

DEPTH_MODEL = MODELS / "depth-anything-v2-small"
OW, OH = 1920, 1080
MARGIN = 1.1                       # the source covers 110% of the frame, so sideways moves never show an edge
_model = None


def depth_of(img_path):
    cache = Path(str(img_path) + ".depth.npy")
    if cache.exists():
        return np.load(cache).astype(np.float32)
    global _model
    from transformers import AutoImageProcessor, AutoModelForDepthEstimation
    if _model is None:
        _model = (AutoImageProcessor.from_pretrained(DEPTH_MODEL, use_fast=False), AutoModelForDepthEstimation.from_pretrained(DEPTH_MODEL).eval())
    proc, model = _model
    im = Image.open(img_path).convert("RGB")
    with torch.no_grad():
        d = model(**proc(images=im, return_tensors="pt")).predicted_depth          # relative inverse depth: larger = nearer
    d = F.interpolate(d[None], size=(im.height // 4, im.width // 4), mode="bilinear", align_corners=False)[0, 0].numpy()
    lo, hi = np.percentile(d, 2), np.percentile(d, 98)
    d = np.clip((d - lo) / max(1e-6, hi - lo), 0, 1)
    np.save(cache, d.astype(np.float16))
    return d


def clip(img_path, nframes, mode, out, side=1):
    im = Image.open(img_path).convert("RGB")
    sw, sh = round(OW * MARGIN), round(OH * MARGIN)
    sc = max(sw / im.width, sh / im.height)                                        # cover, then centre-crop
    im = im.resize((round(im.width * sc), round(im.height * sc)), Image.LANCZOS)
    x0, y0 = (im.width - sw) // 2, (im.height - sh) // 2
    src = torch.from_numpy(np.array(im.crop((x0, y0, x0 + sw, y0 + sh)))).permute(2, 0, 1)[None].float() / 255
    d = torch.from_numpy(depth_of(img_path))[None, None]
    d = F.interpolate(d, size=(im.height // 8, im.width // 8), mode="area")                 # same cover-crop, then blur hard
    d = d[..., round(y0 / 8):round(y0 / 8) + round(sh / 8), round(x0 / 8):round(x0 / 8) + round(sw / 8)]
    d = F.avg_pool2d(F.pad(d, (6, 6, 6, 6), mode="replicate"), 13, stride=1)
    d = F.interpolate(d, size=(OH, OW), mode="bilinear", align_corners=False)[0, 0]       # depth at each output pixel
    ys, xs = torch.meshgrid(torch.linspace(-1, 1, OH), torch.linspace(-1, 1, OW), indexing="ij")
    focus = float(d.median())
    proc = subprocess.Popen([str(FFMPEG), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{OW}x{OH}", "-r", "24",
                             "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p", str(out)],
                            stdin=subprocess.PIPE)
    for n in range(nframes):
        t = n / max(1, nframes - 1)
        t = t * t * (3 - 2 * t)
        if mode == "in":
            zoom, shift = 1 + t * (0.07 + 0.035 * d), 0.0
        elif mode == "out":
            zoom, shift = 1 + (1 - t) * (0.07 + 0.035 * d), 0.0
        else:
            zoom, shift = 1 + t * (0.03 + 0.02 * d), side * (t - 0.5) * 0.02 * (d - focus)
        gx = xs / MARGIN / zoom + shift
        gy = ys / MARGIN / zoom
        fr = F.grid_sample(src, torch.stack([gx, gy], -1)[None], mode="bilinear", padding_mode="border", align_corners=True)
        proc.stdin.write((fr[0].permute(1, 2, 0).clamp(0, 1) * 255).round().byte().numpy().tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise SystemExit(f"parallax: ffmpeg failed for {out}")


def main():
    edl = json.load(open(sys.argv[1]))
    torch.set_grad_enabled(False)
    made = kept = 0
    for s in edl["shots"]:
        target = s.get("parallax")
        if not target:
            continue
        out = Path(target)
        if out.exists() and out.stat().st_size > 10000:
            kept += 1
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.stem + ".part.mp4")
        clip(s["src"], s["nframes"], s.get("zoom") or "drift", tmp, side=s.get("parallax_side", 1))
        tmp.replace(out)
        made += 1
        print(f"parallax: {out.name} ({s['nframes']} frames)", flush=True)
    print(f"parallax: {made} made, {kept} unchanged")


if __name__ == "__main__":
    main()

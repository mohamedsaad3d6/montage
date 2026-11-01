"""Picture quality vs the raw: full-resolution luma PSNR / SSIM of the same frames in our v2 and in
the reference editor's export (30 frames each, mid-segment, frame-matched through the keep lists).

    <core python> -m monteer.learn.editor_compare.quality --edits <episode output> --auto-video <our v2 .mp4>
        --raw-video <raw .mp4> --out <compare dir>

--out holds editor_keep.json (and editor.mp4 unless --editor-video says otherwise) and receives quality.json;
--edits holds edl_v2.json. Decodes 3 x 30 single frames with ffmpeg (no full decode).
"""
import argparse
import json
import subprocess
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter

from ...core.paths import FFMPEG

FF = str(FFMPEG)
W, H = 1920, 1080


def frame(path, k):
    t = max(0.0, (k - 0.25) / 24)
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{t:.4f}", "-i", path, "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(H, W).astype(np.float64)


def psnr(a, b):
    mse = ((a - b) ** 2).mean()
    return 99.0 if mse == 0 else 10 * np.log10(255 ** 2 / mse)


def ssim(a, b):
    C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    mu_a, mu_b = gaussian_filter(a, 1.5), gaussian_filter(b, 1.5)
    va = gaussian_filter(a * a, 1.5) - mu_a ** 2
    vb = gaussian_filter(b * b, 1.5) - mu_b ** 2
    cov = gaussian_filter(a * b, 1.5) - mu_a * mu_b
    m = ((2 * mu_a * mu_b + C1) * (2 * cov + C2)) / ((mu_a ** 2 + mu_b ** 2 + C1) * (va + vb + C2))
    return float(m.mean())


def sharp(a):
    """Detail left in the picture: mean absolute Laplacian."""
    lap = a[1:-1, 1:-1] * 4 - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:]
    return float(np.abs(lap).mean())


def main():
    ap = argparse.ArgumentParser(description="Picture quality of our v2 and of the editor's export against the raw.")
    ap.add_argument("--edits", required=True, help="episode output folder with edl_v2.json")
    ap.add_argument("--auto-video", required=True, help="our v2 render (.mp4)")
    ap.add_argument("--raw-video", required=True, help="the raw camera recording (.mp4)")
    ap.add_argument("--editor-video", help="the editor's export (default <out>/editor.mp4)")
    ap.add_argument("--out", required=True, help="comparison folder with editor_keep.json; quality.json goes here")
    opt = ap.parse_args()
    D = Path(opt.out)
    editor = json.load(open(D / "editor_keep.json"))
    keep = json.load(open(Path(opt.edits) / "edl_v2.json"))["keep"]
    v2, t = [], 0.0
    for a, b in keep:
        v2.append({"ed_s": t, "ed_e": t + b - a, "src_s": a})
        t += b - a
    res = {}
    for name, path, segs in (("v2", opt.auto_video, v2), ("editor", opt.editor_video or D / "editor.mp4", editor)):
        long = [s for s in segs if s["ed_e"] - s["ed_s"] > 2.0]
        pick = [long[i] for i in np.linspace(0, len(long) - 1, 30).astype(int)]
        rows = []
        for s in pick:
            k = int(round((s["ed_s"] + s["ed_e"]) / 2 * 24))
            m = int(round((s["src_s"] + k / 24 - s["ed_s"]) * 24))
            a = frame(path, k)
            # best of +-1 frame, so a timing doubt never counts as quality loss
            b = max((frame(opt.raw_video, m + d) for d in (-1, 0, 1)), key=lambda f: psnr(a, f))
            rows.append({"ed_frame": k, "raw_frame": m, "psnr": psnr(a, b), "ssim": ssim(a, b),
                         "detail_edit": sharp(a), "detail_raw": sharp(b)})
        res[name] = {"psnr_median": float(np.median([r["psnr"] for r in rows])),
                     "psnr_min": float(min(r["psnr"] for r in rows)),
                     "ssim_median": float(np.median([r["ssim"] for r in rows])),
                     "ssim_min": float(min(r["ssim"] for r in rows)),
                     "detail_kept": float(np.median([r["detail_edit"] / r["detail_raw"] for r in rows])),
                     "frames": rows}
        print(name, {k: round(v, 3) for k, v in res[name].items() if k != "frames"}, flush=True)
    json.dump(res, open(D / "quality.json", "w"), indent=0)


if __name__ == "__main__":
    main()

"""Small-frame image registration for the montage study (measurement only).

A published frame P is compared with the source frame C it was made from: is it C as-is, a punch-in
(C scaled by s and cropped), C with something laid over part of it, or something else entirely?

Frames are 128x72 grey. The top band (logo / channel tag) is left out of every comparison.

Not a command; imported by the other style-study tools.
"""
import subprocess

import numpy as np
from scipy.ndimage import zoom as nd_zoom
from scipy.signal import fftconvolve

from ...core.paths import FFMPEG as _FFMPEG

W, H = 128, 72
TOP = 12                     # rows 0..11 hold the channel logo / tag in the published video
FFMPEG = str(_FFMPEG)
SCALES = np.round(np.r_[1.0, np.geomspace(1.04, 2.4, 22)], 3)


def frames(path, fps=None, t0=0.0, dur=None, size=(W, H), gray=True):
    """Decode a video to an (n, h, w[, 3]) uint8 array, optionally resampled to fps."""
    vf = ([f"fps={fps}"] if fps else []) + [f"scale={size[0]}:{size[1]}:flags=area"]
    cmd = [FFMPEG, "-v", "error", "-ss", str(t0)] + (["-t", str(dur)] if dur else []) + \
          ["-i", str(path), "-vf", ",".join(vf), "-pix_fmt", "gray" if gray else "rgb24", "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    shape = (size[1], size[0]) if gray else (size[1], size[0], 3)
    return np.frombuffer(raw, np.uint8).reshape((-1,) + shape)


def _ncc_map(I, T):
    """Normalised cross-correlation of template T at every valid position in image I."""
    h, w = T.shape
    T = T - T.mean()
    tn = np.sqrt((T ** 2).sum()) + 1e-6
    num = fftconvolve(I, T[::-1, ::-1], mode="valid")
    S = np.cumsum(np.cumsum(np.pad(I, ((1, 0), (1, 0))), 0), 1)
    S2 = np.cumsum(np.cumsum(np.pad(I ** 2, ((1, 0), (1, 0))), 0), 1)

    def box(A):
        return A[h:, w:] - A[:-h, w:] - A[h:, :-w] + A[:-h, :-w]
    n = h * w
    var = box(S2) - box(S) ** 2 / n
    flat = var < 4.0 * n            # window std under 2 grey levels: nothing to correlate
    r = num / (np.sqrt(np.maximum(var, 1e-6)) * tn)
    r[flat] = 0.0
    return np.clip(r, -1, 1)


def match(P, C, scales=SCALES):
    """Best (score, s, x, y): P[TOP:] ~ C zoomed by s, window at (x, y) of the zoomed image."""
    P = P.astype(np.float32)
    C = C.astype(np.float32)
    T = P[TOP:]
    if T.std() < 3:
        return 0.0, 1.0, 0, 0
    best = (-1.0, 1.0, 0, 0)
    for s in scales:
        Z = C if s == 1.0 else nd_zoom(C, s, order=1)
        if Z.shape[0] < H or Z.shape[1] < W:
            continue
        Z = Z[: int(round(H * s)), : int(round(W * s))]
        m = _ncc_map(Z, T)
        k = int(np.argmax(m))
        y, x = divmod(k, m.shape[1])
        if m.flat[k] > best[0]:
            best = (float(m.flat[k]), float(s), int(x), int(y) - TOP)
    return best


def aligned(C, s, x, y):
    """The part of C that a punch-in (s, x, y) shows, as a full-size frame."""
    Z = C.astype(np.float32) if s == 1.0 else nd_zoom(C.astype(np.float32), s, order=1)
    out = np.zeros((H, W), np.float32)
    ys, xs = max(0, y), max(0, x)
    crop = Z[ys: ys + H, xs: xs + W]
    out[: crop.shape[0], : crop.shape[1]] = crop
    return out


def cells(P, A, ny=3, nx=4):
    """Per-cell correlation (grid ny x nx, top band excluded) of P with the aligned source A."""
    P = P.astype(np.float32)
    res = np.zeros((ny, nx))
    ys = np.linspace(TOP, H, ny + 1).astype(int)
    xs = np.linspace(0, W, nx + 1).astype(int)
    for i in range(ny):
        for j in range(nx):
            a = P[ys[i]:ys[i + 1], xs[j]:xs[j + 1]].ravel()
            b = A[ys[i]:ys[i + 1], xs[j]:xs[j + 1]].ravel()
            if a.std() < 2 and b.std() < 2:
                res[i, j] = 1.0 if abs(a.mean() - b.mean()) < 12 else 0.0
            else:
                res[i, j] = float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else 0.0
    return res


def match_patch(P, C, scales=SCALES, box=(16, 60, 16, 112)):
    """Like match, but only a central patch of P (rows/cols in box) must be found in the zoomed C:
    two punch-ins framed at different places still share the middle of the picture."""
    y0, y1, x0, x1 = box
    T = P[y0:y1, x0:x1].astype(np.float32)
    if T.std() < 3:
        return 0.0, 1.0, 0, 0
    C = C.astype(np.float32)
    best = (-1.0, 1.0, 0, 0)
    for s in scales:
        Z = C if s == 1.0 else nd_zoom(C, s, order=1)
        Z = Z[: int(round(H * s)), : int(round(W * s))]
        m = _ncc_map(Z, T)
        k = int(np.argmax(m))
        if m.flat[k] > best[0]:
            y, x = divmod(k, m.shape[1])
            best = (float(m.flat[k]), float(s), int(x), int(y))
    return best

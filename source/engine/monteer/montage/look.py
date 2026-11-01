"""The look (rule 21): grain, archive grade, paper overlay. Shared by samples and the render so they match.

GRAIN: ffmpeg noise on the luma only, changing every frame (temporal), light. Applied to stock, photo and AI shots only,
never to our text or graphics (rule 21 as approved).
PAPER: archive photos in the history section get the paper overlay with a soft-light blend.
"""
from pathlib import Path

GRAIN = "noise=c0s=9:c0f=t+u"                      # light film grain (luma strength 9, temporal, uniform)
GRADE_ARCHIVE = "eq=contrast=1.04:saturation=0.85:gamma=0.97,curves=preset=vintage"
PAPER_OPACITY = 0.55
VIGNETTE = "vignette=PI/5"


def archive_still_chain(in_label="0:v", paper_label="1:v", out_label="v", zoom=1.0, fx=0.5, fy=0.5):
    """filter_complex for one archive photo on 1920x1080: cover-crop (zoom, focus fx/fy as shares of the spare width/height,
    e.g. to keep a brand sign out of frame), archive grade, paper overlay (soft light), vignette, grain.
    Inputs: [0] the photo, [1] TEX/paper_overlay.png"""
    w, h = int(1920 * zoom) // 2 * 2, int(1080 * zoom) // 2 * 2
    return (f"[{in_label}]scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop=1920:1080:(iw-1920)*{fx}:(ih-1080)*{fy},setsar=1,{GRADE_ARCHIVE},format=gbrp[ph];"
            f"[{paper_label}]format=gbrp[pp];[ph][pp]blend=all_mode=softlight:all_opacity={PAPER_OPACITY},{VIGNETTE},format=yuv420p,{GRAIN}[{out_label}]")

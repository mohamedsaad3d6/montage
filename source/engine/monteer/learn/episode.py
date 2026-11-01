"""Shared helpers for the learning tools: they run outside a project run, on folders given on the command line.

Several monteer.cut modules (silence, sync, script_text, selfcheck, fixloop, run ...) build their file paths at
import time from monteer.cut.common (WORK, OUT, SCRIPT_DOCX), which normally come from MONTEER_PROJECT. bind() sets
those paths explicitly; call it BEFORE importing any of those modules. frame_db() is silence.frame_db on an explicit
file instead of the module-level synced audio.

Not a command; imported by the tools under monteer/learn.
"""
from pathlib import Path

import numpy as np
from scipy.io import wavfile

FRAME = 0.01


def bind(work, out=None, script=None):
    """Point monteer.cut's module-level paths at an episode's work folder (transcripts, synced audio, script.docx)
    and output folder. Returns the work folder as a Path."""
    from ..cut import common
    common.WORK = Path(work).expanduser().resolve()
    if out is not None:
        common.OUT = Path(out).expanduser().resolve()
    common.SCRIPT_DOCX = Path(script).expanduser().resolve() if script else common.WORK / "script.docx"
    return common.WORK


def frame_db(wav):
    """10 ms RMS level in dBFS of a wav file (same measure as monteer.cut.silence.frame_db)."""
    sr, x = wavfile.read(wav)
    x = x.astype(np.float32) / 32768.0
    if x.ndim == 2:
        x = x.mean(axis=1)
    hop = int(sr * FRAME)
    n = len(x) // hop
    rms = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    return 20 * np.log10(rms)

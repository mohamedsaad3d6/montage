"""Shared settings of the cut, read from the project being run, plus Arabic normalization and small helpers.

The project comes from MONTEER_PROJECT (set by the step runner). Settings used here (project.json):
  inputs.video            the camera recording (talking head)
  inputs.audio            the external microphone, when it is a separate file (omit when it is already on the video)
  inputs.reference_edit   a human editor's cut of the same recording, for comparison only (optional)
  inputs.script           the script (.docx)
  options.keep_outro      keep the spoken outro after the last script line (default false)
  options.version         output version number (default 1): outputs are never overwritten, a new run gets a new number
"""
import os
import re
import subprocess

from ..core import io as _io
from ..core.paths import MODELS as _MODELS

PROJECT = None
if os.environ.get("MONTEER_PROJECT"):
    from ..core.project import Project
    PROJECT = Project(os.environ["MONTEER_PROJECT"])

MODELS = _MODELS / "whisper"          # ggml-<model>.bin
if PROJECT is not None:
    WORK = PROJECT.work
    OUT = PROJECT.output
    NAME = PROJECT.name
    VERSION = int(PROJECT.opt("version", 1))
    EDIT_VIDEO = OUT / f"cut_v{VERSION}.mp4"
    RAW_VIDEO = PROJECT.input("video")
    EXT_AUDIO = PROJECT.input("audio")
    REF_VIDEO = PROJECT.input("reference_edit")
    KEEP_OUTRO = bool(PROJECT.opt("keep_outro", False))
    SCRIPT_DOCX = PROJECT.input("script")
    CHANNEL = bool(getattr(PROJECT, "profile", None))   # a channel episode: the cut fixes of 22 Oct 2026 apply (never the classic projects)
else:                                 # imported outside a run (learning tools): no project paths
    WORK = OUT = EDIT_VIDEO = RAW_VIDEO = EXT_AUDIO = REF_VIDEO = SCRIPT_DOCX = None
    NAME, VERSION, KEEP_OUTRO, CHANNEL = "", 1, False, False

FPS = 24
SR = 16000  # analysis sample rate

_DIACRITICS = re.compile("[\\u0610-\\u061A\\u064B-\\u065F\\u0670\\u06D6-\\u06ED\\u0640]")  # tashkeel, Quranic marks, tatweel (escaped: editors reorder combining marks)
_PUNCT = re.compile(r"[^\w\s%]|_", re.UNICODE)
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def normalize_ar(text):
    """Orthographic normalization used for matching and for 'normalized' WER."""
    t = text.translate(_AR_DIGITS)
    t = _DIACRITICS.sub("", t)
    t = re.sub("[أإآٱ]", "ا", t)
    t = t.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    t = t.replace("،", " ").replace("؛", " ").replace("؟", " ")
    t = _PUNCT.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def words(text):
    return normalize_ar(text).split()


run = _io.run
save_json = _io.save_json
load_json = _io.load_json
cached = _io.done


def ffprobe_duration(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True, check=True)
    return float(r.stdout.strip())


def tc(sec):
    """Seconds -> H:MM:SS.s timecode for reports."""
    sec = round(max(0.0, sec), 1)  # round first, so 179.96 s prints 03:00.0, not 02:60.0
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:04.1f}" if h else f"{int(m):02d}:{s:04.1f}"

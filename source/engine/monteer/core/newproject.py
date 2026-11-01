"""Make a new video project: the one way both `bin/monteer new` and the web panel's New episode screen create one
(Works/output/web_panel_plan.md, phase 2). The type is chosen here and never changes afterwards.

  create(folder, type, name, video=, audio=, script=, profile=, output=, run_mode=, instructions=, clips=[])
     profile    the channel profile's slug (monteer/core/profile.py): required, no default (owner's answer 3 of 18 Oct
                2026); the type must be one the profile offers
     type       "presenter" (with presenter, بمذيع: camera video + script .docx, an optional separate mic) or
                "audio" (audio only, صوت بس: a narration file, and optionally its approved script, .docx or .txt, so the
                on-screen words are spelled as the script writes them: montage/scripttext.py)
     output     "montage" (the full montage, default) or "cut" (the cut only: the presenter type only; owner's decision 3a)
     run_mode   "auto" (the engine decides and goes on). "step": after the plan the agent asks its numbered questions and
                the run waits for the answers (montage/questions.py; built with the panel's phase 3 on the owner's request)
     instructions  the owner's words for this episode, given to the plan (never above the standing rules)
     ad, series_tag, opening   what an episode of its profile may choose (monteer/core/profile.py episode_options):
                the ad put in after the intro clip (a video file; الحدث الأخير: only when the episode has an ad), the
                channel's series tag in its corner (on/off), how the fast intro opens (motion | timelapse)
     clips      the owner's own extra clips (files), used by the montage like any footage after the same checks
                (owner's decision 8b): they are listed in inputs.clips and prepared by the "clips" step
The raw files are referred to where they are (nothing is copied); clips are kept where the caller put them.
"""
import json
from pathlib import Path

from .profile import SLUGS, TYPES, ProfileError, check_type, episode_options
from .project import Project

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts"}
AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"} | VIDEO_EXT     # a video whose sound is the narration
SCRIPT_EXT = {".docx"}
AUDIO_SCRIPT_EXT = {".docx", ".txt"}                                       # the audio type's optional script


class Refused(ValueError):
    """a reason in plain words, for the person (the panel shows it as it is)"""


def check_file(path, exts, what):
    p = Path(path).expanduser()
    if not p.exists() or not p.is_file():
        raise Refused(f"{what}: the file is not there ({p})")
    if p.suffix.lower() not in exts:
        raise Refused(f"{what}: {p.name} is not a {'/'.join(sorted(exts))} file")
    return p.resolve()


def create(folder, type, name=None, video=None, audio=None, script=None, profile=None, output="montage", run_mode="auto",
           instructions="", clips=(), ad=None, series_tag=False, opening=None, sources=None):
    folder = Path(folder).expanduser().resolve()
    if (folder / "project.json").exists():
        raise Refused(f"{folder} already has a project (its type stays as it was chosen)")
    if type not in ("presenter", "audio"):
        raise Refused("choose the type: presenter (with presenter) or audio (audio only)")
    if not profile:
        raise Refused("choose the channel profile: " + ", ".join(SLUGS))
    try:
        check_type(profile, type)
    except ProfileError as e:
        raise Refused(str(e))
    mode = TYPES[type]
    eo = episode_options(profile)
    if ad and not eo["ad"]:
        raise Refused("this channel has no ad slot")
    if series_tag and not eo["series_tag"]:
        raise Refused("this channel has no series tag")
    if opening and opening not in eo["openings"]:
        raise Refused(f"this channel's openings are {eo['openings'] or 'not set'}")
    if sources not in (None, "", "both", "free", "paid"):
        raise Refused("«المصادر» is both, free only or paid only")
    if sources in ("free", "paid") and not eo["paid_sources"]:
        raise Refused("this channel has no paid sources: its footage is the free sources only")
    if output not in ("montage", "cut"):
        raise Refused("the output is the full montage or the cut only")
    if output == "cut" and mode != "talking_head":
        raise Refused("«cut only» is offered for a video with presenter only")
    if run_mode not in ("auto", "step"):
        raise Refused("the run mode is auto or step by step")
    ins = {}
    if mode == "talking_head":
        if not video or not script:
            raise Refused("a video with presenter needs the camera video and the script (.docx)")
        ins["video"] = str(check_file(video, VIDEO_EXT, "the camera video"))
        ins["script"] = str(check_file(script, SCRIPT_EXT, "the script"))
        if audio:
            ins["audio"] = str(check_file(audio, AUDIO_EXT, "the mic audio"))
    else:
        if not audio:
            raise Refused("an audio-only video needs the narration (an audio file, or a video whose sound is used)")
        ins["audio"] = str(check_file(audio, AUDIO_EXT, "the narration"))
        if script:
            ins["script"] = str(check_file(script, AUDIO_SCRIPT_EXT, "the script"))
    cl = [str(check_file(c, VIDEO_EXT, "an extra clip")) for c in (clips or [])]
    if cl:
        ins["clips"] = cl
    if ad:
        ins["ad"] = str(check_file(ad, VIDEO_EXT, "the ad"))
    folder.mkdir(parents=True, exist_ok=True)
    cfg = {"name": (name or folder.name).strip() or folder.name, "mode": mode, "profile": profile, "language": "ar", "inputs": ins,
           "options": {"version": 1, "output": output, "run_mode": run_mode}}
    if series_tag:
        cfg["options"]["series_tag"] = True
    if sources in ("free", "paid"):    # «المصادر» (owner's (c) of 20 Oct 2026); "both" is the default and is not written
        cfg["options"]["sources"] = sources
    if opening and opening != eo["opening"]:
        cfg["options"]["opening"] = opening
    if instructions and instructions.strip():
        cfg["instructions"] = instructions.strip()[:4000]
    (folder / "project.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    return Project(folder)

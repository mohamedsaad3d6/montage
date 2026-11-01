"""The training library (web panel plan, "later": owner's answer 6 of the panel plan; built on the owner's request of
18 Oct 2026 as the plan's first version): pairs of a channel's raw material and what was published from it, kept per
channel in AI agent/channels/<slug>/training/pairs.json. Large files stay where they are (only their paths are kept).

Nothing is learned from the pairs yet: learning from them is a project of its own. What the agent learns from today is
listed with each channel (its style guide from scripts, the measured montage profile, «عام»'s lessons).

  pairs(slug) / add(slug, pair, by) / remove(slug, id)
  pair: {"title", "raw_video"?, "raw_audio"?, "script"?, "published_video"?, "published_link"?, "notes"?}
"""
import re
import time
from pathlib import Path

from .io import load_json, save_json
from .profile import SLUGS, folder

FIELDS = ("title", "raw_video", "raw_audio", "script", "published_video", "published_link", "notes")


def file_of(slug):
    return folder(slug) / "training" / "pairs.json"


def pairs(slug):
    f = file_of(slug)
    return load_json(f)["pairs"] if f.exists() else []


def add(slug, pair, by):
    p = {k: (str(pair.get(k) or "").strip() or None) for k in FIELDS}
    if not p["title"]:
        raise ValueError("give the pair a title")
    if not (p["raw_video"] or p["raw_audio"]):
        raise ValueError("a pair needs its raw material (the camera video or the audio)")
    if not (p["published_video"] or p["published_link"]):
        raise ValueError("a pair needs what was published (the video file or its link)")
    for k in ("raw_video", "raw_audio", "script", "published_video"):
        if p[k] and not Path(p[k]).expanduser().exists():
            raise ValueError(f"{k}: the file is not there ({p[k]})")
    if p["published_link"] and not re.match(r"https?://", p["published_link"]):
        raise ValueError("the published link starts with http:// or https://")
    rows = pairs(slug)
    import secrets
    p.update(id=time.strftime("%Y%m%d-%H%M%S") + "_" + secrets.token_hex(3), by=(by or "").strip() or "owner", added_at=time.strftime("%Y-%m-%d %H:%M:%S"), learned=False)
    rows.append(p)
    save_json(file_of(slug), {"note": "raw + published pairs (core/training.py); nothing is learned from them yet", "pairs": rows})
    return p


def remove(slug, pid):
    rows = pairs(slug)
    if not any(r["id"] == pid for r in rows):
        raise ValueError("no such pair")
    save_json(file_of(slug), {"note": "raw + published pairs (core/training.py); nothing is learned from them yet",
                              "pairs": [r for r in rows if r["id"] != pid]})


def learns_from(slug):
    """what the agent does learn from today, for this channel"""
    ch = folder(slug)
    out = []
    st = ch / "style" / "style_profile.json"
    if (ch / "style" / "style_guide.md").exists():
        sc = load_json(st).get("scripts") if st.exists() else None
        n = len(sc) if isinstance(sc, list) else (sc or "?")
        out.append({"what": "the style guide", "from": f"{n} of the channel's scripts (bin/monteer script learn-style)"})
    ref = (load_json(ch / "channel.json").get("montage") or {}).get("reference") or {}
    if ref:
        out.append({"what": "the montage profile", "from": "the measured reference videos (" + ", ".join(ref.get("study", []) or ["?"]) + ")"})
    if slug == "general":
        out.append({"what": "«عام»'s lessons", "from": "every profile's finished videos, the AI's sent-back answers and the owner's notes"})
    return out


def library():
    from .profile import load
    return [{"slug": s, "name": load(s).get("name", s), "pairs": pairs(s), "learns_from": learns_from(s)} for s in SLUGS]


__all__ = ["pairs", "add", "remove", "library", "learns_from"]

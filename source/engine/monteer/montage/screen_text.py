"""On-screen words that come from the transcription (owner's answer 5a of 19 Oct 2026). Without an approved script, our
graphics take their words from whisper's transcript, so its spelling reaches the screen (the first real test showed
«الإتمان», «الإصالات», «خمسة ألاف»). Every such text is flagged in the report and on the Result screen («اتفرّج على دول
الأول») for the owner to read; with an approved script nothing is flagged (the script spells them).

  from_transcript(p, edl)  -> [{t, scene, text}] in time order; [] with an approved script or outside the phrase montage
  outside_band(p)          -> {scene: [renderer lines]} text the renderer could not fit inside its band (gfx/text_fit.json)
"""
import re
from pathlib import Path

from ..core.io import load_json

ARABIC = re.compile(r"[\u0600-\u06FF]")


def approved_script(p):
    return any(x and Path(x).exists() for x in (p.folder / "script" / "lines.json", p.input("script")))


def from_transcript(p, edl):
    from .steps import decision
    if p.montage != "phrases" or approved_script(p):
        return []
    scenes = {x["name"]: x for x in (decision(p, "graphics", "scenes") or []) if isinstance(x, dict) and x.get("name")}
    out, seen = [], set()
    for s in edl["shots"]:
        for n in ([s["scene"]] if s["kind"] == "gfx" else []) + [o["name"] for o in s.get("overlays", [])]:
            if n in seen or n not in scenes:
                continue
            seen.add(n)
            texts = [it.get("text") or it.get("label") for it in scenes[n].get("items", [])]
            texts = [x for x in texts if isinstance(x, str) and ARABIC.search(x)]
            if texts:
                out.append({"t": round(float(scenes[n].get("t_in", s["f0"] / 24)), 2), "scene": n, "text": " / ".join(texts)})
    return sorted(out, key=lambda x: x["t"])


def outside_band(p):
    f = p.work / "montage" / "gfx" / "text_fit.json"
    return load_json(f) if f.exists() else {}

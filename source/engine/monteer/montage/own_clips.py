"""The owner's own extra clips (owner's decision 8b of 16 Oct 2026, the New episode screen): used by the montage like any
other footage, after the same checks. Step "clips", before the plan, in both video types.

  1. each clip in inputs.clips is converted to the montage's own format (H.264, at most 1920 px wide, 24 fps, no sound,
     at most its first 3 minutes) as the project's "library" asset own_<id>.mp4; the original stays where it is;
     a provenance record says it is the owner's own footage (credits name the file);
  2. a numbered sheet of three frames per clip; the brain looks at it and describes each clip in plain English (what it
     shows, its subject, its country if one is plain), or rejects it for the reasons any footage is rejected (a flag, a
     logo or brand name, close-up faces of private people, black or unusable; flags and brand logos allowed when the
     profile says so, answer 12 of 18 Oct 2026, montage/place.py) -> decision sources/own_clips and
     work/montage/own_clips.json;
  3. the plan gets the usable clips with their descriptions and uses them first where one shows the phrase: the audio-only
     plan as shot type "own" (with the clip's key), the presenter plan as library footage (S:own_<id>). They then go
     through the clip review (usable window, grade), the repeat rule and the mix count ("own" is neither stock nor archive).
"""
import hashlib
import subprocess
from pathlib import Path

from ..core.io import atomic, load_json, save_json
from ..core.paths import FFMPEG, FFPROBE
from .place import allowed

MAX_S = 180


def M(p, *n):
    return p.work.joinpath("montage", *n)


def clip_files(p):
    out = []
    for c in p.cfg.get("inputs", {}).get("clips", []) or []:
        f = p.resolve(c)
        if f and f.is_dir():
            out += sorted(x for x in f.iterdir() if x.suffix.lower() in (".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts"))
        elif f:
            out.append(f)
    return out


def key_of(f):
    st = Path(f).stat()
    return "own_" + hashlib.sha256(f"{Path(f).resolve()}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:10]


def duration(f):
    r = subprocess.run([str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def prepare(p, log=print):
    """convert each clip (once) and record it -> [{key, file, name, seconds}]"""
    from .sources import Ledger
    led = Ledger(p)
    out = []
    lib = p.asset_dir("library")
    lib.mkdir(parents=True, exist_ok=True)
    for f in clip_files(p):
        if not f.exists():
            log(f"own clip missing: {f}")
            continue
        key = key_of(f)
        dst = lib / f"{key}.mp4"
        if not (dst.exists() and dst.stat().st_size > 10000):
            with atomic(dst) as tmp:
                r = subprocess.run([str(FFMPEG), "-v", "error", "-y", "-i", str(f), "-t", str(MAX_S), "-an",
                                    "-vf", "scale='min(1920,iw)':-2,fps=24", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                                    "-pix_fmt", "yuv420p", "-f", "mp4", str(tmp)], capture_output=True, text=True)
                if r.returncode:
                    log(f"own clip {f.name}: could not be read as video ({r.stderr[-200:].strip()})")
                    continue
        led.add(f"S:{key}", kind="own footage", source="your own clip", page="", title=f.name, author="the channel",
                licence="own footage", file=str(dst), original=str(f))
        out.append({"key": key, "file": str(f), "name": f.name, "seconds": round(duration(dst), 2)})
    return out


def sheet(p, clips):
    """three frames per clip (15 %, 50 %, 85 %), numbered by clip"""
    from .steps_phrase import sheet_of
    frames = []
    tdir = M(p, "own_clips")
    tdir.mkdir(parents=True, exist_ok=True)
    for i, c in enumerate(clips):
        src = p.asset_dir("library") / f"{c['key']}.mp4"
        for k, share in enumerate((0.15, 0.5, 0.85)):
            fr = tdir / f"{c['key']}_{k}.jpg"
            if not fr.exists():
                subprocess.run([str(FFMPEG), "-v", "error", "-y", "-ss", f"{max(0.0, c['seconds'] * share):.2f}", "-i", str(src),
                                "-frames:v", "1", "-vf", "scale=400:-2", str(fr)], check=False)
            frames.append((fr, f"{i + 1} {c['key'][-4:]}"))
    return sheet_of(frames, tdir / "sheet.jpg")


SCHEMA = {"type": "object", "required": ["clips"], "properties": {"clips": {"type": "object", "additionalProperties": {
    "type": "object", "required": ["usable", "shows"], "properties": {
        "usable": {"type": "boolean"}, "shows": {"type": "string"}, "subject": {"type": "string"}, "place": {"type": "string"},
        "why": {"type": "string"}}}}}}


def step_clips(p, ask):
    clips = prepare(p)
    if not clips:
        save_json(M(p, "own_clips.json"), {"clips": {}})
        return
    sh = sheet(p, clips)

    def check(d):
        miss = [c["key"] for c in clips if c["key"] not in d["clips"]]
        if miss:
            raise ValueError(f"describe every clip: missing {miss}")
    d = ask(p, "sources", "own_clips",
            "These are the owner's OWN extra clips for this episode (owner's decision 8b): the sheet shows three frames of each, "
            "numbered in the order of the context. For each clip (by its key) say what it shows in plain English (shows, 3-12 "
            "words), its subject (1-3 words, as the plan names subjects), its place (\"EGY\" when it is plainly Egypt, another "
            "ISO-3 when plainly another country, else \"\"), and usable: false (with why) when it would be refused as any "
            + ("footage is: close-up faces of private people, black, blurred or broken (flags and brand logos are allowed, "
               "owner 18 Oct 2026). " if all(allowed(p)) else
               "footage is: a flag of any country, a logo or brand name (even in part), close-up faces of private people, black, "
               "blurred or broken. ")
            + "Answer with JSON only.",
            {"clips": {clips[0]["key"]: {"usable": True, "shows": "…", "subject": "…", "place": "", "why": "…"}}},
            read=[sh], extra={"context": {"clips": [{"n": i + 1, "key": c["key"], "file_name": c["name"], "seconds": c["seconds"]}
                                                    for i, c in enumerate(clips)]}}, schema=SCHEMA, check=check,
            fallback=lambda: {"clips": {c["key"]: {"usable": False, "shows": "", "why": "not looked at (the brain gave no usable answer)"}
                                        for c in clips}})
    out = {}
    for c in clips:
        x = d["clips"][c["key"]]
        out[c["key"]] = dict(c, **{k: x.get(k, "") for k in ("usable", "shows", "subject", "place", "why")})
    save_json(M(p, "own_clips.json"), {"clips": out})
    print(f"own clips: {sum(1 for v in out.values() if v['usable'])} of {len(out)} usable"
          + "".join(f"; {v['name']} not used: {v['why']}" for v in out.values() if not v["usable"]))


def usable(p):
    f = M(p, "own_clips.json")
    return {k: v for k, v in (load_json(f)["clips"] if f.exists() else {}).items() if v.get("usable")}


def plan_text(p):
    """what the plan request says about the owner's clips ("" when there are none)"""
    u = usable(p)
    if not u:
        return ""
    rows = "; ".join(f"{k} ({v['seconds']:.0f} s): {v['shows']}" + (f" [place {v['place']}]" if v.get("place") else "") for k, v in u.items())
    return ("THE OWNER'S OWN CLIPS (owner's decision 8b): use them FIRST wherever one shows the phrase, like any footage "
            "(same rules: the right place, the repeat rule, the mix): " + rows + ".")

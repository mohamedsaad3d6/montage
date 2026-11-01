"""The Channels screen (recorded for a later web phase on 18 Oct 2026, built on the owner's request): each channel profile
as it is today, read-only (editing comes later, with the owner's approval of each change):

  data() -> [{slug, name, types, settings, files, clips, corner, reference, style, sources}]
    settings   every montage setting of the profile, flattened ("structure.fast_open_s": [15, 20]) and marked as read by
               the engine today (core/profile.py READ_NOW) or recorded for a later phase
    files      the identity files in the profile folder (logos, stings, intro, outro, badge, producer ending…): name, kind,
               size, and whether a channel clip that uses it is switched on
"""
from .io import load_json
from .profile import READ_NOW, SLUGS, folder, load

IMG = (".png", ".jpg", ".jpeg")
MEDIA = (".mp4", ".mov", ".wav")


def flat(d, pre=""):
    out = {}
    for k, v in d.items():
        key = f"{pre}{k}"
        if isinstance(v, dict) and v and not key.endswith(("note", "measured")):
            out.update(flat(v, key + "."))
        else:
            out[key] = v
    return out


def read_now(key):
    return any(key == r or key.startswith(r + ".") for r in READ_NOW)


def one(slug):
    ch = folder(slug)
    prof = load(slug)
    m = prof.get("montage") or {}
    settings = [{"key": k, "value": v, "read": read_now(k)} for k, v in flat(m).items()
                if not k.endswith(("note", "_note")) and k not in ("types",)]
    clips = ((m.get("structure") or {}).get("identity_clips")) or []
    used = {c.get("file"): c.get("enabled", True) for c in clips}
    files = []
    for f in sorted((ch / "assets").rglob("*")) if (ch / "assets").exists() else []:
        if f.is_file() and f.suffix.lower() in IMG + MEDIA and "rebuild" not in str(f.relative_to(ch)):
            rel = str(f.relative_to(ch))
            files.append({"path": rel, "kind": "image" if f.suffix.lower() in IMG else "media", "bytes": f.stat().st_size,
                          "clip_on": used.get(rel)})
    for k in ("logo", "logo_light"):
        if prof.get(k) and (ch / prof[k]).exists() and not any(x["path"] == prof[k] for x in files):
            files.append({"path": prof[k], "kind": "image", "bytes": (ch / prof[k]).stat().st_size, "clip_on": None})
    ref = (m.get("reference") or {})
    rdir = (ch / ref["videos"]).resolve() if ref.get("videos") else None
    vids = sorted(x.name for x in rdir.iterdir() if x.suffix.lower() in (".mp4", ".mov")) if rdir and rdir.exists() else []
    from ..script import style as ST
    st, _ = ST.status(ch)
    srcs = load_json(ch / "sources.json") if (ch / "sources.json").exists() else None
    return {"slug": slug, "name": prof.get("name", slug), "types": m.get("types", []), "settings": settings, "files": files,
            "clips": [{"what": c.get("what") or c.get("file"), "at": c.get("at"), "on": c.get("enabled", True) is not False} for c in clips],
            "corner": prof.get("corner_overlays") or [], "reference": {"study": ref.get("study", []), "videos": vids},
            "style": st, "sources": {"on": sum(1 for s in srcs if s.get("on")), "all": len(srcs)} if srcs else None}


def data():
    return [one(s) for s in SLUGS]


def asset_path(slug, rel):
    """an image of the profile folder the panel may show (never outside it)"""
    ch = folder(slug).resolve()
    p = (ch / rel).resolve()
    if ch not in p.parents or p.suffix.lower() not in IMG or not p.exists():
        return None
    return p


__all__ = ["data", "one", "asset_path"]

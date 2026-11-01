"""Channel profiles (owner's answers of 18 Oct 2026 on the channel-profiles report): one folder per channel, outside the
engine, under AI agent/channels/<slug>/ (paths.CHANNELS):

    al-hadath      «الحدث الأخير»       secret-files   «الملفات السرية»      ahmes   «اقتصاد احمس»
    trend-tweet    «ترند وتويتة»        general        «عام»

Each folder is a channel profile as before (channel.json with logo, font, corner overlays, promo slot …; sources.json and
style/ for the script tool; style_ledger.json for the variety rule) plus a "montage" section in channel.json: how that
channel's videos are built. A project names its profile with "profile": "<slug>" in project.json; its channel folder is
then channels/<slug> (no machine path is stored, so a project moves with the engine). The profile is chosen when the
episode is made (bin/monteer new --profile, the panel's New episode screen; no default: answer 3) and never changes.

What the engine reads from "montage" today:
  types                                    which video types the profile offers: "presenter" and/or "audio"
  materials.flags_in_real_footage          flags may be seen in real footage and photos (answer 12)
  materials.brand_logos_in_real_footage    brand logos and names may be seen in real footage and photos (answer 12)
  phase 2C, the episode's structure (montage/structure.py): structure.fast_open_s, fast_open_shot_s, cold_open_s,
  opening / openings_allowed / timelapse_pattern, identity_clips; presenter.first_appearance, body_alternation_s;
  pace.body, footage_shot_s, slow_zoom; sound.music.where; assets.series_tag (an on/off option per episode)
  phase 2C answers and 2D: presenter.body ("mostly_presenter"), pace.transitions ("few"); text.subtitles (the intro's
  running subtitles, montage/subtitles.py); sound.text_sfx ("paper")
  audio                                    the voice-only («صوت بس») episode's differences from the rest of the section
                                           (owner's decision 1A of 20 Oct 2026): merged over it, key by key, for an
                                           audio-only project only; a presenter project never sees it
And outside "montage": corner_overlays (the corner logo, hidden while the channel's own clips play) and font.
Drawn (AI) images never draw a flag or a logo, whatever the profile. Every other key is the owner's recorded choice for a
later phase and is not read yet (PLANNED below); a key the owner has not given a value for is null.
A project with no profile (only the classic same-result test projects) keeps the earlier rules: no flags, no brands.
"""
import json

from .paths import CHANNELS

SLUGS = ("al-hadath", "secret-files", "ahmes", "trend-tweet", "general")
TYPES = {"presenter": "talking_head", "audio": "voice_only"}          # profile type -> project.json "mode"
TYPE_OF_MODE = {v: k for k, v in TYPES.items()}
DEFAULTS = {"types": ["presenter", "audio"],
            "materials": {"flags_in_real_footage": True, "brand_logos_in_real_footage": True}}
READ_NOW = ("types", "audio", "sources.magnific", "sources.storyblocks", "footage.video_min_share", "footage.ai_images", "materials.flags_in_real_footage", "materials.brand_logos_in_real_footage",
            "structure.fast_open_s", "structure.fast_open_shot_s", "structure.cold_open_s", "structure.opening",
            "structure.openings_allowed", "structure.timelapse_pattern", "structure.identity_clips", "presenter.first_appearance",
            "presenter.body_alternation_s", "pace.body", "pace.footage_shot_s", "pace.slow_zoom", "sound.music.where",
            "assets.series_tag", "presenter.body", "pace.transitions", "text.subtitles", "sound.text_sfx", "news.mode",
            "news.highlight", "presenter.layout", "presenter.popups", "presenter.black_and_white_open_s",
            "presenter.subscribe_badge", "sound.effects", "text.labels.style", "real_footage_min", "repeats.subject_max_share",
            "learn.from", "learn.applies_by_itself", "learn.off", "sound.voice_reference", "sources.archive", "graphics",
            "presenter.cold_open_alternation", "cut", "labels")
PLANNED = ("reference", "format", "logo (recorded measurements)", "graphics (\"few\": read as real_footage_min)",
           "repeats.file_max/file_gap_s (the rule for every video already)", "audio_variant")


class ProfileError(ValueError):
    """a reason in plain words (the panel shows it as it is)"""


def folder(slug):
    if slug not in SLUGS:
        raise ProfileError(f"القناة «{slug}» مش معروفة؛ القنوات هي: {'، '.join(SLUGS)}")
    return CHANNELS / slug


def load(slug):
    """the profile's channel.json, with "_folder" and "_slug" added"""
    f = folder(slug) / "channel.json"
    if not f.exists():
        raise ProfileError(f"the profile {slug} has no channel.json in {f.parent}")
    prof = json.loads(f.read_text(encoding="utf-8"))
    if not isinstance(prof.get("montage"), dict):
        raise ProfileError(f"{f}: no \"montage\" section")
    prof["_folder"], prof["_slug"] = str(f.parent), slug
    return prof


def merged(base, over):
    """over merged into base, key by key (dicts inside dicts too); any other value of over replaces base's"""
    out = dict(base)
    for k, v in over.items():
        out[k] = merged(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def montage(prof, type_=None):
    """the profile's "montage" section with the engine's defaults filled in for the keys it reads today; for type_
    "audio" (an audio-only project) its "audio" block merged over it. The block itself is never part of the result."""
    m = dict(prof.get("montage") or {})
    audio = m.pop("audio", None) or {}
    if type_ == "audio":
        m = merged(m, {k: v for k, v in audio.items() if k not in ("note", "types")})
    m["types"] = list(m.get("types") or DEFAULTS["types"])
    m["materials"] = dict(DEFAULTS["materials"], **(m.get("materials") or {}))
    bad = [t for t in m["types"] if t not in TYPES]
    if bad or not m["types"]:
        raise ProfileError(f"profile {prof.get('_slug')}: types must be presenter and/or audio (got {m['types']})")
    return m


def check_type(slug, type_):
    """refuse a video type the profile does not offer (answer 5: a profile can offer both)"""
    m = montage(load(slug))
    if type_ not in m["types"]:
        names = {"presenter": "with presenter (بمذيع)", "audio": "audio only (صوت بس)"}
        raise ProfileError(f"the profile «{load(slug).get('name', slug)}» offers: {' and '.join(names[t] for t in m['types'])}")


def episode_options(slug):
    """what an episode of this profile may choose (bin/monteer new, the panel): an ad (when the profile has an ad slot),
    the series tag, the opening"""
    m = load(slug).get("montage") or {}
    st = m.get("structure") or {}
    return {"ad": any(c.get("file") == "input:ad" for c in st.get("identity_clips") or []),
            "series_tag": bool(((m.get("assets") or {}).get("series_tag") or {}).get("file")),
            "openings": list(st.get("openings_allowed") or ([st["opening"]] if st.get("opening") else [])),
            "opening": st.get("opening"),
            "subtitles": bool(((m.get("text") or {}).get("subtitles") or {}).get("intro")),
            "paid_sources": [k for k in ("storyblocks", "magnific") if (m.get("sources") or {}).get(k)]}


def available():
    """[{slug, name, types}] for every profile folder that is in place (the panel's picker, bin/monteer profiles list)"""
    out = []
    for s in SLUGS:
        try:
            prof = load(s)
            out.append({"slug": s, "name": prof.get("name", s), "types": montage(prof)["types"], "options": episode_options(s)})
        except ProfileError:
            continue
    return out


def main(argv):
    """bin/monteer profiles list | show <slug> | migrate [--apply]"""
    sub = argv[0] if argv else "list"
    if sub == "list":
        rows = available()
        if not rows:
            print(f"no profiles in {CHANNELS}")
        for r in rows:
            print(f"{r['slug']:14s} {r['name']:20s} {' + '.join(r['types'])}")
        return 0
    if sub == "show":
        prof = load(argv[1])
        print(json.dumps(dict(prof, montage=montage(prof)), ensure_ascii=False, indent=1))
        print(f"\nread by the engine today: {', '.join(READ_NOW)}; recorded for later phases: {', '.join(PLANNED)}")
        return 0
    if sub == "migrate":
        from .migrate import main as migrate
        return migrate(argv[1:])
    print(main.__doc__)
    return 1


__all__ = ["SLUGS", "TYPES", "load", "montage", "folder", "check_type", "available", "episode_options", "ProfileError"]

"""How a channel profile shapes an episode (phase 2C of the channel profiles, owner's answers of 18 Oct 2026). Read from
the profile's "montage" section (monteer/core/profile.py); every default is the engine as it was, so a project with no
profile (the classic same-result tests) or with a profile that sets none of these (general «عام») is built exactly as
before, with the same requests to the brain.

  structure.fast_open_s        [lo, hi] s: the fast intro (Ramadan: 15-20 s); null = no fast intro (ترند وتويتة)
  structure.fast_open_shot_s   [lo, hi] s: its shots (default 1-3 s)
  structure.cold_open_s        [lo, hi] s: the documentary cold open (الحدث الأخير: 4-5 min), which begins with the fast
                               intro and ends on the presenter's teaser; absent = no cold open
  presenter.first_appearance   {"near_s", "for_s"}: the presenter's one short appearance inside the cold open
  presenter.cold_open_alternation {"first_s", "every_s", "for_s": [lo, hi]}: instead, the presenter early and often in the
                               cold open (owner's decision of 22 Oct 2026, like the channel's reference episode: from about
                               0:45, then about every every_s, each time lo-hi s)
  presenter.body_alternation_s about this long of footage, then of the presenter, in the body (default: rule 8)
  pace.body                    "calm": fewer and softer transitions after the cold open
  presenter.body               "mostly_presenter": after the intro mostly the presenter, a B-roll block about once a
                               minute or less (الملفات السرية, owner's answer 2 of phase 2C)
  pace.transitions             "few": transitions only into graphics and at section changes (ترند وتويتة, answer 5)
  sound.music.where            "all" (default) | "cold_open_only"
  sound.music.where            also "none": no music at all under the voice (اقتصاد احمس, measured on v01-v03: music only
                               in the channel's own clips); no cue is made
  sound.music.gain_db          the music's level in the mix (montage/mix.py music_gain_db), when a channel's own is known;
                               absent = the engine's / the sound plan's own
  sound.effects                "none": no sound effects at all (اقتصاد احمس, measured: its pop-ups and badge are silent,
                               no whooshes or hits); absent = the engine's effects
  sound.text_sfx               "paper": a paper sound (made in code, montage/sfx.py) when on-screen text appears, in place of
                               the pop (الحدث الأخير: Ramadan's guide); default the pop
  pace.footage_shot_s          [lo, hi] s: footage shots after the intro, audio only (default 1.5-6 s)
  pace.slow_zoom               true: every footage shot slowly pushes in or pulls out (audio only)
  structure.opening            "motion" | "timelapse": how the fast intro opens (الحدث الأخير: motion by default; an
                               episode may ask for the time-lapse with options.opening, among structure.openings_allowed)
  structure.identity_clips     [{"file", "sound", "at", "what"}]: the channel's own clips put into the finished video between
                               two sentences: at "intro_end" (after the fast intro), "cold_open_end", "bw_open_end" (the
                               black-and-white open of اقتصاد احمس, montage/steps_popups.py) or "end". "file" is
                               a path in the profile folder, or "input:ad" (the episode's ad, only when it has one). The
                               corner logo is hidden while they play. Optional: "enabled": false (kept but not put in,
                               e.g. until a channel confirms), "fade_before_s" (the picture fades to black before it).
  audio only (a profile's montage.audio block, owner's decisions 6A/7A of 20 Oct 2026 for اقتصاد احمس):
  structure.bw_open_s          [lo, hi] s: the open is shown in black and white; code ends it on a pause in the window
                               (montage/phrases.py bw_open_end) and the identity clip at "bw_open_end" goes there
  look.photos "framed"         archive photos in the channel's tan frame with the striped reveal (montage/popup_art.py)
                               over a blurred copy of themselves
  look.maps "country_popup"    a map of one country with no places is the channel's pop-up map (its outline, filled
                               with its flag when there is one), full frame
"""
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

FPS = 24


@dataclass
class Structure:
    fast_open: tuple = (15.0, 20.0)          # None: no fast intro
    fast_shot: tuple = (1.0, 3.0)
    cold_open: tuple = None
    presenter_near: float = None
    presenter_for: float = None
    cold_alt: dict = None                    # the presenter early and often in the cold open (owner, 22 Oct 2026)
    body_alternation: float = None
    calm_body: bool = False
    mostly_presenter: bool = False
    few_transitions: bool = False
    text_sfx: str = "pop"
    music_gain_db: float = None
    effects: str = None
    placement: str = None
    music_where: str = "all"
    footage_shot: tuple = None               # None: the phrase montage's own 1.5-6 s
    slow_zoom: bool = False
    bw_open: tuple = None                    # audio only: the black-and-white open's window (اقتصاد احمس, 6A)
    photos_framed: bool = False              # audio only: archive photos framed with the striped reveal (6A)
    popup_maps: bool = False                 # audio only: one-country maps as the channel's pop-up map (6A)
    clips: list = field(default_factory=list)
    opening: str = None                      # None: as before; "motion" | "timelapse" (Ramadan's guide)
    timelapse: list = None                   # [[shots, seconds], ...]

    @property
    def fast_limits(self):
        """what the code accepts for the fast intro's end (default 13-22 s, as before)"""
        lo, hi = self.fast_open
        return lo - 2.0, hi + 2.0

    @property
    def fast_shot_limits(self):
        """what the code accepts for a fast-intro shot (default 0.9-3.3 s, as before)"""
        return round(self.fast_shot[0] * 0.9, 3), round(self.fast_shot[1] * 1.1, 3)

    @property
    def cold_limits(self):
        """the cold open's end that the code accepts: Ramadan's numbers are approximate («قواعد تقريبية»), and the script
        decides where the teaser is (a script written with a shorter cold open still makes a video)"""
        lo, hi = self.cold_open
        return min(90.0, lo * 0.8), hi * 1.2

    @property
    def is_default_intro(self):
        return self.fast_open == (15.0, 20.0) and self.fast_shot == (1.0, 3.0)

    def presenter_window(self, cold_end=None):
        """where the presenter's short cold-open appearance may start, and how long it may last: near 3:00 (Ramadan), or
        about two thirds into a cold open too short for that"""
        n, f = self.presenter_near, self.presenter_for
        if cold_end is not None and n + 30.0 > cold_end - 20.0:
            n = round(cold_end * 0.65, 1)
        return (n - 30.0, n + 30.0), (max(4.0, f * 0.6), f * 1.5)


def _rng(v):
    return (float(v[0]), float(v[1])) if v else None


def of(p):
    """this project's structure (defaults when the profile says nothing)"""
    m = p.profile_montage() if p is not None else {}
    st, pres, pace, snd = (m.get("structure") or {}), (m.get("presenter") or {}), (m.get("pace") or {}), (m.get("sound") or {})
    s = Structure()
    if "fast_open_s" in st:
        s.fast_open = _rng(st["fast_open_s"])
    if st.get("fast_open_shot_s"):
        s.fast_shot = _rng(st["fast_open_shot_s"])
    if st.get("cold_open_s"):
        s.cold_open = _rng(st["cold_open_s"])
        fa = pres.get("first_appearance") or {}
        s.presenter_near, s.presenter_for = float(fa.get("near_s", 180)), float(fa.get("for_s", 10))
        ca = pres.get("cold_open_alternation")
        if ca:
            s.cold_alt = {"first_s": float(ca.get("first_s", 45)), "every_s": float(ca.get("every_s", 50)),
                          "for_s": _rng(ca.get("for_s") or [8, 20])}
    if pres.get("body_alternation_s"):
        s.body_alternation = float(pres["body_alternation_s"])
    s.calm_body = pace.get("body") == "calm"
    s.mostly_presenter = pres.get("body") == "mostly_presenter"
    s.few_transitions = pace.get("transitions") == "few"
    s.music_where = ((snd.get("music") or {}).get("where")) or "all"
    s.text_sfx = snd.get("text_sfx") or "pop"
    if (snd.get("music") or {}).get("gain_db") is not None:
        s.music_gain_db = float(snd["music"]["gain_db"])
    s.effects = snd.get("effects")
    s.placement = snd.get("placement")      # "on_beat": effects on their moment, over speech (owner's fix 8; mix.py)
    if pace.get("footage_shot_s"):
        s.footage_shot = _rng(pace["footage_shot_s"])
    s.slow_zoom = bool(pace.get("slow_zoom"))
    s.clips = list(st.get("identity_clips") or [])
    s.bw_open = _rng(st.get("bw_open_s"))
    look = m.get("look") or {}
    s.photos_framed, s.popup_maps = look.get("photos") == "framed", look.get("maps") == "country_popup"
    if st.get("opening"):
        want = p.opt("opening") or st["opening"]
        if want not in (st.get("openings_allowed") or [st["opening"]]):
            raise SystemExit(f"options.opening {want!r}: this channel's openings are {st.get('openings_allowed')}")
        s.opening = want
        if want == "timelapse":
            s.timelapse = st.get("timelapse_pattern") or [[2, 3.0], [3, 2.0], [6, 1.0], [10, 0.5]]
            s.fast_shot = (min(x[1] for x in s.timelapse), max(x[1] for x in s.timelapse))
    return s


# ---------------------------------------------------------------------------------------------------- identity clips
def probe_frames(f):
    out = subprocess.run([str(_ffprobe()), "-v", "error", "-select_streams", "v:0", "-count_packets", "-show_entries",
                          "stream=nb_read_packets,r_frame_rate", "-of", "json", str(f)], capture_output=True, text=True, check=True).stdout
    s = json.loads(out)["streams"][0]
    return int(s["nb_read_packets"]), s["r_frame_rate"]


def _ffprobe():
    from ..core.paths import FFPROBE
    return FFPROBE


def anchors(p, edl):
    """the narration times the clips may go at: the fast intro's end, the cold open's end, the end"""
    from .steps import M, decision
    tl = decision(p, "montage", "timeline", {}) or {}
    ps = M(p, "presenter_sound.json")
    if p.montage == "presenter" and ps.exists():
        tl = json.loads(ps.read_text(encoding="utf-8"))
    return {"intro_end": tl.get("intro_end_s"), "cold_open_end": tl.get("cold_open_end_s"), "bw_open_end": tl.get("bw_open_end_s"),
            "end": edl["total_frames"] / FPS}


def splices(p, edl):
    """[{"what", "file", "sound", "frame"}]: each identity clip and the frame of the cut list it goes in front of (a shot
    boundary within 1 s of its anchor, else the anchor's own frame); in the order the profile lists them"""
    S = of(p)
    if not S.clips:
        return []
    at = anchors(p, edl)
    bounds = sorted({s["f0"] for s in edl["shots"]} | {edl["total_frames"]})
    prof = Path(p.channel_profile().get("_folder", "."))
    out = []
    for c in S.clips:
        if c.get("enabled") is False:        # kept in the profile, switched off (montage/structure.py)
            continue
        t = at.get(c.get("at"))
        if t is None or (c.get("at") == "intro_end" and not t):
            continue
        if c["file"] == "input:ad":
            f = p.input("ad")
            if not f:
                continue                       # Ramadan: no ad slot when the episode has no ad
            snd = f
        else:
            f, snd = prof / c["file"], (prof / c["sound"]) if c.get("sound") else None
        fr = round(t * FPS)
        near = [b for b in bounds if abs(b - fr) <= FPS]
        fr = min(near, key=lambda b: abs(b - fr)) if near else fr
        out.append({"what": c.get("what") or c["file"], "file": str(f), "sound": str(snd) if snd else None, "at": c.get("at"),
                    "frame": int(min(fr, edl["total_frames"])), "fade_before_frames": round(float(c.get("fade_before_s") or 0) * FPS)})
    return out


def music_dips(p, edl):
    """narration times where the music fades out and back in around an identity clip (the clip brings its own sound)"""
    return [round(s["frame"] / FPS, 3) for s in splices(p, edl) if s["frame"] < edl["total_frames"]]


def loudness(f):
    """(integrated LUFS, true peak dBTP) of a sound file"""
    from ..core.paths import FFMPEG
    r = subprocess.run([str(FFMPEG), "-i", str(f), "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True).stderr
    lufs = float(r.split("Integrated loudness:")[1].split("I:")[1].split("LUFS")[0])
    tp = float(r.split("True peak:")[1].split("Peak:")[1].split("dBFS")[0])
    return lufs, tp


def assemble(p, edl, mix_wav, mix_plan, out_wav, record):
    """the finished sound and the piece list with the channel's clips put in: the narration's mix up to each clip (10 ms
    fades at the joins), the clip with its own sound, then on. Each clip's sound is set to the narration mix's loudness
    (a placeholder value: the channel gave none, answer 5) with its true peak kept under -1.5 dBTP.
    -> (pieces for render.final_spliced, hide intervals [(s, s)] on the finished timeline); writes record (splices.json)"""
    import numpy as np
    from ..core.io import atomic, save_json
    from ..core.paths import FFMPEG
    from .mix import SR, db, load
    sp = splices(p, edl)
    total = edl["total_frames"]
    mix = load(mix_wav)
    mix = np.vstack([mix, np.zeros((max(0, total * SR // FPS - len(mix)), 2), np.float32)])[:total * SR // FPS]
    spf = SR // FPS                                   # samples per frame (2000)
    pieces, hide, parts, rows, cur, t_out = [], [], [], [], 0, 0
    fade = int(0.01 * SR)

    def main_part(a, b):
        x = mix[a * spf:b * spf].copy()
        if len(x) > 2 * fade:
            if a > 0:
                x[:fade] *= np.linspace(0, 1, fade)[:, None]
            if b < total:
                x[-fade:] *= np.linspace(1, 0, fade)[:, None]
        return x
    for c in sp:
        if c["frame"] > cur:
            pieces.append(("main", cur, c["frame"], min(c.get("fade_before_frames", 0), c["frame"] - cur)))
            parts.append(main_part(cur, c["frame"]))
            t_out += c["frame"] - cur
            cur = c["frame"]
        n, rate = probe_frames(c["file"])
        if rate == f"{FPS}/1":                         # the channel's prepared clips (monteer/learn/channel_identity.py)
            nfr = n
        else:                                          # any other clip (an ad): its length at 24 fps
            d = float(subprocess.run([str(_ffprobe()), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", c["file"]],
                                     capture_output=True, text=True).stdout)
            nfr = int(round(d * FPS))
        snd = np.zeros((nfr * spf, 2), np.float32)
        gain = None
        if c.get("sound"):
            x = load(c["sound"])[:nfr * spf]
            lufs, tp = loudness(c["sound"])
            gain = mix_plan["lufs"] - lufs
            gain = min(gain, -1.5 - tp)
            snd[:len(x)] = x * db(gain)
        pieces.append(("clip", c["file"], nfr))
        parts.append(snd)
        hide.append((t_out / FPS, (t_out + nfr) / FPS))
        rows.append(dict(c, frames=nfr, finished_from_s=round(t_out / FPS, 3), finished_to_s=round((t_out + nfr) / FPS, 3),
                         sound_gain_db=None if gain is None else round(gain, 2),
                         sound_level="placeholder: set to the narration mix's loudness (no value given by the channel)"))
        t_out += nfr
    if cur < total:
        pieces.append(("main", cur, total))
        parts.append(main_part(cur, total))
        t_out += total - cur
    y = np.concatenate(parts).astype(np.float32)
    with atomic(Path(out_wav)) as tmp:
        subprocess.run([str(FFMPEG), "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-", "-c:a", "pcm_s24le", str(tmp)],
                       input=y.tobytes(), check=True)
    save_json(record, {"note": "the channel's own clips put into the finished video (montage/structure.py); frames are 24 fps",
                       "narration_frames": total, "finished_frames": t_out, "clips": rows})
    return pieces, hide


def to_finished(t, rows):
    """a narration time -> the same moment on the finished video (after the channel's clips put in before it)"""
    return round(t + sum(r["frames"] for r in rows if r["frame"] <= round(t * FPS)) / FPS, 3)


def apply_to_sound(p, d_sound, edl):
    """the profile's part of the sound plan (both video types): music only in the cold open when the channel says so, and
    the music fading out before each identity clip and back after it (mix.py "music_dips"). Unchanged without a profile
    that sets them."""
    S = of(p)
    out = dict(d_sound)
    if S.music_where == "cold_open_only":
        ce = anchors(p, edl).get("cold_open_end")
        if ce:
            secs = []
            for sec in out.get("sections", []):
                if sec["from"] >= ce - 0.5:
                    continue
                if sec["to"] > ce:
                    sec = dict(sec, to=round(ce, 2), fade_out=1.5)
                secs.append(sec)
            out["sections"] = secs
    dips = music_dips(p, edl)
    if dips:
        out["music_dips"] = dips
    if S.text_sfx == "paper":           # Ramadan's guide: on-screen text comes with a paper sound (mix.py "papers")
        out["papers"] = list(out.get("pops", []))
        out["pops"] = []
    if S.music_where == "none":         # no music under the voice at all (measured on the channel's episodes)
        out["sections"] = []
    if S.effects == "none":             # no sound effects at all (measured on the channel's episodes)
        for k in ("pops", "papers", "hits", "stops", "whoosh_extra", "whoosh_scenes", "intro_clicks"):
            out[k] = []
    if S.music_gain_db is not None:     # the channel's own music level (measured on its episodes)
        out["music_gain_db"] = S.music_gain_db
    return out


__all__ = ["Structure", "of", "splices", "music_dips", "anchors", "probe_frames", "apply_to_sound", "assemble", "loudness"]

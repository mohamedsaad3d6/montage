"""One video = one project folder:

    <project>/project.json   settings (below)
    <project>/decisions/     judgement-step decisions (the brain's answers), kept so a rerun repeats them exactly
    <project>/work/          intermediate files (safe to delete; the run remakes them)
    <project>/output/        finished files (never overwritten: new versions get new names)
    <project>/run/           run record, log, lock

project.json:
{
  "name": "...",                       shown in reports
  "mode": "talking_head" | "voice_only",  THE VIDEO TYPE, chosen at the start (required; owner's decision of 16 Oct 2026):
                                         talking_head = with presenter (بمذيع): the presenter montage (montage/steps_presenter.py)
                                         voice_only   = audio only (صوت بس): the phrase montage (montage/steps_phrase.py)
                                       The two types are kept apart: each runs its own montage, never the other's.
  "language": "ar",
  "profile": "<slug>",                 THE CHANNEL PROFILE, chosen at the start (required for new projects; owner's answer 3 of
                                         18 Oct 2026): al-hadath, secret-files, ahmes, trend-tweet or general. The channel
                                         folder is then channels/<slug> (monteer/core/profile.py)
  "channel": "<channel profile folder>",          only in projects made before the profiles (the classic same-result tests)
  "inputs": {"video": ..., "audio": ..., "script": ..., "reference_edit": ...},   paths, relative to the project folder or absolute
  "options": {...},                    per-project switches (documented where they are read)
  "assets": {"stock": ..., ...}        optional: where downloaded footage/photos live (default <project>/work/assets/...)
}
"""
import json
from pathlib import Path

MODES = ("talking_head", "voice_only")
TYPE_NAMES = {"talking_head": "with presenter (بمذيع)", "voice_only": "audio only (صوت بس)"}
MONTAGE_OF = {"talking_head": "presenter", "voice_only": "phrases"}


class Project:
    def __init__(self, folder):
        self.folder = Path(folder).expanduser().resolve()
        f = self.folder / "project.json"
        if not f.exists():
            raise SystemExit(f"no project.json in {self.folder}")
        self.cfg = json.loads(f.read_text(encoding="utf-8"))
        self.name = self.cfg.get("name", self.folder.name)
        self.mode = self.cfg.get("mode")
        if self.mode not in MODES:
            raise SystemExit(f"project.json: choose the video type at the start: \"mode\": \"talking_head\" (with presenter, بمذيع) "
                             f"or \"voice_only\" (audio only, صوت بس); got {self.mode!r}")
        self.options = self.cfg.get("options", {})
        if self.options.get("output", "montage") == "cut" and self.mode != "talking_head":
            raise SystemExit("project.json: «cut only» is offered for a video with presenter only (owner's decision 3a)")
        if self.cfg.get("profile"):
            from .profile import TYPE_OF_MODE, ProfileError, check_type
            try:
                check_type(self.cfg["profile"], TYPE_OF_MODE[self.mode])
            except ProfileError as e:
                raise SystemExit(f"project.json: {e}")
        self.work = self.folder / "work"
        self.output = self.folder / "output"
        self.decisions = self.folder / "decisions"
        self.run = self.folder / "run"
        for d in (self.work, self.output, self.decisions, self.run):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def instructions(self):
        """the owner's words for this episode (the New episode screen's box), or "" """
        return (self.cfg.get("instructions") or "").strip()

    @property
    def type_name(self):
        return TYPE_NAMES[self.mode]

    @property
    def montage(self):
        """the montage this video type runs: "presenter" (with presenter) or "phrases" (audio only). One exception, for
        the same-result tests only: an audio-only project with options.montage "classic" replays the earlier free-form
        montage that made 5b (no user ever chooses it; bin/monteer new never writes it)."""
        want = self.options.get("montage")
        if self.mode == "voice_only" and want == "classic":
            return "classic"
        if want not in (None, MONTAGE_OF[self.mode], "sentences" if self.mode == "voice_only" else None):
            raise SystemExit(f"project.json: a {TYPE_NAMES[self.mode]} video runs the {MONTAGE_OF[self.mode]} montage only; "
                             f"remove options.montage ({want!r})")
        return MONTAGE_OF[self.mode]

    def resolve(self, p):
        if p is None:
            return None
        p = Path(p).expanduser()
        return p if p.is_absolute() else (self.folder / p)

    def input(self, key):
        return self.resolve(self.cfg.get("inputs", {}).get(key))

    def opt(self, key, default=None):
        return self.options.get(key, default)

    def asset_dir(self, key):
        """where one kind of downloaded asset lives (stock, wiki, ai, sfx, music ...)"""
        return self.resolve(self.cfg.get("assets", {}).get(key)) or (self.work / "assets" / key)

    @property
    def profile(self):
        """the channel profile's slug, or None (a project from before the profiles)"""
        return self.cfg.get("profile")

    @property
    def channel(self):
        if self.profile:                        # the profile's own folder: no machine path is stored in project.json
            from .profile import folder
            return folder(self.profile)
        c = self.cfg.get("channel")
        return self.resolve(c) if c else None

    def profile_montage(self):
        """the profile's "montage" section with the engine's defaults (monteer/core/profile.py), or {} without a profile"""
        if not self.profile:
            return {}
        from .profile import load, montage
        return montage(load(self.profile), "audio" if self.mode == "voice_only" else None)   # the audio block (1A)

    def channel_profile(self):
        """the channel profile's settings (channel.json in the profile folder), or {}"""
        c = self.channel
        if c and (c / "channel.json").exists():
            prof = json.loads((c / "channel.json").read_text(encoding="utf-8"))
            prof["_folder"] = str(c)
            return prof
        return {}

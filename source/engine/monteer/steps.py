"""The one command's steps, in their fixed order. `bin/monteer run <project>` goes through this list every time.

Each step: name, what it does, the modes it applies to, its Python environment (core / ml), a version (raise it
when the step's behaviour changes, so finished projects redo it), and functions giving its inputs (files and
settings that decide its result: a change makes the step run again) and outputs (all present = finished).
Steps are imported lazily so the runner itself loads no heavy library.
"""
from dataclasses import dataclass, field
from typing import Callable, Optional

TH, VO = "talking_head", "voice_only"
BOTH = (TH, VO)


@dataclass
class Step:
    name: str
    what: str
    modes: tuple
    target: str                       # "module:function", called with the Project
    env: str = "core"
    version: int = 1
    inputs: Optional[Callable] = None
    outputs: Optional[Callable] = None
    params: Optional[Callable] = None
    adopt: bool = False               # outputs found without a run record count as finished (copied-in earlier work)
    always: bool = False              # runs on every run (cheap checks)
    alongside_until: Optional[str] = None   # a channel episode runs it at the same time as the next steps; this step waits for it
    notes: list = field(default_factory=list)

    def fn(self, proj):
        import importlib
        import os
        os.environ["MONTEER_PROJECT"] = str(proj.folder)
        mod, func = self.target.split(":")
        return getattr(importlib.import_module(mod), func)(proj)


def _w(p, *names):
    return [p.work / n for n in names]


def _opt(*keys):
    return lambda p: {k: p.opt(k) for k in keys}


STEPS = [
    Step("check", "tools, models and keys file are in place (keys never inside the engine)", BOTH,
         "monteer.core.checks:step_check", version=1, always=True),
    # ---------------------------------------------------------------- the cut (talking head)
    Step("sync", "camera and microphone on one timeline", (TH,), "monteer.cut.pipeline:step_sync",
         inputs=lambda p: [p.input("video"), p.input("audio")], outputs=lambda p: _w(p, "sync.json", "sync_ext16.wav", "sync_ext48.wav"),
         adopt=True),
    Step("transcribe", "whisper large-v3: every word with its time", (TH,), "monteer.cut.pipeline:step_transcribe",
         inputs=lambda p: _w(p, "sync_ext16.wav"), outputs=lambda p: _w(p, "asr_ext_large-v3.json"), adopt=True),
    Step("literal_words", "Egyptian wav2vec2: literal words (stammers and repeats stay in)", (TH,), "monteer.cut.pipeline:step_literal_words",
         inputs=lambda p: _w(p, "sync_ext16.wav"), outputs=lambda p: _w(p, "asr_ext_ctc.json"), adopt=True),
    Step("script", "the script's sentences and words", (TH,), "monteer.cut.pipeline:step_script",
         inputs=lambda p: [p.input("script")], outputs=lambda p: _w(p, "script.json")),
    Step("cut", "the keep list: takes, pauses, breaths, every cut with its reason", (TH,), "monteer.cut.pipeline:step_cut", version=1,
         inputs=lambda p: _w(p, "asr_ext_large-v3.json", "asr_ext_ctc.json", "script.json", "sync_ext16.wav")
         + [p.input("editor_keep")] + _w(p, "manual_fixes.json"),
         outputs=lambda p: [p.output / "edl.json"],
         params=_opt("cut_content", "keep_outro", "fix_loop", "script_last_sentence", "script_end_sentence", "labels")),
    Step("cut_draft", "render the cut (draft, for checking)", (TH,), "monteer.cut.pipeline:step_cut_draft",
         inputs=lambda p: [p.output / "edl.json", p.input("video")], outputs=lambda p: _w(p, "cut_draft.mp4")),
    Step("cut_verify", "transcribe the draft, cut repeats still in it (confirmed on short clips)", (TH,),
         "monteer.cut.pipeline:step_cut_verify", inputs=lambda p: _w(p, "cut_draft.mp4"), params=_opt("verify_rounds", "cut_content")),
    Step("cut_final", "the finished cut: output/cut_v<version>.mp4 (never overwritten)", (TH,), "monteer.cut.pipeline:step_cut_final",
         inputs=lambda p: _w(p, "cut_draft.mp4"), outputs=lambda p: [p.output / f"cut_v{int(p.opt('version', 1))}.mp4"]),
    Step("cut_report", "the cut report and measured transcription accuracy", (TH,), "monteer.cut.pipeline:step_cut_report",
         inputs=lambda p: [p.output / f"cut_v{int(p.opt('version', 1))}.mp4"], outputs=lambda p: [p.output / "report.md"]
         if p.opt("cut_content", "engine") == "engine" and p.input("reference_edit") is None else []),
]

by_name = {s.name: s for s in STEPS}


def register(after, *steps):
    """montage steps add themselves after a given step (keeps this file's order the only order)"""
    i = next(k for k, s in enumerate(STEPS) if s.name == after) + 1
    for s in steps:
        STEPS.insert(i, s)
        by_name[s.name] = s
        i += 1


from .montage import steps as _montage_steps  # noqa: E402,F401  (adds the voice/montage steps in their place)

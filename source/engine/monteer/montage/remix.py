"""Audio-only re-mix (owner's decision of 21 Oct 2026, after the first camera-mic episode): a finished episode's sound made
again and put on its finished picture, which is COPIED as it is (no new encode). Only the sound's steps run: the camera
voice (cleaned again when its chain or the cut list changed), the mix, the channel's clips' sound put in as the final step
does, then the self-check and the credits of the new video. The cut and its report are not run again (the cut is the
same: cut_v<N+1>.mp4 is a copy of cut_v<N>.mp4), and every earlier version stays (output/versions/v<N>/).

    bin/monteer remix-audio "<project>" --sample START [--seconds 60]   a check first: the new sound on the finished
                                                                         picture from START s (a short file; nothing replaced)
    bin/monteer remix-audio "<project>"                                  the new version: video_v<N+1>.mp4
"""
import os
import shutil
import subprocess
import time

from ..core.io import atomic, load_json, save_json
from ..core.paths import FFMPEG, tool_env

FF = str(FFMPEG)
STEPS_DONE = ("cut_final", "cut_report", "voice_clean", "mix", "final", "selfcheck", "credits")   # what this path stands for


def _bind(p):
    """as a run does: the engine's tools first on the PATH, the cut modules' project"""
    os.environ.update(tool_env())
    os.environ["MONTEER_PROJECT"] = str(p.folder)


def voice_current(p):
    """the cleaned camera voice is already made by this chain from this cut list"""
    from . import voice_chain as VC
    rec, out = p.work / "montage" / "voice_chain.json", VC.clean_out(p)
    if not (rec.exists() and out.exists()):
        return False
    r = load_json(rec)
    return r.get("chain") == VC.AUTO_SIG and r.get("reference") == VC.reference(p) and \
        out.stat().st_mtime >= (p.output / "edl.json").stat().st_mtime


def sound(p, log=print):
    """the new finished sound -> its wav on the finished video's timeline (the channel's clips in, as the final step puts them)"""
    from . import steps as ST, structure, voice_chain as VC
    _bind(p)
    if VC.auto_voice(p):
        if voice_current(p):
            log("voice: already cleaned by this chain from this cut list")
        else:
            VC.step(p)
    ST.step_mix(p)
    edl = load_json(ST.M(p, "edl.json"))
    if structure.splices(p, edl):
        structure.assemble(p, edl, ST.M(p, "mix.wav"), load_json(ST.M(p, "mix_plan.json")), ST.M(p, "mix_finished.wav"), ST.M(p, "splices.json"))
        return ST.M(p, "mix_finished.wav")
    return ST.M(p, "mix.wav")


def finished(p):
    from .steps import out_name
    v = out_name(p)
    if not v.exists():
        raise SystemExit(f"no finished video {v.name}: the audio-only re-mix needs a finished version")
    return v


def sample(p, start, seconds=60.0, log=print):
    """the new sound on the finished picture from start s, for a check -> the short video (its picture encoded again, as
    a cut can only start on a frame of its own) and its sound as a wav; nothing of the episode is replaced"""
    from ..montage.edits import current_version
    prev = finished(p)
    wav = sound(p, log)
    name = f"{prev.stem.rsplit('_v', 1)[0]}_v{current_version(p) + 1}_sample_{start:g}".replace(".", "_") + "s"   # 361.67 -> 361_67s
    mp4, wv = p.output / (name + ".mp4"), p.output / (name + ".wav")
    with atomic(mp4) as tmp:
        subprocess.run([FF, "-v", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{seconds:.3f}", "-i", str(prev), "-ss", f"{start:.3f}", "-t", f"{seconds:.3f}",
                        "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", "-f", "mp4", str(tmp)], check=True)
    with atomic(wv) as tmp:
        subprocess.run([FF, "-v", "error", "-y", "-ss", f"{start:.3f}", "-t", f"{seconds:.3f}", "-i", str(wav), "-c:a", "pcm_s24le", "-f", "wav", str(tmp)],
                       check=True)
    log(f"sample: {mp4.name} and its sound {wv.name}")
    return mp4


def full(p, log=print):
    """the new version: the new sound on the finished picture, copied as it is -> output/video_v<N+1>.mp4"""
    from ..core.project import Project
    from ..core.runctl import lock_pid
    from ..core.runner import fingerprint
    from . import steps as ST
    from .edits import current_version, snapshot
    from ..steps import STEPS
    if lock_pid(p.folder):
        raise SystemExit("a run of this episode is going: wait for it to finish")
    prev, v = finished(p), current_version(p)
    cut_prev = p.output / f"cut_v{v}.mp4"
    wav = sound(p, log)
    snapshot(p, v)                     # the version before, kept (output/versions/v<N>/)
    cfg = load_json(p.folder / "project.json")
    cfg.setdefault("options", {})["version"] = v + 1
    save_json(p.folder / "project.json", cfg)
    q = Project(p.folder)
    out = ST.out_name(q)
    if out.exists():
        raise SystemExit(f"{out.name} exists: outputs are never overwritten")
    t0 = time.time()
    with atomic(out) as tmp:           # the picture copied as it is; the new sound encoded as the final step encodes it
        subprocess.run([FF, "-v", "error", "-y", "-i", str(prev), "-i", str(wav), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart", "-f", "mp4", str(tmp)], check=True)
    cut_new = q.output / f"cut_v{v + 1}.mp4"
    if cut_prev.exists() and not cut_new.exists():    # the same cut under the new version's name (a clone: no space used)
        if subprocess.run(["cp", "-c", str(cut_prev), str(cut_new)], capture_output=True).returncode != 0:
            shutil.copy2(cut_prev, cut_new)
    log(f"{out.name}: the picture of {prev.name} with the new sound ({time.time() - t0:.0f} s)")
    ST.step_selfcheck(q)
    ST.step_credits(q)
    rec_f = q.run / "record.json"      # the run record: what this path made counts as done (the next run does not redo it)
    rec = load_json(rec_f) if rec_f.exists() else {}
    at = time.strftime("%Y-%m-%d %H:%M:%S")
    for s in STEPS:
        if s.name in STEPS_DONE and q.mode in s.modes:
            rec[s.name] = {"status": "done", "fp": fingerprint(s, q), "at": at, "by": f"audio-only re-mix v{v} -> v{v + 1}"}
    save_json(rec_f, rec)
    return out

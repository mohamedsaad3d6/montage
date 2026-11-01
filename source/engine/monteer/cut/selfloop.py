"""Self-check loop: after the EDL is built, render the edit's audio, transcribe it with both models,
run selfcheck.py, turn each confirmed finding into a source-time fix (work/selfcheck_fixes.json),
rebuild the EDL and repeat until nothing fixable is left. The video is rendered once at the end.

    (a step of `bin/monteer run`; see monteer/steps.py)
"""
import argparse
import subprocess

import numpy as np
from scipy.io import wavfile

from . import script_text
from . import selfcheck
from .asr import transcribe
from .common import OUT, WORK, load_json, save_json, tc
from .sync import SYNC16

FADE = 0.01
LOOP_DIR = WORK / "selfloop"


def audio_edit(keep, dst):
    """The edit's audio (16 kHz mono) straight from the synced track, 10 ms fades like render.py."""
    sr, x = wavfile.read(str(SYNC16))
    f = int(FADE * sr)
    ramp = np.linspace(0, 1, f, dtype=np.float32)
    parts = []
    for s, e in keep:
        seg = x[int(round(s * sr)): int(round(e * sr))].astype(np.float32)
        if len(seg) > 2 * f:
            seg[:f] *= ramp
            seg[-f:] *= ramp[::-1]
        parts.append(seg)
    wavfile.write(str(dst), sr, np.concatenate(parts).astype(np.int16))
    return dst


def check(name, keep, models=("large-v3", "large-v3-turbo"), wav=None):
    LOOP_DIR.mkdir(parents=True, exist_ok=True)
    wav = wav or audio_edit(keep, LOOP_DIR / f"{name}.wav")
    trs = [(m, transcribe(wav, f"loop_{name}", m)["words"]) for m in models]
    script = script_text.build()
    data = load_json(WORK / "report_data.json")
    missing = {m["i"] for m in data["missing_script_sentences"]}
    last = selfcheck.last_sentence(script, missing)
    outro = [u for u in data["unsure"] if u["why"].startswith("start of the kept channel outro")]
    stop_at = outro[0]["out"] if outro else 1e9
    src = load_json(WORK / "asr_ext_large-v3.json")["words"]
    found, aligned = selfcheck.run_check(trs, wav, keep, script, last, src, stop_at)
    save_json(LOOP_DIR / f"{name}_findings.json", found)
    return found, aligned, trs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-only")
    a = ap.parse_args()
    if a.check_only:
        found, _, _ = check(a.check_only, load_json(OUT / "edl.json")["keep"])
        for f in found:
            print(f"{tc(f['out'])}  {f['type']:<26} {'+'.join(f['models']):<26} {f['text'][:80]}")

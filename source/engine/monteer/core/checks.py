"""The first step of every run: is everything in place? Writes nothing but the log."""
import json

from . import apikeys, guard
from .paths import BIN, CORE_PY, DATA, ENGINE, FFMPEG, FFPROBE, ML_PY, MODELS, SETUP, WHISPER_CLI


def step_check(p):
    guard.refuse_if_keys_inside()
    missing = [str(x) for x in (FFMPEG, FFPROBE, WHISPER_CLI, CORE_PY, ML_PY) if not x.exists()]
    man = json.loads((SETUP / "models.json").read_text())["models"]
    for mid, m in man.items():
        for f in m["files"]:
            q = MODELS / m["dest"] / f["path"]
            if not q.exists() or q.stat().st_size != f["size"]:
                missing.append(f"model {mid}: {f['path']}")
    if missing:
        raise SystemExit("not set up (run bin/monteer setup):\n  " + "\n  ".join(missing))
    print(f"engine {ENGINE}\ndata   {DATA}\ntools  {BIN}")
    print("keys file:", apikeys.KEYS, apikeys.status())
    from . import brain, claudebrain
    b = brain.brain_name(p)
    print(f"project «{p.name}» mode {p.mode}; brain: {b}")
    if b == "claude-bg":
        ok, why = claudebrain.status()
        print(why)
        if not ok:
            raise SystemExit(f"STOP: the background brain needs Claude Code: {why}")

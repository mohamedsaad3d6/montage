"""Safe file writing: a file only appears under its real name once it is complete.

Every writer puts its output under a temporary name next to the target and renames it at the end
(os.replace is atomic on the same disk). A crash therefore never leaves a half-written file that a
rerun would mistake for a finished one.
"""
import contextlib
import json
import os
import subprocess
from pathlib import Path


def tmp_name(path):
    path = Path(path)
    return path.with_name(f".{path.stem}.part{os.getpid()}{path.suffix}")


@contextlib.contextmanager
def atomic(path):
    """with atomic(out) as tmp: write to tmp (any tool, same extension); renamed to out when the block ends cleanly."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_name(path)
    try:
        yield tmp
        if tmp.is_dir() or tmp.exists():
            os.replace(tmp, path)
        else:
            raise FileNotFoundError(f"nothing was written to {tmp}")
    finally:
        if tmp.exists() and not tmp.is_dir():
            tmp.unlink()


def save_json(path, obj, indent=1):
    with atomic(path) as tmp:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=indent)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_text(path, text):
    with atomic(path) as tmp:
        Path(tmp).write_text(text, encoding="utf-8")


def done(path):
    """a finished output (atomic writes guarantee a present file is complete)"""
    p = Path(path)
    return p.exists() and (p.is_dir() or os.path.getsize(p) > 0)


def run(cmd, **kw):
    print("$", " ".join(str(c) for c in cmd)[:300], flush=True)
    return subprocess.run([str(c) for c in cmd], check=True, **kw)

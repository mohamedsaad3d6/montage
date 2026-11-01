"""Checks made before any run: no keys inside the engine folder, one run at a time per project, Mac kept awake."""
import fnmatch
import os
import subprocess
import sys
import time
from pathlib import Path

from .paths import ENGINE, KEYS

KEY_PATTERNS = ["keys*", "*keys*.json", "*.key", "*.pem", ".env", ".env.*", "credentials*", "secrets*", "*token*.json"]
SKIP_DIRS = {".git", "__pycache__"}
# files whose names match a pattern above but hold no keys, each named exactly (never a folder or a pattern), with why
NOT_KEYS = {"docs/design/monteer-design-source/tokens.json": "the panel design's colour, type and spacing tokens"}


def keys_inside_engine():
    """every file in the engine folder whose name looks like a keys/credentials file"""
    found = []
    for root, dirs, files in os.walk(ENGINE):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if any(fnmatch.fnmatch(f.lower(), p) for p in KEY_PATTERNS):
                if (Path(root) / f).relative_to(ENGINE).as_posix() in NOT_KEYS:
                    continue
                found.append(Path(root) / f)
    return found


def refuse_if_keys_inside():
    bad = keys_inside_engine()
    if bad:
        sys.exit("STOP: a keys file is inside the engine folder, which must never hold keys:\n  "
                 + "\n  ".join(str(b) for b in bad)
                 + f"\nMove it out (keys belong in {KEYS}) and run again.")
    try:
        if KEYS.resolve().is_relative_to(ENGINE):
            sys.exit(f"STOP: the keys file path {KEYS} points inside the engine folder.")
    except OSError:
        pass


class Lock:
    """<project>/run/lock: one run at a time per project. A lock left by a process that no longer exists is taken over."""

    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, f"{os.getpid()} {time.strftime('%Y-%m-%d %H:%M:%S')}\n".encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    pid = int(self.path.read_text().split()[0])
                    os.kill(pid, 0)
                except (ValueError, IndexError, ProcessLookupError):
                    print(f"[lock] taking over a stale lock ({self.path.read_text().strip()})", flush=True)
                    self.path.unlink(missing_ok=True)
                    continue
                except PermissionError:
                    pass
                sys.exit(f"STOP: another run is working on this project (lock {self.path}: {self.path.read_text().strip()}).")
        sys.exit(f"STOP: could not take the lock {self.path}")

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


def keep_awake():
    """caffeinate for as long as this process lives (macOS); returns the child or None"""
    if sys.platform != "darwin":
        return None
    try:
        return subprocess.Popen(["caffeinate", "-dims", "-w", str(os.getpid())], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        return None

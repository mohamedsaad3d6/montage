"""One heavy model at a time on this Mac (fast mode, phase D; owner's decision 9 of 19 Oct 2026): ACE-Step (the music,
about 21 GB) and SDXL (the drawn images, about 26 GB) each use the whole processor, so they never run together, whatever
step or project starts them. A lock file for the whole Mac (<monteer_data>/locks/heavy_model.lock, flock: the system frees
it when its process ends, even when it is killed, so a stopped run never leaves it held). The drawn images go first: while
they wait or run, the music does not start its next take (a take already going is finished first).

  with hold("music M3", log=print) as waited: ...                      waits its turn, then holds the lock (waited: seconds)
  with hold("drawn images", first=True, log=print) as waited: ...     the same, and the music lets it go first
"""
import fcntl
import os
import time
from contextlib import contextmanager

from .paths import DATA

DIR = DATA / "locks"
LOCK = DIR / "heavy_model.lock"            # its text: who holds it (for the waiting one's message only; the flock decides)
FIRST = DIR / "heavy_model.first"          # "<pid> <who>": a waiting or running holder that goes first ("" when none)
POLL = 5.0


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def first_in_line(me):
    """who goes first (a live process other than me), or None"""
    try:
        f = FIRST.read_text().split(None, 1)
        pid = int(f[0])
    except (OSError, ValueError, IndexError):
        return None
    return (f[1] if len(f) > 1 else "another model") if pid != me and alive(pid) else None


def holder():
    try:
        return LOCK.read_text().strip() or "another heavy model"
    except OSError:
        return "another heavy model"


@contextmanager
def hold(who, first=False, log=print, poll=None):
    DIR.mkdir(parents=True, exist_ok=True)
    me = os.getpid()
    if first:
        FIRST.write_text(f"{me} {who}")
    f = open(LOCK, "a+")
    held, said, t0 = False, False, time.time()
    try:
        while True:
            ahead = None if first else first_in_line(me)
            if ahead is None:
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    held = True
                    break
                except BlockingIOError:
                    ahead = holder()
            if not said:
                log(f"{who}: waiting for {ahead} to finish (one heavy model at a time on this Mac)")
                said = True
            time.sleep(poll or POLL)
        waited = round(time.time() - t0, 1)
        if said:
            log(f"{who}: its turn after {waited:.0f} s of waiting")
        f.seek(0)
        f.truncate()
        f.write(f"{who} (since {time.strftime('%H:%M:%S')})")
        f.flush()
        yield waited
    finally:
        if held:
            f.seek(0)
            f.truncate()
            f.flush()
            fcntl.flock(f, fcntl.LOCK_UN)
        f.close()
        if first:
            try:
                if FIRST.read_text().split(None, 1)[:1] == [str(me)]:
                    FIRST.write_text("")
            except OSError:
                pass

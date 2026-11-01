"""Start and stop a project's run from outside it (the web panel, phase 2; `bin/monteer stop`).

  start(folder, stage="video")  starts `bin/monteer run` (or `script`) as its own background process group, detached from
                                the caller: closing the panel or its terminal does not stop it. The runner's own lock
                                still allows one run per project. -> {"started": pid} or {"refused": why}
  stop(folder)                  stops the run holding the project's lock and everything it started: the whole process
                                tree is collected first (some tools, such as the music generator, run in a session of their
                                own), then SIGTERM to every group in it, SIGKILL after 15 s to anything left.
                                Finished steps stay done (the record is written after each step) and the next run resumes;
                                the stopped step starts again from its own beginning (long steps resume inside themselves).
                                Writes run/stopped.json and a log line. -> {"stopped": pid} or {"refused": why}
A run that ends at once with an error (for example the runner's own checks refusing to start) is reported as
{"refused": what it said}, and kept in run/start_failed.json until the next start, so the episode page can say it.
"""
import json
import os
import signal
import subprocess
import threading
import time
from pathlib import Path

from .paths import ENGINE

BIN = ENGINE / "bin" / "monteer"


def alive(pid):
    """a running process (a finished one not yet collected by its parent, a zombie, is not running)"""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(st) and not st.startswith("Z")


def lock_pid(folder):
    f = Path(folder) / "run" / "lock"
    try:
        pid = int(f.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None
    return pid if alive(pid) else None


def tree(pid):
    """the process and all its descendants (by parent), whatever session or group each one is in"""
    rows = subprocess.run(["ps", "-axo", "pid=,ppid=,pgid="], capture_output=True, text=True).stdout.split("\n")
    kids, group = {}, {}
    for r in rows:
        f = r.split()
        if len(f) == 3:
            kids.setdefault(int(f[1]), []).append(int(f[0]))
            group[int(f[0])] = int(f[2])
    out, todo = [], [pid]
    while todo:
        x = todo.pop()
        out.append(x)
        todo += kids.get(x, [])
    return out, {group[x] for x in out if x in group}


def start(folder, stage="video"):
    folder = Path(folder).resolve()
    if lock_pid(folder):
        return {"refused": "a run of this project is already going"}
    (folder / "run").mkdir(parents=True, exist_ok=True)
    cmd = [str(BIN), "run" if stage == "video" else "script", str(folder)]
    slog = folder / "run" / "panel_start.log"
    with open(slog, "a", encoding="utf-8") as out:
        out.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] started: {' '.join(cmd)}\n")
        out.flush()
        mark = out.tell()
        p = subprocess.Popen(cmd, cwd=str(ENGINE), stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                             start_new_session=True)
    threading.Thread(target=p.wait, daemon=True).start()     # collect it when it ends (no zombie holding the lock)
    for f in ("stopped.json", "start_failed.json"):
        (folder / "run" / f).unlink(missing_ok=True)
    for _ in range(40):                      # wait until the runner holds its lock (or has already finished/failed)
        if lock_pid(folder) or p.poll() is not None:
            break
        time.sleep(0.25)
    if p.poll() is not None and p.returncode != 0 and not lock_pid(folder):
        with open(slog, "rb") as f:
            f.seek(mark)
            said = f.read().decode("utf-8", "replace").strip()
        why = said[-1200:] or f"it ended at once (code {p.returncode})"
        (folder / "run" / "start_failed.json").write_text(
            json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "why": why}, ensure_ascii=False), encoding="utf-8")
        return {"refused": why}
    return {"started": p.pid}


def stop(folder, by="you"):
    folder = Path(folder).resolve()
    pid = lock_pid(folder)
    if not pid:
        return {"refused": "nothing is running for this project"}
    pids, groups = tree(pid)                 # before anything dies: children are re-parented once their parent goes
    groups.discard(os.getpgid(0))            # never the caller's own group (a run started from this same shell)
    for g in groups:
        try:
            os.killpg(g, signal.SIGTERM)
        except OSError:
            pass
    for x in pids:
        try:
            os.kill(x, signal.SIGTERM)
        except OSError:
            pass
    for _ in range(60):
        if not any(alive(x) for x in pids):
            break
        time.sleep(0.25)
    else:
        for x in pids:
            try:
                os.kill(x, signal.SIGKILL)
            except OSError:
                pass
    run = folder / "run"
    lk = run / "lock"
    if lk.exists() and not lock_pid(folder):
        lk.unlink()
    at = time.strftime("%Y-%m-%d %H:%M:%S")
    (run / "stopped.json").write_text(json.dumps({"at": at, "by": by, "pid": pid}, ensure_ascii=False))
    with open(run / "log.txt", "a", encoding="utf-8") as f:
        f.write(f"[{at[11:]}] === stopped by {by} (bin/monteer stop): finished steps stay; the next run resumes\n")
    return {"stopped": pid}

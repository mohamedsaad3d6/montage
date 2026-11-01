"""The web panel as a background service of this Mac (launchd, the Mac's own way to keep a program running for one user):
it starts by itself when the owner logs in, stays at one fixed address, and comes back by itself if it ever crashes.

    bin/monteer panel install     set it up and start it now (once per Mac; it then starts at every login)
    bin/monteer panel stop        stop it (until `start`, or the next login)
    bin/monteer panel start       start it again
    bin/monteer panel restart     stop and start (after an engine update)
    bin/monteer panel status      running or not, and the address
    bin/monteer panel uninstall   stop it and remove it (it no longer starts at login)

The fixed address is http://127.0.0.1:8765/ (PORT). The service listens on 127.0.0.1 only, like the panel started by hand:
no other device can reach it (monteer/panel/server.py says how the page itself is guarded). Video runs it starts are
processes of their own: stopping or restarting the panel does not stop a run (use the panel's Stop, or `bin/monteer stop`).
Its file: ~/Library/LaunchAgents/com.monteer.panel.plist (paths only, no secret). Its log: monteer_data/logs/panel.log.
"""
import os
import plistlib
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from ..core.paths import DATA, ENGINE

LABEL = "com.monteer.panel"
PORT = 8765
URL = f"http://127.0.0.1:{PORT}/"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG = DATA / "logs" / "panel.log"
TARGET = f"gui/{os.getuid()}"


def launchctl(*a):
    return subprocess.run(["launchctl", *a], capture_output=True, text=True)


def path_env():
    """the programs a run needs (Claude Code, node, git, swiftc): their folders as found now, then the usual ones"""
    dirs = []
    for prog in ("claude", "node", "git", "swiftc"):
        w = shutil.which(prog)
        if w:
            dirs.append(str(Path(w).parent))
    dirs += [str(Path.home() / ".local" / "bin"), "/opt/homebrew/bin", "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    return ":".join(dict.fromkeys(dirs))


def write_plist():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    cfg = {"Label": LABEL,
           "ProgramArguments": [str(ENGINE / "bin" / "monteer"), "panel", "--no-open", "--port", str(PORT)],
           "WorkingDirectory": str(ENGINE),
           "EnvironmentVariables": {"PATH": path_env(), "LANG": "en_US.UTF-8", "PYTHONUNBUFFERED": "1"},
           "RunAtLoad": True,
           "KeepAlive": {"SuccessfulExit": False},       # back after a crash; a clean stop stays stopped
           "ThrottleInterval": 20,                       # e.g. while the port is held by a panel started by hand
           "ProcessType": "Interactive",
           "LimitLoadToSessionType": "Aqua",             # the logged-in desktop: the file window can show
           "StandardOutPath": str(LOG), "StandardErrorPath": str(LOG)}
    PLIST.write_bytes(plistlib.dumps(cfg))


def loaded():
    return launchctl("print", f"{TARGET}/{LABEL}").returncode == 0


def pid():
    r = launchctl("print", f"{TARGET}/{LABEL}")
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("pid = "):
            return int(line.split("=")[1])
    return None


def answering(wait=0.0):
    """the panel answers at its address (any answer: the page itself needs the browser's cookie)"""
    end = time.time() + wait
    while True:
        try:
            urllib.request.urlopen(urllib.request.Request(URL, method="HEAD"), timeout=2)
            return True
        except urllib.error.HTTPError:
            return True
        except OSError:
            if time.time() >= end:
                return False
            time.sleep(0.5)


def start():
    if not PLIST.exists():
        write_plist()
    if not loaded():
        r = launchctl("bootstrap", TARGET, str(PLIST))
        if r.returncode and not loaded():
            return f"could not start the panel service: {r.stderr.strip()}"
    else:
        launchctl("kickstart", f"{TARGET}/{LABEL}")
    if answering(wait=20):
        return f"the panel is running: {URL}"
    return f"the service started but the panel does not answer yet; see {LOG}"


def stop():
    if not loaded():
        return "the panel service is not running"
    launchctl("bootout", f"{TARGET}/{LABEL}")
    for _ in range(40):
        if not loaded():
            break
        time.sleep(0.25)
    return "the panel is stopped (it starts again with  bin/monteer panel start, or at the next login)"


def status():
    p = pid()
    if not PLIST.exists():
        return "the panel service is not installed (bin/monteer panel install)"
    if not loaded():
        return "the panel service is installed but stopped (bin/monteer panel start)"
    return (f"the panel is running (process {p}): {URL}" if p and answering(wait=2)
            else f"the panel service is loaded but the panel does not answer; see {LOG}")


def main(cmd):
    if cmd == "install":
        if loaded():
            stop()
        write_plist()
        print(start())
        print("It now starts by itself at every login. Bookmark: " + URL)
    elif cmd == "uninstall":
        print(stop())
        PLIST.unlink(missing_ok=True)
        print("removed: it no longer starts at login")
    elif cmd == "start":
        print(start())
    elif cmd == "stop":
        print(stop())
    elif cmd == "restart":
        stop()
        print(start())
    elif cmd == "status":
        print(status())
    return 0

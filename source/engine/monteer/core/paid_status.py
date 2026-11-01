"""Are the paid services connected? (the «حلقة جديدة» sources card, owner's bug report of 21 Oct 2026)

  Magnific     its API key is in the keys file (present / missing; the value never leaves the keys file)
  Storyblocks  the Storyblocks connector on this Mac's Claude account answers: `claude mcp get "claude.ai Storyblocks"`
               (about 3 s; the panel keeps the answer 10 minutes)

  status() -> {"magnific": {"connected", "detail"}, "storyblocks": {"connected", "detail"}, "checked_at"}
"""
import os
import subprocess
import time
from pathlib import Path

CLAUDE = Path(os.path.expanduser("~/.local/bin/claude"))
SERVER = "claude.ai Storyblocks"


def storyblocks():
    if not CLAUDE.exists():
        return {"connected": False, "detail": "Claude Code is not installed on this Mac"}
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    try:
        r = subprocess.run([str(CLAUDE), "mcp", "get", SERVER], capture_output=True, text=True, timeout=30, env=env,
                           cwd=os.path.expanduser("~"))
    except (OSError, subprocess.TimeoutExpired):
        return {"connected": None, "detail": "the check did not answer in time"}
    line = next((ln.strip() for ln in (r.stdout + r.stderr).splitlines() if ln.strip().lower().startswith("status:")), "")
    if not line:
        return {"connected": False, "detail": "the Storyblocks connector is not on this Mac's Claude account"}
    return {"connected": "connected" in line.lower() and "✘" not in line and "not" not in line.lower(), "detail": line}


def status():
    from . import apikeys
    from ..montage.sources import magnific as MG
    key = bool(apikeys.get(MG.KEY))
    return {"magnific": {"connected": key, "detail": "API key present" if key else "no API key in the keys file"},
            "storyblocks": storyblocks(), "checked_at": time.strftime("%Y-%m-%d %H:%M:%S")}

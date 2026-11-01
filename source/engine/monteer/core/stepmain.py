"""Runs one step in its own process (the runner calls this in the step's Python environment).

    <env python> -m monteer.core.stepmain <step> <project folder> [stage: video | script]

A step running at the same time as the main ones (MONTEER_ALONGSIDE = its own waiting file, fast mode phase D) keeps
its waiting items in that file: it never touches the main steps' run/waiting.json.
"""
import os
import sys
from pathlib import Path

from .brain import WAITING_EXIT, BrainUnavailable, NeedsDecision
from .io import save_json
from .project import Project

def main():
    name, folder = sys.argv[1], sys.argv[2]
    from .runner import stage_steps
    _, by_name = stage_steps(sys.argv[3] if len(sys.argv) > 3 else "video")
    proj = Project(folder)
    side = os.environ.get("MONTEER_ALONGSIDE")
    waiting = Path(side) if side else proj.run / "waiting.json"
    try:
        by_name[name].fn(proj)
    except NeedsDecision as e:
        save_json(waiting, e.items)
        sys.exit(WAITING_EXIT)
    except BrainUnavailable as e:
        sys.exit(f"STOP: no brain could answer: {e}")
    waiting.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

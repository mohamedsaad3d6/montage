"""Projects made before the channel profiles move to «عام» (general): owner's answer 2 of 18 Oct 2026, who accepts that
the brain decides again for them (the channel folder named in every request changes, and so does project.json).

    bin/monteer profiles migrate [--apply] [FOLDER ...]

Looks at every project in AI agent/monteer_projects/ and AI agent/monteer_tests/ (or the folders given). A project that
has no "profile" gets "profile": "general"; its "channel" setting is removed (the folder now comes from the profile:
channels/general, which carries the earlier channel's settings, source list, style guide and variety ledger). The old
project.json is kept as run/project.before_profiles.json, so the move can be undone by hand.

Left as they are, with the reason printed:
  - projects already on a profile;
  - the classic same-result test projects (options.montage "classic"): they replay earlier results exactly, and the
    classic montage is not a montage any profile runs;
  - a project whose run is going on (its lock is held): move it after the run.
Without --apply nothing is written (a dry run).
"""
import json
import shutil

from .paths import ENGINE
from .runctl import lock_pid

ROOTS = (ENGINE.parent / "monteer_projects", ENGINE.parent / "monteer_tests")
TARGET = "general"


def plan(folders=None):
    """[(folder, action, why)] with action "move" or "keep" """
    if folders:
        from pathlib import Path
        cands = [Path(f).expanduser().resolve() for f in folders]
    else:
        cands = sorted(d for r in ROOTS if r.exists() for d in r.iterdir() if (d / "project.json").exists())
    out = []
    for d in cands:
        f = d / "project.json"
        if not f.exists():
            out.append((d, "keep", "no project.json"))
            continue
        cfg = json.loads(f.read_text(encoding="utf-8"))
        if cfg.get("profile"):
            out.append((d, "keep", f"already on the profile {cfg['profile']}"))
        elif (cfg.get("options") or {}).get("montage") == "classic":
            out.append((d, "keep", "a classic same-result test project"))
        elif lock_pid(d):
            out.append((d, "keep", "its run is going on: move it after the run"))
        else:
            out.append((d, "move", f"channel was {cfg.get('channel') or 'none'}"))
    return out


def move(folder):
    f = folder / "project.json"
    cfg = json.loads(f.read_text(encoding="utf-8"))
    keep = folder / "run" / "project.before_profiles.json"
    keep.parent.mkdir(parents=True, exist_ok=True)
    if not keep.exists():
        shutil.copy2(f, keep)
    new = {}
    for k, v in cfg.items():                  # same order, "profile" where "channel" was (or after "mode")
        if k == "channel":
            new["profile"] = TARGET
            continue
        new[k] = v
        if k == "mode" and "channel" not in cfg:
            new["profile"] = TARGET
    new.setdefault("profile", TARGET)
    tmp = f.with_name(".project.json.part")
    tmp.write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(f)


def main(argv):
    apply = "--apply" in argv
    rows = plan([a for a in argv if a != "--apply"])
    for d, action, why in rows:
        print(f"{'moved ' if apply and action == 'move' else 'move  ' if action == 'move' else 'keep  '} {d.name:42s} {why}")
        if apply and action == "move":
            move(d)
    n = sum(1 for _, a, _ in rows if a == "move")
    print(f"{n} project(s) {'moved' if apply else 'to move'} to the profile {TARGET}" + ("" if apply else " (dry run: add --apply)"))
    return 0

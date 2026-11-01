"""The panel's Trash (owner's request of 18 Oct 2026): «حذف الحلقة» / «وقّف واحذف» and «ابدأ من الأول» never delete
anything. A running episode is stopped safely first (core/runctl.py stop: its finished steps stay).

  trash_episode(folder, by)  the whole episode folder -> <projects>/.trash/<name> (+ trashed.json: when, who, from where)
  restart(folder, by)        the episode's run, work, output and decisions -> <projects>/.trash/<name>__restart_<time>;
                             project.json (the same inputs and options), its input/ files and its script/ stay; the run
                             starts again from zero
  items(projects)            what is in the Trash
  restore(projects, name)    an episode goes back where it was; the files of a restart come back as an episode of their
                             own («<name> — before the restart»), so nothing is merged into the new run
  set_aside_refused(folder, why, kind)  a new script or episode refused at once (the panel's «ابدأ البحث», «حلقة جديدة»):
                             its just-made folder -> <projects>/.refused/<name> (+ refused.json: why, when); not in the Trash
  set_aside_used_draft(draft)  an upload folder whose files went into a new episode -> <projects>/.drafts_used/<name>
Nothing here deletes a file; emptying the Trash is the owner's own act (the folder <projects>/.trash in Finder).
"""
import shutil
import time
from pathlib import Path

from .io import load_json, save_json
from .runctl import lock_pid, stop

KEEP_ON_RESTART = ("project.json", "input", "script")


def trash_dir(projects):
    d = Path(projects) / ".trash"
    d.mkdir(parents=True, exist_ok=True)
    return d


def stop_and_wait(folder, by, wait_s=60):
    """a running episode is stopped safely (its finished steps stay); raises when it does not stop"""
    if not lock_pid(folder):
        return False
    stop(folder, by=by)
    for _ in range(int(wait_s * 4)):
        if not lock_pid(folder):
            return True
        time.sleep(0.25)
    raise RuntimeError("the run did not stop: try again in a minute")


def _free_name(d, name):
    out, k = d / name, 2
    while out.exists():
        out, k = d / f"{name}_{k}", k + 1
    return out


def trash_episode(folder, by):
    folder = Path(folder).resolve()
    stopped = stop_and_wait(folder, by=f"{by} (delete)")
    dst = _free_name(trash_dir(folder.parent), folder.name)
    name = (load_json(folder / "project.json").get("name") if (folder / "project.json").exists() else None) or folder.name
    shutil.move(str(folder), str(dst))
    save_json(dst / "trashed.json", {"kind": "episode", "name": name, "from": str(folder), "by": by,
                                     "at": time.strftime("%Y-%m-%d %H:%M:%S"), "was_running": stopped})
    return {"trashed": dst.name, "stopped": stopped}


def restart(folder, by):
    from . import runctl
    folder = Path(folder).resolve()
    stopped = stop_and_wait(folder, by=f"{by} (start from zero)")
    name = load_json(folder / "project.json").get("name") or folder.name
    dst = _free_name(trash_dir(folder.parent), f"{folder.name}__restart_{time.strftime('%Y%m%d-%H%M%S')}")
    dst.mkdir()
    moved = []
    for x in sorted(folder.iterdir()):
        if x.name in KEEP_ON_RESTART or x.name.startswith("."):
            continue
        shutil.move(str(x), str(dst / x.name))
        moved.append(x.name)
    shutil.copy2(folder / "project.json", dst / "project.json")
    save_json(dst / "trashed.json", {"kind": "restart", "name": name, "from": str(folder), "by": by, "moved": moved,
                                     "at": time.strftime("%Y-%m-%d %H:%M:%S"), "was_running": stopped})
    return {"trashed": dst.name, "moved": moved, "stopped": stopped, "started": runctl.start(folder)}


def items(projects):
    d = Path(projects) / ".trash"
    out = []
    for x in sorted(d.iterdir()) if d.exists() else []:
        f = x / "trashed.json"
        if x.is_dir() and f.exists():
            out.append(dict(load_json(f), folder=x.name))
    return sorted(out, key=lambda r: r.get("at", ""), reverse=True)


def restore(projects, name):
    projects = Path(projects)
    src = projects / ".trash" / Path(name).name
    if not (src / "trashed.json").exists():
        raise ValueError("no such item in the Trash")
    rec = load_json(src / "trashed.json")
    if rec["kind"] == "episode":
        dst = Path(rec["from"])
        if dst.exists() or dst.parent.resolve() != projects.resolve():
            dst = _free_name(projects, Path(rec["from"]).name)
    else:                                   # the files from before a restart: an episode of their own
        dst = _free_name(projects, Path(rec["from"]).name + "_before_restart")
        cfg = load_json(src / "project.json")
        cfg["name"] = f"{cfg.get('name') or Path(rec['from']).name} — قبل البداية من الأول / before the restart"
        save_json(src / "project.json", cfg)
    (src / "trashed.json").rename(src / f"restored_{time.strftime('%Y%m%d-%H%M%S')}.json")
    shutil.move(str(src), str(dst))
    return {"restored": dst.name}


__all__ = ["trash_episode", "restart", "items", "restore", "stop_and_wait"]


def _move_aside(folder, into, note, record):
    """owner's rule of 20 Oct 2026: nothing is deleted. folder -> into/<name> (+ note: the record); None when there is no
    folder"""
    folder = Path(folder)
    if not folder.exists():
        return None
    Path(into).mkdir(parents=True, exist_ok=True)
    dst = _free_name(Path(into), folder.name)
    shutil.move(str(folder), str(dst))
    save_json(dst / note, dict(record, **{"from": str(folder), "at": time.strftime("%Y-%m-%d %H:%M:%S")}))
    return dst


def set_aside_refused(folder, why, kind="new script refused"):
    """the folder the panel made for a new script or episode that was refused -> <projects>/.refused/<name>, with why"""
    return _move_aside(folder, Path(folder).parent / ".refused", "refused.json", {"kind": kind, "why": why})


def set_aside_used_draft(draft):
    """an upload folder (<projects>/.drafts/<id>) whose files were moved into a new episode -> <projects>/.drafts_used/<id>"""
    return _move_aside(draft, Path(draft).parent.parent / ".drafts_used", "used.json", {"kind": "upload folder used by a new episode"})

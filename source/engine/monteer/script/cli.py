"""bin/monteer script — the script tool (the first stage: script -> recording or voice -> montage).

  bin/monteer script new "<project>" --topic "…" --profile SLUG [--angle "…"] [--minutes N] --mode talking_head|voice_only
  bin/monteer script "<project>" [--brain claude-bg|claude-code|api|local] [--from STEP] [--only STEP]
        runs the steps; stops where the brain or you are needed; run it again to continue (and to import your Word edits)
  bin/monteer script status "<project>"
  bin/monteer script outline-ok "<project>" --name "<who>"           your yes to the outline
  bin/monteer script outline-edit "<project>" --notes "…"            your changes: the outline is made again with them
  bin/monteer script approve "<project>" --name "<who>" [--accept-local]
  bin/monteer script learn-style "<channel>" --from "<Works folder>"  measure past scripts + ask the brain for the style guide
  bin/monteer script style-approve "<channel>" --name "<who>"
  bin/monteer script steps
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from ..core import runner
from ..core.io import load_json, save_json
from ..core.project import Project


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "new":
        ap = argparse.ArgumentParser(prog="monteer script new")
        ap.add_argument("project")
        ap.add_argument("--topic", required=True)
        from ..core.profile import SLUGS
        ap.add_argument("--profile", choices=list(SLUGS), help="the channel profile (required for a new project; no default)")
        ap.add_argument("--angle", default="")
        ap.add_argument("--minutes", type=float)
        ap.add_argument("--mode", required=True, choices=["talking_head", "voice_only"],
                        help="the video type, chosen at the start: talking_head = with presenter (بمذيع), voice_only = audio only (صوت بس)")
        ap.add_argument("--name")
        a = ap.parse_args(argv[1:])
        folder = Path(a.project).expanduser().resolve()
        folder.mkdir(parents=True, exist_ok=True)
        pj = folder / "project.json"
        if not pj.exists():
            if not a.profile:
                raise SystemExit("المشروع الجديد محتاج قناة: --profile (" + ", ".join(SLUGS) + ")")
            from ..core.profile import TYPE_OF_MODE, ProfileError, check_type
            try:
                check_type(a.profile, TYPE_OF_MODE[a.mode])
            except ProfileError as e:
                raise SystemExit(str(e))
            save_json(pj, {"name": a.name or folder.name, "mode": a.mode, "profile": a.profile, "language": "ar",
                           "inputs": {}, "options": {"version": 1}})
        p = Project(folder)
        t = {"topic": a.topic, "angle": a.angle, "minutes": a.minutes, "language": "ar", "dialect": "egyptian",
             "today": time.strftime("%Y-%m-%d"), "created": time.strftime("%Y-%m-%d %H:%M:%S")}
        save_json(folder / "script" / "topic.json", t)
        print(f"project {p.folder}: topic set. Next:  bin/monteer script \"{p.folder}\"")
        return 0
    if cmd == "steps":
        from .steps import STEPS
        for s in STEPS:
            print(f"{s.name:12s} {s.what}")
        return 0
    if cmd == "status":
        p = Project(argv[1])
        runner.status(argv[1], stage="script")
        from .common import S, latest_version
        v = latest_version(p)
        print(f"latest checked draft: v{v}" if v else "no checked draft yet")
        if S(p, "outline_ok.json").exists():
            print("outline: approved by", load_json(S(p, "outline_ok.json"))["by"])
        a = S(p, "approved.json")
        print(f"approval: by {load_json(a)['by']} at {load_json(a)['at']} (v{load_json(a)['version']})" if a.exists() else "approval: none")
        return 0
    if cmd == "outline-ok":
        ap = argparse.ArgumentParser(prog="monteer script outline-ok")
        ap.add_argument("project")
        ap.add_argument("--name", required=True)
        a = ap.parse_args(argv[1:])
        from .common import S, sha
        p = Project(a.project)
        o = load_json(S(p, "outline.json"))
        save_json(S(p, "outline_ok.json"), {"by": a.name, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "sha": sha(o["outline"])})
        print(f"outline approved by {a.name}. Next:  bin/monteer script \"{p.folder}\"")
        return 0
    if cmd == "outline-edit":
        ap = argparse.ArgumentParser(prog="monteer script outline-edit")
        ap.add_argument("project")
        ap.add_argument("--notes", required=True)
        a = ap.parse_args(argv[1:])
        from .common import S
        p = Project(a.project)
        f = S(p, "outline_notes.json")
        d = load_json(f) if f.exists() else {"notes": []}
        d["notes"].append(a.notes)
        save_json(f, d)
        S(p, "outline_ok.json").unlink(missing_ok=True)
        print(f"notes saved ({len(d['notes'])}). Next:  bin/monteer script \"{p.folder}\"  (the outline is made again)")
        return 0
    if cmd == "approve":
        ap = argparse.ArgumentParser(prog="monteer script approve")
        ap.add_argument("project")
        ap.add_argument("--name", required=True)
        ap.add_argument("--accept-local", action="store_true")
        a = ap.parse_args(argv[1:])
        os.environ["MONTEER_PROJECT"] = str(Project(a.project).folder)
        from . import approve
        approve.approve(Project(a.project), a.name, a.accept_local)
        return 0
    if cmd == "learn-style":
        ap = argparse.ArgumentParser(prog="monteer script learn-style")
        ap.add_argument("channel")
        ap.add_argument("--from", dest="works", required=True)
        a = ap.parse_args(argv[1:])
        from ..core.brain import WAITING_EXIT, NeedsDecision
        from . import style
        try:
            prof, good, bad = style.learn(a.channel, a.works)
        except NeedsDecision as e:
            for i in e.items:
                print(f"WAITING for the brain: {i['step']}/{i['key']} -> {i['request']}")
            return WAITING_EXIT
        print(f"style guide written ({len(good)} excerpts kept, {len(bad)} rejected as not word-for-word). "
              f"Default length {prof['length']['default_minutes']} min ≈ {prof['length']['default_words']} words. "
              f"Read and edit {Path(a.channel) / 'style' / 'style_guide.md'}, then: bin/monteer script style-approve …")
        return 0
    if cmd == "style-approve":
        ap = argparse.ArgumentParser(prog="monteer script style-approve")
        ap.add_argument("channel")
        ap.add_argument("--name", required=True)
        a = ap.parse_args(argv[1:])
        from . import style
        style.approve(a.channel, a.name)
        print("style guide:", style.status(a.channel)[0])
        return 0
    ap = argparse.ArgumentParser(prog="monteer script")
    ap.add_argument("project")
    ap.add_argument("--brain", choices=["claude-bg", "claude-code", "api", "local"])
    ap.add_argument("--from", dest="start_from")
    ap.add_argument("--only")
    ap.add_argument("--until")
    a = ap.parse_args(argv)
    if a.brain:
        os.environ["MONTEER_BRAIN"] = a.brain
    return runner.run(a.project, start_from=a.start_from, only=a.only, until=a.until, stage="script")


def sources_main(argv):
    if not argv or argv[0] in ("-h", "--help", "help") or len(argv) < 2:
        print(__doc__.split("\n")[0], "\n  bin/monteer sources init|list|on|off|add|check \"<channel>\" [ID] [--json '{…}']")
        return 0
    from . import sources
    cmd, ch = argv[0], argv[1]
    if cmd == "init":
        print(sources.init(ch))
    elif cmd == "list":
        for s in sources.load(ch):
            chk = s.get("checked", {})
            print(f"{'ON ' if s.get('on') else 'off'} {s['id']:20s} {s['kind']:9s} {s['access']:16s} {s['name']}"
                  + (f"   [{chk.get('at')}: {chk.get('result')}]" if chk else "") + (f"   — {s['note']}" if s.get("note") else ""))
    elif cmd in ("on", "off"):
        srcs = sources.load(ch)
        hit = [s for s in srcs if s["id"] == argv[2]]
        if not hit:
            raise SystemExit(f"مفيش مصدر اسمه {argv[2]!r}")
        hit[0]["on"] = cmd == "on"
        sources.save(ch, srcs)
        print(f"{argv[2]}: {cmd}")
    elif cmd == "add":
        if "--json" not in argv:
            raise SystemExit('إضافة مصدر محتاجة --json \'{"id": "...", "name": "...", "kind": "news", "lang": "ar", "access": "rss", '
                             '"url": "...", "domains": ["..."], "terms": "..."}\'')
        new = json.loads(argv[argv.index("--json") + 1])
        for k in ("id", "name", "kind", "lang", "access", "url"):
            if k not in new:
                raise SystemExit(f"المصدر الجديد ناقصه {k!r}")
        new.setdefault("on", True)
        srcs = [s for s in sources.load(ch) if s["id"] != new["id"]] + [new]
        sources.save(ch, srcs)
        print(f"added {new['id']}; check it with  bin/monteer sources check \"{ch}\"")
    elif cmd == "check":
        rows, changed = sources.check(ch)
        print(f"checked {sum(1 for r in rows if r[1] != 'off')} sources; switched off: {', '.join(changed) or 'none'}")
    else:
        print(f"unknown: {cmd}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

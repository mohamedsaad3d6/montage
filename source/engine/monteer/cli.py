"""bin/monteer: the one command.

    bin/monteer new "<project>" --profile SLUG --type presenter|audio [--video F] [--audio F] [--script F] [--name N]
                                [--output montage|cut] [--run-mode auto] [--instructions "…"] [--clip F ...]
                                [--ad F] [--series-tag] [--opening motion|timelapse]   (as the profile offers)
                                                            a new video: its channel profile and type are chosen here, at
                                                            the start (presenter = with presenter, بمذيع; audio = audio
                                                            only, صوت بس); only the types the profile offers
    bin/monteer profiles [list] | show SLUG                 the channel profiles (AI agent/channels/<slug>/)
    bin/monteer profiles migrate [--apply]                  projects from before the profiles -> «عام» (dry run without --apply)
    bin/monteer edit "<project>" new REQUESTS.json | prepare N | apply N | cancel N | show
                                                            edit until satisfied (montage/edits.py): REQUESTS.json =
                                                            [{"text": "…", "t": 83.5}, …]; new prepares the round and
                                                            shows what will be redone; apply makes the next version
    bin/monteer approve-final "<project>" --video NAME.mp4 --by "<your name>"
                                                            your final approval of one finished version (output/approved.json)
    bin/monteer answer "<project>" accept-all | let-it-decide | ANSWERS.json
                                                            step by step: your answers to the agent's questions on the plan
                                                            (ANSWERS.json: {"1": {"choice": "b"}, "2": {"choice": "other",
                                                            "text": "…"}}); then run it again
    bin/monteer learn show ["<project>"] | tell "<words>" | forget N | refresh "<project>"
                                                            what «عام» learned (montage/learning.py); tell it something
    bin/monteer run "<project>" [--from STEP] [--only STEP] [--until STEP] [--brain claude-bg|claude-code|api|local]
    bin/monteer stop "<project>"                             stop its run (finished steps stay; the next run resumes)
    bin/monteer remix-audio "<project>" [--sample START [--seconds 60]]   a finished episode's sound made again on its
                                                             picture, copied as it is (--sample: a short check first)
    bin/monteer library import [<project>…] | status        the local picture library (Commons files kept on this Mac)
    bin/monteer music import | auto | status | list | approve ID | reject ID   the music library (approved: no word heard)
    bin/monteer status "<project>" [--json]                  which steps are done; --json: the panel's summary
    bin/monteer panel [--port 8765] [--no-open]              the web panel on this Mac only (http://127.0.0.1)
    bin/monteer panel install|stop|start|restart|status|uninstall   the panel as a background service: starts at
                                                            login, always at http://127.0.0.1:8765/
    bin/monteer steps
    bin/monteer brain list "<project>"                      decisions waiting, and the ones made
    bin/monteer brain show "<project>" STEP KEY             the request (what is needed, which files, answer shape)
    bin/monteer brain answer "<project>" STEP KEY FILE      store the decision (a JSON file) for that request
    bin/monteer brain accept "<project>" STEP KEY           keep a stale decision unchanged for the new request
    bin/monteer brain redo "<project>" STEP KEY             set a decision aside: the next run asks for it again
    (brain commands also take a channel folder, for the style guide's decision)

    bin/monteer script ...                                  the script tool: see  bin/monteer script help
    bin/monteer sources init|list|on|off|add|check "<channel>" [ID] [--json '{...}']   the channel's source list
"""
import argparse
import json
import sys

from .core import brain, runner
from .core.project import Project


def ctx(folder):
    """a project, or a channel folder (its style guide's decisions)"""
    from pathlib import Path
    f = Path(folder).expanduser()
    if (f / "project.json").exists() or not (f / "channel.json").exists():
        return Project(folder)
    from .script.style import ChannelCtx
    return ChannelCtx(folder)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "audio-review":
        from .audio_review.pipeline import main as review_main
        return review_main(argv[1:])
    if cmd == "run":
        ap = argparse.ArgumentParser(prog="monteer run")
        ap.add_argument("project")
        ap.add_argument("--from", dest="start_from")
        ap.add_argument("--only")
        ap.add_argument("--until")
        ap.add_argument("--brain", choices=list(brain.BRAINS))
        a = ap.parse_args(argv[1:])
        if a.brain:
            import os
            os.environ["MONTEER_BRAIN"] = a.brain
        return runner.run(a.project, start_from=a.start_from, only=a.only, until=a.until)
    if cmd == "remix-audio":            # the sound made again, the picture copied (montage/remix.py)
        ap = argparse.ArgumentParser(prog="monteer remix-audio")
        ap.add_argument("project")
        ap.add_argument("--sample", type=float)
        ap.add_argument("--seconds", type=float, default=60.0)
        a = ap.parse_args(argv[1:])
        from .core.project import Project
        from .montage import remix
        p = Project(a.project)
        out = remix.sample(p, a.sample, a.seconds) if a.sample is not None else remix.full(p)
        print(out)
        return 0
    if cmd == "new":
        return new(argv[1:])
    if cmd == "profiles":
        from .core import profile
        try:
            return profile.main(argv[1:])
        except profile.ProfileError as e:
            raise SystemExit(str(e))
    if cmd == "edit":
        from .montage import edits as ED
        p, sub = Project(argv[1]), argv[2] if len(argv) > 2 else "show"
        try:
            if sub == "new":
                n = ED.new_round(p, json.load(open(argv[3], encoding="utf-8")), by="owner (bin/monteer edit)")
                r = ED.prepare(p, n)
            elif sub == "prepare":
                r = ED.prepare(p, int(argv[3]))
            elif sub == "apply":
                print(json.dumps(ED.apply(p, int(argv[3])), ensure_ascii=False))
                return 0
            elif sub == "cancel":
                ED.cancel(p, int(argv[3]))
                print("cancelled")
                return 0
            else:
                print(json.dumps(ED.history(p), ensure_ascii=False, indent=1))
                return 0
        except ValueError as e:
            raise SystemExit(str(e))
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if r["status"] == "prepared" else 1
    if cmd == "approve-final":                      # the owner's final approval of one finished version
        from .montage import result as RES
        ap = argparse.ArgumentParser(prog="monteer approve-final")
        ap.add_argument("project")
        ap.add_argument("--video", required=True, help="the finished video's file name in output/")
        ap.add_argument("--by", required=True, help="your name (approvals are the person's own)")
        a = ap.parse_args(argv[1:])
        try:
            rec = RES.approve(Project(a.project), a.video, a.by)
        except ValueError as e:
            raise SystemExit(str(e))
        print(f"approved: {rec['video']} (version {rec['version']}) by {rec['by']}")
        return 0
    if cmd == "answer":
        from .montage import questions
        p = Project(argv[1])
        how = argv[2]
        mode = {"accept-all": "accept_all", "let-it-decide": "let_it_decide"}.get(how, "answers")
        given = None if mode != "answers" else json.load(open(how, encoding="utf-8"))
        try:
            rows = questions.store(p, mode, given, by="owner (bin/monteer answer)")
        except ValueError as e:
            raise SystemExit(str(e))
        print(f"kept {len(rows)} answer(s) ({mode}); run it again: bin/monteer run \"{p.folder}\"")
        return 0
    if cmd == "music":
        from .music import library as music_library
        return music_library.main(argv[1:])
    if cmd == "library":
        from .montage.sources import local_library
        return local_library.main(argv[1:])
    if cmd == "learn":
        from .montage import learning
        return learning.main(argv[1:])
    if cmd == "status":
        if "--json" in argv:            # one summary for the panel and scripts (monteer/core/summary.py)
            from .core import summary
            summary.main([a for a in argv[1:] if a != "--json"][0])
        else:
            runner.status(argv[1])
        return 0
    if cmd == "stop":                   # stop a running run cleanly (monteer/core/runctl.py)
        from .core import runctl
        print(json.dumps(runctl.stop(argv[1]), ensure_ascii=False))
        return 0
    if cmd == "panel":
        from .panel import server
        return server.main(argv[1:])
    if cmd == "steps":
        from .steps import STEPS
        for s in STEPS:
            print(f"{s.name:16s} [{s.env:4s}] {'/'.join(m.replace('_', '-') for m in s.modes):24s} {s.what}")
        return 0
    if cmd == "script":
        from .script import cli as script_cli
        return script_cli.main(argv[1:])
    if cmd == "sources":
        from .script import cli as script_cli
        return script_cli.sources_main(argv[1:])
    if cmd == "brain":
        sub, proj = argv[1], ctx(argv[2])
        if sub == "list":
            for f in sorted(x for x in proj.decisions.rglob("*.json") if ".replaced_" not in x.name):
                kind = "WAITING " if f.name.endswith(".request.json") else "decided "
                print(kind, f.relative_to(proj.decisions))
        elif sub == "show":
            print((proj.decisions / argv[3] / f"{argv[4]}.request.json").read_text())
        elif sub == "answer":
            print("stored", brain.answer(proj, argv[3], argv[4], json.loads(open(argv[5], encoding="utf-8").read())))
        elif sub == "redo":
            brain.redo(proj, argv[3], argv[4])
            print("set aside; the next run asks again")
        elif sub == "accept":
            brain.accept(proj, argv[3], argv[4])
            print("accepted")
        return 0
    print(__doc__)
    return 1


def new(argv):
    """a new video project; the type is required and decides the montage (monteer/core/newproject.py)"""
    from .core.newproject import Refused, create
    ap = argparse.ArgumentParser(prog="monteer new")
    from .core.profile import SLUGS
    ap.add_argument("project")
    ap.add_argument("--profile", required=True, choices=list(SLUGS),
                    help="the channel profile (no default): al-hadath = الحدث الأخير, secret-files = الملفات السرية, "
                         "ahmes = اقتصاد احمس, trend-tweet = ترند وتويتة, general = عام")
    ap.add_argument("--type", required=True, choices=["presenter", "audio"],
                    help="presenter = with presenter (بمذيع): camera + microphone + script; audio = audio only (صوت بس): a narration")
    ap.add_argument("--video")
    ap.add_argument("--audio")
    ap.add_argument("--script")
    ap.add_argument("--name")
    ap.add_argument("--output", default="montage", choices=["montage", "cut"], help="cut = the cut only (presenter type only)")
    ap.add_argument("--run-mode", default="auto", choices=["auto", "step"])
    ap.add_argument("--instructions", default="", help="your words for this episode, given to the plan")
    ap.add_argument("--clip", action="append", default=[], help="one of your own extra clips (repeat for more)")
    ap.add_argument("--ad", help="the episode's ad (a video), put in after the channel's intro clip (al-hadath)")
    ap.add_argument("--series-tag", action="store_true", help="the channel's series tag in its corner (al-hadath)")
    ap.add_argument("--opening", choices=["motion", "timelapse"], help="how the fast intro opens (al-hadath; default motion)")
    a = ap.parse_args(argv)
    try:
        p = create(a.project, a.type, a.name, a.video, a.audio, a.script, a.profile, a.output, a.run_mode, a.instructions, a.clip,
                   ad=a.ad, series_tag=a.series_tag, opening=a.opening)
    except Refused as e:
        raise SystemExit(str(e))
    print(f"{p.folder}: profile {p.profile}, {p.type_name}, the {p.montage} montage{' (cut only)' if a.output == 'cut' else ''}. "
          f"Next:  bin/monteer run \"{p.folder}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())

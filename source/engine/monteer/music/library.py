"""The music library on this Mac.

Channel episodes (owner's decision of 19 Oct 2026, after the first fast-mode runs): NO music is generated. Each section
gets one of the instrumental tracks downloaded once into this library (kind "track": a clear free licence with its
credit line, the engine's vocals check heard no voice and no word), chosen by mood (pick_tracks) and looped or cut to
the section by the mix. The classic test projects still make their cues with ACE-Step, as before.

The ACE-Step cues of earlier episodes copied in on 19 Oct 2026 (decision 1c) stay here, approved or rejected by the
speech check, but no episode uses them any more.

  <DATA>/music_library/<id>/take.wav     the raw recording (the mix reads it at the record's finishing gain)
                         /<id>/cue.wav      the finished cue (-20 LUFS)
                         /<id>/record.json  the music step's record: generator, licence, credit, finish, takes
                         index.json         {id: {kind ("track" | an ACE cue), prompt, seconds, moods, voice_score, words_heard,
                                                   licence, approval: "approved" | "rejected", by, at}}

  tracks()                 the approved downloaded tracks (the only music a channel episode uses)
  pick_tracks(cues)        {cue: track}: best mood fit first, each track once while there are unused ones
  add_track(wav, meta, check) / add_tracks(manifest)   a downloaded track in, checked, approved or rejected
  use(id, out_dir, cue)    the library's cue as the episode's cue <name>.wav/.json (its record says where it came from)

  bin/monteer music tracks | add-tracks <manifest.json> | status | list | import | auto | approve <id> | reject <id>
"""
import fcntl
import hashlib
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from ..core.io import load_json, save_json
from ..core.paths import DATA

LIB = DATA / "music_library"
INDEX = LIB / "index.json"
BOILER = set("instrumental no vocals documentary underscore low and steady under narration energetic punchy percussion".split())


def index():
    return load_json(INDEX) if INDEX.exists() else {}


@contextmanager
def editing():
    """one writer of index.json at a time (two episodes' music can end together since phase D)"""
    LIB.mkdir(parents=True, exist_ok=True)
    with open(LIB / ".index.lock", "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def moods(prompt):
    """the words of a cue's prompt that say its mood and colour (not the words every cue has)"""
    return sorted({w for w in re.findall(r"[a-z]+", (prompt or "").lower()) if w not in BOILER and len(w) > 2})


def fit(a, b):
    a, b = set(a), set(b)
    return len(a & b) / len(a | b) if a | b else 0.0


def _copy(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    if subprocess.run(["cp", "-c", str(src), str(tmp)], capture_output=True).returncode != 0:
        shutil.copy2(src, tmp)
    tmp.replace(dst)


AUTO = "automatic: the speech check"


def auto(words_heard):
    """approved when the speech check heard no word at all in the cue, rejected when it heard any"""
    return "rejected" if (words_heard or "").strip() else "approved"


def _usable(j):
    """an ACE-Step cue whose last take was accepted by the vocals check"""
    t = (j.get("takes") or [{}])[-1]
    return j.get("generator", "ace-step") == "ace-step" and str(t.get("result", "")).startswith("accepted") and \
        not (t.get("vocal_check") or {}).get("vocals") and Path(t.get("file", "")).exists()


def _add(idx, wav, j, project, name, log):
    t = j["takes"][-1]
    sha = hashlib.sha256(Path(t["file"]).read_bytes()).hexdigest()[:12]
    if any(r.get("sha") == sha for r in idx.values()):
        return None
    cid = re.sub(r"[^A-Za-z0-9]+", "_", f"{project}_{name}")[-48:].strip("_")
    _copy(Path(t["file"]), LIB / cid / "take.wav")
    _copy(wav, LIB / cid / "cue.wav")
    save_json(LIB / cid / "record.json", dict(j, takes=[dict(t, file=str(LIB / cid / "take.wav"))]))   # the music step's own record
    vc = t.get("vocal_check") or {}
    heard = " ".join(vc.get("words") or [])[:300]
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    idx[cid] = {"prompt": j.get("prompt", ""), "seconds": j.get("seconds"), "moods": moods(j.get("prompt")), "sha": sha,
                "voice_score": vc.get("voice_score"), "words_heard": heard, "from_project": project, "cue": name,
                "added_at": now, "approval": auto(heard), "by": AUTO, "at": now}
    log(f"music library: {cid} added, {idx[cid]['approval']} ({'words heard: ' + heard[:60] if heard else 'no word heard'})")
    return cid


def default_roots():
    from ..core.paths import ENGINE
    import glob
    base = ENGINE.parent
    return sorted({Path(m).parents[2] for m in glob.glob(str(base / "monteer_projects" / "*" / "work" / "assets" / "music"))
                   + glob.glob(str(base / "monteer_tests" / "**" / "work" / "assets" / "music"), recursive=True)})


def import_projects(roots=None, log=print):
    with editing():
        return _import_projects(roots, log)


def _import_projects(roots, log):
    idx = index()
    n = 0
    for root in roots or default_roots():
        d = Path(root) / "work" / "assets" / "music"
        for js in sorted(d.glob("*.json")) if d.exists() else []:
            wav = js.with_suffix(".wav")
            if ".replaced_" in js.name or not wav.exists():
                continue
            j = load_json(js)
            if j.get("from_library") or not _usable(j):
                continue
            if _add(idx, wav, j, Path(root).name, js.stem, lambda *a: None):
                n += 1
    save_json(INDEX, idx)
    log(f"music library: {n} cue(s) copied in, {len(idx)} in all, {sum(1 for r in idx.values() if r['approval'] == 'approved')} approved")
    return n


def add(project_folder, music_dir, name, log=print):
    """a cue this episode has just made joins the library, approved or rejected at once (auto)"""
    js = Path(music_dir) / f"{name}.json"
    if not js.exists():
        return None
    j = load_json(js)
    if j.get("from_library") or not _usable(j):
        return None
    with editing():
        idx = index()
        cid = _add(idx, js.with_suffix(".wav"), j, Path(project_folder).name, name, log)
        if cid:
            save_json(INDEX, idx)
    return cid


def auto_all(log=print):
    """the automatic approval for every cue it decides (a cue set by hand keeps that) -> {"approved": n, "rejected": n}"""
    with editing():
        idx = index()
        for r in idx.values():
            if r.get("by", AUTO) == AUTO or r.get("approval") == "waiting":
                r.update(approval=auto(r.get("words_heard")), by=AUTO, at=r.get("at") or time.strftime("%Y-%m-%d %H:%M:%S"))
        save_json(INDEX, idx)
    n = {a: sum(1 for r in idx.values() if r["approval"] == a) for a in ("approved", "rejected")}
    log(f"music library: {n['approved']} approved, {n['rejected']} rejected (automatic: words heard = rejected)")
    return n


def set_approval(cid, ok, by, note=""):
    with editing():
        idx = index()
        if cid not in idx:
            raise KeyError(f"no cue {cid} in the music library")
        idx[cid].update(approval="approved" if ok else "rejected", by=by, at=time.strftime("%Y-%m-%d %H:%M:%S"), note=note)
        save_json(INDEX, idx)
    return idx[cid]


def approved():
    return {k: r for k, r in index().items() if r.get("approval") == "approved" and (LIB / k / "take.wav").exists()}


def use(cid, out_dir, c, log=print):
    """the library cue as this episode's cue c (its record keeps the episode's prompt and length, so the music step sees it
    as made, and says where it came from)"""
    r = index()[cid]
    out_dir = Path(out_dir)
    _copy(LIB / cid / "cue.wav", out_dir / f"{c['name']}.wav")
    src = load_json(LIB / cid / "record.json")
    save_json(out_dir / f"{c['name']}.json", dict(src, prompt=c["prompt"], seconds=c["seconds"], from_library=cid,
                                                  library_prompt=r["prompt"], approved_by=r.get("by", "")))
    log(f"music: {c['name']} reuses {cid} from the music library (approved by {r.get('by', '?')})")


def heard_in(j):
    """the words the speech check heard in a cue's last take ("" when none)"""
    return " ".join(((j.get("takes") or [{}])[-1].get("vocal_check") or {}).get("words") or []).strip()


def replace_heard(project_folder, log=print):
    """an episode made before the automatic approval (owner's decision 2a of 19 Oct 2026): each of its own cues the speech
    check heard words in is replaced by the best-fitting approved cue of another episode (best fits first, each once;
    nothing is generated). The old cue is kept aside as <name>.rejected_words_<stamp>.wav/.json, never deleted; the
    episode's music step later keeps the replacement as it is (its prompt is the plan's). -> {cue: library id}"""
    folder = Path(project_folder).resolve()
    out = folder / "work" / "assets" / "music"
    lib = {k: r for k, r in approved().items() if r.get("from_project") != folder.name}
    bad = {}
    for js in sorted(out.glob("*.json")):
        if "." in js.stem or not (out / f"{js.stem}.wav").exists():
            continue
        j = load_json(js)
        if not j.get("from_library") and heard_in(j):
            bad[js.stem] = j
    if not bad:
        log("music: no cue of this episode has words heard; nothing replaced")
        return {}
    if not lib:
        raise SystemExit("music: no approved cue of another episode in the library; nothing replaced")
    m = {n: moods(j.get("prompt")) for n, j in bad.items()}
    secs = lambda n, k: abs(float(lib[k].get("seconds") or 0) - float(bad[n].get("seconds") or 0))   # equal fits: the closest length
    pairs = sorted(((fit(m[n], r["moods"]), n, k) for n in bad for k, r in lib.items()), key=lambda x: (-x[0], secs(x[1], x[2]), x[1], x[2]))
    pick, used = {}, set()
    for score, n, k in pairs:
        if n not in pick and (k not in used or len(used) == len(lib)):
            pick[n] = k
            used.add(k)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for n, k in sorted(pick.items()):
        j = bad[n]
        for ext in (".wav", ".json"):
            (out / f"{n}{ext}").replace(out / f"{n}.rejected_words_{stamp}{ext}")
        use(k, out, {"name": n, "prompt": j.get("prompt", ""), "seconds": j.get("seconds")}, log)
        log(f"music: {n} had words heard ({heard_in(j)[:60]}); now {k} (mood fit {fit(m[n], lib[k]['moods']):.2f}); "
            f"the old cue kept as {n}.rejected_words_{stamp}.wav")
    save_json(folder / "work" / "montage" / f"music_replaced_{stamp}.json",
              {n: {"library": k, "words_heard": heard_in(bad[n])[:300], "kept_as": f"{n}.rejected_words_{stamp}.wav"} for n, k in pick.items()})
    return pick


# ---------------------------------------------------------------------------------------------------- downloaded tracks
# Since 19 Oct 2026 (owner's decision after the first fast-mode runs) a channel episode makes no music: ACE-Step is off,
# every section gets one of the instrumental tracks downloaded once into this library (kind "track", free licence, the
# speech check heard no word in it), chosen by mood and looped or cut to the section by the mix.
FAMILY = {}
for fam, words in {
        "dark": "dark ominous sinister brooding gloomy grim menacing drone deep low cold shadow",
        "tense": "tense tension suspense suspenseful unnerving eerie nervous urgent ticking thriller intense danger",
        "mystery": "mysterious mystery curious enigmatic investigative hidden secret secrets intrigue mystical",
        "calm": "calm calming relaxed gentle soft peaceful reflective thoughtful contemplative minimal ambient intellectual",
        "sad": "sad somber melancholic emotional mournful tragic loss despair haunting",
        "bright": "bright hopeful uplifting optimistic inspiring inspired resolve warm positive triumph triumphant",
        "epic": "epic orchestral cinematic grand heroic war historical build building rising climactic swell launch",
        "drive": "driving pulse pulsing rhythm rhythmic action energetic propulsive modern electronic industrial fast",
        "world": "exotic ancient world oriental eastern pacific tribal ethnic period santur gamelan bazaar",
        "piano": "piano pianos", "strings": "strings string cello cellos violin violins violas viola basses",
        "synth": "synth synths synthesizer", "drums": "drums drum percussion timpani taiko", "brass": "brass horn horns trombones tuba trumpets"}.items():
    for w in words.split():
        FAMILY[w] = fam


def families(words):
    return {FAMILY[w] for w in words if w in FAMILY}


def track_fit(cue_moods, track_moods):
    """the share of the cue's mood families the track has (0-1)"""
    want = families(cue_moods)
    return len(want & families(track_moods)) / len(want) if want else 0.0


def tracks():
    """the approved downloaded tracks (the only music a channel episode uses)"""
    return {k: r for k, r in approved().items() if r.get("kind") == "track"}


def add_track(wav, meta, check, log=print):
    """a downloaded instrumental track into the library: the raw 48 kHz take, the finished cue (-20 LUFS) and its record
    (licence and credit line); approved when the engine's vocals check finds no voice (its verdict, not the speech
    recognition's words alone), the words heard kept on record"""
    from .music import finish
    cid = "trk_" + re.sub(r"[^A-Za-z0-9]+", "_", meta["title"]).strip("_")[:40]
    with editing():
        idx = index()
        if cid in idx:
            return cid
        _copy(Path(wav), LIB / cid / "take.wav")
        fin = finish(LIB / cid / "take.wav", LIB / cid / ".cue.part.wav", meta["seconds"])
        (LIB / cid / ".cue.part.wav").replace(LIB / cid / "cue.wav")
        heard = " ".join(check.get("words") or [])[:300]
        rec = {"generator": "library-track", "prompt": "", "seconds": meta["seconds"], "title": meta["title"], "author": meta["author"],
               "source": meta["source"], "page": meta["page"], "licence": meta["licence"], "credit": meta["credit"],
               "finish": fin, "takes": [{"file": str(LIB / cid / "take.wav"), "result": "accepted" if not check.get("vocals") else "rejected",
                                         "vocal_check": {k: check.get(k) for k in ("vocals", "reasons", "voice_score", "words")}}]}
        save_json(LIB / cid / "record.json", rec)
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        # a downloaded track is approved on the vocals check's own verdict (sound classifier + words together): on these
        # instrumentals the speech recognition alone "heard" the same invented phrases it hears on any music ("end of
        # day", "be right back", "visit www.fema.org"); its words stay on record (19 Oct 2026, see NOTES.md)
        ok = not check.get("vocals")
        idx[cid] = {"kind": "track", "prompt": meta["title"], "seconds": meta["seconds"], "moods": sorted(set(meta["moods"])),
                    "voice_score": check.get("voice_score"), "words_heard": heard, "from_project": meta["source"], "cue": meta["title"],
                    "licence": meta["licence"], "added_at": now, "approval": "approved" if ok else "rejected", "by": AUTO, "at": now}
        save_json(INDEX, idx)
    log(f"music library: track {cid} added, {idx[cid]['approval']}" + (f" (words heard: {heard[:60]})" if heard else ""))
    return cid


def pick_tracks(cues, lib=None):
    """{cue name: track id} for one episode: the best mood fits first, each track once while there are unused ones; a
    track at least as long as its section wins a tie (no loop)"""
    lib = tracks() if lib is None else lib
    if not lib:
        return {}
    m = {c["name"]: moods(c["prompt"]) for c in cues}
    score = lambda c, k: track_fit(m[c["name"]], lib[k]["moods"]) + (0.05 if (lib[k].get("seconds") or 0) >= c["seconds"] else 0)  # noqa: E731
    out, used = {}, {}
    pairs = sorted(((score(c, k), c["name"], k) for c in cues for k in lib), key=lambda x: (-x[0], x[1], x[2]))
    for s_, name, k in pairs:
        if name not in out and k not in used:
            out[name], used[k] = k, 1
    for c in cues:                                   # more sections than tracks: the best fit, the least used first
        if c["name"] not in out:
            k = max(lib, key=lambda k: (score(c, k) - 0.5 * used.get(k, 0), k))
            out[c["name"]] = k
            used[k] = used.get(k, 0) + 1
    return out


def add_tracks(manifest, log=print):
    """the tracks a manifest lists (a JSON list of {file, title, author, source, page, licence, credit, moods}) into the
    library: each decoded to 48 kHz, checked by the engine's own vocals check (sound classifier + speech recognition), and
    added approved or rejected (music/library.py add_track) -> {id: approval}"""
    from ..core.paths import ENGINE, FFMPEG, ML_PY, tool_env
    from .music import last_json, measure
    items = load_json(manifest)
    out = {}
    for it in items:
        src = Path(it["file"])
        wav = LIB / ".incoming" / (src.stem + ".wav")
        wav.parent.mkdir(parents=True, exist_ok=True)
        if not wav.exists():
            subprocess.run([str(FFMPEG), "-v", "error", "-y", "-i", str(src), "-ac", "2", "-ar", "48000", "-c:a", "pcm_s16le", str(wav)], check=True)
        chk = it.get("check")                 # the engine's vocals check, already run on this file (its JSON line)
        if chk is None:
            r = subprocess.run([str(ML_PY), "-m", "monteer.music.vocal_check", str(wav)], capture_output=True, text=True,
                               cwd=str(ENGINE), env=tool_env())
            chk = last_json(r.stdout) if r.returncode == 0 else None
        if chk is None:
            log(f"music library: {it['title']}: the vocals check could not run, not added")
            continue
        meta = dict(it, seconds=round(measure(wav)[2], 2))
        cid = add_track(wav, meta, chk, log)
        out[cid] = index()[cid]["approval"]
    return out


def main(argv):
    sub = argv[0] if argv else "status"
    if sub == "add-tracks" and len(argv) > 1:
        add_tracks(argv[1])
        return 0
    if sub == "tracks":
        for k, r in sorted(index().items()):
            if r.get("kind") == "track":
                print(f"  {r['approval']:8} {k}  {r.get('seconds')} s  {r.get('licence')}  moods: {', '.join(r.get('moods', []))[:80]}")
        return 0
    if sub == "replace-heard" and len(argv) > 1:
        replace_heard(argv[1])
        return 0
    if sub == "import":
        import_projects([Path(a) for a in argv[1:]] or None)
        return 0
    if sub == "auto":
        auto_all()
        return 0
    idx = index()
    if sub in ("status", "list"):
        n = {a: sum(1 for r in idx.values() if r["approval"] == a) for a in ("approved", "rejected")}
        print(f"music library {LIB}: {len(idx)} cues ({n['approved']} approved, {n['rejected']} rejected; approval is automatic: "
              "a word heard = rejected)")
        if sub == "list":
            for k, r in sorted(idx.items()):
                print(f"  {r['approval']:8} {k}  {r.get('seconds')} s  voice {r.get('voice_score')}  "
                      f"{('words heard: ' + r['words_heard'][:60]) if r.get('words_heard') else ''}")
        return 0
    if sub in ("approve", "reject") and len(argv) > 1:
        r = set_approval(argv[1], sub == "approve", by="owner (bin/monteer music)", note=" ".join(argv[2:]))
        print(f"{argv[1]}: {r['approval']}")
        return 0
    print("bin/monteer music tracks | add-tracks <manifest.json> | import | auto | status | list | approve <id> [note] | reject <id> [note] | replace-heard <project>",
          file=sys.stderr)
    return 2


__all__ = ["LIB", "auto", "auto_all", "import_projects", "add", "set_approval", "approved", "use", "moods", "tracks", "add_track", "add_tracks", "pick_tracks", "heard_in", "replace_heard", "main"]

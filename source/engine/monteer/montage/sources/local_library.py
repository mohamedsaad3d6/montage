"""The local picture library on this Mac (owner's decision of 19 Oct 2026): every valid file an episode already downloaded
from Wikimedia Commons, with its licence and credit record, is COPIED (never moved) into <monteer_data>/library, and every
episode searches it first, with no network call. Wikimedia Commons itself is no longer searched or downloaded from.

  <DATA>/library/photos/<key>.jpg, videos/<key>.mp4, index.json {code: record}
      record: kind (photo | video), file (relative to the library), source, page, title, author, licence, description,
              from_project, added_at; code = P:<key> for a photo, S:<key> for a video, the same key the project used, so
              a picture keeps its code from episode to episode (the repeat rule and the credits see the same file)

  import_projects(roots)   copies what is not there yet: a record from a project's assets.json whose source is Wikimedia
                           Commons, whose file is a real JPEG or a video that plays, and whose licence passes the gate
  search(query)            the records whose title and description hold every main word of the query (search.on_topic)
  use(p, code, ledger)     the file copied into the project (photos/ or library/) with its credits record

  bin/monteer library import [project folders…]   (no folder: every project and test project on this Mac)
  bin/monteer library status
"""
import glob
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ...core.io import load_json, save_json
from ...core.paths import DATA
from . import licence_ok, picture_kind, video_ok

LIB = DATA / "library"
INDEX = LIB / "index.json"
FROM = ("Wikimedia Commons",)          # the sources whose files are kept here (the disconnected one)


def index():
    return load_json(INDEX) if INDEX.exists() else {}


def _copy(src, dst):
    """a copy that shares the disk blocks on APFS (cp -c) where it can; never a move"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    if subprocess.run(["cp", "-c", str(src), str(tmp)], capture_output=True).returncode != 0:
        shutil.copy2(src, tmp)
    tmp.replace(dst)


def default_roots():
    from ...core.paths import ENGINE
    base = ENGINE.parent
    return sorted({Path(w).parent for w in glob.glob(str(base / "monteer_projects" / "*" / "work"))
                   + glob.glob(str(base / "monteer_tests" / "**" / "work"), recursive=True)})


def import_projects(roots=None, log=print):
    """copies the valid Commons files of these project folders (default: all) -> {"added", "skipped": {why: n}}"""
    idx = index()
    added, skipped = 0, {}
    for root in roots or default_roots():
        root = Path(root)
        led = root / "work" / "montage" / "assets.json"
        if not led.exists():
            continue
        for code, r in load_json(led).items():
            if r.get("source") not in FROM or ":" not in code:
                continue
            kd, key = code.split(":", 1)
            if kd not in ("P", "S"):
                continue
            why = None
            src = root / "work" / "assets" / ("photos" if kd == "P" else "library") / (key + (".jpg" if kd == "P" else ".mp4"))
            if code in idx:
                why = "already in the library"
            elif not src.exists():
                why = "no file"
            elif not (picture_kind(src) == "JPEG" if kd == "P" else video_ok(src)):
                why = "not a real picture or video"
            elif not licence_ok(r.get("licence")) or not (r.get("page") or r.get("title")):
                why = "no licence or credit record"
            if why:
                skipped[why] = skipped.get(why, 0) + 1
                continue
            rel = Path("photos" if kd == "P" else "videos") / src.name
            _copy(src, LIB / rel)
            idx[code] = {"kind": "photo" if kd == "P" else "video", "file": str(rel), "source": r["source"], "page": r.get("page", ""),
                         "title": r.get("title", ""), "author": r.get("author", ""), "licence": r["licence"],
                         "description": r.get("description", ""), "from_project": root.name, "added_at": time.strftime("%Y-%m-%d %H:%M:%S")}
            added += 1
    if added:
        save_json(INDEX, idx)
    log(f"library: {added} file(s) copied in, {len(idx)} in all; skipped {skipped}")
    return {"added": added, "skipped": skipped, "total": len(idx)}


def search(query):
    """every record (no network); the caller keeps those on topic (search.on_topic, on title + description)"""
    return [dict(r, code=code) for code, r in index().items() if (LIB / r["file"]).exists()]


def use(p, code, ledger, log=print, as_key=None):
    """the library file copied into the project with its credits record -> True when it is there (as_key: under the key
    a classic sources decision gave it)"""
    r = index().get(code)
    if not r or not (LIB / r["file"]).exists():
        log(f"library {code}: not in the library")
        return False
    kd, key = code.split(":", 1)
    key = as_key or key
    code = f"{kd}:{key}"
    out = p.asset_dir("photos" if kd == "P" else "library") / (key + (".jpg" if kd == "P" else ".mp4"))
    if not out.exists():
        _copy(LIB / r["file"], out)
    ledger.add(code, kind="archive photo" if kd == "P" else "archive video", source=r["source"], page=r.get("page", ""),
               title=r.get("title", ""), author=r.get("author", ""), licence=r["licence"], file=str(out), via="the local library")
    return True


def main(argv):
    sub = argv[0] if argv else "status"
    if sub == "import":
        import_projects([Path(a) for a in argv[1:]] or None)
        return 0
    if sub == "status":
        idx = index()
        size = sum((LIB / r["file"]).stat().st_size for r in idx.values() if (LIB / r["file"]).exists())
        n = {k: sum(1 for r in idx.values() if r["kind"] == k) for k in ("photo", "video")}
        print(f"library {LIB}: {n['photo']} photos, {n['video']} videos, {size / 1e9:.2f} GB")
        return 0
    print("bin/monteer library import [project folders…] | status", file=sys.stderr)
    return 2


__all__ = ["LIB", "index", "import_projects", "search", "use", "main"]

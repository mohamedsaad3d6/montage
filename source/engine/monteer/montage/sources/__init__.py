"""Sourcing: download what the sources decision lists, through ONE licence gate, and keep a provenance record per file.

The footage sources (owner's decision of 19 Oct 2026, after the first fast-mode runs): Pixabay (videos and photos, the
official API with the key from the keys file) and the local library on this Mac (sources/local_library.py). Nothing else
is searched or downloaded (except Magnific's stock videos for the channels that turn it on, sources/magnific.py,
20 Oct 2026): Wikimedia Commons, Pexels, the Internet Archive, The Met, Wellcome, Cleveland, NASA,
Smithsonian and DVIDS were removed (their earlier code is in engine/retired/, NOTES.md says why). A picture an earlier
decision chose from a removed source is used only when its file is already in the project or the local library.

Licence gate (the same for every file): public domain, Public Domain Mark, CC0, CC BY (any version), US federal works,
and the stock sites' own free licences (Pexels License, Pixabay Content License: files of earlier projects). Refused:
ShareAlike, NonCommercial, NoDerivatives, "editorial use only", "no known restrictions", unknown.

Provenance: work/montage/assets.json, one record per file: kind, key, source, page, author, licence, file, fetched_at.
Credits and the self-check are built from these records. Network requests send a neutral User-Agent and never the
user's email or name.

Every download is checked (owner's answers 1a and 2a of 19 Oct 2026): a file is kept only when it is what it should be
(a JPEG picture, a video that plays), a refusal is tried again after a wait, and anything else is set aside under
work/assets/set_aside/ (never deleted) with why; only real files get a credits record.
"""
import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
from pathlib import Path

from ...core import apikeys
from ...core.io import atomic, load_json, save_json, tmp_name
from ...core.paths import FFPROBE

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0 Safari/537.36"


UA_API = "MonteerMontage/1.0 (a local video-montage tool) curl"      # nothing personal, ever
ALLOWED = re.compile(r"^(public domain|pd\b|pd-|cc0|cc by[ -]?\d|cc-by-\d|cc by$|us federal|pexels license|pixabay (content )?license|"
                     r"own footage$|magnific (premium|free) licence|storyblocks business licence)", re.I)   # own footage: the owner's clips (decision 8b); Magnific:
#                                       the paid source of two channels (sources/magnific.py, 20 Oct 2026); Storyblocks:
#                                       the company's subscription through its official MCP (sources/storyblocks.py)
REFUSED = re.compile(r"(-sa\b| sa\b|sharealike|-nc\b| nc\b|noncommercial|-nd\b| nd\b|noderiv|editorial)", re.I)


MODES = ("both", "free", "paid")


def mode(p):
    """the episode's «المصادر» (owner's (c) of 20 Oct 2026; options.sources, chosen on «حلقة جديدة»): "both" (default),
    "free" (Pixabay and the local library only: no Storyblocks or Magnific call), "paid" (Storyblocks and Magnific only:
    no free footage); always "both" for a channel with no paid source (nothing to choose)"""
    try:
        m = p.opt("sources", "both") if hasattr(p, "opt") else "both"
    except Exception:  # noqa: BLE001
        m = "both"
    return m if m in MODES else "both"


def licence_ok(lic):
    lic = (lic or "").strip()
    return bool(lic) and bool(ALLOWED.search(lic)) and not REFUSED.search(lic)


def curl(url, out=None, ua=UA, headers=None, max_bytes=None, max_time=None):
    """(http code, body or None); never sends a personal header. max_bytes: curl stops a bigger file (code 063); max_time:
    curl gives up after that many seconds (the free archive's time limit)"""
    cmd = ["curl", "-s", "-L", "-A", ua, "-w", "%{http_code}"] + sum([["-H", h] for h in (headers or [])], [])
    if max_bytes:
        cmd += ["--max-filesize", str(int(max_bytes))]
    if max_time:
        cmd += ["--max-time", str(max(1, int(max_time)))]
    cmd += ["-o", str(out) if out else "-"]
    r = subprocess.run(cmd + [url], capture_output=True, timeout=1800)
    if max_bytes and r.returncode == 63:          # curl's "maximum file size exceeded"
        return "063", None
    if out:
        return r.stdout.decode().strip(), None
    return r.stdout[-3:].decode(), r.stdout[:-3]


class Ledger:
    def __init__(self, p):
        self.path = p.work / "montage" / "assets.json"
        self.rec = load_json(self.path) if self.path.exists() else {}

    def add(self, key, **kw):
        self.rec[key] = dict(kw, fetched_at=time.strftime("%Y-%m-%d %H:%M:%S"))
        save_json(self.path, self.rec)

    def drop(self, key):
        """a file that was set aside loses its credits record (the record is kept with the file, see set_aside)"""
        rec = self.rec.pop(key, None)
        if rec is not None:
            save_json(self.path, self.rec)
        return rec


# ---------------------------------------------------------------------------------------------------- checked downloads
WAITS = (0, 10, 30, 90)               # seconds before each try: a refusal (HTTP 429) gets time to clear
GAP_S = {"pixabay.com": 0.65}          # at least this long between two requests to one host (Pixabay's API: 100 a minute)
RETRY = {"000", "408", "429", "500", "502", "503", "504"}
_last = {}
_ok = {}
_lock = threading.Lock()               # the searches run for several shots at once (step_sources)


def _turn(url):
    host = urllib.parse.urlparse(url).netloc
    gap = GAP_S.get(host, 0)
    if not gap:
        return
    while True:
        with _lock:
            wait = _last.get(host, 0) + gap - time.time()
            if wait <= 0:
                _last[host] = time.time()
                return
        time.sleep(wait)


def picture_kind(path):
    """the picture format of a file ("JPEG", "PNG", "GIF", …), or None when it is not a picture (e.g. an error page)"""
    try:
        from PIL import Image
        with Image.open(path) as im:
            im.verify()
            return im.format
    except Exception:  # noqa: BLE001  (anything PIL cannot read is not a picture)
        return None


def as_jpeg(path):
    """True when the file is a JPEG picture; a picture in another format (a GIF, a PNG, a WebP) is saved as JPEG in its
    place first (the renderer reads stills as JPEG; the test's GIF could not be opened)"""
    k = picture_kind(path)
    if k == "JPEG":
        return True
    if not k:
        return False
    from PIL import Image
    with Image.open(path) as im:
        rgb = im.convert("RGB")
    rgb.save(path, "JPEG", quality=92)
    return picture_kind(path) == "JPEG"


def video_ok(path):
    """a file with a video stream that lasts (read by ffprobe)"""
    path = Path(path)
    try:
        st = path.stat()
    except OSError:
        return False
    sig = (str(path), st.st_mtime_ns, st.st_size)
    if sig not in _ok:
        try:
            r = subprocess.run([str(FFPROBE), "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=codec_name:format=duration",
                                "-of", "json", str(path)], capture_output=True, text=True, timeout=60)
            d = json.loads(r.stdout or "{}")
            codec = ((d.get("streams") or [{}])[0]).get("codec_name", "")
            _ok[sig] = bool(d.get("streams")) and codec not in ("mjpeg", "png", "gif", "webp") and \
                float((d.get("format") or {}).get("duration") or 0) > 0.5
        except (OSError, ValueError, subprocess.TimeoutExpired):
            _ok[sig] = False
    return _ok[sig]


def set_aside(p, path, why, ledger=None, key=None):
    """a file that is not what it should be: moved under work/assets/set_aside/ (never deleted), listed with why in
    set_aside.json together with its credits record, which leaves the credits"""
    path = Path(path)
    if not path.exists():
        return None
    base = p.work / "assets" / "set_aside"
    try:
        rel = path.relative_to(p.work)
    except ValueError:
        rel = Path(path.name)
    dst, k = base / rel, 2
    while dst.exists():
        dst, k = base / rel.with_name(f"{rel.stem}_{k}{rel.suffix}"), k + 1
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(path, dst)
    rec = ledger.drop(key) if ledger is not None and key else None
    man = base / "set_aside.json"
    items = load_json(man) if man.exists() else []
    items.append(dict({"file": str(dst), "was": str(path), "why": why, "at": time.strftime("%Y-%m-%d %H:%M:%S")},
                      **({"credits_record": rec} if rec else {})))
    save_json(man, items)
    return dst


def download(p, url, out, check, ua=None, max_bytes=None, max_time=None):
    """url -> out, tried after each of WAITS while the answer is a refusal; out is written only when check(file) holds ->
    (True, "") or (False, why). The last failed answer is set aside, never kept as out. max_bytes: a bigger file is
    stopped and refused (Magnific's size guard)."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = tmp_name(out)
    why = ""
    for w in WAITS:
        if w:
            time.sleep(w)
        _turn(url)
        code, _ = curl(url, out=tmp, ua=ua or UA_API, **({"max_bytes": max_bytes} if max_bytes else {}),
                       **({"max_time": max_time} if max_time else {}))
        if max_bytes and (code == "063" or (tmp.exists() and tmp.stat().st_size > max_bytes)):
            why = f"bigger than {max_bytes / 1e6:.0f} MB (stopped)"
            break
        if code == "200" and tmp.exists() and check(tmp):
            os.replace(tmp, out)
            return True, ""
        why = f"HTTP {code}" if code != "200" else "the file is not what it should be (not a picture or not a video)"
        if code != "200" and code not in RETRY:
            break
    set_aside(p, tmp, f"a failed download ({why}) of {url}")
    return False, why


def asset_file(p, code):
    kd, key = code.split(":", 1)
    return {"V": p.asset_dir("stock") / f"{key}.mp4", "P": p.asset_dir("photos") / f"{key}.jpg",
            "S": p.asset_dir("library") / f"{key}.mp4"}.get(kd)


def asset_ok(p, code):
    """a chosen picture's file is really there: a JPEG picture (P:) or a video that plays (V:, S:); drawn images (A:) are
    made by the engine itself"""
    f = asset_file(p, code)
    if f is None:
        return True
    return picture_kind(f) == "JPEG" if code.startswith("P:") else video_ok(f)


def sweep(p, ledger=None, log=print):
    """the project's downloaded files checked once: a picture that is not a JPEG is kept as JPEG (the original set aside),
    anything that is not a picture or a video is set aside (owner's answer 1a: the broken files get a folder of their own)"""
    ledger = ledger or Ledger(p)
    moved = 0
    for d, code in (("photos", "P"), ("stock", "V"), ("library", "S")):
        for f in sorted(p.asset_dir(d).glob("*.*")) if p.asset_dir(d).exists() else []:
            if f.name.startswith(".") or f.suffix not in (".jpg", ".mp4"):
                continue
            if code == "P":
                k = picture_kind(f)
                if k == "JPEG":
                    continue
                if k:                                  # a real picture in another format: a JPEG copy takes its place
                    keep = set_aside(p, f, f"a {k} picture saved as .jpg: kept here, a JPEG copy is used")
                    from PIL import Image
                    with Image.open(keep) as im:
                        im.convert("RGB").save(f, "JPEG", quality=92)
                    log(f"photo {f.stem}: a {k} picture, now a JPEG (the original is in set_aside)")
                    continue
                why = "not a picture (an error page saved by an earlier run)"
            else:
                if video_ok(f):
                    continue
                why = "not a playable video (saved by an earlier run)"
            set_aside(p, f, why, ledger, f"{code}:{f.stem}")
            moved += 1
    if moved:
        log(f"downloads checked: {moved} broken file(s) set aside in work/assets/set_aside (listed in set_aside.json)")
    return moved


def earlier_clip(p, item, ledger, log):
    """a clip an earlier decision chose from a source that is no longer used (Pexels): its file in the project, or nothing"""
    out = p.asset_dir("stock") / f"{item['id']}.mp4"
    if out.exists() and video_ok(out):
        return
    log(f"{item.get('source', '?')} {item['id']}: left out, that source is no longer used and the file is not on this Mac")


def pixabay(p, item, ledger, log):
    key = apikeys.get("pixabay_api_key")
    if not key:
        log(f"pixabay {item['id']}: SKIPPED — no pixabay_api_key in the keys file (Pixabay has no keyless download)")
        return
    out = p.asset_dir("stock") / f"{item['id']}.mp4"
    if out.exists() and out.stat().st_size > 100000 and video_ok(out):
        return
    if out.exists():
        set_aside(p, out, "not a playable video (saved by an earlier run)", ledger, f"V:{item['id']}")
    code, body = curl(f"https://pixabay.com/api/videos/?key={urllib.parse.quote(key)}&id={item['id']}", ua=UA_API)
    hits = json.loads(body).get("hits", []) if code == "200" else []
    if not hits:
        raise SystemExit(f"pixabay {item['id']}: not found (HTTP {code})")
    v = hits[0]["videos"]
    url = (v.get("large") or v.get("medium"))["url"]
    ok, why = download(p, url, out, video_ok, ua=UA)
    if not ok:
        log(f"pixabay {item['id']}: left out, the download failed ({why})")
        return
    ledger.add(f"V:{item['id']}", kind="stock video", source="Pixabay", page=hits[0].get("pageURL", ""), title=item.get("title", ""),
               licence="Pixabay Content License", file=str(out), how="Pixabay API (key present)")
    log(f"pixabay {item['id']}: Pixabay API")


def earlier_photo(p, item, ledger, log):
    """a photo an earlier decision chose from a removed source (Wikimedia Commons): the project's own file, else the local
    library's copy; nothing is asked of the network"""
    out = p.asset_dir("photos") / f"{item['key']}.jpg"
    if out.exists() and out.stat().st_size > 50000 and picture_kind(out) == "JPEG":
        return
    if out.exists() and picture_kind(out) != "JPEG":
        set_aside(p, out, f"not a JPEG picture ({picture_kind(out) or 'an error page'}), saved by an earlier run", ledger, f"P:{item['key']}")
    from . import local_library
    if not local_library.use(p, f"P:{item['key']}", ledger, log=lambda *a: None):
        log(f"photo {item['key']}: left out, its source is no longer used and the local library does not have it")


def library(p, item, ledger, log):
    """a clip already on this Mac (e.g. from an earlier project), copied into this project's library"""
    if not licence_ok(item.get("licence")):
        log(f"library {item['key']}: REFUSED by the licence gate ({item.get('licence')!r})")
        return
    out = p.asset_dir("library") / f"{item['key']}.mp4"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        if subprocess.run(["cp", "-c", item["file"], str(out)], capture_output=True).returncode != 0:
            shutil.copy2(item["file"], out)
    ledger.add(f"S:{item['key']}", kind="stock video", source=item.get("source", ""), page=item.get("page", ""), title=item.get("title", ""),
               licence=item["licence"], file=str(out))


def fetch_all(p, assets, log=print):
    for d in ("stock", "photos", "library"):
        p.asset_dir(d).mkdir(parents=True, exist_ok=True)
    ledger = Ledger(p)
    log("keys:", apikeys.status())
    sb = [it for it in assets.get("stock", []) if it.get("source") == "storyblocks"]
    sb_failed = []
    if sb:                             # the company's Storyblocks clips: their links asked in background runs, 10 at a time
        from . import storyblocks
        sb_failed = storyblocks.fetch_many(p, sb, ledger, log) or []
    budget = None
    if any(it.get("source") in ("archive", "commons_video") for it in assets.get("stock", [])) or \
            any(it.get("src") == "commons" for it in assets.get("photos", [])):
        from . import free_archive as FA
        budget = FA.Budget(p)          # the episode's archive time limit, searches and downloads together
    for it in assets.get("stock", []):
        if it.get("source") == "storyblocks":
            continue
        if it.get("source") in ("archive", "commons_video"):
            FA.fetch_film(p, it, ledger, budget, log)
            continue
        if it.get("source") == "magnific":
            from . import magnific
            magnific.fetch(p, it, ledger, log)
            continue
        (pixabay if it.get("source") == "pixabay" else earlier_clip)(p, it, ledger, log)
    for it in assets.get("library", []):
        library(p, it, ledger, log)
    for it in assets.get("photos", []):
        if it.get("src") == "commons":
            FA.fetch_photo(p, it, ledger, budget, log)
        elif it.get("src") and it.get("src") != "library":
            from . import photos
            photos.fetch(p, it, ledger, log)
        elif it.get("src") == "library":
            from . import local_library
            local_library.use(p, it["code"], ledger, log, as_key=it.get("key"))
        else:                          # a Commons photo of an earlier decision: on this Mac only
            earlier_photo(p, it, ledger, log)
    if sb_failed:                      # never «done» without the picked clips (owner, 21 Oct 2026); the next run asks only these
        raise SystemExit(f"Storyblocks: {len(sb_failed)} of the episode's picked clips could not be fetched: "
                         + "; ".join(sb_failed[:8]) + ("; …" if len(sb_failed) > 8 else "")
                         + ". Everything else is downloaded and kept; run again to ask for these once more.")

"""Free archive, for ARCHIVE SHOTS ONLY (owner's fix 3 of 21 Oct 2026: it re-connects, for this one use, what was disconnected
on 19 Oct 2026; the first camera episode had no archive picture at all, its 1969 and 2016 stretches shown with today's
aerials). In a channel episode, the plan's archive searches (its search_photos) look here, with the year kept:

  Internet Archive films   Universal Newsreels and Prelinger items marked public domain or CC0, and US federal films (a
                           federal agency's own item: identifier gov.* or NARA's ARC_*). Never Defense Department or C-SPAN
                           items (legal doubt), and FedFlix membership alone is not enough (it also holds UN and CBS films).
  Wikimedia Commons        videos (at least 1280 px wide) and photos (at least 1200 x 700), each file's licence read from
                           its own page data.

Every item passes the one licence gate (sources.licence_ok: public domain, CC0, CC BY, US federal works; never ShareAlike,
NonCommercial or NoDerivatives). A HARD TIME LIMIT per episode: BUDGET_S seconds for all its archive searches and downloads
together (kept in the project, so a resumed run goes on with what is left), at most MAX_FILES files; past it the archive
is skipped and the log says so. A film or a Commons video becomes the project's library clip S:<key> (archive material); a
Commons photo the photo P:<key>. Searches are cached 7 days.

Owner's fix 1 of 22 Oct 2026 («المملكة المتحدة تنهار» v1: 45 searches, 0 files): the plan's long archive searches («British
troops Derry August 1969») match nothing (every word must be found), so each is tried as SHORT EVENT / PLACE + YEAR searches
(short_queries: «Derry 1969», «British troops 1969» …, the first that finds something wins); Commons is asked more slowly
(one request every 2 s, one short wait on its «too many requests», never the 50 s of waits that used up the search time);
each new version of an episode has its own time limit.

  on(p)                         a channel episode whose «المصادر» is not «paid only»
  search(p, query, n)           -> candidates: films first, then Commons videos ({"source": "archive" | "commons_video"}),
                                   and Commons photos ({"src": "commons"})
  fetch_film(p, item, ledger)   -> S:<key> or None          fetch_photo(p, item, ledger) -> P:<key> or None
"""
import hashlib
import json
import re
import subprocess
import threading
import time
import urllib.parse

from ...core.io import atomic, load_json, save_json
from ...core.paths import CACHE, FFMPEG
from . import GAP_S, UA_API, _turn, as_jpeg, curl, download, licence_ok, set_aside, video_ok

BUDGET_S = 12 * 60            # s per episode, searches and downloads together
SEARCH_S = 5 * 60             # of which the searches may take this much
MAX_FILES = 24
FILM_MAX_MB = 250
COMMONS_VIDEO_MAX_MB = 200
CACHE_DIR = CACHE / "free_archive"
WEEK = 7 * 86400
COMMONS = "https://commons.wikimedia.org/w/api.php"
GAP_S["commons.wikimedia.org"] = max(GAP_S.get("commons.wikimedia.org", 0), 2.0)
GAP_S.setdefault("archive.org", 0.3)
IA_COLLECTIONS = ("universal_newsreels", "FedFlix", "prelinger")
PD = re.compile(r"publicdomain/(mark|zero)|creativecommons\.org/publicdomain", re.I)
DOUBT_IA = re.compile(r"^(org\.c-span|gov\.dod|dvids)", re.I)
DOUBT = re.compile(r"\b(centcom|dvids|department of defense|dod|u\.?s\.? (army|navy|air force|marines?)|airstrike|air strike|"
                   r"bodycam|body cam|shootout)\b", re.I)
_lock = threading.Lock()


def on(p):
    from . import mode
    return bool(getattr(p, "profile", None)) and mode(p) != "paid"


# ---------------------------------------------------------------------------------------------------- the hard time limit
class Budget:
    """the episode's archive time (work/montage/free_archive.json), shared by the threads that search at once"""

    def __init__(self, p, fresh=False):
        self.f = p.work / "montage" / "free_archive.json"
        self.version = int(p.opt("version", 1))
        d = load_json(self.f) if self.f.exists() else {}
        if fresh or int(d.get("version", 1)) != self.version:   # each sources run has its own time limit (owner, 22 Oct 2026:
            d = {}                                              # v2's second run found its archive time used up by the first)
        self.used, self.search_used, self.files = d.get("used_s", 0.0), d.get("search_s", 0.0), d.get("files", 0)
        self.said = False

    def left(self, search=False):
        return max(0.0, min(BUDGET_S - self.used, SEARCH_S - self.search_used if search else BUDGET_S))

    def spend(self, seconds, search=False, file=False):
        with _lock:
            self.used += seconds
            if search:
                self.search_used += seconds
            if file:
                self.files += 1
            save_json(self.f, {"used_s": round(self.used, 1), "search_s": round(self.search_used, 1), "files": self.files,
                               "budget_s": BUDGET_S, "search_budget_s": SEARCH_S, "max_files": MAX_FILES, "version": self.version})

    def stop(self, log, what):
        if not self.said:
            self.said = True
            log(f"free archive: the episode's time limit is reached ({BUDGET_S // 60} min, {MAX_FILES} files): {what} skipped")


def _cached(kind, query, get):
    f = CACHE_DIR / f"{kind}_{hashlib.sha256(query.lower().encode()).hexdigest()[:20]}.json"
    if f.exists() and time.time() - load_json(f)["at"] < WEEK:
        return load_json(f)["hits"]
    hits = get()
    if hits is not None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        save_json(f, {"at": time.time(), "query": query, "hits": hits})
    return hits or []


# ---------------------------------------------------------------------------------------------------- Internet Archive films
def _ia_licence(doc):
    lic = doc.get("licenseurl") or ""
    lic = (lic[0] if lic else "") if isinstance(lic, list) else lic
    if PD.search(lic):
        return "Public Domain Mark" if "mark" in lic.lower() else "CC0"
    return None


def ia_search(query):
    def get():
        q = f"({query}) AND mediatype:movies AND (" + " OR ".join(f"collection:{c}" for c in IA_COLLECTIONS) + ")"
        url = "https://archive.org/advancedsearch.php?" + urllib.parse.urlencode(
            [("q", q), ("rows", "25"), ("output", "json")] + [("fl[]", x) for x in ("identifier", "title", "year", "licenseurl", "collection")])
        _turn(url)
        code, body = curl(url, ua=UA_API)
        if code != "200":
            return None
        hits = []
        for d in json.loads(body).get("response", {}).get("docs", []):
            ident = d["identifier"]
            cols = [d.get("collection")] if isinstance(d.get("collection"), str) else (d.get("collection") or [])
            us_gov = re.match(r"^(gov\.|ARC_)", ident) is not None          # a US federal agency's own item (NARA, DOT …)
            lic = "US federal work (public domain)" if us_gov else _ia_licence(d)
            trusted = us_gov or (lic and any(c in ("universal_newsreels", "prelinger") for c in cols))
            if not trusted or DOUBT_IA.search(ident):
                continue
            hits.append({"id": "ia_" + ident, "ident": ident, "title": str(d.get("title", ""))[:160], "year": d.get("year"),
                         "licence": lic, "page": f"https://archive.org/details/{ident}", "thumb": f"https://archive.org/services/img/{ident}",
                         "collection": [c for c in cols if c in IA_COLLECTIONS], "source": "archive"})
        return hits
    return [h for h in _cached("ia", query, get) if licence_ok(h["licence"])]


def _key(item):
    return re.sub(r"[^A-Za-z0-9]+", "_", item["id"])[:60] if item.get("source") == "archive" else \
        "wv_" + hashlib.sha256(item["title"].encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------------------------------- Wikimedia Commons
def commons_get(params):
    q = urllib.parse.urlencode(dict(params, format="json"))
    url = f"{COMMONS}?{q}"
    for wait in (0, 6):                # one short wait on «too many requests» (it was 10 s then 40 s: the search time went)
        time.sleep(wait)
        _turn(url)
        code, body = curl(url, ua=UA_API)
        if code == "200" and body.startswith(b"{"):
            return json.loads(body)
    return {}


def _commons(query, filetype):
    def get():
        d = commons_get({"action": "query", "generator": "search", "gsrnamespace": "6", "gsrsearch": f"{query} filetype:{filetype}",
                         "gsrlimit": "25", "prop": "imageinfo", "iiprop": "url|extmetadata|size|mime", "iiurlwidth": "320"})
        if not d:
            return None
        hits = []
        for pg in (d.get("query", {}).get("pages", {}) or {}).values():
            ii = (pg.get("imageinfo") or [{}])[0]
            meta = ii.get("extmetadata", {})
            hits.append({"title": pg.get("title", ""), "page": ii.get("descriptionurl", ""), "url": ii.get("url", ""),
                         "licence": meta.get("LicenseShortName", {}).get("value", ""),
                         "author": re.sub("<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip()[:120],
                         "width": ii.get("width"), "height": ii.get("height"), "duration": ii.get("duration"), "size": ii.get("size"),
                         "thumb": ii.get("thumburl", ""),
                         "description": re.sub("<[^>]+>", "", meta.get("ImageDescription", {}).get("value", ""))[:200]})
        return hits
    return _cached("commons_" + filetype, query, get)


def commons_videos(query):
    return [dict(h, id="cv_" + hashlib.sha256(h["title"].encode()).hexdigest()[:12], source="commons_video")
            for h in _commons(query, "video")
            if licence_ok(h["licence"]) and (h.get("width") or 0) >= 1280 and (h.get("size") or 0) <= COMMONS_VIDEO_MAX_MB * 2 ** 20
            and (h.get("duration") or 5) >= 3 and h.get("url") and not DOUBT.search(h["title"] + " " + h.get("description", ""))]


def commons_photos(query):
    return [dict(h, src="commons", source="Wikimedia Commons") for h in _commons(query, "bitmap")
            if licence_ok(h["licence"]) and (h.get("width") or 0) >= 1200 and (h.get("height") or 0) >= 700
            and not DOUBT.search(h["title"] + " " + h.get("description", ""))]


# ---------------------------------------------------------------------------------------------------- search and fetch
def search(p, query, budget, n=6, log=print):
    """an archive search, the year kept -> (clips, photos); nothing once the episode's search time is spent"""
    if budget.left(search=True) <= 0:
        budget.stop(log, f"the search «{query}»")
        return [], []
    clips, photos = [], []
    t = time.time()                    # Internet Archive: the names of the search, any of them, the year checked on the results
    films = ia_films(query)[:n]
    budget.spend(time.time() - t, search=True)
    for q in short_queries(query):
        if budget.left(search=True) <= 0:
            budget.stop(log, f"the search «{q}»")
            break
        t = time.time()
        clips = films + commons_videos(q)[:n // 2]
        photos = commons_photos(q)[:n]
        budget.spend(time.time() - t, search=True)
        if clips or photos:
            if q != query:
                log(f"free archive «{query}»: found as «{q}»")
            break
    return clips, photos


def ia_films(query, near=6):
    """Internet Archive films for an archive search (owner, 22 Oct 2026: the whole search, every word required and the year
    as a word, found nothing; NARA's «Ulster» (1970) says «Northern Ireland» only in its description): its names (and its
    first two words), ANY of them, in the trusted collections; a film whose year is known is kept only within near years of
    the search's year -> [hits], the closest years first"""
    toks = re.findall(r"[A-Za-z][A-Za-z'\-]*|\d{4}", query)
    year = next((int(t) for t in toks if re.fullmatch(r"1[89]\d\d|20\d\d", t)), None)
    words = [t for t in toks if not re.fullmatch(r"\d{4}", t) and t.lower() not in MONTHS and t.lower() not in GENERIC]
    names = [t for t in words if t[0].isupper()]
    terms = []
    for i, t in enumerate(names):          # neighbouring names belong together («Northern Ireland», «Good Friday»)
        if terms and words.index(t) == words.index(names[i - 1]) + 1:
            terms[-1] += " " + t
        else:
            terms.append(t)
    terms += [t for t in names if t not in terms]           # and each name on its own («Troubles», «Belfast»)
    if not terms:
        terms = [" ".join(words[:2])] if words else []
    if not terms:
        return []
    q = " OR ".join(f'"{x}"' if " " in x else x for x in terms[:6])
    hits = ia_search(q)
    if year:
        def y(h):
            try:
                return int(str(h.get("year"))[:4])
            except (TypeError, ValueError):
                return None
        hits = [h for h in hits if y(h) is None or abs(y(h) - year) <= near]
        hits.sort(key=lambda h: abs((y(h) or year + near) - year))
    return hits


def topic_films(plan_text, years, most=6, near=6):
    """the episode's own archive search (owner, 22 Oct 2026: its single searches never said «Northern Ireland», the only words
    NARA's «Ulster» 1970 has): the place names its plan uses most (3 times or more; a name of two words first), any of them, in
    the trusted collections; films of the years its archive searches ask (± near), a year known -> [hits]"""
    from collections import Counter
    if not years:
        return []
    names = Counter(m for m in re.findall(r"[A-Z][a-z']+(?:\s+[A-Z][a-z']+)*", plan_text)
                    if m.lower() not in MONTHS and m.split()[0].lower() not in GENERIC and len(m) > 3)
    top = [n for n, c in sorted(names.items(), key=lambda kv: (-(" " in kv[0]), -kv[1])) if c >= 3][:most]
    if not top:
        return []
    q = " OR ".join(f'"{x}"' if " " in x else x for x in top)
    lo, hi = min(years) - near, max(years) + near
    out = []
    for h in ia_search(q):
        try:
            y = int(str(h.get("year"))[:4])
        except (TypeError, ValueError):
            continue
        if lo <= y <= hi:
            out.append(h)
    return out


MONTHS = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"}
GENERIC = {"footage", "film", "video", "archive", "photo", "photos", "news", "scene", "shot", "aerial", "view", "street", "streets",
           "the", "of", "in", "on", "at", "and", "a", "an", "with", "during", "after", "before"}


def short_queries(query, most=3):
    """a long archive search -> short ones, the year kept (owner's fix 1 of 22 Oct 2026): the names in it (capitalised
    words, months left out) with the year; its first two words with the year; its last name with the year. The long one
    is tried first only when it is already short (3 words or fewer)"""
    toks = re.findall(r"[A-Za-z][A-Za-z'\-]*|\d{4}", query)
    year = next((t for t in toks if re.fullmatch(r"1[89]\d\d|20\d\d", t)), None)
    words = [t for t in toks if not re.fullmatch(r"\d{4}", t) and t.lower() not in MONTHS]
    names = [t for t in words if t[0].isupper() and t.lower() not in GENERIC]
    plain = [t for t in words if t.lower() not in GENERIC]
    y = f" {year}" if year else ""
    out = []
    if len(query.split()) <= 3:
        out.append(query.strip())
    if names and (len(names) >= 2 or year):
        out.append(" ".join(names[:3]) + y)
    if len(plain) >= 2:
        out.append(" ".join(plain[:2]) + y)
    if names and year:                 # one name alone only with its year (never «Scottish» on its own)
        out.append(names[-1] + y)
    seen, res = set(), []
    for q in out:
        k = q.lower().strip()
        if k and k not in seen and len(k) > 2:
            seen.add(k)
            res.append(q.strip())
    return res[:most] or [query]


def fetch_film(p, item, ledger, budget, log=print):
    """an Internet Archive film or a Commons video -> the library clip S:<key> (H.264, at most its first 60 s for a Commons
    video), with its credits record; None when it cannot be had within the episode's limit"""
    key = _key(item)
    out = p.asset_dir("library") / f"{key}.mp4"
    done_segs = sorted(p.asset_dir("library").glob(f"{key}_[0-9][0-9].mp4"))
    if done_segs:                      # cut into its scenes by an earlier run
        return [f"S:{x.stem}" for x in done_segs]
    if out.exists() and out.stat().st_size > 100000 and video_ok(out):
        return f"S:{key}"
    if budget.left() <= 20 or budget.files >= MAX_FILES:
        budget.stop(log, f"the archive film {item.get('title', '')[:50]}")
        return None
    if out.exists():
        set_aside(p, out, "not a playable video (saved by an earlier run)", ledger, f"S:{key}")
    t = time.time()
    try:
        if item.get("source") == "archive":
            code, body = curl(f"https://archive.org/metadata/{urllib.parse.quote(item['ident'])}", ua=UA_API)
            if code != "200":
                log(f"archive {item['ident']}: metadata HTTP {code}")
                return None
            meta = json.loads(body)
            lic = item.get("licence") if re.match(r"^(gov\.|ARC_)", item["ident"]) else _ia_licence(meta.get("metadata", {}))
            if not licence_ok(lic):
                log(f"archive {item['ident']}: REFUSED by the licence gate ({lic!r})")
                return None
            files = [f for f in meta.get("files", []) if f.get("name", "").lower().endswith(".mp4")
                     and int(f.get("height") or 480) >= 400 and int(f.get("size") or 0) < FILM_MAX_MB * 2 ** 20]
            if not files:
                log(f"archive {item['ident']}: no MP4 of a usable size")
                return None
            f = min(files, key=lambda x: int(x.get("size") or 1 << 40))
            url = f"https://archive.org/download/{urllib.parse.quote(item['ident'])}/{urllib.parse.quote(f['name'])}"
            out.parent.mkdir(parents=True, exist_ok=True)
            ok, why = download(p, url, out, video_ok, max_bytes=FILM_MAX_MB * 1e6, max_time=budget.left())
            src_name, author = "Internet Archive", ", ".join(item.get("collection", []))
        else:
            lic = item.get("licence")
            if not licence_ok(lic):
                log(f"commons video {item['title']}: REFUSED by the licence gate ({lic!r})")
                return None
            raw = p.work / "montage" / "commons_video" / f"{key}.src"
            raw.parent.mkdir(parents=True, exist_ok=True)
            ok, why = download(p, item["url"], raw, video_ok, max_bytes=COMMONS_VIDEO_MAX_MB * 1e6, max_time=budget.left())
            if ok:                       # its first 60 s as the pipeline's H.264, no sound
                with atomic(out) as tmp:
                    subprocess.run([str(FFMPEG), "-v", "error", "-y", "-i", str(raw), "-t", "60", "-an", "-vf", "scale=-2:1080",
                                    "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p", "-f", "mp4", str(tmp)], check=True)
            src_name, author = "Wikimedia Commons", item.get("author", "")
    finally:
        budget.spend(time.time() - t, file=True)
    if not ok:
        log(f"archive film {item.get('title', '')[:60]}: left out, the download failed ({why})")
        return None
    ledger.add(f"S:{key}", kind="archive video", source=src_name, page=item.get("page", ""), title=item.get("title", ""),
               author=author, licence=lic, file=str(out))
    log(f"archive film {item.get('title', '')[:60]}: {lic} ({src_name})")
    segs = segments(p, out, key, ledger, dict(source=src_name, page=item.get("page", ""), title=item.get("title", ""), author=author,
                                              licence=lic), log)
    return segs or f"S:{key}"


SEG_FROM_S = 90.0          # a film longer than this is cut into its scenes (each a library clip S:<key>_<nn>)
SEG_MIN, SEG_MAX, SEG_MOST = 2.5, 10.0, 40


def scene_cuts(path):
    r = subprocess.run([str(FFMPEG), "-hide_banner", "-i", str(path), "-vf", "select='gt(scene,0.32)',showinfo", "-f", "null", "-"],
                       capture_output=True, text=True)
    return sorted(float(m) for m in re.findall(r"pts_time:([\d.]+)", r.stderr))


def segments(p, film, key, ledger, rec, log=print):
    """a long archive film -> its scenes as library clips S:<key>_<nn> (2.5-10 s, at most SEG_MOST, its first and last 8 s
    left out: titles); the whole film kept aside in library/_whole -> [codes] (none for a short film)"""
    from ...core.io import atomic as _atomic
    dur = float(subprocess.run([str(FFMPEG).replace("ffmpeg", "ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of",
                                "csv=p=0", str(film)], capture_output=True, text=True).stdout or 0)
    if dur < SEG_FROM_S:
        return []
    cuts = [0.0] + [c for c in scene_cuts(film) if 8.0 < c < dur - 8.0] + [dur]
    spans = []
    for a, b in zip(cuts, cuts[1:]):
        if a < 8.0 or b > dur - 8.0:
            continue
        while b - a > SEG_MAX:
            spans.append((a + 0.2, a + SEG_MAX * 0.8))
            a += SEG_MAX * 0.8
        if b - a >= SEG_MIN:
            spans.append((a + 0.2, b - 0.2))
    if len(spans) > SEG_MOST:          # spread over the whole film
        step = len(spans) / SEG_MOST
        spans = [spans[int(i * step)] for i in range(SEG_MOST)]
    codes = []
    for n, (a, b) in enumerate(spans, 1):
        out = p.asset_dir("library") / f"{key}_{n:02d}.mp4"
        if not (out.exists() and out.stat().st_size > 20000):
            with _atomic(out) as tmp:
                subprocess.run([str(FFMPEG), "-v", "error", "-y", "-ss", f"{a:.2f}", "-t", f"{b - a:.2f}", "-i", str(film), "-an",
                                "-vf", "scale=-2:1080:flags=lanczos,fps=24", "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                                "-pix_fmt", "yuv420p", "-f", "mp4", str(tmp)], check=True)
        ledger.add(f"S:{key}_{n:02d}", kind="archive video", file=str(out), part_of=f"S:{key}", from_s=round(a, 2), to_s=round(b, 2), **rec)
        codes.append(f"S:{key}_{n:02d}")
    whole = p.asset_dir("library") / "_whole"
    whole.mkdir(exist_ok=True)
    film.replace(whole / film.name)    # kept aside, not offered whole (its scenes are)
    log(f"archive film {rec.get('title', '')[:50]}: {len(codes)} scenes as library clips")
    return codes


def fetch_photo(p, item, ledger, budget, log=print, width=2560):
    """a Commons photo the picker chose (by its title) -> P:<key>, with its credits record"""
    out = p.asset_dir("photos") / f"{item['key']}.jpg"
    if out.exists() and out.stat().st_size > 50000:
        return f"P:{item['key']}"
    if budget.left() <= 5 or budget.files >= MAX_FILES:
        budget.stop(log, f"the archive photo {item['key']}")
        return None
    t = time.time()
    try:
        d = commons_get({"action": "query", "titles": item["title"], "prop": "imageinfo", "iiprop": "url|extmetadata", "iiurlwidth": str(width)})
        ii = (next(iter(((d.get("query") or {}).get("pages") or {}).values()), {}).get("imageinfo") or [None])[0]
        if not ii:
            log(f"photo {item['key']}: left out, Commons gave no file information")
            return None
        meta = ii.get("extmetadata", {})
        lic = meta.get("LicenseShortName", {}).get("value", "") or item.get("licence")
        if not licence_ok(lic):
            log(f"photo {item['key']}: REFUSED by the licence gate ({lic!r})")
            return None
        src = ii.get("thumburl") or ii["url"]
        out.parent.mkdir(parents=True, exist_ok=True)
        ok, why = download(p, src, out, as_jpeg, max_time=budget.left())
    finally:
        budget.spend(time.time() - t, file=True)
    if not ok:
        log(f"photo {item['key']}: left out, the download failed ({why})")
        return None
    author = item.get("author") or re.sub("<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip()
    ledger.add(f"P:{item['key']}", kind="archive photo", source="Wikimedia Commons", page=item.get("page", ""), title=item["title"],
               author=author, licence=lic, file=str(out), src=src)
    log(f"photo {item['key']}: {lic} (Wikimedia Commons)")
    return f"P:{item['key']}"

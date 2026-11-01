"""Magnific (formerly Freepik) stock videos: the official REST API with the key from the keys file (owner's manager's
decision of 20 Oct 2026: a paid source for الحدث الأخير and اقتصاد احمس only; the old "no paid tools" rule stays for the
other channels). Turned on per channel by "montage.sources.magnific": true in its channel.json, and used only while the
key is in the keys file; the classic same-result projects never see it.

  search(query)   GET https://api.magnific.com/v1/videos?term=… (header x-magnific-api-key), cached 24 h like Pixabay's;
                  footage only, 16:9, at least 1080p, never AI-made, kept in code.
  fetch(item)     GET /v1/videos/{id}/download -> a link to the file, downloaded and checked like every download
                  (sources.download); only the clips a plan picked are downloaded, once. That link is the clip's
                  ORIGINAL file (the real test of 20 Oct 2026: a 32 s 4K ProRes, 2.26 GB, 12 minutes): the size guard
                  reads the original's size first (GET /v1/videos/{id}, free) and refuses one over MAX_MB, and the
                  download itself stops at MAX_MB. Smaller copies are listed (1080p H.264, 46 MB) but no documented
                  request downloads them; /videos/{id}/download/{option id} answered 404. So only clips whose
                  original is at most MAX_MB are offered at all (small_only: their sizes read when found, kept).

The key goes in a request header from Python (never in a command line, a log or a file of the project). Requests send a
neutral User-Agent and nothing personal. Licence (Magnific's terms of use): a premium clip under the plan's licence, a
free one with its author named; both are recorded in the credits ledger (sources.Ledger) and pass the one licence gate.
Use is counted in DATA/usage/magnific.jsonl (searches, downloads, the reply's credit and rate-limit headers when it gives
them) for «التكاليف»; at most DAILY_CAP downloads a day (the Premium and Pro plans' cap through the API).
"""
import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from ...core import apikeys
from ...core.io import load_json, save_json
from ...core.paths import CACHE, DATA
from . import UA, UA_API, download, set_aside, video_ok

API = "https://api.magnific.com/v1"
KEY = "magnific_api_key"
USAGE = DATA / "usage" / "magnific.jsonl"
CACHE_DIR = CACHE / "stock_search"
DAY = 24 * 3600
DAILY_CAP = 100
MAX_MB = 150           # owner's size guard (20 Oct 2026): the download gives a clip's original (a 32 s 4K ProRes was 2.26 GB)
LICENCE = {True: "Magnific Premium licence (the plan's subscription)", False: "Magnific Free licence (attribution: its author on Magnific)"}


def on(p):
    """the channel turned Magnific on and the key is in the keys file"""
    from . import mode
    if mode(p) == "free":              # «المصادر» of this episode: free only
        return False
    if not getattr(p, "profile", None) or not apikeys.get(KEY):
        return False
    try:
        return bool((p.profile_montage().get("sources") or {}).get("magnific"))
    except Exception:  # noqa: BLE001  (no profile section: off)
        return False


def note(what, **kw):
    """one line of use for «التكاليف» (never the key)"""
    USAGE.parent.mkdir(parents=True, exist_ok=True)
    with open(USAGE, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(at=time.strftime("%Y-%m-%d %H:%M:%S"), what=what, **kw), ensure_ascii=False) + "\n")


def usage():
    out = []
    if USAGE.exists():
        for ln in USAGE.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
    return out


def downloads_today():
    today = time.strftime("%Y-%m-%d")
    return sum(1 for u in usage() if u.get("what") == "download" and u.get("ok") and u.get("at", "").startswith(today))


def _get(path, params=None):
    """(http code, json or None, the reply's credit/limit headers); the key only in the header"""
    key = apikeys.get(KEY)
    url = f"{API}{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"x-magnific-api-key": key, "User-Agent": UA_API, "Accept": "application/json",
                                               "Accept-Language": "en-US"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            heads = {k.lower(): v for k, v in r.headers.items() if any(w in k.lower() for w in ("credit", "ratelimit", "rate-limit"))}
            return str(r.status), json.loads(r.read().decode() or "null"), heads
    except urllib.error.HTTPError as e:
        heads = {k.lower(): v for k, v in (e.headers or {}).items() if any(w in k.lower() for w in ("credit", "ratelimit", "rate-limit"))}
        return str(e.code), None, heads
    except (urllib.error.URLError, OSError, ValueError):
        return "000", None, {}


def seconds(hms):
    try:
        h, m, s = (hms or "0:0:0").split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)
    except ValueError:
        return 0.0


QUALITY_OK = {"1080p", "2k", "4k"}


def usable(h):
    return h.get("active", True) is not False and h.get("item_subtype", "footage") == "footage" and \
        h.get("aspect_ratio", h.get("aspect-ratio")) == "16:9" and h.get("quality") in QUALITY_OK and not h.get("is_ai_generated")


def search(query, n=12, project=""):
    """[{id: "mg<id>", title, tags, seconds, page, user, thumb, premium}] for one query, cached 24 h -> (hits, note)"""
    if not apikeys.get(KEY):
        return [], f"no {KEY} in the keys file"
    f = CACHE_DIR / f"magnific_{hashlib.sha256(query.lower().encode()).hexdigest()[:20]}.json"
    if f.exists():
        d = load_json(f)
        if time.time() - d["at"] < DAY:
            return d["hits"][:n], "ok (cached)"
    code, body, heads = _get("/videos", {"term": query[:100], "order": "relevance", "page": 1})
    note("search", query=query[:100], http=code, project=project, **({"headers": heads} if heads else {}))
    if code != "200" or not isinstance(body, dict):
        return [], f"HTTP {code}"
    hits = []
    for h in body.get("data") or []:
        if not usable(h):
            continue
        thumb = ((h.get("thumbnails") or [{}])[0]).get("url", "")
        hits.append({"id": f"mg{h['id']}", "title": h.get("name", ""), "tags": h.get("name", ""), "seconds": seconds(h.get("duration")),
                     "page": h.get("url", ""), "user": (h.get("author") or {}).get("name", ""), "thumb": thumb,
                     "premium": bool(int(h.get("premium") or 0)), "quality": h.get("quality", "")})
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    save_json(f, {"at": time.time(), "query": query, "hits": hits, "total": ((body.get("meta") or {}).get("pagination") or {}).get("total")})
    return hits[:n], "ok"


SIZES = CACHE / "magnific_sizes.json"     # {id: MB of its original}: a clip's original never changes
_sizes_lock = threading.Lock()


def original_mb(num):
    """the size in MB of the clip's original file (what /download gives), from GET /videos/{id} (free), kept in SIZES;
    None when unknown"""
    num = str(num)
    with _sizes_lock:
        known = load_json(SIZES) if SIZES.exists() else {}
    if num in known:
        return known[num]
    code, body, _ = _get(f"/videos/{num}")
    opts = (((body or {}).get("data") or {}).get("options") or []) if code == "200" and isinstance(body, dict) else []
    orig = next((o for o in opts if o.get("is_original")), None)
    try:
        mb = float(orig["size"]) if orig and orig.get("size") is not None else None
    except (TypeError, ValueError):
        mb = None
    if mb is not None:
        with _sizes_lock:
            known = load_json(SIZES) if SIZES.exists() else {}
            known[num] = mb
            SIZES.parent.mkdir(parents=True, exist_ok=True)
            save_json(SIZES, known)
    return mb


def small_only(hits, want, max_checks=None):
    """the first `want` hits whose original is at most MAX_MB (owner's option 2 of 20 Oct 2026: only clips the size guard
    lets through are offered), each with its "mb"; at most max_checks sizes asked (default 3 x want); an unknown size is
    left out"""
    out, checks = [], 0
    for h in hits:
        if len(out) >= want or checks >= (max_checks or 3 * want):
            break
        checks += 1
        mb = original_mb(str(h["id"])[2:] if str(h["id"]).startswith("mg") else h["id"])
        if mb is not None and mb <= MAX_MB:
            out.append(dict(h, mb=mb))
    return out


def fetch(p, item, ledger, log):
    """the picked clip -> work/assets/stock/mg<id>.mp4 with its credits record, or nothing (said in the log)"""
    key = str(item["id"])
    num = key[2:] if key.startswith("mg") else key
    out = p.asset_dir("stock") / f"mg{num}.mp4"
    if out.exists() and out.stat().st_size > 100000 and video_ok(out):
        return
    if out.exists():
        set_aside(p, out, "not a playable video (saved by an earlier run)", ledger, f"V:mg{num}")
    if not apikeys.get(KEY):
        log(f"magnific {num}: SKIPPED — no {KEY} in the keys file")
        return
    if downloads_today() >= DAILY_CAP:
        log(f"magnific {num}: left out, {DAILY_CAP} downloads today already (the plan's daily cap)")
        return
    size = original_mb(num)            # the file the download gives, from the clip's own record (a free request)
    if size is not None and size > MAX_MB:
        note("refused-size", id=num, mb=size, project=p.folder.name)
        log(f"magnific {num}: left out, its download is the original file ({size:.0f} MB), over {MAX_MB} MB")
        return
    code, body, heads = _get(f"/videos/{num}/download")
    url = ((body or {}).get("data") or {}).get("url") if isinstance(body, dict) else None
    if code != "200" or not url:
        note("download", id=num, http=code, ok=False, project=p.folder.name, **({"headers": heads} if heads else {}))
        log(f"magnific {num}: left out, no download link (HTTP {code})")
        return
    ok, why = download(p, url, out, video_ok, ua=UA, max_bytes=MAX_MB * 1e6)
    if not ok and why.startswith("bigger than"):
        note("refused-size", id=num, mb=None, project=p.folder.name, stopped=True)
    note("download", id=num, http=code, ok=ok, project=p.folder.name, premium=item.get("premium"), **({"headers": heads} if heads else {}))
    if not ok:
        log(f"magnific {num}: left out, the download failed ({why})")
        return
    ledger.add(f"V:mg{num}", kind="stock video", source="Magnific", page=item.get("page", ""), title=item.get("title", ""),
               author=item.get("user", ""), licence=LICENCE[bool(item.get("premium"))], file=str(out), how="Magnific API (key present)")
    log(f"magnific {num}: Magnific API")


# ---------------------------------------------------------------------------------------------------- the credit balance
BALANCE = DATA / "usage" / "magnific_balance.jsonl"
BALANCE_TOOL = "mcp__claude_ai_magnific__account_balance"
PAGE_EVERY_S = 3600              # the page reads it at most once an hour


def balances():
    out = []
    if BALANCE.exists():
        for ln in BALANCE.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
    return out


def read_balance(why="page", project="", cwd=None, log=print):
    """the plan and credits from Magnific's own read-only account_balance tool (the Magnific connector on this Mac's
    Claude account; it never charges), through a background Claude allowed that one tool only (as Storyblocks' runs) ->
    the reading (also kept in BALANCE), or None"""
    from .storyblocks import run_claude
    prompt = (f"Load the tool {BALANCE_TOOL} with ToolSearch (query \"select:{BALANCE_TOOL}\"). Call it once with no "
              "arguments. Call no other tool. When done, reply with the single word done.")
    calls, st = run_claude(prompt, BALANCE_TOOL, cwd or (DATA / "usage" / "runs"), log)
    for _, txt, err in calls:
        if err:
            continue
        try:
            d = json.loads(txt)
        except ValueError:
            continue
        cr, pl = d.get("credits") or {}, d.get("plan") or {}
        rec = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "why": why, "project": project, "available": cr.get("available"),
               "total_plan": cr.get("totalPlan"), "spent": cr.get("spent"), "extra": cr.get("hasExtraCredits"), "scope": cr.get("scope"),
               "tier": pl.get("tier"), "plan": pl.get("productName"), "paid": pl.get("isPaidPlan")}
        BALANCE.parent.mkdir(parents=True, exist_ok=True)
        with open(BALANCE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return rec
    log(f"magnific: the balance could not be read ({st['status']})")
    return None


def on_any():
    """Magnific can be read at all: its key is in the keys file"""
    return bool(apikeys.get(KEY))


def balance_due():
    """the page may read the balance again (the last page reading is older than an hour)"""
    last = [b for b in balances() if b.get("why") == "page"]
    if not last:
        return True
    try:
        return time.time() - time.mktime(time.strptime(last[-1]["at"], "%Y-%m-%d %H:%M:%S")) > PAGE_EVERY_S
    except (ValueError, KeyError):
        return True


def episode_reading(p, why):
    """the balance at the start / end of an episode's sources step (its credits spent = the difference); never stops a run"""
    if not on(p):
        return None
    try:
        return read_balance(why, project=p.folder.name, cwd=p.work / "montage" / "storyblocks_runs", log=lambda *a: None)
    except Exception:  # noqa: BLE001
        return None

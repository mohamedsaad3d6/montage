"""Still pictures from Pixabay's photos (the official API with the key from the keys file; Pixabay Content License),
searched in code, cached 24 h like the other searches (Pixabay's rule), each item through the ONE licence gate.

  search(src, query)          -> [{src, source, id, title, description, licence, page, author, thumb, width, height}]
  key_of(src, id)             the picture's key in the project (P:<key>), readable and stable
  fetch(p, item, ledger, log) the full picture, checked (a real picture, at least MIN_W wide, kept as JPEG), with its
                              credits record; a failed download leaves the shot without it, never stops the run

The other still sources (The Met, Wellcome Collection, Cleveland Museum of Art, NASA) were removed on 19 Oct 2026 (owner's
decision after the first fast-mode runs: 19 of 184 pictures between them, and The Met took most of the search time); the
earlier refusals (Library of Congress, Art Institute of Chicago, Openverse, Europeana, the Internet Archive's images,
Smithsonian) are in NOTES.md.
"""
import json
import re
import time
import urllib.parse

from ...core import apikeys
from ...core.io import save_json
from . import UA, UA_API, _turn, as_jpeg, curl, download, licence_ok, picture_kind
from .search import _cached

SOURCES = ("pixabay",)
NAME = {"pixabay": "Pixabay"}
MIN_W = 1000                            # a still narrower than this looks soft on a 1920 frame, even with the slow push


def _get(url, ua=UA_API, tries=2):
    """JSON from an API, or None; a refusal (403, 429) is tried once more after a short wait"""
    for n in range(tries):
        _turn(url)
        code, body = curl(url, ua=ua)
        if code == "200" and body and body[:1] in (b"{", b"["):
            return json.loads(body)
        if code not in ("403", "429", "500", "502", "503", "504", "000"):
            return None
        time.sleep(3 * (n + 1))
    return None


def _pixabay(q):
    key = apikeys.get("pixabay_api_key")
    if not key:
        return []
    d = _get("https://pixabay.com/api/?" + urllib.parse.urlencode({"key": key, "q": q[:100], "image_type": "photo",
                                                                     "per_page": 30, "safesearch": "true", "order": "popular"}))
    return [{"id": str(h["id"]), "title": h.get("tags", ""), "description": "", "licence": "Pixabay Content License",
             "page": h.get("pageURL", ""), "author": h.get("user", ""), "thumb": h.get("webformatURL", ""),
             "width": h.get("imageWidth"), "height": h.get("imageHeight"), "ai_generated": bool(h.get("isAiGenerated"))}
            for h in (d or {}).get("hits", []) if (h.get("imageWidth") or 0) >= 1280]


SEARCH = {"pixabay": _pixabay}


def search(src, query):
    """the source's licence-gated hits for one query (cached 24 h)"""
    hits, f = _cached(f"photo_{src}", query.lower())
    if hits is None:
        try:
            hits = SEARCH[src](query)
        except (ValueError, KeyError, TypeError):
            hits = []
        save_json(f, {"at": time.time(), "query": query, "hits": hits})
    return [dict(h, src=src, source=NAME[src]) for h in hits if licence_ok(h["licence"]) and h.get("thumb")]


def key_of(src, ident):
    return f"{src[:3]}_" + re.sub(r"[^A-Za-z0-9-]+", "_", str(ident))[:40]


def _big(path):
    """a real picture, kept as JPEG, at least MIN_W wide"""
    if not as_jpeg(path):
        return False
    from PIL import Image
    with Image.open(path) as im:
        return im.width >= MIN_W


def _full_url(item):
    if item["src"] == "pixabay":                   # the API's file links are not kept long: asked again by id
        d = _get("https://pixabay.com/api/?" + urllib.parse.urlencode({"key": apikeys.get("pixabay_api_key") or "", "id": item["id"]}))
        h = ((d or {}).get("hits") or [{}])[0]
        return h.get("largeImageURL")
    return None


def fetch(p, item, ledger, log=print):
    """-> the picture's code P:<key>, or None when it was left out (item key: the key a classic sources decision gave it)"""
    key = item.get("key") or key_of(item["src"], item["id"])
    if item.get("src") not in SEARCH:                # a source removed on 19 Oct 2026: its picture only if already here
        out = p.asset_dir("photos") / f"{key}.jpg"
        return f"P:{key}" if out.exists() and picture_kind(out) == "JPEG" and f"P:{key}" in ledger.rec else None
    out = p.asset_dir("photos") / f"{key}.jpg"
    code = f"P:{key}"
    if out.exists() and picture_kind(out) == "JPEG" and code in ledger.rec:
        return code
    if not licence_ok(item.get("licence")):
        log(f"photo {key}: REFUSED by the licence gate ({item.get('licence')!r})")
        return None
    url = _full_url(item)
    if not url:
        log(f"photo {key}: left out, {item['source']} gave no file")
        return None
    ok, why = download(p, url, out, _big, ua=UA)    # as the Pixabay videos
    if not ok:
        log(f"photo {key}: left out, the download failed ({why})")
        return None
    ledger.add(code, kind="stock photo", source=item["source"],
               page=item.get("page", ""), title=item.get("title", ""), author=item.get("author", ""), licence=item["licence"],
               file=str(out), src=url)
    log(f"photo {key}: {item['source']}, {item['licence']}")
    return code


__all__ = ["SOURCES", "NAME", "search", "key_of", "fetch"]

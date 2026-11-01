"""Searching free sources in code, so the brain only chooses among candidates (it never browses the web).

  Pixabay videos   the official API with the key from the keys file (never printed or logged). Pixabay's rules
                   (engine/NOTES.md): the same search is not repeated within 24 h (cached with its time), no systematic
                   mass downloads (only the clips a plan uses are downloaded, by fetch_all), files downloaded, never
                   hotlinked. Licence: Pixabay Content License.
  Still photos     the local library first (sources/local_library.py: the files already on this Mac, no network), then
                   Pixabay's photos (sources/photos.py), each item through the one licence gate (sources.licence_ok).

Since 19 Oct 2026 (owner's decision after the first fast-mode runs) these are the only footage sources: Wikimedia
Commons, Pexels, the Internet Archive, The Met, Wellcome, Cleveland, NASA, Smithsonian and DVIDS are not searched.

-> work/montage/candidates.json {"stock": {query: [{id, title, tags, seconds, width, page, user}]},
                                 "photos": {query: [{title, page, licence, author, src, id | code}]}}
"""
import hashlib
import json
import os
import re
import time
import urllib.parse

from ...core import apikeys
from ...core.io import load_json, save_json
from ...core.paths import CACHE
from . import UA_API, _turn, curl

CACHE_DIR = CACHE / "stock_search"
DAY = 24 * 3600


def queries_from_plan(plan, cap=True):
    """the plan's search words -> {"stock": [{query, for}], "photos": [...]}. cap: the classic projects' first 14 / 12 (their
    requests stay as they were). A channel episode searches EVERY word the plan asks (owner's fix 1 of 21 Oct 2026: with the
    cap, the first episode searched only the first 3:20 of its 16 minutes), and each search keeps the plan blocks it serves
    ("blocks": [index]), so what it finds belongs to that part of the episode"""
    st, ph = [], []
    for i, b in enumerate((plan or {}).get("blocks", [])):
        why = f"{b.get('in')}-{b.get('out')} s: {', '.join(b.get('shows', []))[:80]}"
        st += [{"query": q, "for": why, "block": i} for q in b.get("search_stock", [])]
        ph += [{"query": q, "for": why, "block": i} for q in b.get("search_photos", [])]
    if cap:
        dedup = lambda xs: list({x["query"].strip().lower(): {"query": x["query"], "for": x["for"]} for x in xs  # noqa: E731
                                 if x["query"].strip()}.values())
        return {"stock": dedup(st)[:14], "photos": dedup(ph)[:12]}

    def merged(xs):
        out = {}
        for x in xs:
            k = x["query"].strip().lower()
            if not k:
                continue
            if k in out:
                out[k]["blocks"].append(x["block"])
            else:
                out[k] = {"query": x["query"].strip(), "for": x["for"], "blocks": [x["block"]]}
        return list(out.values())
    return {"stock": merged(st), "photos": merged(ph)}


def by_block(plan, queries, cand):
    """each footage block of the plan with the candidates its own searches found -> {block: {in, out, shows, stock: [ids],
    photos: [titles]}} (a candidate found by several blocks' searches belongs to each of them)"""
    out, lists = {}, {}
    blocks = (plan or {}).get("blocks", [])
    for q in queries.get("stock", []) + queries.get("photos", []):
        for i in q.get("blocks", []):
            b = blocks[i]
            out.setdefault(str(i), {"in": b.get("in"), "out": b.get("out"), "shows": b.get("shows", []), "stock": [], "photos": []})
            for kind in ("stock", "photos"):    # an archive search finds films (clips) as well as photos
                got = cand[kind].get(q["query"], [])
                if got:
                    lists.setdefault((str(i), kind), []).append([c["id"] if kind == "stock" else c["title"] for c in got])
    for (i, kind), ls in lists.items():   # the block's searches in turn: the first of each, then the second of each …
        e = out[i][kind]
        for k in range(max(map(len, ls), default=0)):
            for x in ls:
                if k < len(x) and x[k] not in e:
                    e.append(x[k])
    return dict(sorted(out.items(), key=lambda kv: int(kv[0])))


def wrong_block(blocks, d):
    """the picker's picks not found by the own searches of the block they name -> ["id (block n)"]"""
    out = [f"{x['id']} (block {x.get('block')})" for x in d.get("stock", []) if x["id"] not in blocks.get(str(x.get("block")), {}).get("stock", [])]
    out += [f"{x['title'][:40]} (block {x.get('block')})" for x in d.get("photos", [])
            if x["title"] not in blocks.get(str(x.get("block")), {}).get("photos", [])]
    return out


THUMBS = CACHE / "thumbs"
SHEET_MAX = 48                 # candidates on one block's sheet (8 rows; its searches in turn)


def _thumb(c):
    """a candidate's own preview picture (the URL its source's search returned; no clip is downloaded) -> local file or None"""
    url = c.get("thumb") or ""
    if not url.startswith("https://"):
        return None
    f = THUMBS / (hashlib.sha256(url.encode()).hexdigest()[:24] + ".jpg")
    if f.exists() and f.stat().st_size > 1000:
        return f
    THUMBS.mkdir(parents=True, exist_ok=True)
    part = f.with_suffix(".part")      # a failed fetch leaves only this (written over next time)
    code, _ = curl(url, out=part, ua=UA_API)
    if code == "200" and part.exists() and part.stat().st_size > 1000:
        os.replace(part, f)
        return f
    return None


def pick_sheets(blocks, cand, out_dir):
    """one contact sheet per footage block: its candidates' preview pictures, each labelled with its id, 6 a row ->
    {block: sheet path}. The picker reads them (owner's fix 2 of 21 Oct 2026: it chose from titles only)"""
    from PIL import Image, ImageDraw
    out_dir.mkdir(parents=True, exist_ok=True)
    stock = {c["id"]: c for v in cand["stock"].values() for c in v}
    photos = {c["title"]: c for v in cand["photos"].values() for c in v}
    sheets = {}
    every = {id(c): c for b in blocks.values() for c in ([stock[k] for k in b["stock"] if k in stock][:SHEET_MAX]
                                                         + [photos[t] for t in b["photos"] if t in photos][:SHEET_MAX])}
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(8) as ex:  # the preview pictures fetched 8 at a time (one at a time took 5.6 min for 650)
        got = dict(zip(every, ex.map(_thumb, every.values())))
    for i, b in blocks.items():
        items = [(str(k), stock[k]) for k in b["stock"] if k in stock] + [(t[:28], photos[t]) for t in b["photos"] if t in photos]
        tiles = []
        for label, c in items[:SHEET_MAX]:
            f = got.get(id(c))
            if f is None:
                continue
            try:
                im = Image.open(f).convert("RGB")
            except OSError:
                continue
            im.thumbnail((320, 180))
            tile = Image.new("RGB", (320, 206), "black")
            tile.paste(im, ((320 - im.width) // 2, 0))
            ImageDraw.Draw(tile).text((6, 186), label, fill="yellow")
            tiles.append(tile)
        if not tiles:
            continue
        cols, rows = 6, (len(tiles) + 5) // 6
        sheet = Image.new("RGB", (cols * 320, rows * 206), "black")
        for k, t in enumerate(tiles):
            sheet.paste(t, ((k % cols) * 320, (k // cols) * 206))
        path = out_dir / f"block_{int(i):02d}.jpg"
        sheet.save(path, quality=80)
        sheets[i] = path
    return sheets


def _cached(kind, q):
    f = CACHE_DIR / f"{kind}_{hashlib.sha256(q.encode()).hexdigest()[:20]}.json"
    if f.exists():
        d = load_json(f)
        if time.time() - d["at"] < DAY:
            return d["hits"], f
    return None, f


def pixabay(query, n=12):
    key = apikeys.get("pixabay_api_key")
    if not key:
        return [], "no pixabay_api_key in the keys file"
    hits, f = _cached("pixabay60", query.lower())      # 60 results a search since Phase 2 (more chances of a real clip)
    if hits is not None and hits and "thumb" not in hits[0]:
        hits = None                                   # cached before thumbnails were kept: search again
    if hits is None:
        url = "https://pixabay.com/api/videos/?" + urllib.parse.urlencode({"key": key, "q": query[:100], "per_page": max(60, n),
                                                                            "safesearch": "true", "order": "popular"})
        _turn(url)
        code, body = curl(url, ua=UA_API)
        if code != "200":
            return [], f"HTTP {code}"
        hits = []
        for h in json.loads(body).get("hits", []):
            v = h.get("videos", {})
            big = v.get("large") or v.get("medium") or {}
            hits.append({"id": h["id"], "title": h.get("tags", ""), "tags": h.get("tags", ""), "seconds": h.get("duration"),
                         "width": big.get("width"), "page": h.get("pageURL", ""), "user": h.get("user", ""),
                         "thumb": (v.get("small") or v.get("tiny") or {}).get("thumbnail", ""),
                         "ai_generated": bool(h.get("isAiGenerated"))})
        save_json(f, {"at": time.time(), "query": query, "hits": hits})
    return [h for h in hits if (h.get("width") or 0) >= 1280][:n], "ok"


STOP = {"the", "and", "with", "for", "from", "into", "over", "under", "near", "of", "in", "on", "at", "to", "a", "an", "by"}


def tokens(text):
    return set(re.findall(r"[a-z0-9]+", (text or "").lower()))


def main_words(query):
    return [w for w in re.findall(r"[a-z0-9]+", query.lower()) if w not in STOP and (len(w) > 2 or w.isdigit())]


def _has(words, toks):
    return all(w in toks or (w.endswith("s") and w[:-1] in toks) or w + "s" in toks for w in words)


def on_topic(hits, query, text_of, tagged=False):
    """hits that hold EVERY main word of the query as a whole word (owner's decision 2a, 16 Oct 2026). tagged (Pixabay's
    comma-separated tags): the words sit in ONE tag (the phrase itself), or they are all there and the head word (the last
    one) is among the clip's first three tags, its main subject. «oil field» no longer lets a sunflower field with "oil"
    somewhere in its tags through; «tanker ship» still finds "ship, freight ship, tanker". Years may be anywhere."""
    need = main_words(query)
    if not need:
        return []
    years = [w for w in need if w.isdigit()]
    words = [w for w in need if not w.isdigit()]
    out = []
    for h in hits:
        text = text_of(h)
        if years and not _has(years, tokens(text)):
            continue
        if tagged:
            tags = text.split(",")
            phrase = any(_has(words, tokens(tag)) for tag in tags)
            # or every word present and the head word (the last one: "pump", "ship") among the clip's first three tags
            head = _has(words, tokens(text)) and _has(words[-1:], tokens(",".join(tags[:3])))
            if words and not (phrase or head):
                continue
        elif not _has(words, tokens(text)):
            continue
        out.append(h)
    return out


def still_photos(query, per_source=2, n=10):
    """on-topic still photos for one query: the local library first, then each photo source -> [{title (unique), …}]"""
    from . import local_library as library, photos
    out = [dict(h, src="library", title=h["title"] or h["code"]) for h in
           on_topic(library.search(query), query, lambda h: h["title"] + " " + h.get("description", ""))
           if h["kind"] == "photo"][:per_source + 1]
    for src in photos.SOURCES:
        out += [dict(h, title=f"{h['title']} [{h['source']} {h['id']}]") for h in
                on_topic(photos.search(src, query), query, lambda h: h["title"] + " " + h.get("description", ""))[:per_source]]
    return out[:n]


def archive_fallback(p):
    """the channel's archive settings say Storyblocks' news-style footage stands in when no archive film is found"""
    try:
        return bool(((p.profile_montage().get("sources") or {}).get("archive") or {}).get("storyblocks_news_fallback"))
    except Exception:  # noqa: BLE001
        return False


def news_query(q):
    """an archive search as a Storyblocks search: the year and months out (its footage is of today), «news» style"""
    import re
    months = r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\b"
    t = re.sub(r"\b(1[89]\d\d|20\d\d)s?\b", " ", q)
    t = re.sub(months, " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    return (t + " news footage") if t else q


def candidates(p, queries, log=print):
    out = {"stock": {}, "photos": {}, "notes": [], "made_at": time.strftime("%Y-%m-%d %H:%M:%S")}
    from . import magnific, storyblocks
    mg = magnific.on(p)                # the channel's paid clips (sources/magnific.py): their ids are "mg<number>"
    sb = storyblocks.on(p)             # the company's Storyblocks clips (sources/storyblocks.py): ids "sb<number>", FIRST
    if sb:
        storyblocks.search_many([q["query"] for q in queries.get("stock", [])], p.work / "montage" / "storyblocks_runs",
                                project=p.folder.name, log=log)
    from . import mode as src_mode
    paid_only = src_mode(p) == "paid"  # «المصادر»: paid only: no Pixabay clips, no free photos
    for q in queries.get("stock", []):
        hits, note = pixabay(q["query"]) if not paid_only else ([], "paid only")
        out["stock"][q["query"]] = hits
        out["notes"].append(f"pixabay «{q['query']}» ({q.get('for', '')}): {len(hits)} usable ({note})")
        if mg:
            found, note = magnific.search(q["query"], 40, project=p.folder.name)
            more = magnific.small_only(found, 6)          # only clips whose download is at most 150 MB
            out["stock"][q["query"]] = hits + [dict(h, source="magnific") for h in more]
            out["notes"].append(f"magnific «{q['query']}»: {len(more)} usable under {magnific.MAX_MB} MB ({note})")
        if sb:
            first = [dict(h, source="storyblocks") for h in (storyblocks.cached(q["query"]) or [])[:6]]
            out["stock"][q["query"]] = first + out["stock"][q["query"]]
            out["notes"].append(f"storyblocks «{q['query']}»: {len(first)} HD clips under {storyblocks.MAX_MB} MB")
    for q in ([] if paid_only else queries.get("photos", [])):
        hits = still_photos(q["query"])
        out["photos"][q["query"]] = hits
        out["notes"].append(f"photos «{q['query']}»: {len(hits)} on topic (local library and free photo sources)")
    from . import free_archive as FA
    if FA.on(p) and queries.get("photos"):   # owner's fix 3 of 21 Oct 2026: the archive searches ask the free archive too
        budget = FA.Budget(p, fresh=True)        # this sources run's own archive time (owner, 22 Oct 2026)
        from concurrent.futures import ThreadPoolExecutor
        qs = [q["query"] for q in queries["photos"]]
        with ThreadPoolExecutor(4) as ex:
            found = list(ex.map(lambda q: FA.search(p, q, budget, log=log), qs))
        for q, (clips, photos) in zip(qs, found):
            if clips:                      # archive films FIRST for an archive search (a block's pick sheet shows its first 48)
                out["stock"][q] = clips + out["stock"].get(q, [])
            if photos:
                out["photos"][q] = out["photos"].get(q, []) + photos
            out["notes"].append(f"free archive «{q}»: {len(clips)} film(s), {len(photos)} photo(s) through the licence gate")
        films = {c["id"]: c for clips, _ in found for c in clips if c.get("source") == "archive"}
        try:                               # and the episode's own search on the names its plan uses most (topic_films)
            import re as _re0
            plan = load_json(p.decisions / "montage" / "plan.json").get("decision") or {}
            text = " ".join(" ".join(b.get("shows", []) + b.get("search_photos", []) + b.get("search_stock", [])) for b in plan.get("blocks", []))
            yrs = sorted({int(m) for q in qs for m in _re0.findall(r"\b(1[89]\d\d|20\d\d)", q)})
            tf = FA.topic_films(text, yrs)
            out["notes"].append(f"free archive (the episode's names): {len(tf)} film(s): " + ", ".join(str(c.get('title', ''))[:40] for c in tf[:6]))
            films.update({c["id"]: c for c in tf})
        except Exception as e:  # noqa: BLE001
            out["notes"].append(f"free archive (the episode's names): not searched ({e})")
        if films:                          # a film found by one archive search serves every archive search of its years
            import re as _re                # (owner, 22 Oct 2026: NARA's «Ulster» 1970 for the protests, the army, the bombings)

            def _year(x):
                m = _re.search(r"\b(1[89]\d\d|20\d\d)", str(x or ""))
                return int(m.group(1)) if m else None
            for q in qs:
                yq = _year(q)
                if yq is None:
                    continue
                have = {c.get("id") for c in out["stock"].get(q, [])}
                more = [c for c in films.values() if c["id"] not in have and (_year(c.get("year")) is None or abs(_year(c.get("year")) - yq) <= 6)
                        and _year(c.get("year")) is not None]
                if more:
                    out["stock"][q] = more + out["stock"].get(q, [])
                    out["notes"].append(f"free archive «{q}»: {len(more)} film(s) of its years found by the episode's other searches")
        if sb and archive_fallback(p):     # owner's fix 1 of 22 Oct 2026: an archive search the free archive found no film for
            empty = [q for q, (clips, _) in zip(qs, found) if not clips]          # gets Storyblocks' news-style footage
            sbq = {q: news_query(q) for q in empty}
            if sbq:
                storyblocks.search_many(sorted(set(sbq.values())), p.work / "montage" / "storyblocks_runs", project=p.folder.name, log=log)
            for q, q2 in sbq.items():
                more = [dict(h, source="storyblocks") for h in (storyblocks.cached(q2) or [])[:6]]
                if more:
                    out["stock"][q] = out["stock"].get(q, []) + more
                out["notes"].append(f"storyblocks (archive fallback) «{q2}» for «{q}»: {len(more)} HD clips")
    for n in out["notes"]:
        log(n)
    save_json(p.work / "montage" / "candidates.json", out)
    return out

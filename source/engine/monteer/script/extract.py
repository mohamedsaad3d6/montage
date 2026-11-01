"""An article page -> its text and facts about it (outlet, title, date), and whether it is fully free.

Text: trafilatura (Apache-2.0). Paywall signs (any one = not used, never worked around):
  - the page's own data says isAccessibleForFree: false, or article:content_tier is "locked" / "metered";
  - the page's own word count or articleBody is much longer than the text we can read (the rest is held back);
  - the readable text is under 120 words.
"""
import json
from .text import norm_date
import re
from html import unescape

import trafilatura

MIN_WORDS = 120


def _jsonld(html):
    out = []
    for m in re.finditer(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            d = json.loads(m.group(1).strip())
        except ValueError:
            continue
        stack = [d]
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack.extend(x)
            elif isinstance(x, dict):
                out.append(x)
                stack.extend(v for k, v in x.items() if k == "@graph")
    return out


def _meta(html, prop):
    m = re.search(r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]+content=["\']([^"\']*)' % re.escape(prop), html, re.I) or \
        re.search(r'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']%s["\']' % re.escape(prop), html, re.I)
    return m.group(1).strip() if m else ""


def article(html_bytes, url):
    """{ok, why, title, outlet, date, text, words, lang, free}"""
    html = html_bytes.decode("utf-8", "replace") if isinstance(html_bytes, bytes) else html_bytes
    lds = _jsonld(html)
    art = next((d for d in lds if str(d.get("@type", "")).lower().endswith(("newsarticle", "article", "reportagenewsarticle",
                                                                             "analysisnewsarticle", "blogposting"))), {})
    free_flags = [d.get("isAccessibleForFree") for d in lds if "isAccessibleForFree" in d]
    tier = _meta(html, "article:content_tier").lower()
    text = trafilatura.extract(html, url=url, include_comments=False, include_tables=True, favor_precision=True) or ""
    md = trafilatura.extract_metadata(html, default_url=url)
    words = len(text.split())
    publisher = art.get("publisher")
    title = (md.title if md else "") or _meta(html, "og:title")
    site = (md.sitename if md else "") or ""
    host = re.sub(r"^www\.", "", re.sub(r"^https?://([^/]+).*$", r"\1", url))
    outlet = (publisher.get("name") if isinstance(publisher, dict) else None) or _meta(html, "og:site_name") or site or host
    raw_title = unescape(re.sub(r"\s+", " ", (re.findall(r"<title[^>]*>(.*?)</title>", html, re.S | re.I) or [""])[0])).strip()
    if outlet != host and (len(outlet) > 50 or any(t and outlet.lower() in t.lower() and len(outlet) < len(t) + 1 and
                                                   not t.lower().endswith(outlet.lower()) for t in (title, raw_title))):
        outlet = host                    # a page title (a person, a topic) taken for the site's name: use the site
    res = {"title": title, "outlet": outlet or "",
           "date": norm_date(art.get("datePublished") or (md.date if md else "") or _meta(html, "article:published_time") or ""),
           "modified": (art.get("dateModified") or _meta(html, "article:modified_time") or "")[:10],
           "text": text, "words": words, "lang": (md.language if md else "") or "", "free": True, "ok": True, "why": ""}
    if any(str(f).lower() == "false" for f in free_flags) or tier in ("locked", "metered"):
        res.update(free=False, ok=False, why="the page says it is not free (paywall): skipped, not worked around")
    stated = 0
    try:
        stated = int(art.get("wordCount") or 0)
    except (TypeError, ValueError):
        pass
    body_words = len(str(art.get("articleBody") or "").split())
    if res["ok"] and max(stated, body_words) > 2 * max(words, 1) and max(stated, body_words) > 300:
        res.update(free=False, ok=False, why=f"only {words} of about {max(stated, body_words)} words can be read (held back): skipped")
    if res["ok"] and words < MIN_WORDS:
        res.update(ok=False, why=f"only {words} readable words (under {MIN_WORDS}): not an article we can check facts in")
    return res

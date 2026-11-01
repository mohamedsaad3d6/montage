"""The source list (one per channel, <channel>/sources.json, yours to edit) and one adapter per way of reaching a source.

sources.json is a list; each entry:
  {"id", "on": true|false, "name" (as it appears in «المصدر»), "kind": news|official|data|legal|reference|discovery,
   "lang", "access": rss|gdelt|wikipedia|wikidata|worldbank|treasury|ecb|eurostat|bls|federal_register|domain,
   "url" (feed or API address), "domains" (sites whose articles count as this source), "terms" (one line),
   "gap" (seconds between requests, optional), "note", "checked": {...written by `sources check`}}
Edit it by hand (switch "on", add an outlet) or with `bin/monteer sources list|on|off|add|check "<channel>"`.

Every adapter goes through fetch.py (robots incl. Claude-User, spacing, cache, no paywall bypass). An item whose text
may not go to the brain (Claude-User disallowed) is a LEAD ONLY: its headline, outlet and date may point the brain to
the same fact in an allowed source (decision 3a); its text is never read for the brain.
"""
import json
import re
import time
import urllib.parse
from html import unescape
from pathlib import Path

from ..core.io import load_json, save_json, write_text
from . import fetch
from .text import norm

DEFAULT_SOURCES = [
    # ---- finding news (discovery): titles, outlets, dates, links only
    {"id": "gdelt", "on": True, "name": "GDELT", "kind": "discovery", "lang": "multi", "access": "gdelt",
     "url": "https://api.gdeltproject.org/api/v2/doc/doc", "gap": 10,
     "terms": "Free for any use, including commercial, with citation; one request per 5 s; last 3 months.",
     "note": "Only finds articles; only outlets switched on in this list are kept."},
    # ---- Arabic news outlets (feeds + their article pages)
    {"id": "bbc_arabic", "on": True, "name": "بي بي سي عربي", "kind": "news", "lang": "ar", "access": "rss",
     "url": "https://feeds.bbci.co.uk/arabic/rss.xml", "domains": ["bbc.com/arabic", "bbc.co.uk/arabic"],
     "terms": "Feeds offered for syndication; article pages per robots.txt (Claude-User allowed, ClaudeBot not)."},
    {"id": "independent_arabia", "on": True, "name": "اندبندنت عربية", "kind": "news", "lang": "ar", "access": "rss",
     "url": "https://www.independentarabia.com/rss.xml", "domains": ["independentarabia.com"], "gap": 10,
     "terms": "Feed + article pages per robots.txt; Crawl-delay 10 s."},
    {"id": "skynews_arabia", "on": True, "name": "سكاي نيوز عربية", "kind": "news", "lang": "ar", "access": "rss",
     "url": "https://www.skynewsarabia.com/rss", "domains": ["skynewsarabia.com"],
     "terms": "Feed + article pages per robots.txt (no AI rules)."},
    {"id": "dw_arabic", "on": True, "name": "DW عربية", "kind": "news", "lang": "ar", "access": "rss",
     "url": "https://rss.dw.com/rdf/rss-ar-all", "domains": ["dw.com/ar"],
     "terms": "Feed + article pages per robots.txt (Claude-User allowed, ClaudeBot not)."},
    {"id": "youm7", "on": True, "name": "اليوم السابع", "kind": "news", "lang": "ar", "access": "rss",
     "url": "https://www.youm7.com/rss/SectionRss?SectionID=297", "domains": ["youm7.com"],
     "terms": "Feed + article pages per robots.txt (article paths open to Claude-User)."},
    {"id": "shorouk", "on": True, "name": "الشروق", "kind": "news", "lang": "ar", "access": "rss",
     "url": "https://www.shorouknews.com/Economy/rss", "domains": ["shorouknews.com"],
     "terms": "Feed + article pages per robots.txt (no AI rules)."},
    {"id": "masrawy", "on": True, "name": "مصراوي", "kind": "news", "lang": "ar", "access": "rss",
     "url": "https://www.masrawy.com/rss/feed/25/economy", "domains": ["masrawy.com"],
     "terms": "Feed + article pages per robots.txt (no AI rules)."},
    {"id": "alborsa", "on": True, "name": "جريدة البورصة", "kind": "news", "lang": "ar", "access": "rss",
     "url": "https://www.alborsaanews.com/feed", "domains": ["alborsaanews.com"],
     "terms": "Feed + article pages per robots.txt (no AI rules)."},
    # ---- Egyptian outlets indexed by GDELT (report decision 2b, 15 Oct 2026)
    {"id": "almasryalyoum", "on": True, "name": "المصري اليوم", "kind": "news", "lang": "ar", "access": "rss", "url": "https://www.almasryalyoum.com/rss/rssfeed", "domains": ["almasryalyoum.com"], "terms": "Feed + article pages per robots.txt (no AI rules). Added 15 Oct 2026 (report decision 2b: indexed by GDELT)."},
    {"id": "elwatan", "on": True, "name": "الوطن", "kind": "news", "lang": "ar", "access": "domain", "url": "https://www.elwatannews.com/", "domains": ["elwatannews.com"], "terms": "robots.txt allows everything. Added 15 Oct 2026 (report decision 2b).", "note": "No feed found (/rss, /feed answer 404): its articles come in through GDELT."},
    {"id": "dostor", "on": True, "name": "الدستور", "kind": "news", "lang": "ar", "access": "rss", "url": "https://www.dostor.org/rss", "domains": ["dostor.org"], "terms": "Feed + article pages per robots.txt (no AI rules). Added 15 Oct 2026 (report decision 2b)."},
    {"id": "vetogate", "on": True, "name": "فيتو", "kind": "news", "lang": "ar", "access": "rss", "url": "https://www.vetogate.com/rss.aspx", "domains": ["vetogate.com"], "terms": "Feed + article pages per robots.txt (no AI rules). Added 15 Oct 2026 (report decision 2b)."},
    {"id": "elbalad", "on": True, "name": "صدى البلد", "kind": "news", "lang": "ar", "access": "rss", "url": "https://www.elbalad.news/rss.aspx", "domains": ["elbalad.news", "el-balad.com"], "terms": "Feed + article pages per robots.txt (no AI rules). Added 15 Oct 2026 (report decision 2b)."},
    {"id": "egyptindependent", "on": True, "name": "Egypt Independent", "kind": "news", "lang": "en", "access": "rss", "url": "https://www.egyptindependent.com/feed/", "domains": ["egyptindependent.com"], "terms": "Al-Masry Al-Youm's English edition. Feed + article pages per robots.txt. Added 15 Oct 2026 (report decision 2b)."},
    {"id": "france24_ar", "on": True, "name": "فرانس 24", "kind": "news", "lang": "ar", "access": "rss",
     "url": "https://www.france24.com/ar/rss", "domains": ["france24.com"],
     "terms": "robots.txt blocks Claude-User: LEAD ONLY (headline + date), its text never goes to the brain."},
    {"id": "cnbc_arabia", "on": False, "name": "CNBC عربية", "kind": "news", "lang": "ar", "access": "domain",
     "url": "https://www.cnbcarabia.com/", "domains": ["cnbcarabia.com"],
     "terms": "No AI rules in robots.txt.", "note": "No feed found (15 Oct 2026); its articles still count when GDELT finds them, if switched on."},
    {"id": "almal", "on": False, "name": "المال", "kind": "news", "lang": "ar", "access": "domain",
     "url": "https://almalnews.com/", "domains": ["almalnews.com"], "terms": "No AI rules in robots.txt.",
     "note": "Feed address /feed/ answers 404 (15 Oct 2026)."},
    {"id": "asharq_business", "on": False, "name": "الشرق للأعمال", "kind": "news", "lang": "ar", "access": "domain",
     "url": "https://asharqbusiness.com/", "domains": ["asharqbusiness.com"], "terms": "-",
     "note": "Answers 403 to our honest agent (15 Oct 2026): skipped, no workaround."},
    {"id": "aljazeera_net", "on": False, "name": "الجزيرة نت", "kind": "news", "lang": "ar", "access": "domain",
     "url": "https://www.aljazeera.net/", "domains": ["aljazeera.net"], "terms": "-",
     "note": "No connection from this Mac (robots.txt unreachable, 15 Oct 2026)."},
    # ---- other languages
    {"id": "bbc_business", "on": True, "name": "BBC News", "kind": "news", "lang": "en", "access": "rss",
     "url": "https://feeds.bbci.co.uk/news/business/rss.xml", "domains": ["bbc.com/news", "bbc.co.uk/news"],
     "terms": "Feeds offered for syndication; article pages per robots.txt."},
    {"id": "bbc_world", "on": True, "name": "BBC News", "kind": "news", "lang": "en", "access": "rss",
     "url": "https://feeds.bbci.co.uk/news/world/rss.xml", "domains": ["bbc.com/news", "bbc.co.uk/news"],
     "terms": "Feeds offered for syndication; article pages per robots.txt."},
    {"id": "dw_business", "on": True, "name": "DW", "kind": "news", "lang": "en", "access": "rss",
     "url": "https://rss.dw.com/rdf/rss-en-bus", "domains": ["dw.com/en"], "terms": "Feed + article pages per robots.txt."},
    # ---- official press (primary statements)
    {"id": "fed_press", "on": True, "name": "الاحتياطي الفيدرالي الأمريكي", "kind": "official", "lang": "en", "access": "rss",
     "url": "https://www.federalreserve.gov/feeds/press_all.xml", "domains": ["federalreserve.gov"],
     "terms": "US federal government: public domain."},
    {"id": "ecb_press", "on": True, "name": "البنك المركزي الأوروبي", "kind": "official", "lang": "en", "access": "rss",
     "url": "https://www.ecb.europa.eu/rss/press.html", "domains": ["ecb.europa.eu"],
     "terms": "Free reuse with the source named (ECB copyright notice)."},
    {"id": "imf", "on": False, "name": "صندوق النقد الدولي", "kind": "official", "lang": "en", "access": "domain",
     "url": "https://www.imf.org/", "domains": ["imf.org"],
     "terms": "IMF data: free use with attribution, but commercial reuse needs permission (copyright@imf.org); www.imf.org refuses our agent (16 Oct 2026). Off.",
     "note": "Answers 403 to our agent (15 Oct 2026)."},
    {"id": "cbe", "on": False, "name": "البنك المركزي المصري", "kind": "official", "lang": "ar", "access": "domain",
     "url": "https://www.cbe.org.eg/", "domains": ["cbe.org.eg"],
     "terms": "cbe.org.eg rejects our agent at its firewall, robots.txt included (16 Oct 2026): off. Its own figures (reserves, external debt, its payment schedule) come through the World Bank's Global Economic Monitor and QEDS (worldbank, source 15 / 22)."},
    # ---- economic data (numbers come from the data itself, with the series and its date)
    {"id": "worldbank", "on": True, "name": "البنك الدولي", "kind": "data", "lang": "en", "access": "worldbank",
     "url": "https://api.worldbank.org/v2/", "terms": "CC BY 4.0."},
    {"id": "us_treasury", "on": True, "name": "وزارة الخزانة الأمريكية", "kind": "data", "lang": "en", "access": "treasury",
     "url": "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/", "terms": "US federal: public domain."},
    {"id": "ecb_data", "on": True, "name": "البنك المركزي الأوروبي", "kind": "data", "lang": "en", "access": "ecb",
     "url": "https://data-api.ecb.europa.eu/service/data/", "terms": "Free reuse with the source named."},
    {"id": "eurostat", "on": True, "name": "يوروستات", "kind": "data", "lang": "en", "access": "eurostat",
     "url": "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/", "terms": "Free reuse with the source named."},
    {"id": "bls", "on": False, "note": "api.bls.gov's robots.txt disallows the API for every agent (15 Oct 2026): off.", "name": "مكتب إحصاءات العمل الأمريكي", "kind": "data", "lang": "en", "access": "bls",
     "url": "https://api.bls.gov/publicAPI/v1/timeseries/data/", "terms": "US federal: public domain; 25 queries a day without a key."},
    {"id": "oecd", "on": False, "name": "OECD", "kind": "data", "lang": "en", "access": "domain",
     "url": "https://sdmx.oecd.org/public/rest/", "domains": ["oecd.org"], "terms": "CC BY 4.0.",
     "note": "Reachable, but its query language needs an adapter not built yet."},
    # ---- legal (primary texts first)
    {"id": "federal_register", "on": True, "name": "السجل الفيدرالي الأمريكي", "kind": "legal", "lang": "en",
     "access": "federal_register", "url": "https://www.federalregister.gov/api/v1/", "domains": ["federalregister.gov"],
     "terms": "US federal: public domain."},
    {"id": "pravo_ru", "on": True, "name": "البوابة الرسمية للتشريعات الروسية", "kind": "legal", "lang": "ru", "access": "domain",
     "url": "http://publication.pravo.gov.ru/", "domains": ["publication.pravo.gov.ru", "pravo.gov.ru"],
     "terms": "Official publication; counts when Wikipedia's references lead to it."},
    {"id": "eurlex", "on": False, "name": "EUR-Lex", "kind": "legal", "lang": "en", "access": "domain",
     "url": "https://eur-lex.europa.eu/", "domains": ["eur-lex.europa.eu"], "terms": "Free reuse (Decision 2011/833/EU).",
     "note": "The search page answers 202 (a bot check): off; no workaround."},
    # ---- reference
    {"id": "wikipedia", "on": True, "name": "ويكيبيديا", "kind": "reference", "lang": "multi", "access": "wikipedia",
     "url": "https://{lang}.wikipedia.org/wiki/", "terms": "CC BY-SA: LEADS ONLY (decision 5a). Its references are followed and cited; its text is never used."},
    {"id": "wikidata", "on": True, "name": "ويكي بيانات", "kind": "reference", "lang": "multi", "access": "wikidata",
     "url": "https://www.wikidata.org/wiki/Special:EntityData/", "terms": "CC0: may be cited for dates, names and places."},
]

KIND_AR = {"news": "خبر", "official": "بيان رسمي", "data": "بيانات", "legal": "نص قانوني", "reference": "مرجع"}


# ------------------------------------------------------------------------------------------------ the list
def list_path(channel):
    return Path(channel) / "sources.json"


def load(channel):
    p = list_path(channel)
    if not p.exists():
        raise SystemExit(f"مفيش قايمة مصادر في {p}: اعملها بالأمر bin/monteer sources init \"{channel}\"")
    return load_json(p)


def save(channel, srcs):
    save_json(list_path(channel), srcs)


def init(channel):
    p = list_path(channel)
    if p.exists():
        return f"kept the existing {p}"
    save(channel, DEFAULT_SOURCES)
    return f"wrote {p} ({len(DEFAULT_SOURCES)} sources)"


def by_url(srcs, url):
    """the source whose domains cover this URL (longest match), or None"""
    u = re.sub(r"^https?://(www\.)?", "", url.lower())
    best = None
    for s in srcs:
        for d in s.get("domains", []):
            d2 = re.sub(r"^www\.", "", d.lower())
            if u.startswith(d2) and (best is None or len(d2) > best[0]):
                best = (len(d2), s)
    return best[1] if best else None


def domain_name(url):
    return re.sub(r"^www\.", "", fetch.host_of(url))


# ------------------------------------------------------------------------------------------------ helpers
def strip_html(s):
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


AR_MONTHS = {"يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4, "إبريل": 4, "مايو": 5, "يونيو": 6, "يوليو": 7,
             "أغسطس": 8, "اغسطس": 8, "سبتمبر": 9, "أكتوبر": 10, "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12,
             "كانون الثاني": 1, "شباط": 2, "آذار": 3, "نيسان": 4, "أيار": 5, "حزيران": 6, "تموز": 7, "آب": 8, "أيلول": 9,
             "تشرين الأول": 10, "تشرين الثاني": 11, "كانون الأول": 12}


def feed_date(e):
    for k in ("published_parsed", "updated_parsed"):
        if e.get(k):
            return time.strftime("%Y-%m-%d", e[k])
    raw = e.get("published") or e.get("updated") or e.get("dc_date") or ""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return m.group(0)
    m = re.search(r"(\d{1,2})\s+(" + "|".join(sorted(AR_MONTHS, key=len, reverse=True)) + r")\s+(\d{4})", raw)
    if m:
        return f"{m.group(3)}-{AR_MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", raw)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return ""


def matches(text, terms):
    """the text mentions one of the terms (every word of the term, normalised)"""
    t = " " + norm(text) + " "
    for term in terms:
        ws = norm(term).split()
        if ws and all((" " + w) in t or (" ال" + w) in t for w in ws):
            return True
    return False


# ------------------------------------------------------------------------------------------------ adapters: finding
def rss_items(src, terms):
    import feedparser
    r = fetch.get(src["url"], max_age=3600, gap=src.get("gap"))
    if not r["ok"]:
        return [], f"feed not fetched ({r.get('code')}: {r.get('why') or r.get('error')})"
    f = feedparser.parse(r["body"])
    out = []
    for e in f.entries:
        title, summ = strip_html(e.get("title", "")), strip_html(e.get("summary", ""))[:600]
        if terms and not matches(title + " " + summ, terms):
            continue
        link = e.get("link", "")
        perm = fetch.permissions(link) if link else {"fetch": False, "brain": False, "why": "no link"}
        out.append({"kind": src["kind"], "source_id": src["id"], "outlet": src["name"], "title": title, "date": feed_date(e),
                    "url": link, "lang": src["lang"], "summary": summ if perm["brain"] and r["brain"] else "",
                    "lead_only": not perm["brain"], "lead_why": perm["why"], "how": f"feed {src['url']}"})
    return out, f"{len(f.entries)} entries, {len(out)} match"


def gdelt_items(src, terms_by_lang, since_days, srcs):
    """GDELT DOC 2.0 article list, kept only for outlets switched on in the list"""
    news = [s for s in srcs if s.get("on") and s["kind"] in ("news", "official") and s.get("domains")]
    doms = sorted({re.sub(r"/.*$", "", re.sub(r"^www\.", "", d)) for s in news for d in s["domains"]})
    langs = {"ar": "arabic", "en": "english", "fr": "french", "ru": "russian", "de": "german", "es": "spanish"}
    span = f"{min(max(int(since_days or 30), 1), 90)}d"
    out, notes = [], []
    # GDELT searches every language through its English translation: English terms work for Arabic articles too
    # (tested 15 Oct 2026: Arabic keywords found nothing; English keywords with sourcelang:arabic found Arabic articles)
    en_terms = [t for t in terms_by_lang.get("en", []) if t.strip()][:5]
    for lang in [l for l in terms_by_lang if l in langs] or ["en"]:
        terms = en_terms
        if not terms:
            continue
        q0 = "(" + " OR ".join(f'"{t}"' if " " in t else t for t in terms) + ")" if len(terms) > 1 else (f'"{terms[0]}"' if " " in terms[0] else terms[0])
        q0 += f" sourcelang:{langs[lang]}"
        batches, cur = [], []
        for d in doms:              # GDELT refuses queries over about 250 characters: the outlets go in batches
            if cur and len(q0) + len(" (" + " OR ".join(f"domain:{x}" for x in cur + [d]) + ")") > 240:
                batches.append(cur)
                cur = []
            cur.append(d)
        if cur:
            batches.append(cur)
        found = kept = 0
        for b in batches:
            q = q0 + (" (" + " OR ".join(f"domain:{d}" for d in b) + ")" if len(b) > 1 else f" domain:{b[0]}")
            url = src["url"] + "?" + urllib.parse.urlencode({"query": q, "mode": "artlist", "maxrecords": 75, "format": "json",
                                                             "timespan": span, "sort": "hybridrel"})
            r = fetch.get_json(url, max_age=24 * 3600, gap=src.get("gap", 10))
            if not r["ok"]:
                body = (r.get("body") or b"")[:80].decode("utf-8", "replace").strip()
                notes.append(f"{lang} {b[0]}…: not answered ({r.get('code')} {r.get('error') or ''} {body})")
                continue
            arts = r["json"].get("articles", [])
            found += len(arts)
            for a in arts:
                s = by_url(srcs, a.get("url", ""))
                if not s or not s.get("on"):
                    continue
                perm = fetch.permissions(a["url"])
                d = a.get("seendate", "")
                out.append({"kind": s["kind"], "source_id": s["id"], "outlet": s["name"], "title": a.get("title", ""),
                            "date": f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) >= 8 else "", "url": a["url"], "lang": lang, "summary": "",
                            "lead_only": not perm["brain"], "lead_why": perm["why"], "how": "GDELT"})
                kept += 1
        notes.append(f"{lang}: {len(batches)} queries, {found} found, {kept} from outlets on the list")
    return out, "; ".join(notes)


MAX_REFS = 40                     # references kept per Wikipedia page (leads only)


def wikipedia_leads(src, lead, srcs):
    """a Wikipedia page's references, as leads to citable sources (its own text is never used: decision 5a)"""
    lang, title = lead.get("lang", "en"), lead["title"]
    url = f"https://{lang}.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
    r = fetch.get(url, max_age=7 * 24 * 3600)
    if not r["ok"]:
        return [], None, f"{title}: not fetched ({r.get('code')} {r.get('why') or r.get('error')})"
    html = r["body"].decode("utf-8", "replace")
    qid = (re.search(r'"wgWikibaseItemId":"(Q\d+)"', html) or [None, None])[1]
    out = []
    for li in re.findall(r'<li[^>]*\bid="cite_note-[^"]*"[^>]*>(.*?)</li>', html, re.S):
        links = [re.search(r'href="([^"]+)"', a).group(1) for a in re.findall(r'<a\b[^>]*>', li)
                 if 'class="external' in a and 'href="' in a]
        links = [unescape(u) for u in links if u.startswith("http") and "archive.org" not in u and "wikipedia.org" not in u
                 and "doi.org" not in u and "worldcat" not in u and "jstor.org" not in u and "books.google" not in u]
        if not links:
            continue
        cite = strip_html(li)[:300]
        u = links[0]
        from .fetch import held
        if held(u):                      # a site the owner holds off (fetch.HELD): not even listed
            continue
        s = by_url(srcs, u)
        # robots.txt is checked when a reference is chosen and read (step read), not here: a page can list hundreds of
        # sites, and checking each one's robots.txt made gathering take half an hour (15 Oct 2026)
        out.append({"kind": s["kind"] if s else "reference", "source_id": s["id"] if s else "wikipedia_ref",
                    "outlet": s["name"] if s else domain_name(u), "title": cite, "date": "", "url": u, "lang": lang,
                    "summary": "", "lead_only": False, "robots": "checked when read",
                    "how": f"reference in Wikipedia «{title}» ({lang})", "off_list": not (s and s.get("on"))})
        if len(out) >= MAX_REFS:
            break
    return out, qid, f"{title}: {len(out)} references with a link"


WD_PROPS = {"P571": "inception", "P580": "start time", "P582": "end time", "P585": "point in time", "P569": "date of birth",
            "P570": "date of death", "P576": "dissolved", "P577": "publication date", "P1082": "population",
            "P2131": "nominal GDP", "P1619": "date of official opening"}


def wikidata_text(qid):
    """a Wikidata item's labels and its dates/quantities as text (CC0, may be cited)"""
    url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
    r = fetch.get_json(url, max_age=7 * 24 * 3600)
    if not r["ok"]:
        return None, url, f"{qid}: not fetched ({r.get('code')} {r.get('why') or r.get('error')})"
    e = r["json"]["entities"].get(qid) or next(iter(r["json"]["entities"].values()))
    lab = lambda d, l: (d.get(l) or {}).get("value", "")  # noqa: E731
    lines = [f"Wikidata {qid}", f"label (ar): {lab(e.get('labels', {}), 'ar')}", f"label (en): {lab(e.get('labels', {}), 'en')}",
             f"description (en): {lab(e.get('descriptions', {}), 'en')}"]
    for p, name in WD_PROPS.items():
        for c in e.get("claims", {}).get(p, [])[:5]:
            v = c.get("mainsnak", {}).get("datavalue", {}).get("value")
            if isinstance(v, dict) and "time" in v:
                t = v["time"].lstrip("+")
                prec = v.get("precision", 11)
                t = t[:4] if prec <= 9 else (t[:7] if prec == 10 else t[:10])
                lines.append(f"{name} ({p}): {t}")
            elif isinstance(v, dict) and "amount" in v:
                lines.append(f"{name} ({p}): {v['amount'].lstrip('+')}")
    return "\n".join(lines), url, f"{qid}: {len(lines) - 4} dated or numeric statements"


# ------------------------------------------------------------------------------------------------ adapters: data
def _fmt(v):
    if v is None:
        return "-"
    if isinstance(v, (int, float)):
        return f"{v:.6g}" if abs(v) < 1e6 else f"{v:,.0f}"
    return str(v)


WB_SOURCES = {15: "Global Economic Monitor (monthly)", 22: "Quarterly External Debt Statistics (SDDS)", 6: "International Debt Statistics"}


def worldbank(req):
    """World Bank data (CC BY 4.0). source (optional): 15 = Global Economic Monitor (monthly reserves, exchange rates, prices:
    e.g. TOTRESV, DPANUSLCU), 22 = Quarterly External Debt Statistics, the figures each country's central bank reports
    (e.g. DT.DOD.DECT.CD.AR.EN.US, the gross external debt position; the "Gross Ext. Debt Pmt" series are the payment
    schedule by horizon). Owner's decision 3a of 16 Oct 2026: Egypt's figures come from the World Bank directly (CEIC off
    for good; cbe.org.eg refuses our agent; IMF data needs the IMF's permission for commercial reuse)."""
    c, ind = req.get("country", "WLD"), req["indicator"]
    src = req.get("source")
    url = (f"https://api.worldbank.org/v2/country/{urllib.parse.quote(c)}/indicator/{urllib.parse.quote(ind)}?format=json&per_page=100"
           + (f"&source={int(src)}" if src else "")
           + (f"&frequency={req.get('frequency') or 'M'}" if src and int(src) == 15 else (f"&frequency={req['frequency']}" if req.get("frequency") else ""))
           + (f"&date={req['years']}" if req.get("years") else "&mrv=12"))
    r = fetch.get_json(url, max_age=24 * 3600)
    if not r["ok"] or not isinstance(r["json"], list) or len(r["json"]) < 2 or not r["json"][1]:
        return None, url, f"no data ({r.get('code')} {r.get('why') or r.get('error') or ''})"
    rows = r["json"][1]
    name, cname = rows[0]["indicator"]["value"].rstrip(","), rows[0]["country"]["value"]
    lines = [f"World Bank{' — ' + WB_SOURCES.get(int(src), '') if src else ''} — {name} ({ind}) — {cname}"] + [f"{x['date']}: {_fmt(x['value'])}" for x in rows if x["value"] is not None]
    return "\n".join(lines), url, f"{len(lines) - 1} values"


def treasury(req):
    ep = req.get("endpoint", "v2/accounting/od/debt_to_penny").strip("/")
    q = {"sort": req.get("sort", "-record_date"), "page[size]": str(req.get("rows", 12))}
    if req.get("fields"):
        q["fields"] = req["fields"]
    if req.get("filter"):
        q["filter"] = req["filter"]
    url = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/" + ep + "?" + urllib.parse.urlencode(q)
    r = fetch.get_json(url, max_age=24 * 3600)
    if not r["ok"] or not r.get("json", {}).get("data"):
        return None, url, f"no data ({r.get('code')} {r.get('why') or r.get('error') or ''})"
    rows = r["json"]["data"]
    labels = r["json"].get("meta", {}).get("labels", {})
    lines = [f"US Treasury Fiscal Data — {ep}"] + ["; ".join(f"{labels.get(k, k)}: {v}" for k, v in row.items()) for row in rows]
    return "\n".join(lines), url, f"{len(rows)} rows"


def ecb(req):
    url = (f"https://data-api.ecb.europa.eu/service/data/{req['flow']}/{req['key']}?format=jsondata"
           f"&lastNObservations={int(req.get('last', 12))}")
    r = fetch.get_json(url, max_age=24 * 3600)
    if not r["ok"]:
        return None, url, f"no data ({r.get('code')} {r.get('why') or r.get('error') or ''})"
    j = r["json"]
    try:
        series = next(iter(j["dataSets"][0]["series"].values()))
        times = j["structure"]["dimensions"]["observation"][0]["values"]
        title = next((a["values"][0]["name"] for a in j["structure"]["attributes"]["series"] if a["id"] == "TITLE" and a["values"]), req["key"])
    except (KeyError, IndexError, StopIteration):
        return None, url, "unexpected answer"
    lines = [f"ECB Data Portal — {title} ({req['flow']}.{req['key']})"]
    for k, v in sorted(series["observations"].items(), key=lambda kv: int(kv[0])):
        lines.append(f"{times[int(k)]['id']}: {_fmt(v[0])}")
    return "\n".join(lines), url, f"{len(lines) - 1} values"


def eurostat(req):
    q = dict(req.get("filters", {}))
    q["lastTimePeriod"] = str(int(req.get("last", 12)))
    url = f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{req['dataset']}?" + urllib.parse.urlencode(q)
    r = fetch.get_json(url, max_age=24 * 3600)
    if not r["ok"] or "value" not in r["json"]:
        return None, url, f"no data ({r.get('code')} {r.get('why') or r.get('error') or ''})"
    j = r["json"]
    tdim = j["dimension"]["time"]["category"]["index"]
    inv = {v: k for k, v in tdim.items()}
    sizes = j["size"]
    stride = 1
    for s in sizes[j["id"].index("time") + 1:]:
        stride *= s
    lines = [f"Eurostat — {j.get('label', req['dataset'])} — {q}"]
    for k, v in sorted(j["value"].items(), key=lambda kv: int(kv[0])):
        lines.append(f"{inv.get((int(k) // stride) % len(tdim), '?')}: {_fmt(v)}")
    return "\n".join(lines), url, f"{len(lines) - 1} values"


def bls(req):
    url = f"https://api.bls.gov/publicAPI/v1/timeseries/data/{urllib.parse.quote(req['series'])}"
    r = fetch.get_json(url, max_age=24 * 3600)
    if not r["ok"] or r["json"].get("status") != "REQUEST_SUCCEEDED":
        return None, url, f"no data ({r.get('code')} {r.get('why') or r.get('error') or ''} {r.get('json', {}).get('message') if r.get('json') else ''})"
    s = r["json"]["Results"]["series"][0]
    lines = [f"US BLS — series {req['series']}"] + [f"{d['year']} {d['periodName']}: {d['value']}" for d in s["data"][:24]]
    return "\n".join(lines), url, f"{len(lines) - 1} values"


_MONTHS_EN = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august", "september",
                                           "october", "november", "december"], 1)}


def data_period(text):
    """(first, last) period a data text covers, from its rows: "2024: …", "2026-09-04: …", "Record Date: 2026-09-30; …",
    "2026 September: …" (BLS); (None, None) when no row has a period"""
    found = []
    for line in (text or "").splitlines()[1:]:
        m = re.match(r"\s*(?:Record Date:\s*)?(\d{4}(?:-\d{2}(?:-\d{2})?)?)\b", line)
        if m:
            found.append(m.group(1))
            continue
        m = re.match(r"\s*(\d{4}) ([A-Za-z]+):", line)
        if m and m.group(2).lower() in _MONTHS_EN:
            found.append(f"{m.group(1)}-{_MONTHS_EN[m.group(2).lower()]:02d}")
    return (min(found), max(found)) if found else (None, None)


DATA_ADAPTERS = {"worldbank": worldbank, "treasury": treasury, "ecb": ecb, "eurostat": eurostat, "bls": bls}


def federal_register(src, term, since=None):
    q = {"conditions[term]": term, "per_page": "15", "order": "relevance"}
    if since:
        q["conditions[publication_date][gte]"] = since
    url = "https://www.federalregister.gov/api/v1/documents.json?" + urllib.parse.urlencode(q)
    r = fetch.get_json(url, max_age=24 * 3600)
    if not r["ok"]:
        return [], f"not answered ({r.get('code')})"
    out = []
    for d in r["json"].get("results", []):
        u = d.get("html_url", "")
        perm = fetch.permissions(u)
        out.append({"kind": "legal", "source_id": src["id"], "outlet": src["name"], "title": d.get("title", ""),
                    "date": d.get("publication_date", ""), "url": u, "lang": "en", "summary": (d.get("abstract") or "")[:600],
                    "lead_only": not perm["brain"], "lead_why": perm["why"], "how": f"Federal Register search «{term}»",
                    "type": d.get("type", "")})
    return out, f"«{term}»: {len(out)} documents"


# ------------------------------------------------------------------------------------------------ check
def check(channel, log=print):
    """reachability, robots (incl. AI agents), a sample fetch per source; a source that fails is switched off"""
    srcs = load(channel)
    day = time.strftime("%Y-%m-%d")
    rows, changed = [], []
    for s in srcs:
        res, why = "ok", ""
        if not s.get("on"):
            rows.append((s, "off", s.get("note", "")))
            continue
        acc = s["access"]
        try:
            if acc == "rss":
                items, why = rss_items(s, [])
                perm = fetch.permissions(s["url"])
                if not items:
                    res = "FAIL"
                else:
                    a = next((i for i in items if i["url"]), None)
                    pa = fetch.permissions(a["url"]) if a else {"brain": False, "why": "no article link"}
                    lead = "" if pa["brain"] and perm["brain"] else " — LEAD ONLY (" + (pa["why"] or perm["why"]) + ")"
                    why = f"{why}; article pages: fetch {'yes' if pa.get('fetch', True) else 'NO'}, brain {'yes' if pa['brain'] else 'NO'}{lead}"
            elif acc == "gdelt":
                items, why = gdelt_items(s, {"ar": [], "en": ["economy"]}, 3, srcs)
                res = "ok" if re.search(r"[1-9]\d* found", why) else "FAIL"
            elif acc == "wikipedia":
                items, qid, why = wikipedia_leads(s, {"lang": "en", "title": "Bretton Woods system"}, srcs)
                res = "ok" if items else "FAIL"
            elif acc == "wikidata":
                text, _, why = wikidata_text("Q79")
                res = "ok" if text else "FAIL"
            elif acc in DATA_ADAPTERS:
                sample = {"worldbank": {"indicator": "NY.GDP.MKTP.KD.ZG", "country": "EG"},
                          "treasury": {"endpoint": "v2/accounting/od/debt_to_penny", "rows": 2},
                          "ecb": {"flow": "FM", "key": "B.U2.EUR.4F.KR.DFR.LEV", "last": 2},
                          "eurostat": {"dataset": "prc_hicp_manr", "filters": {"geo": "EA", "coicop": "CP00"}, "last": 2},
                          "bls": {"series": "CUUR0000SA0"}}[acc]
                text, _, why = DATA_ADAPTERS[acc](sample)
                res = "ok" if text else "FAIL"
            elif acc == "federal_register":
                items, why = federal_register(s, "tariff")
                res = "ok" if items else "FAIL"
            elif acc == "domain":
                perm = fetch.permissions(s["url"])
                r = fetch.get(s["url"], max_age=24 * 3600)
                res = "ok" if r["ok"] else "FAIL"
                why = f"site {'reachable' if r['ok'] else 'NOT reachable (' + str(r.get('code')) + ' ' + str(r.get('why') or r.get('error')) + ')'}" \
                      + ("" if perm["brain"] else f" — LEAD ONLY ({perm['why']})")
            else:
                res, why = "FAIL", f"unknown access {acc!r}"
        except Exception as e:  # noqa: BLE001  (a broken source must not stop the check of the others)
            res, why = "FAIL", f"{type(e).__name__}: {e}"
        if res == "FAIL" and re.search(r"\b429\b|refused us earlier", why):
            res = "busy"                # "too many requests" is a busy site, not a broken one: it stays on (tried with back-off)
        if res == "FAIL":
            s["on"] = False
            s["note"] = f"switched off by sources check {day}: {why}"
            changed.append(s["id"])
        s["checked"] = {"at": day, "result": res, "detail": why}
        rows.append((s, res, why))
        log(f"{s['id']:20s} {res:5s} {why}")
    save(channel, srcs)
    md = [f"# Sources check — {day}", "", f"Channel: `{channel}`. Every request went through the fetch layer (robots.txt for *,"
          " monteer-research and Claude-User; one request at a time per site; cache; honest agent).", "",
          "| Source | Kind | Access | Result | Detail |", "|---|---|---|---|---|"]
    for s, res, why in rows:
        md.append(f"| {s['name']} (`{s['id']}`) | {s['kind']} | {s['access']} | {res} | {why.replace('|', '/')} |")
    md += ["", f"Switched off by this check: {', '.join(changed) or 'none'}. \"busy\" = the site asked us to slow down (HTTP 429): kept on."]
    write_text(Path(channel) / f"sources_check_{day}.md", "\n".join(md) + "\n")
    return rows, changed

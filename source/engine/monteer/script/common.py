"""Where the script tool keeps things, and small shared helpers.

<project>/script/topic.json            the topic (bin/monteer script new)
<project>/script/research/items.json   everything found: news, official, data, legal, references (+ leads)
<project>/script/research/texts/       the texts read (INTERNAL research record: never published)
<project>/script/facts.json            fact cards, each with its checked passage
<project>/script/outline.json/.md      the outline; outline_ok.json = your yes; outline_notes.json = your edits
<project>/script/drafts/v<N>.json      draft N (lines with type, cards, labels) + v<N>.checks.json
<project>/script/review_v<N>.docx      the review copy (Word, comments in the margin)
<project>/script/sources_v<N>.md       INTERNAL: outlet, date, link and passage of every source
<project>/script/approved.json         who approved, when, the text's fingerprint, the brain used
<project>/script/script.docx           the recording copy -> project.json inputs.script
<project>/script/lines.json, news_items.json, data_series.json   for the montage
"""
import hashlib
import json
import re
import time
from pathlib import Path

from ..core.io import load_json

TYPES = {"archive": "أرشيف", "news": "خبر موثق", "stock": "لقطات عامة", "story": "قصة مصورة", "map": "خريطة", "numbers": "أرقام"}
TYPE_FROM_AR = {v: k for k, v in TYPES.items()} | {"ستوك": "stock", "خبر": "news", "رسم": "story", "ارشيف": "archive"}
TYPE_HELP = {
    "archive": "a past event, year, person or place that real archive footage or photos can show",
    "news": "a recent claim reported by a named outlet or official body (must cite a news or official card: it becomes our newspaper graphic)",
    "stock": "generic footage: everyday scenes, money, factories, streets (at most 40% of lines)",
    "story": "an event told step by step that has no footage (a meeting, a decision, a night attack): drawn or animated",
    "map": "a place matters: countries, straits, cities, routes",
    "numbers": "a number, percentage or amount that is the point of the line: a chart or counter (must cite a number or data card)"}
MIX = {"archive_min": 0.15, "news_min": 0.10, "stock_max": 0.40, "run_max": 3}


def S(p, *parts):
    return p.folder.joinpath("script", *parts)


def topic(p):
    f = S(p, "topic.json")
    if not f.exists():
        raise SystemExit(f"لسه مفيش موضوع: bin/monteer script new \"{p.folder}\" --topic \"...\"")
    return load_json(f)


def channel_dir(p):
    c = p.channel
    if not c or not c.exists():
        raise SystemExit("المشروع مالهوش قناة في project.json (القناة هي اللي فيها قايمة المصادر ودليل الأسلوب)")
    return c


def style_dir(channel):
    return Path(channel) / "style"


def sha(obj):
    data = obj if isinstance(obj, (bytes, str)) else json.dumps(obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()[:16]


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def latest_version(p):
    d = S(p, "drafts")
    vs = [int(m.group(1)) for f in d.glob("v*.json") if (m := re.fullmatch(r"v(\d+)\.json", f.name))] if d.exists() else []
    return max(vs) if vs else 0


def draft(p, v=None):
    v = v or latest_version(p)
    return load_json(S(p, "drafts", f"v{v}.json")) if v else None


def cards(p, only_ok=True):
    f = S(p, "facts.json")
    if not f.exists():
        return []
    cs = load_json(f)["cards"]
    return [c for c in cs if c["status"] == "ok"] if only_ok else cs


def card_brief(c):
    """what the writer may see of a card (never the article text; the passage only for quotes)"""
    when = (c.get("period") or c.get("series_period") or "") if c.get("source_kind") == "data" or c.get("period") else (c.get("pub_date") or "")
    b = {"id": c["id"], "kind": c["kind"], "statement": c["statement"], "outlet": c["outlet"], "date": when,
         "source_kind": c["source_kind"]}
    if c.get("event_date"):
        b["event_date"] = c["event_date"]
    if c["kind"] == "quote":
        b.update(speaker=c.get("speaker", ""), quote_ar=c.get("quote_ar", ""), disputed=bool(c.get("disputed")))
    return b

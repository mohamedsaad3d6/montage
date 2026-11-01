"""The phrase montage, built in code from the phrase plan (montage/phrases.py) and the chosen pictures:
  timeline blocks (montage/timeline.py's format), our graphics scenes (gfx renderer), the sound plan (montage/mix.py),
  transitions on cuts (montage/render.py) and the variety choices for this video.

What it applies (the owner's decisions of 16 Oct 2026, Ramadan's notes, the approved material decisions, rules 18-24):
  - one block per planned shot, from its phrase's first word to the next shot's (timeline.py cuts 2 frames before a word);
  - every on-screen item and every element of our graphics appears ON ITS WORD: 2 frames before the word's start, the
    same lead as a cut (key words for about 2 s, re-hooks up to 5 s, the word montage until its last word);
  - our graphics, designed per video: a map (countries highlighted, each place's pin on its word), a number (on its
    word), steps (boxes appearing one by one as each is said, linked by arrows, lighting up together on a word), a
    headline card (our own newspaper-style typography, the keyword in red at the word-montage spot), the documented-news
    newspaper card (our own design, «المصدر: outlet – date»);
  - the word montage (rule 20): the key word in one fixed spot over several quick shots and the headline cards;
  - the fast intro: a transition on every cut and a low click under each (decision taken alone, 15 Oct); after the intro,
    transitions into graphics, at section changes and on every second footage cut; pops when text appears, a whoosh into
    graphics and sections, music stops before key facts and a hit on them (rules 18, 22);
  - archive photos: about one in two enters with the rule-19 slide and camera sound; archive and history photos get paper
    texture (21); a shot marked in/out pushes in or pulls out, the last shot pulls out (23);
  - no «رسم توضيحي» or similar label on any image (owner's decision, 16 Oct 2026);
  - variety: transition order, newspaper style, key-word colour, music style and fonts differ from the last 3 videos.
"""
import hashlib
import math
import random
import re
import time
from pathlib import Path

from ..core.io import load_json, save_json
from . import maps
from .phrases import Plan

FPS = 24
LEAD = 2 / FPS                    # text and graphic elements appear 2 frames before their word, like a cut
TRANSITIONS = ["zoom", "flash", "slide", "zoomflash"]
PAPER_STYLES = {
    "broadsheet": {"paper": "#EDE5D3", "ink": "#1B1712", "rule": "#8E1F1A", "masthead": "أخبار"},
    "modern": {"paper": "#F4F2EE", "ink": "#12223A", "rule": "#1F4E8C", "masthead": "اليوم"},
    "clipping": {"paper": "#E6DCC4", "ink": "#2A2219", "rule": "#5B4A2E", "masthead": "قصاصة"},
}
KW_COLOURS = ["#E0B04A", "#F06A3A", "#5FB3E6", "#9BD36A"]
# OFL fonts under monteer_data/assets/fonts (setup/tools.json; owner's materials decision 9): one for on-screen text, and one
# for the newspaper that suits its style
TEXT_FONTS = ["Cairo[slnt,wght].ttf", "Tajawal-Bold.ttf", "Almarai-Bold.ttf", "IBMPlexSansArabic-Bold.ttf", "NotoKufiArabic[wght].ttf",
              "ReadexPro[HEXP,wght].ttf"]
NEWS_FONTS = {"broadsheet": ["Amiri-Bold.ttf", "NotoKufiArabic[wght].ttf"], "modern": ["IBMPlexSansArabic-Bold.ttf", "ReadexPro[HEXP,wght].ttf"],
              "clipping": ["Amiri-Bold.ttf", "Almarai-Bold.ttf"]}
CREAM, RED, INK, INK2, CARD = "#F3EBDD", "#D0082A", "#1A1714", "#3A332B", "#1A1510E6"
KW_SPOT = (960, 360)              # the word montage's word: same spot on footage and on headline cards (rule 20)


# ---------------------------------------------------------------------------------------------------- variety
def variety(p, ledger_path):
    """this video's style choices, different from the last 3 videos of the channel (decision 10)"""
    led = load_json(ledger_path) if Path(ledger_path).exists() else {"videos": []}
    last = [v["style"] for v in led["videos"] if v.get("project") != str(p.folder)][-3:]
    rnd = random.Random(int(hashlib.sha256(str(p.folder).encode()).hexdigest()[:8], 16))
    for _ in range(50):
        st = {"transitions": rnd.sample(TRANSITIONS, len(TRANSITIONS)), "paper": rnd.choice(sorted(PAPER_STYLES)),
              "kw_colour": rnd.choice(KW_COLOURS), "music_suffix": rnd.choice(["warm analog", "dark ambient", "cinematic strings", "minimal pulse"]),
              "font": rnd.choice(TEXT_FONTS)}
        st["news_font"] = rnd.choice(NEWS_FONTS[st["paper"]])
        if all((st["paper"] != o.get("paper") or st["kw_colour"] != o.get("kw_colour") or st["transitions"][0] != o.get("transitions", [None])[0])
               and st["font"] != o.get("font") for o in last):
            break
    return st, last


def record_variety(p, ledger_path, style):
    led = load_json(ledger_path) if Path(ledger_path).exists() else {"videos": []}
    led["videos"] = [v for v in led["videos"] if v.get("project") != str(p.folder)] + [
        {"project": str(p.folder), "name": p.name, "style": style, "at": time.strftime("%Y-%m-%d %H:%M:%S")}]
    save_json(ledger_path, led)


# ---------------------------------------------------------------------------------------------------- text helpers
def disp(text):
    """on screen only: a one-letter conjunction glued to a digit («و4%») gets a thin space, or right-to-left layout shows
    it as «%4و» (seen in the renderer, 15 Oct 2026). The words themselves are unchanged."""
    return re.sub(r"(?<![\w])([وبلف])(?=\d)", "\\1\u2009", text or "")


def fix_text(scenes):
    """on-screen text as shown: disp(), and no comma, semicolon or colon left hanging at its end (the first real test showed
    «لقرون طويلة،»)"""
    for sc in scenes:
        for it in sc.get("items", []):
            for k in ("text", "keyword", "label"):
                if isinstance(it.get(k), str):
                    it[k] = disp(it[k]).rstrip(" ،,؛;:")
    return scenes


SCALES = ((1e12, "تريليون", "تريليونات"), (1e9, "مليار", "مليارات"), (1e6, "مليون", "ملايين"), (1e3, "ألف", "آلاف"))


def num_text(v, unit=""):
    """a number as it reads on screen (owner's answer 4a of 19 Oct 2026): «1.2 مليون», «5 آلاف», «250 ألف»; never the
    scientific «1.2e+06» the first real test drew; years and everyday numbers stay as they are («1971», «35», «2.5»)"""
    v = float(v)
    in_unit = any(w in (unit or "") for _, one, few in SCALES for w in (one, few, "الف", "الاف"))
    for size, one, few in SCALES:
        if in_unit or abs(v) < size or (size == 1e3 and (v % 1000 or abs(v) < 3000)):
            continue
        n = v / size
        word = few if n == int(n) and 3 <= abs(n) <= 10 else one
        return f"{n:.2f}".rstrip("0").rstrip(".") + " " + word
    if v == int(v):
        return f"{int(v):,}" if abs(v) >= 1e6 else str(int(v))
    return f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) >= 1e6 else f"{v:g}"


def card_words(phrase, n=7):
    """a word card's text ends where the words end (owner's answer 5a of 19 Oct 2026; the test showed «ولا يطلب الجميع سحبه
    في»): the whole phrase when it is short, else up to its first comma or stop within n words, else its last n - 2 words
    (they end with the phrase)"""
    ws = phrase.split()
    if len(ws) > n:
        cut = next((i for i, w in enumerate(ws[:n]) if i >= 2 and w[-1:] in "،,؛;.!؟?:"), None)
        ws = ws[:cut + 1] if cut is not None else ws[-(n - 2):]
    return " ".join(ws)


def scene_frames(a, b):
    return int(round((b - a) * FPS))


def scene(name, a, b, items, bg="dark", **kw):
    return {"name": name, "t_in": round(a, 3), "t_out": round(b, 3), "frames": scene_frames(a, b), "bg": bg, "items": items, **kw}


def T(text, x, y, t0, size=90, weight=900, color=CREAM, pop=True, **kw):
    d = {"type": "text", "text": text, "x": x, "y": y, "t0": round(max(0.0, t0), 3), "size": size, "weight": weight, "color": color}
    if pop:
        d["pop"] = True
    d.update(kw)
    return d


def R(x, y, w, h, color, t0=0.0, **kw):
    d = {"type": "rect", "x": x, "y": y, "w": w, "h": h, "color": color, "t0": round(max(0.0, t0), 3)}
    d.update(kw)
    return d


def L(x, y, x1, y1, t0, t1, color, width=8):
    return {"type": "line", "x": x, "y": y, "x1": x1, "y1": y1, "t0": round(max(0.0, t0), 3), "t1": round(max(0.0, t1), 3),
            "color": color, "width": width}


# ---------------------------------------------------------------------------------------------------- our graphics
def map_scene(name, a, b, g, style, P):
    from .maps import _load
    iso = set(g.get("countries", []))
    xs, ys = [], []
    for f in _load("50m"):
        if (f["properties"].get("ADM0_A3") or f["properties"].get("ISO_A3")) in iso:
            geo = f["geometry"]
            rings = [q[0] for q in geo["coordinates"]] if geo["type"] == "MultiPolygon" else [geo["coordinates"][0]]
            biggest = max(rings, key=len)
            xs += [pt[0] for pt in biggest]
            ys += [pt[1] for pt in biggest]
    for pl in g.get("places", []):
        xs.append(pl["lon"])
        ys.append(pl["lat"])
    if not xs:
        xs, ys = [25, 45], [15, 35]
    lon0, lon1, lat0, lat1 = min(xs), max(xs), min(ys), max(ys)
    padx, pady = max(4, (lon1 - lon0) * 0.35), max(3, (lat1 - lat0) * 0.35)
    bbox = (lon0 - padx, lat0 - pady, lon1 + padx, lat1 + pady)
    w, h = (bbox[2] - bbox[0]) * 10, (bbox[3] - bbox[1]) * 10
    sc = min(1920 / w, 1080 / h)
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    items = [{"type": "map", "polys": maps.polys(bbox, tol=0.04, turn={c: (style["kw_colour"], 0.3) for c in iso})}]
    for k, pl in enumerate(g.get("places", [])):
        items.append({"type": "pin", "x": round(pl["lon"] * 10, 2), "y": round(-pl["lat"] * 10, 2), "label": pl["name"],
                      "t0": round(max(0.0, P.t(pl["at"]) - LEAD - a), 3), "pop": True, "size": 48, "align": "right" if k % 2 else "left"})
    return scene(name, a, b, items, cam=[maps.cam(0, cx, cy, sc * 0.92), maps.cam(b - a, cx, cy, sc * 1.0)])


def number_scene(name, a, b, g, style, P):
    t = P.t(g["at"]) - LEAD - a
    big = f"{num_text(g['value'], g.get('unit', ''))} {g.get('unit', '')}".strip()
    items = [T(big, 960, 470, t, size=200, color=style["kw_colour"], shadow=20, w=1700, fit=[110, 1810]),
             L(1160, 600, 760, 600, t + 0.1, t + 0.6, style["kw_colour"], width=6)]
    if g.get("label"):
        items.append(T(g["label"], 960, 690, t + 0.2, size=64, weight=700, w=1500))
    return scene(name, a, b, items)


def steps_scene(name, a, b, g, style, P):
    """a row of boxes (right to left) appearing as each is said, linked by arrows; all light up red on all_at (5b's chain)"""
    its = g.get("items", [])
    n = len(its)
    w, h, gap = (420, 190, 70) if n <= 3 else (330, 170, 50)
    w = min(w, (1640 - (n - 1) * gap) / max(n, 1))   # five or more boxes stay inside the frame (the test's steps ran to 85 px)
    total = n * w + (n - 1) * gap
    x_right = 960 + total / 2
    y = 560 if g.get("title") else 520
    gold = style["kw_colour"]
    out = []
    if g.get("title"):
        out.append(T(g["title"]["text"], 960, 250, P.t(g["title"]["at"]) - LEAD - a, size=120, color=gold, shadow=18, w=1600))
    lit = P.t(g["all_at"]) - LEAD - a if g.get("all_at") is not None else None
    for i, it in enumerate(its):
        at = P.t(it["at"]) - LEAD - a
        x1 = x_right - i * (w + gap)
        out.append(R(x1 - w, y - h / 2, w, h, CARD, at, radius=28, color2=gold, width=3, pop=True))
        if lit is not None:
            out.append(R(x1 - w, y - h / 2, w, h, "#D0082A40", lit + 0.15 * i, radius=28, color2=RED, width=5, pop=True))
        out.append(T(it["text"], x1 - w / 2, y, at, size=64 if n <= 3 else 54, w=w - 50))
        if i > 0:
            out.append(L(x1 + gap - 8, y, x1 + 8, y, at - 0.25, at, gold, width=6))
    return scene(name, a, b, out)


def kw_size(text, keyword, size=160, half=800, per_char=0.58):
    """the keyword stays at KW_SPOT (rule 20), so the words on its longer side decide the size: each side must fit in
    `half` px (inside the title-safe area); per_char is a Tajawal/Cairo Black character's width as a share of the size,
    measured on v12's card (an over-long headline ran off the left edge at 160)"""
    ws = text.split()
    k = next((i for i, w in enumerate(ws) if w == keyword or keyword in w), 0)
    side = max(len(" ".join(ws[:k])), len(" ".join(ws[k + 1:]))) + 1
    need = (len(ws[k]) / 2 + side) * per_char
    return int(max(60, min(size, half / max(need, 1e-6))))


def headline_scene(name, a, b, g, style, paper_png):
    """our own newspaper-style card (no outlet name, logo or design): the headline with its keyword in red at KW_SPOT"""
    items = [R(140, 112, 1640, 9, INK), R(140, 130, 1640, 2, INK), R(1500, 160, 280, 12, "#8A7F70", radius=3),
             R(140, 160, 180, 12, "#8A7F70", radius=3)]
    if g.get("keyword"):
        items.append({"type": "kwtext", "text": g["headline"], "keyword": g["keyword"], "x": KW_SPOT[0], "y": KW_SPOT[1],
                      "size": kw_size(g["headline"], g["keyword"]), "weight": 900, "color": INK, "color2": "#9E1B1B", "t0": 0.0,
                      "fit": [160, 1760], "minsize": 72})      # inside the card's rules (owner's answer 4a of 19 Oct 2026)
    else:
        items.append(T(g["headline"], KW_SPOT[0], KW_SPOT[1], 0.0, size=150, color=INK, pop=False, w=1600, minsize=72, fit=[160, 1760]))
    items.append(R(140, 488, 1640, 2, INK))
    if g.get("line"):
        items.append(T(g["line"], 1780, 545, 0.15, size=50, weight=700, color=INK2, pop=False, align="right", w=1620))
    yy = 610
    while yy < 990:                       # column text as grey bars (not real words)
        for x0, x1 in ((140, 510), (560, 930), (980, 1350), (1410, 1780)):
            ww = (x1 - x0) * (0.55 + 0.45 * ((yy * 7 + x0) % 11) / 10)
            items.append(R(x1 - ww, yy, ww, 11, "#B9AE98", radius=3))
        yy += 30
    items.append(R(140, 1010, 1640, 2, INK))
    return scene(name, a, b, items, bg="image", bgpath=str(paper_png))


def news_scene(name, a, b, item, style_name, paper_png):
    st = PAPER_STYLES[style_name]
    W, H, X0, Y0 = 1240, 860, 340, 110
    items = [{"type": "image", "path": str(paper_png), "x": 960, "y": 540, "h": H, "from": 1.0, "to": 1.035, "plain": False, "shadow": 60},
             {"type": "rect", "x": X0, "y": Y0, "w": W, "h": H, "color": st["paper"] + "CC", "t0": 0.0},
             {"type": "text", "text": st["masthead"], "x": 960, "y": Y0 + 90, "size": 92, "weight": 900, "color": st["ink"], "t0": 0.0, "slide": 0},
             {"type": "line", "x": X0 + 60, "y": Y0 + 160, "x1": X0 + W - 60, "y1": Y0 + 160, "color": st["rule"], "width": 5, "t0": 0.05, "t1": 0.35},
             {"type": "line", "x": X0 + 60, "y": Y0 + 172, "x1": X0 + W - 60, "y1": Y0 + 172, "color": st["ink"], "width": 2, "t0": 0.1, "t1": 0.4},
             ] + headline_lines(item.get("headline", ""), Y0, W, st["ink"]) + [
             {"type": "line", "x": X0 + 160, "y": Y0 + 470, "x1": X0 + W - 160, "y1": Y0 + 470, "color": "#F2C744", "width": 22,
              "alpha": 0.55, "t0": 0.9, "t1": 1.6},
             {"type": "text", "text": item.get("context", ""), "x": 960, "y": Y0 + 570, "size": 50, "weight": 500, "color": st["ink"],
              "t0": 0.7, "w": W - 160},
             {"type": "text", "text": item.get("source_line", ""), "x": X0 + W - 70, "y": Y0 + H - 60, "size": 34, "weight": 600,
              "color": st["ink"], "align": "right", "t0": 0.9}]
    return scene(name, a, b, items)


def headline_lines(text, Y0, W, ink):
    """a headline on one line, or two balanced lines when it is long (it stays large instead of shrinking)"""
    ws = text.split()
    if len(text) <= 30 or len(ws) < 4:
        rows = [text]
    else:
        best = min(range(1, len(ws)), key=lambda k: abs(len(" ".join(ws[:k])) - len(" ".join(ws[k:]))))
        rows = [" ".join(ws[:best]), " ".join(ws[best:])]
    y0 = Y0 + (330 if len(rows) == 1 else 285)
    return [{"type": "text", "text": r, "x": 960, "y": y0 + 105 * k, "size": 92, "weight": 900, "color": ink, "t0": 0.35 + 0.1 * k,
             "w": W - 140} for k, r in enumerate(rows)]


def card_scene(name, a, b, text):
    return scene(name, a, b, [T(text, 960, 540, 0.1, size=96, w=1600, minsize=64, fit=[160, 1760])])


# ---------------------------------------------------------------------------------------------------- on-screen overlays
def overlay_kw(name, a, b, text, colour, y=900):
    """a key word in a dark band (y = the band's centre; raised in an intro that has running subtitles at the bottom)"""
    return scene(name, a, b, [R(0, y - 100, 1920, 200, "#0B090799", 0.0),
                              {"type": "kwtext", "text": text, "keyword": text, "x": 960, "y": y, "size": 86, "weight": 900,
                               "color": CREAM, "color2": colour, "t0": 0.0, "pop": True, "shadow": 18, "fit": [96, 1824],
                               "minsize": 56}], bg="none")


def overlay_rehook(name, a, b, text):
    return scene(name, a, b, [R(160, 380, 1600, 320, "#0B0907D9", 0.0, radius=24, pop=True),
                              T(text, 960, 540, 0.05, size=88, w=1450)], bg="none")


def overlay_montage(name, a, b, text, colour):
    return scene(name, a, b, [R(KW_SPOT[0] - 300, KW_SPOT[1] - 125, 600, 250, "#0B0907B8", 0.0, radius=34),
                              T(text, KW_SPOT[0], KW_SPOT[1], 0.0, size=176, color=colour, pop=False)], bg="none")


# ---------------------------------------------------------------------------------------------------- the whole build
FRAMED_BOX = (210, 90, 1710, 990)      # اقتصاد احمس audio only (6A): a framed photo fills most of the frame


def popup_map(p, name, a, b, g):
    """a map of exactly one country and no places, as اقتصاد احمس's pop-up map (montage/steps_popups.py map_png: its
    outline filled with its flag when there is one, else a flat blue), full frame on a dark ground; None otherwise"""
    if g.get("kind") != "map" or len(g.get("countries") or []) != 1 or g.get("places"):
        return None
    from . import steps_popups as POP
    from .sources import Ledger
    iso, led = g["countries"][0], Ledger(p)
    try:
        png = POP.map_png(p, iso, led, flag=POP.flag_png(p, iso, led))
    except StopIteration:                  # a code the map data does not know: our own map graphic instead
        return None
    sc = POP.popup_scene(name, a, b, "map", png, (360, 140, 1560, 940))
    sc["bg"] = "dark"
    return sc


def build(p, plan_d, words, L, picks, news_items, style, paper_png):
    """-> (timeline decision, scenes, sound plan, transitions {cut time: kind}, report)"""
    P = Plan(plan_d, words, L)
    shots = plan_d["shots"]
    gids = {g["id"]: g for g in plan_d.get("graphics", [])}
    news = {n["id"]: n for n in news_items}
    from .structure import of as structure_of
    S = structure_of(p)
    slow_zoom = S.slow_zoom
    from .subtitles import config as subtitles_config
    subs_on = bool(subtitles_config(p))
    from . import general as GEN
    bar_on = GEN.bar_on(p)
    t_intro = P.intro_end_s if S.fast_open is not None else 0.0
    from .phrases import cold_open_end
    t_cold = cold_open_end(P, S)           # الحدث الأخير without a presenter (3A): the cold open's end, else None
    from .phrases import bw_open_end
    t_bw = bw_open_end(P, S)               # اقتصاد احمس without a presenter (6A): the black-and-white open's end, else None
    scenes, blocks, overlays, paper_photos, anchors = [], [], [], [], []
    stops, hits, pops, whoosh_extra = [], [], [], []
    trans, report = {}, {"intro_end_s": round(t_intro, 2), "shots": len(shots), "by_type": {}, "fallbacks": []}
    # our graphics: one scene each, from the first shot that shows it to the last (it keeps building in between)
    span = {}
    for k, s in enumerate(shots):
        if s["type"] == "graphic":
            a, b = P.span(k)
            lo, hi = span.get(s["graphic"], (a, b))
            span[s["graphic"]] = (min(lo, a), max(hi, b))
    for gid, (a, b) in span.items():
        g, a = gids[gid], max(0.0, a - 0.1)
        name = f"g_{gid}"
        pm = popup_map(p, name, a, b, g) if S.popup_maps else None
        if pm:                                     # اقتصاد احمس audio only (6A): the channel's own country map, full frame
            sc, els = pm, []
        elif g["kind"] == "map":
            sc = map_scene(name, a, b, g, style, P)
            els = [(pl["name"], pl["at"]) for pl in g.get("places", [])]
        elif g["kind"] == "number":
            sc = number_scene(name, a, b, g, style, P)
            els = [(num_text(g["value"], g.get("unit", "")), g["at"])]
        elif g["kind"] == "steps":
            sc = steps_scene(name, a, b, g, style, P)
            els = [(it["text"], it["at"]) for it in ([g["title"]] if g.get("title") else []) + g.get("items", [])]
        else:
            sc = headline_scene(name, a, b, g, style, paper_png)
            els = []
        scenes.append(sc)
        for text, at in els:
            anchors.append({"scene": name, "text": text, "word_s": round(P.t(at), 3), "shown_s": round(P.t(at) - LEAD, 3), "kind": "graphic"})
            pops.append([text.split()[0], round(P.t(at), 2)])
    photo_n = 0
    seen_g = set()
    last_type = None
    for k, s in enumerate(shots):
        a, b = P.span(k)
        typ = s["type"]
        in_intro = a < t_intro - 0.05
        report["by_type"][typ] = report["by_type"].get(typ, 0) + 1
        if typ == "graphic":
            name = f"g_{s['graphic']}"
            blocks.append(["G", name, a, b])
            if name not in seen_g:
                seen_g.add(name)
                trans[round(a, 3)] = "zoom"
                if not in_intro:
                    whoosh_extra.append([round(a, 2), f"into {name}"])
            last_type = typ
            continue
        if typ == "news" and s.get("news_item") in news:
            name = f"news_{k}"
            from . import news as NEWS     # channel profiles: the real screenshot, no card, no «المصدر» (montage/news.py)
            shot_sc = NEWS.scene(p, name, a, b, s["news_item"]) if NEWS.mode(p) else None
            scenes.append(shot_sc or news_scene(name, a, b, news[s["news_item"]], style["paper"], paper_png))
            blocks.append(["G", name, a, b])
            trans[round(a, 3)] = "zoom"
            whoosh_extra.append([round(a, 2), "into the newspaper card"])
            last_type = typ
            continue
        code = picks.get(k)
        if not code:
            report["fallbacks"].append(f"shot {k} ({typ}): no usable picture; a card of the words said")
            name = f"card_{k}"
            scenes.append(card_scene(name, a, b, card_words(s.get("phrase", "")) or words[s["from"]]["w"]))
            blocks.append(["G", name, a, b])
            last_type = "card"
            continue
        kind, key = code.split(":", 1)
        if kind == "P":
            photo_n += 1
            if typ == "archive" and photo_n % 2 == 1 and not S.photos_framed:
                code = f"PE:{key}"                        # rule 19: about one archive photo in two enters
            if s.get("history") or typ == "archive":
                paper_photos.append(key)
        mod = s.get("motion") or ("out" if k == len(shots) - 1 else "")
        if not mod and slow_zoom:                     # the channel's slow pace: every footage shot moves (pace.slow_zoom)
            mod = "in" if k % 2 == 0 else "out"
        if mod and not code.startswith(("PE", "AE")):
            code += "|" + mod
        if S.photos_framed and kind == "P":          # 6A: the channel's framed photo with its striped reveal
            from .steps_popups import popup_scene
            scenes.append(popup_scene(f"framed_{k}", a, b, "photo", p.asset_dir("photos") / f"{key}.jpg", FRAMED_BOX))
            code += f"|framed_{k}"
        if t_bw is not None and a < t_bw - 0.05:     # 6A: the black-and-white open
            code += "|bw"
        blocks.append(["F", [code], a, b, round(b - a + 1.0, 3)])
        calm = S.calm_body and t_cold is not None and a >= t_cold - 0.05      # the calm body after the cold open (9A)
        if k and not in_intro and not S.few_transitions and not calm and (k % 2 == 0 or typ != last_type):
            trans.setdefault(round(a, 3), style["transitions"][k % len(style["transitions"])])
        last_type = typ
    # on-screen items, each on its word; a key word leaves with its own shot (when 1 s of it is left) and before the next item
    ons = plan_d.get("onscreen", [])
    starts = sorted(P.t(o["at"]) - LEAD for o in ons)
    for j, o in enumerate(ons):
        t = P.t(o["at"]) - LEAD
        if o["kind"] == "word":
            end = min(t + 2.2, L - 0.05, min((x for x in starts if x > t + 0.05), default=L) - 0.05)
            shot_end = P.span(P.shot_at(o["at"]))[1] - LEAD
            if shot_end - t >= 1.0:
                end = min(end, shot_end)
            name = f"kw_{j}"
            if bar_on:                                 # «عام»: v13's caption bar (montage/general.py)
                scenes.append(GEN.bar_scene(name, t, end, o["text"]))
            elif subs_on and t < t_intro:                # the intro's subtitles hold the bottom: the key word goes higher
                scenes.append(overlay_kw(name, t, end, o["text"], style["kw_colour"], y=640))
            else:
                scenes.append(overlay_kw(name, t, end, o["text"], style["kw_colour"]))
        elif o["kind"] == "rehook":
            u = P.t(o["until"]) - LEAD if o.get("until") is not None and o["until"] > o["at"] else t + 4.0
            end = min(max(u, t + 2.5), t + 5.0, L - 0.05)
            name = f"rehook_{j}"
            scenes.append(GEN.bar_scene(name, t, end, *GEN.split_two(o["text"])) if bar_on else overlay_rehook(name, t, end, o["text"]))
        else:
            end = min(P.t(o["until"]) - LEAD, L - 0.05)
            name = f"montage_{j}"
            scenes.append(overlay_montage(name, t, end, o["text"], style["kw_colour"]))
        overlays.append(name)
        anchors.append({"scene": name, "text": o["text"], "word_s": round(P.t(o["at"]), 3), "shown_s": round(t, 3), "kind": o["kind"]})
        pops.append([o["text"].split()[0], round(P.t(o["at"]), 2)])
    for i in plan_d.get("key_facts", []):
        w = words[i]
        if w["s"] >= t_intro:
            stops.append([w["w"], round(w["s"], 2)])
            hits.append([w["w"], round(w["s"], 2)])
    # sections -> music sections, whooshes and transitions at section changes
    secs = sorted(plan_d["sections"], key=lambda z: z["from"])
    music = []
    for j, sec in enumerate(secs):
        a = 0.0 if j == 0 else P.t(sec["from"])
        b = P.t(secs[j + 1]["from"]) if j + 1 < len(secs) else L
        if b - a < 3:
            continue
        music.append({"music": f"M{j + 1}", "from": round(a, 2), "to": round(b, 2), "note": sec.get("title", "")})
        if j:
            whoosh_extra.append([round(a, 2), f"section: {sec.get('title', '')}"])
            trans[round(a, 3)] = "zoomflash"
    if music:
        music[0]["from"] = 0.0
        music[-1]["to"] = round(L, 2)
        for j in range(1, len(music)):
            music[j]["from"] = music[j - 1]["to"]
    if t_bw is not None:                            # our graphics inside the black-and-white open are black and white too
        for sc in scenes:
            if sc["t_out"] <= t_bw + 0.05 and not sc["name"].startswith("framed_"):
                sc["bw"] = True
    timeline = {"length_s": round(L, 3), "blocks": blocks, "overlays": overlays, "strong_clicks": [], "paper_photos": sorted(set(paper_photos)),
                "rehook_scenes": [n for n in overlays if n.startswith("rehook_")], "intro_end_s": round(t_intro, 3), "anchors": anchors}
    if t_cold is not None:                          # the intro clip, the ad and the music's end go there (montage/structure.py)
        timeline["cold_open_end_s"] = t_cold
        report["cold_open_end_s"] = t_cold
    if t_bw is not None:                            # the logo sting goes there (montage/structure.py "bw_open_end")
        timeline["bw_open_end_s"] = t_bw
        report["bw_open_end_s"] = t_bw
    sound = {"length_s": round(L, 3), "music_gain_db": -11.6, "sections": music, "stops": stops, "hits": hits, "pops": pops,
             "whoosh_scenes": [], "whoosh_extra": whoosh_extra, "intro_clicks": [], "intro_end_s": round(t_intro, 3)}
    for sc in scenes:                               # this video's fonts (variety); the renderer falls back to Cairo
        sc["font"] = style.get("news_font" if sc["name"].startswith("news_") else "font", TEXT_FONTS[0])
    return timeline, fix_text(scenes), sound, trans, report


def cues(plan_d, P, style):
    """one music cue per section (rule 22): a mood from the brain plus this video's suffix (variety)"""
    secs = sorted(plan_d["sections"], key=lambda z: z["from"])
    out = []
    for j, sec in enumerate(secs):
        a = 0.0 if j == 0 else P.t(sec["from"])
        b = P.t(secs[j + 1]["from"]) if j + 1 < len(secs) else P.L
        if b - a < 3:
            continue
        energetic = ", energetic, punchy percussion" if j == 0 else ", low and steady under narration"
        out.append({"name": f"M{j + 1}", "seconds": int(min(90, max(20, math.ceil(b - a) + 4))),
                    "prompt": f"instrumental, no vocals, documentary underscore, {sec['music']}, {style['music_suffix']}{energetic}",
                    "seed": 40 + j})
    return out


def apply_transitions(edl, trans, intro_end_s):
    """mark each shot that starts on a transition cut; every cut inside the intro gets one, with a click"""
    order = ["zoom", "flash", "slide", "zoomflash"]
    clicks = []
    for k, s in enumerate(edl["shots"]):
        if k == 0:
            continue
        t = s["f0"] / FPS
        if t < intro_end_s - 0.05:
            s["transition"] = order[k % len(order)]
            clicks.append(round(t, 3))
            continue
        near = [c for c in trans if abs(c - t) <= 0.2]
        if near:
            s["transition"] = trans[min(near, key=lambda c: abs(c - t))]
    return clicks


__all__ = ["build", "cues", "variety", "record_variety", "apply_transitions"]

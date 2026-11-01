"""The presenter layout of اقتصاد احمس (phase 2F of the channel profiles; owner's answers of 18 Oct 2026): ONE continuous
presenter shot for the whole video, no B-roll, no cutaways, no punch-ins; a black-and-white open, then the channel's
logo sting (montage/structure.py identity clip at "bw_open_end"); small still pop-ups beside the presenter while a word
names them (flags, maps, framed photos), on the side away from his face and never over it.

Measured on the reference episodes v01-v03: the black-and-white open ends at 24.5-44 s; about 6.7 pop-ups a minute, most
2.5 s long; 80 % in one spot on the right, x 1337-1821, y 350-727 at 1080p (the presenter sits in the middle).

  presenter.layout = "single_shot_popups", presenter.punch_ins = false, presenter.black_and_white_open_s = [24, 45],
  presenter.popups = {"slot": [x0, y0, x1, y1], "per_min": [lo, hi], "seconds": [lo, hi], "photo_seconds": s}

Judgement decisions: montage/plan (the open's end and the pop-ups, on their words), sources/assets (the photos, chosen
from the candidates), music/cues, montage/sound (as the presenter type). Built in code: the flags (Wikimedia Commons,
public domain or CC0 only, never AI: owner's answer 7 of 2A), the maps (Natural Earth outlines, drawn here), the cut list
(work/montage/edl.json: presenter shots split at the cut's own joins, "bw" on the open, the pop-ups as overlays on the
presenter shots), the graphics scenes (decision graphics/scenes) and work/montage/popups.json (where each went, and why a
pop-up was left out: it would have covered the face on both sides, or its picture could not be had).
Overlays on presenter shots exist only here: every other layout and project keeps the presenter clean.
"""
import json
import re
from pathlib import Path

from ..core.io import load_json, save_json

FPS = 24
LEAD = 2 / FPS
SLOT = (1337, 350, 1821, 727)          # measured on v01-v03 (1080p)
FACE_MARGIN = 40
KINDS = ("flag", "map", "photo", "news")


def M(p, *n):
    return p.work.joinpath("montage", *n)


def config(p):
    m = p.profile_montage() if p is not None else {}
    pres = m.get("presenter") or {}
    pop = pres.get("popups") or {}
    bw = pres.get("black_and_white_open_s") or [24, 45]
    badge = pres.get("subscribe_badge") or {}
    return {"badge": badge if badge.get("file") else None, "slot": tuple(pop.get("slot") or SLOT), "per_min": tuple(pop.get("per_min") or (5, 8)),
            "seconds": tuple(pop.get("seconds") or (2, 3)), "photo_seconds": float(pop.get("photo_seconds") or 5),
            "bw": (float(bw[0]), float(bw[1])) if isinstance(bw, list) else (24.0, 45.0)}


def on(p):
    """this project runs the pop-up layout (اقتصاد احمس)"""
    m = p.profile_montage() if p is not None else {}
    return p is not None and p.montage == "presenter" and (m.get("presenter") or {}).get("layout") == "single_shot_popups"


# ---------------------------------------------------------------------------------------------------- the plan
SCHEMA = {"type": "object", "required": ["bw_open_end_s", "popups"], "properties": {
    "bw_open_end_s": {"type": "number"},
    "popups": {"type": "array", "items": {"type": "object", "required": ["at", "said", "kind", "seconds"], "properties": {
        "at": {"type": "integer"}, "said": {"type": "string"}, "kind": {"type": "string", "enum": list(KINDS)},
        "country": {"type": "string"}, "search": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "subject": {"type": "string"}, "news_item": {"type": "string"}, "seconds": {"type": "number"}}}}}}


def plan_text(p, L):
    c = config(p)
    from . import news as NEWS
    ni = NEWS.usable(p) if NEWS.mode(p) else []
    lo, hi = c["per_min"]
    return (
        "VIDEO TYPE: WITH PRESENTER, the channel's own layout (اقتصاد احمس): ONE CONTINUOUS PRESENTER SHOT for the whole "
        "video, no B-roll, no cutaways, no graphics over the whole frame, no punch-ins. Read sentences.json (the script's "
        "sentences with their times) and words.json (every word with its index and time).\n"
        f"(1) bw_open_end_s: the video opens in BLACK AND WHITE on the presenter until the sentence start where his opening "
        f"hook ends; there the channel's logo sting goes in (added in code). A sentence start between {c['bw'][0]:g} and "
        f"{c['bw'][1]:g} s (the channel's episodes: 24.5-44 s).\n"
        "(2) POP-UPS: small still pictures that appear BESIDE the presenter (in a fixed spot, code places them on the side "
        "away from his face) while a word names them, and only then: kind flag (a country's flag; country = its ISO-3 code), "
        "map (a country's outline; country = ISO-3), photo (a real photo of a person, place, building or thing he names; search "
        "= 1-3 short English searches for public-domain or CC archive photos; subject = what is seen, 1-3 words)"
        + (", news (a documented news item's real screenshot, framed; news_item = its id: " + ", ".join(ni) + ")" if ni else "")
        + f". About {lo:g}-{hi:g} a minute after the open (the channel's episodes: 6.7), none in the black-and-white open; each "
        "starts ON the word that names it: at = that word's index in words.json, said = those words as sentences.json "
        f"spells them; seconds {c['seconds'][0]:g}-{c['seconds'][1]:g} (a photo or news up to {c['photo_seconds']:g}); never "
        "two at once (the next one starts at least 0.5 s after the last one ends). Flags and brand logos are allowed in real "
        "photos. Only what is said; the same picture at most twice in the video, 60 s apart.\n"
        + (("THE OWNER'S INSTRUCTIONS FOR THIS EPISODE (follow them, unless they would break the rules): " + p.instructions + "\n")
           if p.instructions else ""))


def iso3_set():
    from .maps import _load
    return {f["properties"].get("ADM0_A3") or f["properties"].get("ISO_A3") for f in _load("50m")}


def check_plan(p, d, words, L, starts):
    from ..script.text import norm
    c = config(p)
    probs = []
    bw = d["bw_open_end_s"]
    ok = [s for s in starts if c["bw"][0] <= s <= c["bw"][1]]
    if not any(abs(s - bw) <= 0.3 for s in ok):
        probs.append(f"bw_open_end_s {bw:.2f} must be a sentence start between {c['bw'][0]:g} and {c['bw'][1]:g} s "
                     f"(sentence starts there: {[round(s, 2) for s in ok] or 'none'})")
    iso = iso3_set()
    from . import news as NEWS
    ni = set(NEWS.usable(p)) if NEWS.mode(p) else set()
    last_end = bw
    pops = sorted(d["popups"], key=lambda x: x["at"])
    for k, x in enumerate(pops):
        where = f"pop-up {k} (word {x['at']})"
        if not 0 <= x["at"] < len(words):
            probs.append(f"{where}: at must be a word index (0-{len(words) - 1})")
            continue
        t = words[x["at"]]["s"]
        said = norm(x["said"]).split()
        heard = [norm(w["w"]) for w in words[x["at"]:x["at"] + max(1, len(said))]]
        if said and said[0] not in heard[:1] and not any(said[0] in h or h in said[0] for h in heard[:1]):
            probs.append(f"{where}: «{x['said']}» is not what is said at word {x['at']} («{words[x['at']]['w']}»)")
        if t < bw:
            probs.append(f"{where}: no pop-up in the black-and-white open (it ends at {bw:.1f} s)")
        if x["kind"] in ("flag", "map") and x.get("country") not in iso:
            probs.append(f"{where}: country must be an ISO-3 code of the map data (got {x.get('country')!r})")
        if x["kind"] == "photo" and not x.get("search"):
            probs.append(f"{where}: a photo needs 1-3 searches")
        if x["kind"] == "news" and x.get("news_item") not in ni:
            probs.append(f"{where}: news_item must be one of {sorted(ni) or 'none (no screenshot could be taken)'}")
        top = c["photo_seconds"] if x["kind"] in ("photo", "news") else c["seconds"][1]
        if not c["seconds"][0] - 0.01 <= x["seconds"] <= top + 0.01:
            probs.append(f"{where}: seconds {x['seconds']:g} must be {c['seconds'][0]:g}-{top:g}")
        if t < last_end + 0.5 - 1e-6 and k:
            probs.append(f"{where}: starts {t:.1f} s, before the last pop-up ends (+0.5 s) at {last_end:.1f} s")
        last_end = max(last_end, t + x["seconds"])
    mins = max(1e-6, (L - bw) / 60)
    rate = len(pops) / mins
    if L - bw > 90 and not c["per_min"][0] * 0.75 <= rate <= c["per_min"][1] * 1.25:
        probs.append(f"{len(pops)} pop-ups in {mins:.1f} min after the open ({rate:.1f} a minute): about "
                     f"{c['per_min'][0]:g}-{c['per_min'][1]:g} a minute")
    if probs:
        raise ValueError("; ".join(probs[:12]))


def step_plan(p, ask, words, L):
    from . import steps_presenter as SPR
    SPR.sentences(p, words)
    read = [SPR.words_file(p, words, L), M(p, "sentences.json")]
    starts = SPR.starts(p)
    fmt = {"bw_open_end_s": 31.4, "popups": [
        {"at": 120, "said": "السعودية", "kind": "flag", "country": "SAU", "seconds": 2.5},
        {"at": 168, "said": "باب المندب", "kind": "map", "country": "YEM", "seconds": 2.5},
        {"at": 240, "said": "…", "kind": "photo", "search": ["oil tanker red sea"], "subject": "oil tanker", "seconds": 3.5}]}
    ask(p, "montage", "plan", plan_text(p, L), fmt, read=read, schema=SCHEMA,
        docs=["monteer/montage/steps_popups.py"], check=lambda d: check_plan(p, d, words, L, starts))


# ---------------------------------------------------------------------------------------------------- the pictures
PD = re.compile(r"^(public domain|pd\b|pd-|cc0)", re.I)


def country_name(iso):
    from .maps import _load
    for f in _load("50m"):
        pr = f["properties"]
        if (pr.get("ADM0_A3") or pr.get("ISO_A3")) == iso:
            return pr.get("NAME_EN") or pr.get("NAME"), pr.get("ADMIN") or pr.get("NAME"), pr.get("NAME_LONG") or pr.get("NAME")
    return None, None, None


def flag_png(p, iso, ledger, log=print):
    """the country's flag, from the project's own file when an earlier run fetched one -> path or None. Its source was
    Wikimedia Commons, removed on 19 Oct 2026 with every footage source but Pixabay and the local library: a new flag
    source is an open question for the owner (NOTES.md); until then a pop-up shows the map without a flag."""
    out = p.asset_dir("popups") / f"flag_{iso}.png"
    if out.exists() and out.stat().st_size > 2000:
        return out
    log(f"flag {iso}: no flag source (Wikimedia Commons was removed): the map without its flag")
    return None


def map_png(p, iso, ledger, size=(900, 700), fill="#5B8FD1", flag=None):
    """a country's outline, drawn from the map data (Natural Earth, public domain), filled with the country's own
    public-domain flag when there is one (owner's answer 5 of 2F; else a flat blue), a white edge -> path"""
    import math
    from PIL import Image, ImageDraw
    from .maps import _load
    out = p.asset_dir("popups") / (f"map_{iso}_flag.png" if flag else f"map_{iso}.png")
    if out.exists():
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    f = next(x for x in _load("50m") if (x["properties"].get("ADM0_A3") or x["properties"].get("ISO_A3")) == iso)
    g = f["geometry"]
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    rings = [poly[0] for poly in polys]
    area = lambda r: abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(r, r[1:] + r[:1]))) / 2  # noqa: E731
    big = max(area(r) for r in rings)
    rings = [r for r in rings if area(r) > big * 0.02]          # the mainland and the bigger islands
    lat0 = sum(y for r in rings for _, y in r) / sum(len(r) for r in rings)
    k = math.cos(math.radians(lat0))
    xs = [x * k for r in rings for x, _ in r]
    ys = [-y for r in rings for _, y in r]
    W, H = size
    s = min((W - 40) / (max(xs) - min(xs)), (H - 40) / (max(ys) - min(ys)))
    ox, oy = (W - (max(xs) - min(xs)) * s) / 2 - min(xs) * s, (H - (max(ys) - min(ys)) * s) / 2 - min(ys) * s
    mask = Image.new("L", (W * 2, H * 2), 0)
    md = ImageDraw.Draw(mask)
    for r in rings:
        md.polygon([((x * k * s + ox) * 2, (-y * s + oy) * 2) for x, y in r], fill=255)
    bb = mask.getbbox()
    if flag:                            # the flag laid over the country's shape (cover: the flag fills the outline's box)
        fl = Image.open(flag).convert("RGB")
        bw_, bh_ = bb[2] - bb[0], bb[3] - bb[1]
        kk = max(bw_ / fl.width, bh_ / fl.height)
        fl = fl.resize((round(fl.width * kk) + 1, round(fl.height * kk) + 1), Image.LANCZOS)
        fill_im = Image.new("RGB", mask.size, "#000000")
        fill_im.paste(fl, (bb[0] - (fl.width - bw_) // 2, bb[1] - (fl.height - bh_) // 2))
    else:
        fill_im = Image.new("RGB", mask.size, fill)
    im = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    im.paste(fill_im, (0, 0), mask)
    dr = ImageDraw.Draw(im)
    for r in rings:
        dr.line([((x * k * s + ox) * 2, (-y * s + oy) * 2) for x, y in r + r[:1]], fill="#FFFFFF", width=8, joint="curve")
    im = im.resize((W, H), Image.LANCZOS)
    im.crop(im.getbbox()).save(out)
    ledger.add(f"MAP:{iso}", kind="map", source="Natural Earth outline (public domain), drawn by the engine"
               + (", filled with the country's public-domain flag (Wikimedia Commons)" if flag else ""),
               page="https://www.naturalearthdata.com/", title=f"{iso} outline", licence="Public domain", file=str(out))
    return out


def step_sources(p, ask, log=print):
    """the pictures of the plan's pop-ups: flags and maps in code, photos chosen from the free candidates"""
    from .sources import Ledger, fetch_all, search
    d = load_json(p.decisions / "montage" / "plan.json")["decision"]
    ledger = Ledger(p)
    got = {}
    for k, x in enumerate(sorted(d["popups"], key=lambda z: z["at"])):
        if x["kind"] == "flag" and x.get("country"):
            f = flag_png(p, x["country"], ledger, log)
            got[k] = str(f) if f else None
        elif x["kind"] == "map" and x.get("country"):
            fl = flag_png(p, x["country"], ledger, log)
            got[k] = str(map_png(p, x["country"], ledger, flag=fl))
    photos = [(k, x) for k, x in enumerate(sorted(d["popups"], key=lambda z: z["at"])) if x["kind"] == "photo"]
    if photos:
        queries = {"stock": [], "photos": [{"query": q, "for": f"pop{k:03d}: {x.get('subject', '')}"} for k, x in photos for q in x["search"][:2]]}
        cand = search.candidates(p, queries)
        save_json(M(p, "candidates.json"), cand)
        ok_p = {c["title"] for v in cand["photos"].values() for c in v}

        def check(dd):
            bad = [x["title"] for x in dd["photos"] if x["title"] not in ok_p]
            keys = [x["key"] for x in dd["photos"]]
            if bad:
                raise ValueError(f"these are not among the candidates: {bad[:8]}")
            if any(not re.fullmatch(r"pop\d{3}", k) for k in keys) or len(set(keys)) != len(keys):
                raise ValueError("photo keys are pop<NNN>, the pop-up's number, once each")

        def settle(dd):                # the last resort (ask): a photo not among the candidates, or a bad or repeated key -> left out
            out, seen, notes = [], set(), []
            for x in dd["photos"]:
                if x["title"] in ok_p and re.fullmatch(r"pop\d{3}", x["key"]) and x["key"] not in seen:
                    out.append(x)
                    seen.add(x["key"])
                else:
                    notes.append(f"{x['key']}: {x['title'][:60]} left out (that pop-up gets no photo)")
            return dict(dd, photos=out), notes
        a = ask(p, "sources", "assets", "Choose ONE archive photo for each photo pop-up, ONLY from the candidates file (free sources whose "
                "licences pass the gate): the photo that shows what the pop-up's words name. Key = pop<NNN> (the pop-up's number, "
                "as in the candidates' \"for\"). Leave a pop-up out when no candidate shows it. Flags and brand logos may be seen.",
                {"stock": [], "photos": [{"key": "pop003", "title": "File:...", "page": "", "licence": "", "author": ""}]},
                read=[p.decisions / "montage" / "plan.json", M(p, "candidates.json")],
                schema={"type": "object", "required": ["photos"], "properties": {"stock": {"type": "array"}, "photos": {"type": "array", "items": {
                    "type": "object", "required": ["key", "title", "licence"], "properties": {"key": {"type": "string"}, "title": {"type": "string"},
                    "page": {"type": "string"}, "licence": {"type": "string"}, "author": {"type": "string"}}}}}},
                docs=["monteer/montage/sources/__init__.py"], check=check, settle=settle,
                fallback={"stock": [], "photos": []})     # no answer: those pop-ups get no photo
        fetch_all(p, {"stock": [], "photos": a.get("photos", [])}, log=log)
        for k, _ in photos:
            f = p.asset_dir("photos") / f"pop{k:03d}.jpg"
            got[k] = str(f) if f.exists() else None
    save_json(M(p, "popup_pictures.json"), {str(k): v for k, v in got.items()})


# ---------------------------------------------------------------------------------------------------- the cut list
def overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def slot_box(slot, side):
    x0, y0, x1, y1 = slot
    return (x0, y0, x1, y1) if side == "right" else (1920 - x1, y0, 1920 - x0, y1)


def popup_scene(name, a, b, kind, png, box):
    """one pop-up: the picture fitted in its spot, a quick fade in and out, a slight grow (a framed photo gets a light
    frame and a soft shadow)"""
    from PIL import Image
    w, h = Image.open(png).size
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    bw, bh = x1 - x0, y1 - y0
    framed = kind in ("photo", "news")
    pad = 12 if framed else 0
    hh = min(bh - 2 * pad, (bw - 2 * pad) * h / w)
    ww = hh * w / h
    dur = b - a
    items = []
    if framed:
        items.append({"type": "rect", "x": round(cx - ww / 2 - pad, 1), "y": round(cy - hh / 2 - pad, 1), "w": round(ww + 2 * pad, 1),
                      "h": round(hh + 2 * pad, 1), "color": "#F2EEE6", "t0": 0.0, "t2": round(dur - 0.3, 2), "radius": 4})
    grow = 1.0 if framed else 0.94                 # a framed photo keeps its size (its frame does not move)
    items.append({"type": "image", "path": str(png), "x": round(cx, 1), "y": round(cy, 1), "h": round(hh, 1), "from": grow, "to": 1.0,
                  "plain": not framed, "shadow": 30, "t0": 0.0, "t2": round(dur - 0.3, 2)})
    sc = {"name": name, "t_in": round(a, 3), "t_out": round(b, 3), "frames": round(dur * FPS), "bg": "none", "items": items}
    if kind in ("flag", "photo", "news"):     # drawn frame by frame (montage/popup_art.py): a waving flag, a striped reveal
        sc["art"] = {"kind": kind, "png": str(png), "box": list(box)}
    return sc


def badge_scene(name, a, b, png, x, y):
    """the channel's «Subscribe» badge (a still rebuilt from its episodes until the channel's own file comes), faded in
    and out"""
    from PIL import Image
    w, h = Image.open(png).size
    dur = b - a
    return {"name": name, "t_in": round(a, 3), "t_out": round(b, 3), "frames": round(dur * FPS), "bg": "none",
            "items": [{"type": "image", "path": str(png), "x": x + w / 2, "y": y + h / 2, "h": h, "from": 0.96, "to": 1.0, "plain": True,
                       "t0": 0.0, "t2": round(dur - 0.3, 2)}]}


def badge_windows(p, L, bw_end):
    """(from s, to s) of each showing of the badge: 1.5 s after the sting, then every 3 minutes (measured on v01-v03)"""
    c = config(p)
    bd = c["badge"]
    if not bd:
        return []
    out, t = [], bw_end + float(bd.get("first_after_open_s", 1.5))
    while t + float(bd.get("seconds", 7.1)) < L - 5:
        out.append((round(t, 3), round(t + float(bd.get("seconds", 7.1)), 3)))
        t += float(bd.get("every_s", 180))
    return out


def step_timeline(p, words, L, code_decision):
    """the whole cut list in code: presenter shots (no punch-in) split at the cut's joins and at the open's end, the open
    in black and white, the pop-ups as overlays on them; graphics/scenes and montage/timeline as code decisions"""
    from . import presenter as PRES
    c = config(p)
    d = load_json(p.decisions / "montage" / "plan.json")["decision"]
    pics = load_json(M(p, "popup_pictures.json")) if M(p, "popup_pictures.json").exists() else {}
    keep = load_json(p.output / "edl.json")["keep"]
    pieces, joins = PRES.cut_pieces(keep)
    F = PRES.face_boxes(p.output / f"cut_v{int(p.opt('version', 1))}.mp4", pieces, M(p, "faces"))
    total = round(L * FPS)
    bw_f = round(d["bw_open_end_s"] * FPS)
    cuts = sorted({0, total, bw_f} | {round(j * FPS) for j in joins if 0 < round(j * FPS) < total})
    shots = [{"kind": "presenter", "f0": a, "f1": b, "nframes": b - a, "cut_in": round(a / FPS, 4), "zoom": 1.0, "crop": None,
              "push_to": None, **({"bw": True} if b <= bw_f else {})} for a, b in zip(cuts, cuts[1:]) if b > a]
    # the face: the side away from it, and never over it (face boxes per piece, as shares of the frame -> 1080p pixels)
    def faces_in(a, b):
        out = []
        for pc in pieces:
            if pc["o1"] > a and pc["o0"] < b:
                out += [(x * 1920 - FACE_MARGIN, y * 1080 - FACE_MARGIN, (x + w) * 1920 + FACE_MARGIN, (y + h) * 1080 + FACE_MARGIN)
                        for x, y, w, h in F.get(pc["i"], [])]
        return out
    allx = [x + w / 2 for v in F.values() for x, y, w, h in v]
    face_cx = sorted(allx)[len(allx) // 2] if allx else 0.5
    home = "right" if face_cx <= 0.55 else "left"
    scenes, overlays, placed, left_out = [], [], [], []
    bd = c["badge"]
    windows = badge_windows(p, L, d["bw_open_end_s"])
    if windows:
        from PIL import Image
        png = Path(p.channel_profile()["_folder"]) / bd["file"]
        bw_, bh_ = Image.open(png).size
        badge_box = (bd["x"] - 20, bd["y"] - 20, bd["x"] + bw_ + 20, bd["y"] + bh_ + 20)
        for j, (a, b) in enumerate(windows):
            scenes.append(badge_scene(f"badge_{j:02d}", a, b, png, bd["x"], bd["y"]))
            overlays.append(f"badge_{j:02d}")
    for k, x in enumerate(sorted(d["popups"], key=lambda z: z["at"])):
        a = max(0.0, words[x["at"]]["s"] - LEAD)
        b = min(L, a + x["seconds"])
        png = pics.get(str(k))
        if x["kind"] == "news":
            from . import news as NEWS
            png = (NEWS.record(p).get(x.get("news_item")) or {}).get("png")
        if not png or not Path(png).exists():
            left_out.append({"popup": k, "said": x["said"], "why": "its picture could not be had (refused or not found)"})
            continue
        fs = faces_in(a, b) + [badge_box for wa, wb in windows if wa < b and a < wb]      # never over the badge either
        side = next((sd for sd in (home, "left" if home == "right" else "right") if not any(overlap(slot_box(c["slot"], sd), f) for f in fs)), None)
        if not side:
            left_out.append({"popup": k, "said": x["said"], "why": "it would cover the presenter's face on either side"})
            continue
        name = f"pop_{k:03d}"
        scenes.append(popup_scene(name, a, b, x["kind"], png, slot_box(c["slot"], side)))
        overlays.append(name)
        placed.append({"popup": k, "name": name, "kind": x["kind"], "said": x["said"], "from": round(a, 2), "to": round(b, 2), "side": side,
                       "box": slot_box(c["slot"], side), "picture": png})
    sc = {s["name"]: s for s in scenes}
    for s in shots:                     # overlays on the presenter shots: only in this layout
        ov = []
        for n in overlays:
            a, b = round(sc[n]["t_in"] * FPS), round(sc[n]["t_out"] * FPS)
            if a < s["f1"] and s["f0"] < b:
                o = {"name": n, "start_frame": max(0, s["f0"] - a)}
                if a > s["f0"]:
                    o["delay_frames"] = a - s["f0"]
                ov.append(o)
        if ov:
            s["overlays"] = ov
    edl = {"fps": FPS, "total_frames": total, "shots": shots, "layout": "single_shot_popups"}
    from .graphics import check
    if scenes:
        check(scenes)
    code_decision(p, "graphics", "scenes", scenes, "the pop-ups beside the presenter (montage/steps_popups.py)")
    tl = {"length_s": round(L, 3), "blocks": [], "overlays": overlays, "rehook_scenes": [], "strong_clicks": [], "paper_photos": [],
          "intro_end_s": 0.0, "bw_open_end_s": d["bw_open_end_s"], "presenter_overlays": True}
    code_decision(p, "montage", "timeline", tl, "the one-shot presenter layout (montage/steps_popups.py)")
    save_json(M(p, "edl.json"), edl)
    save_json(M(p, "presenter_sound.json"), {"intro_clicks": [], "whooshes": [], "intro_end_s": 0.0, "bw_open_end_s": d["bw_open_end_s"],
                                             "timeline_snapped": tl})
    save_json(M(p, "popups.json"), {"face_centre_x": round(face_cx, 3), "home_side": home, "placed": placed, "left_out": left_out})
    print(f"pop-up layout: {len(shots)} presenter shots (no punch-ins), black and white to {d['bw_open_end_s']:.1f} s, "
          f"{len(placed)} pop-ups placed ({home} side), {len(left_out)} left out")
    return edl


# ---------------------------------------------------------------------------------------------------- the self-check
def checks(p, edl):
    """self-check item 15 for this layout"""
    c = config(p)
    pp = load_json(M(p, "popups.json")) if M(p, "popups.json").exists() else {"placed": [], "left_out": []}
    sh = edl["shots"]
    L = edl["total_frames"] / FPS
    tl = load_json(p.decisions / "montage" / "timeline.json")["decision"] if (p.decisions / "montage" / "timeline.json").exists() else {}
    bw = tl.get("bw_open_end_s", 0)
    broll = [s for s in sh if s["kind"] != "presenter"]
    zoomed = [s for s in sh if s.get("zoom", 1) != 1 or s.get("crop") or s.get("push_to")]
    bw_shots = [s for s in sh if s.get("bw")]
    bw_ok = c["bw"][0] - 0.5 <= bw <= c["bw"][1] + 0.5 and all(s["f1"] <= round(bw * FPS) for s in bw_shots) and \
        sum(s["nframes"] for s in bw_shots) == round(bw * FPS)
    rate = len(pp["placed"]) / max(1e-6, (L - bw) / 60)
    outside = [x["name"] for x in pp["placed"] if tuple(x["box"]) not in (slot_box(c["slot"], "right"), slot_box(c["slot"], "left"))]
    flags = [x for x in pp["placed"] if x["kind"] == "flag"]
    led = load_json(M(p, "assets.json")) if M(p, "assets.json").exists() else {}
    flag_lic = {k: v.get("licence") for k, v in led.items() if k.startswith("FLAG:")}
    flags_pd = all(PD.search((v or "").strip()) for v in flag_lic.values())
    return {"layout": "single_shot_popups", "broll_shots": len(broll), "punch_ins": len(zoomed),
            "black_and_white_open": {"end_s": bw, "shots": len(bw_shots), "ok": bw_ok},
            "popups": {"placed": len(pp["placed"]), "per_minute": round(rate, 2), "range": c["per_min"], "left_out": pp["left_out"],
                       "outside_their_spot": outside},
            "flags": {"licences": flag_lic, "public_domain": flags_pd},
            "ok": not broll and not zoomed and bw_ok and not outside and flags_pd}


__all__ = ["on", "config", "step_plan", "step_sources", "step_timeline", "checks", "flag_png", "map_png", "popup_scene"]

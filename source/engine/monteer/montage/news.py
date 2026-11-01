"""Documented news as real cropped screenshots (phase 2E of the channel profiles; owner's answer 11 of phase 2A): the
important sentence of the article's own public page, cropped to its paragraph, the sentence highlighted in yellow line by
line, a slow push-in. No source line, no masthead, never a full page. It replaces our newspaper card and its «المصدر»
line in every profile ("montage" -> news.mode "screenshot_crop"); a project with no profile (the classic tests) keeps
the card.

  step "news" (before the plan): for each of the script tool's news items (script/news_items.json) its card's passage
  (script/facts.json) is looked for on the card's page by headless Chrome (montage/news_shot.mjs): public pages only,
  no login, no clicks, a fresh profile; a page that is not free, sends to a sign-in, asks for a bot check, or where
  something covers the sentence (a consent box too: owner's answer 2 of 2E) is NOT shot; a bot check gets one more try
  RETRY_S later in the same step (answer 3), never answered -> work/montage/news/<id>.png + news.json {id: {status, why}}
  usable(p)       the item ids with a screenshot; only these are offered as news (the plan, the material mix's
                  news_min, the presenter's ready-made scenes). An item without one is simply not shown as news: its
                  line gets other pictures like any line, and the video's report says which and why.
  scene(...)      the gfx scene: the crop on a soft blurred copy of itself, the highlight sweeping each line in reading
                  order, a 5 % push-in over the shot (render.py "push")
"""
import json
import subprocess
from pathlib import Path

from ..core.io import load_json, save_json

FPS = 24
YELLOW = {"yellow": "#FFD22F"}
MAX_W, MAX_H = 1560, 800


def mode(p):
    m = p.profile_montage() if p is not None else {}
    n = m.get("news") or {}
    return n.get("mode") if n.get("mode") == "screenshot_crop" else None


def folder(p):
    return p.work / "montage" / "news"


def items(p):
    f = p.folder / "script" / "news_items.json"
    return load_json(f)["items"] if f.exists() else []


def jobs(p):
    """[{"id", "url", "passage"}]: each news item's first card that has the page's own words"""
    f = p.folder / "script" / "facts.json"
    if not f.exists():
        return []
    d = load_json(f)
    cards = {c["id"]: c for c in (d["cards"] if isinstance(d, dict) else d)}
    out = []
    for n in items(p):
        c = next((cards[i] for i in n.get("card_ids", []) if i in cards and cards[i].get("passage") and cards[i].get("url")), None)
        if c:
            out.append({"id": n["id"], "url": c["url"], "passage": c["passage"]})
    return out


def step(p):
    """the step "news": screenshots of the news items' pages (channel profiles only; nothing otherwise)"""
    if not mode(p):
        return
    js = jobs(p)
    out = folder(p)
    out.mkdir(parents=True, exist_ok=True)
    rec = {"note": "documented news as screenshots of their public pages (montage/news.py)", "items": {}}
    for n in items(p):
        if n["id"] not in {j["id"] for j in js}:
            rec["items"][n["id"]] = {"status": "no_page", "why": "no card with the page's own words"}
    import shutil
    chrome = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
    if js and (not chrome.exists() or not shutil.which("node")):      # this Mac lacks the tools: no screenshot, the run goes on
        for j in js:
            rec["items"][j["id"]] = {"status": "error", "why": "Google Chrome or Node is not installed on this Mac (see HANDOFF.md)"}
        js = []
    if js:
        got, r = capture(js, out / "shots", out / "jobs.json")
        blocked = [j for j in js if (got.get(j["id"]) or {}).get("status") == "blocked"]
        if blocked:                    # owner's answer 3 of 2E: a bot check gets one more try later in the run, never answered
            import time
            print(f"news: {len(blocked)} page(s) asked for a bot check; one more try in {RETRY_S} s")
            time.sleep(RETRY_S)
            again, _ = capture(blocked, out / "shots_retry", out / "jobs_retry.json")
            for j in blocked:
                g = again.get(j["id"]) or {}
                if g.get("status") == "ok":
                    g["retried"] = True
                    got[j["id"]] = g
                    (out / "shots_retry" / f"{j['id']}.png").replace(out / "shots" / f"{j['id']}.png")
                else:
                    got[j["id"]] = dict(got[j["id"]], why=got[j["id"]].get("why", "") + " (tried twice)")
        for j in js:
            g = got.get(j["id"]) or {"status": "error", "why": (r.stderr or "the capture did not answer")[-300:]}
            if g.get("status") == "ok":
                g["png"] = str(out / "shots" / f"{j['id']}.png")
            rec["items"][j["id"]] = g
    save_json(out / "news.json", rec)
    ok = [k for k, v in rec["items"].items() if v.get("status") == "ok"]
    print(f"news: {len(ok)} of {len(rec['items'])} item(s) shot; not shot: "
          + ("; ".join(f"{k} {v['status']}" for k, v in rec["items"].items() if v.get("status") != "ok") or "none"))


RETRY_S = 120


def capture(js, shots_dir, jobs_file):
    """run the headless capture for these jobs -> ({id: result}, the process)"""
    from ..core.paths import ENGINE
    save_json(jobs_file, js)
    r = subprocess.run(["node", str(ENGINE / "monteer" / "montage" / "news_shot.mjs"), str(shots_dir), str(jobs_file)],
                       capture_output=True, text=True, timeout=900)
    f = Path(shots_dir) / "news_shots.json"
    return (load_json(f) if f.exists() else {}), r


def record(p):
    f = folder(p) / "news.json"
    return load_json(f)["items"] if f.exists() else {}


def usable(p):
    return [k for k, v in record(p).items() if v.get("status") == "ok" and Path(v.get("png", "")).exists()]


def has_news(p):
    """documented news the montage may show: with a screenshot (channel profiles), else the script tool's items"""
    if mode(p):
        return bool(usable(p))
    return (p.folder / "script" / "news_items.json").exists()


def highlight_colour(p):
    n = (p.profile_montage().get("news") or {}) if p is not None else {}
    c = n.get("highlight", "yellow")
    return YELLOW.get(c, c if str(c).startswith("#") else "#FFD22F")


def backdrop(png, out):
    """the crop blurred and darkened to fill the frame (behind the sharp crop)"""
    from PIL import Image, ImageEnhance, ImageFilter
    out = Path(out)
    if not out.exists():
        im = Image.open(png).convert("RGB")
        k = max(1920 / im.width, 1080 / im.height)
        im = im.resize((int(im.width * k) + 1, int(im.height * k) + 1), Image.LANCZOS)
        x0, y0 = (im.width - 1920) // 2, (im.height - 1080) // 2
        im = im.crop((x0, y0, x0 + 1920, y0 + 1080)).filter(ImageFilter.GaussianBlur(28))
        ImageEnhance.Brightness(im).enhance(0.45).save(out, quality=90)
    return str(out)


def scene(p, name, a, b, item_id):
    """the gfx scene of one news item's screenshot over a, b s, or None when it has none"""
    r = record(p).get(item_id) or {}
    if r.get("status") != "ok":
        return None
    png = r["png"]
    w, h = r["crop"]
    k = min(MAX_W / w, MAX_H / h, 1.25)
    fw, fh = w * k, h * k
    x0, y0 = 960 - fw / 2, 540 - fh / 2
    items_ = [{"type": "image", "path": png, "x": 960, "y": 540, "h": round(fh, 1), "from": 1.0, "to": 1.0, "plain": False, "shadow": 40}]
    col = highlight_colour(p)
    t = 0.55
    for x, y, lw, lh in sorted(r.get("lines", []), key=lambda q: q[1]):     # top to bottom, in reading order
        half = lh * k * 0.46                       # the line's round ends stay on the sentence
        L, R, cy = x0 + x * k + half, x0 + (x + lw) * k - half, y0 + (y + lh / 2) * k
        dur = 0.18 + 0.32 * (lw * k) / fw
        if R <= L:
            L = R = (L + R) / 2
        a_, b_ = (R, L) if r.get("rtl") else (L, R)
        items_.append({"type": "line", "x": round(a_, 1), "y": round(cy, 1), "x1": round(b_, 1), "y1": round(cy, 1),
                       "color": col, "width": round(lh * k * 0.92, 1), "alpha": 0.42, "t0": round(t, 2), "t1": round(t + dur, 2)})
        t += dur + 0.05
    bg = backdrop(png, folder(p) / f"{item_id}_bg.jpg")
    return {"name": name, "t_in": round(a, 3), "t_out": round(b, 3), "frames": round((b - a) * FPS), "bg": "image", "bgpath": bg,
            "items": items_, "push": 0.05, "news_item": item_id}


# ---------------------------------------------------------------------------------------------------- with presenter
def line_span(p, words, line_id):
    """(start s, end s) where the script line is said (montage/scripttext.py Aligner over script/lines.json), or None"""
    from .scripttext import Aligner, _clean
    f = p.folder / "script" / "lines.json"
    if not f.exists():
        return None
    off, rng = 0, None
    for ln in load_json(f)["lines"]:
        n = len([t for t in (_clean(w) for w in ln["text"].split()) if t])
        if ln["id"] == line_id:
            rng = (off, off + n)
            break
        off += n
    if not rng:
        return None
    al = Aligner(p, words)
    idx = [i for i, j in al.map.items() if rng[0] <= j < rng[1]]
    return (words[min(idx)]["s"], words[max(idx)]["e"]) if idx else None


def presenter_scenes(p, words, L):
    """the ready-made screenshot scenes for the presenter type: news_<id> where its line is said (5-7 s)"""
    out = []
    by = {n["id"]: n for n in items(p)}
    for k in usable(p):
        n = by.get(k)
        sp = next((line_span(p, words, lid) for lid in (n or {}).get("line_ids", []) if line_span(p, words, lid)), None)
        if not sp:
            continue
        a = max(0.0, sp[0] - 0.1)
        b = min(L, max(a + 5.0, min(sp[1] + 0.4, a + 7.0)))
        sc = scene(p, f"news_{k}", a, b, k)
        if sc:
            out.append(sc)
    return out


def scenes_file(p):
    return folder(p) / "scenes.json"


__all__ = ["mode", "step", "usable", "has_news", "scene", "presenter_scenes", "record", "scenes_file", "line_span"]

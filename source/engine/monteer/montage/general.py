"""«عام»'s own look and plan rules (phase 2G of the channel profiles; owner's answers for «عام»): the liked video's style
(v13, «ألمانيا تعلن الإفلاس الصامت…») for «عام» only, with less repetition than it has. Read from the profile's montage:

  text.labels.style "caption_bar"   key-word labels and re-hooks are v13's caption bar (measured on v13, 720x900, and
                                    scaled to 1920x1080): a green box (#699535) with white bold text, an optional second
                                    line in a grey box (#645E5E) under it, both right-aligned, typed in letter by letter
                                    (about 28 letters a second; the box grows with the text), with a soft shadow.
                                    Drawn by the renderer's "captionbar" item (gfx.swift).
  real_footage_min 0.65             at least 65 % of the counted shots are real pictures (stock, archive, news, the
                                    owner's clips); our graphics and drawn images together the rest (few graphics).
                                    (0.85 until 19 Oct 2026; owner's decision 2b: 65 % until the plan uses fewer cards
                                    and drawn images, then looked at again)
  repeats.subject_max_share 0.25    no single subject (what is seen) over 25 % of the running time.
  repeats.file_max / file_gap_s     one file at most twice, 60 s apart (already the rule for every video, Phase 2).

Without these keys (every other profile and the classic projects) nothing here applies: each function returns its
"off" value and no request text changes.
"""
import math

GREEN, GREY, WHITE = "#699535", "#645E5EF0", "#FFFFFF"     # measured on v13 at 56-61 s (median box colours)
BAR_H, BAR_GAP = 74, 4                                     # one box's height, the gap between the two lines (v13 x 1.2)
TEXT_SIZE, PAD = 50, 22
RIGHT, Y1 = 1575, 847        # the boxes' right edge and the first line's centre (v13: right edge at 82 % of the width, top at 75 %)
CPS = 28.0                   # letters a second (v13: «أم بداية سقوطٍ اقتصادي», 22 letters, in about 0.8 s)
REAL = ("stock", "archive", "news", "own")
NOT_REAL = ("ai", "graphic")


def mont(p):
    return p.profile_montage() if p is not None else {}


def bar_on(p):
    return ((mont(p).get("text") or {}).get("labels") or {}).get("style") == "caption_bar"


def rules(p):
    """{"real_min", "subject_max", "file_max", "file_gap_s"} for «عام», else None"""
    m = mont(p)
    if not m.get("real_footage_min"):
        return None
    r = m.get("repeats") or {}
    return {"real_min": float(m["real_footage_min"]), "subject_max": float(r.get("subject_max_share") or 1.0),
            "file_max": int(r.get("file_max") or 2), "file_gap_s": float(r.get("file_gap_s") or 60)}


# ---------------------------------------------------------------------------------------------------- the caption bar
def split_two(text):
    """a re-hook's question on two lines (v13: the green line, then the grey one), at the word nearest the middle"""
    ws = text.split()
    if len(ws) < 5:
        return text, None
    k = min(range(2, len(ws) - 1), key=lambda i: abs(len(" ".join(ws[:i])) - len(" ".join(ws[i:]))))
    return " ".join(ws[:k]), " ".join(ws[k:])


def bar_items(line1, line2=None, dur=6.0, y=Y1):
    """the renderer's items of one caption bar: line 2 types in when line 1 is done; both leave 0.2 s before the end"""
    out, t = [], 0.0
    for k, (txt, col) in enumerate(((line1, GREEN), (line2, GREY))):
        if not txt:
            continue
        t1 = t + max(0.25, len(txt) / CPS)
        out.append({"type": "captionbar", "text": txt, "x": RIGHT, "y": y + k * (BAR_H + BAR_GAP), "h": BAR_H, "width": PAD,
                    "size": TEXT_SIZE, "weight": 800, "color": WHITE, "color2": col, "w": 1500,
                    "t0": round(t, 3), "t1": round(t1, 3), "t2": round(max(t1 + 0.5, dur - 0.25), 3)})
        t = t1 + 0.1
    return out


def bar_scene(name, a, b, line1, line2=None, y=Y1):
    from .build import scene
    return scene(name, a, b, bar_items(line1, line2, b - a, y), bg="none")


def restyle(p, scenes):
    """with presenter: the brain gives each label (lbl_…) and re-hook (rehook_…) as its words only; code draws them as
    the caption bar. Other scenes and other profiles: unchanged."""
    if not bar_on(p):
        return scenes
    out = []
    for sc in scenes:
        if sc["name"].startswith(("lbl_", "rehook_")):
            txt = [i["text"] for i in sc.get("items", []) if i.get("type") in ("text", "kwtext", "captionbar") and i.get("text")]
            if txt:
                l1, l2 = (txt[0], txt[1]) if len(txt) > 1 else split_two(txt[0]) if sc["name"].startswith("rehook_") else (txt[0], None)
                sc = dict(sc, bg="none", items=bar_items(l1, l2, sc["t_out"] - sc["t_in"]), caption_bar=True)
        out.append(sc)
    return out


def scenes_text(p):
    """the presenter's graphics request, for «عام» only"""
    if not bar_on(p):
        return ""
    return (" THIS CHANNEL'S LABELS ARE ITS CAPTION BAR, drawn in code (montage/general.py): name each key-word label "
            "lbl_<word> and each re-hook rehook_<word>, with bg \"none\" and items = one text item with its words (a label: 1-6 "
            "words) or two text items (two lines: the first in the green box, the second in the grey one under it); give "
            "no rect, colour or position for them. FEW GRAPHICS: our own graphics only where a number, a place or a list "
            "cannot be shown with real footage.")


# ---------------------------------------------------------------------------------------------------- the plan's rules
def plan_text(p, kind):
    """the plan request's added words for «عام» (kind "phrases" or "presenter"), else ''"""
    r = rules(p)
    if not r:
        return ""
    base = "all the plan's shots" if kind == "phrases" else "the B-roll shots"
    lim = f"{r['subject_max'] * 100:.0f} %"
    return ("\nTHIS CHANNEL'S STYLE (the liked video v13, owner's answers): REAL FOOTAGE FIRST, FEW GRAPHICS: of "
            f"{base}, at least {r['real_min'] * 100:.0f} % are real pictures (stock, archive, documented news, the owner's "
            f"clips); our graphics and drawn images together at most {100 - r['real_min'] * 100:.0f} %. LESS REPETITION: one "
            f"file at most {r['file_max']} times, {r['file_gap_s']:.0f} s apart, and no single subject (what is seen) over "
            f"{lim} of the running time"
            + (": every footage shot's subject counts with its length." if kind == "phrases" else
               ": give every B-roll block its subject (1-3 English words, what is seen; the same thing gets the same "
               "subject); the blocks' lengths count per subject.")
            + " Labels and re-hooks are the channel's caption bar (drawn in code); keep each label to 1-6 words.")


def mix_problems(types, r, where="the plan"):
    """types: each counted shot's material type -> [problem] when real pictures are under the profile's share"""
    counted = [t for t in types if t is not None]
    if not r or not counted:
        return []
    n = len(counted)
    not_real = sum(1 for t in counted if t in NOT_REAL)
    most = math.floor((1 - r["real_min"]) * n + 1e-9)
    if not_real > most:
        return [f"{where} has {not_real} graphic or drawn shots of {n}; this channel shows real pictures at least "
                f"{r['real_min'] * 100:.0f} % of the time (few graphics): at most {most}"]
    return []


def subject_shares(spans, L):
    """spans: [(subject, seconds)] -> {subject: share of the running time}, largest first"""
    from .place import subject_key
    tot = {}
    for s, d in spans:
        k = subject_key(s or "")
        if k:
            tot[k] = tot.get(k, 0.0) + d
    return dict(sorted(((k, round(v / max(L, 1e-6), 3)) for k, v in tot.items()), key=lambda kv: -kv[1]))


def subject_problems(spans, L, r, where="the plan"):
    if not r:
        return []
    return [f"{where} shows «{k}» for {v * 100:.0f} % of the running time; no single subject over {r['subject_max'] * 100:.0f} % "
            "(show the idea with another subject)" for k, v in subject_shares(spans, L).items() if v > r["subject_max"] + 1e-9]


def block_problems(p, d, L):
    """with presenter: the plan's blocks (material, subjects) against «عام»'s rules"""
    r = rules(p)
    if not r:
        return []
    probs, types, spans = [], [], []
    for b in d["blocks"]:
        if b.get("presenter"):
            continue
        for t, n in (b.get("material") or {}).items():
            types += [t] * int(n)
        if not b.get("subject"):
            probs.append(f"block {b['in']}-{b['out']}: give its subject (1-3 English words, what is seen)")
        spans.append((b.get("subject", ""), b["out"] - b["in"]))
    return probs + mix_problems(types, r) + subject_problems(spans, L, r)


def phrase_problems(p, d, P, L):
    """audio only: the phrase plan's shots against «عام»'s rules"""
    r = rules(p)
    if not r:
        return []
    from .phrases import FOOTAGE
    sh = d["shots"]
    spans = [(s.get("subject", ""), P.span(k)[1] - P.span(k)[0]) for k, s in enumerate(sh) if s["type"] in FOOTAGE]
    return mix_problems([s["type"] for s in sh], r) + subject_problems(spans, L, r)


def timeline_text(p):
    r = rules(p)
    if not r:
        return ""
    return (f" THIS CHANNEL (v13's style): over the B-roll time at least {r['real_min'] * 100:.0f} % real pictures (stock, "
            "archive, news screenshots, the owner's clips); our graphics (G) and drawn images (A:/AE:) the rest; labels and "
            "re-hooks are its caption bar.")


def cut_problems(p, edl):
    """with presenter, on the cut list: real pictures under «عام»'s share of the B-roll time"""
    r = rules(p)
    if not r:
        return []
    m = measure(p, edl)
    if m["broll_s"] > 0 and m["real_share"] + 1e-9 < r["real_min"]:
        return [f"real pictures are {m['real_share'] * 100:.0f} % of the B-roll time (graphics {m['graphic_share'] * 100:.0f} %, "
                f"drawn images {m['ai_share'] * 100:.0f} %); this channel shows at least {r['real_min'] * 100:.0f} %: use footage "
                "or photos in place of some G blocks and A: images"]
    return []


# ---------------------------------------------------------------------------------------------------- measured on the cut
def measure(p, edl):
    """the finished cut list measured as «عام» counts it: the share of real pictures over the B-roll time, the files'
    repeats -> {"real_share", "graphic_share", "ai_share", "broll_s", "files_over"}"""
    fr = {"real": 0, "graphic": 0, "ai": 0}
    uses = {}
    for s in edl["shots"]:
        n = s["f1"] - s["f0"]
        if s["kind"] == "presenter":
            continue
        if s["kind"] == "gfx":
            fr["real" if str(s.get("scene", "")).startswith("news_") else "graphic"] += n
        elif s["kind"] == "ai":
            fr["ai"] += n
        else:
            fr["real"] += n
        if s.get("asset"):
            uses.setdefault(s["asset"].split(":", 1)[-1], []).append(s["f0"] / 24)
    tot = max(1, sum(fr.values()))
    from .place import file_problems              # the same count as the cut list's check (steps_presenter.check_cut)
    over = {k: [round(t, 1) for t in ts] for k, ts in file_problems([(t, k) for k, ts in uses.items() for t in ts])}
    return {"real_share": round(fr["real"] / tot, 3), "graphic_share": round(fr["graphic"] / tot, 3), "ai_share": round(fr["ai"] / tot, 3),
            "broll_s": round(tot / 24, 1), "files_over": over}


__all__ = ["bar_on", "rules", "bar_scene", "bar_items", "restyle", "scenes_text", "plan_text", "mix_problems", "subject_problems",
           "subject_shares", "block_problems", "phrase_problems", "measure", "split_two"]

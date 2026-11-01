"""A channel's graphics policy (owner's decisions of 22 Oct 2026, after «المملكة المتحدة تنهار» v1 was 41 % graphics, many
of them near-empty text cards held still after their animation; the channel's reference episode has about 6 %).

The profile's "montage.graphics" (absent: nothing here applies, every other channel and the classic projects as before):
  max_share        the cut list's graphics at most this share of the video's time (full-frame scenes and the data
                   overlays ov_*; key-word labels and news screenshots not counted). A check the timeline must meet.
  plan_max_share   the plan's graphic shots at most this share of its B-roll shots (the plan's own count)
  scene_s          [lo, hi] s: a graphic scene lasts this long and animates for all of it; a G block is never longer
                   than its scene (no still hold) nor than hi
  full_frame_for   what a full-frame scene may be: a map, numbers (a counter, a chart, a comparison of figures), people
                   (names with their role) or a comparison; never a card of text alone
  rehooks          "overlay": the narrator's re-hook questions are drawn over the footage (bg "none"), not as cards
  over_footage     true: numbers and names are drawn over real footage (scenes ov_<name>, bg "none", a translucent panel)
                   wherever footage is on screen; the full-frame scenes are kept for maps and charts

  of(p) -> the policy or None;  scene_problems(scenes, L, pol);  settle_scenes(scenes, L, pol) -> (scenes, notes)
  cut_problems(d, edl, scenes, L, pol);  repair_blocks(d, scenes, pol) -> notes;  share(edl, scenes, d) -> seconds
"""
import math

FPS = 24
VISUAL = {"map", "counter", "bar", "line", "route", "pin", "image", "wave", "goldbar", "bill", "flag", "polys"}
DEFAULT = {"max_share": 0.15, "plan_max_share": 0.10, "scene_s": [4.0, 6.0], "rehooks": "overlay", "over_footage": True,
           "full_frame_for": ["map", "numbers", "people", "comparison"]}


def of(p):
    if not getattr(p, "profile", None):
        return None
    try:
        g = p.profile_montage().get("graphics")
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(g, dict) or not g:   # «عام» has "graphics": "few" (read as real_footage_min): not this policy
        return None
    return dict(DEFAULT, **{k: v for k, v in g.items() if not k.startswith("note")})


def is_overlay_data(name):
    return name.startswith("ov_")


def full_frame(sc):
    """a scene drawn over the whole frame (not a label, a re-hook overlay, a data overlay or a news screenshot)"""
    return (sc.get("bg") or "dark") != "none" and not sc["name"].startswith("news_")


def words(sc):
    return sum(len(str(i.get("text", "")).replace("%d", "0").split()) for i in sc.get("items", []) if i.get("text"))


def kind_ok(sc):
    """a full-frame scene with something to see: a map, a figure, a chart, people or a comparison (two or more panels
    with their text); a text-only card is refused"""
    types = {i.get("type") for i in sc.get("items", [])}
    if types & VISUAL:
        return True
    panels = sum(1 for i in sc.get("items", []) if i.get("type") == "rect")
    texts = sum(1 for i in sc.get("items", []) if i.get("type") in ("text", "kwtext"))
    return panels >= 2 and texts >= 4 and words(sc) >= 6


def budget(L, pol):
    """how many graphic scenes (full-frame + data overlays) the video may have: its share at the longest scene length"""
    return max(1, int(math.floor(pol["max_share"] * L / float(pol["scene_s"][1]))))


def text(L, pol):
    lo, hi = pol["scene_s"]
    n = budget(L, pol)
    return (f" GRAPHICS POLICY (this channel's standing rule, owner's decision of 22 Oct 2026): FEW AND RICH. All our graphics "
            f"together (full-frame scenes and data overlays ov_*; key-word labels not counted) are at most {pol['max_share']:.0%} of the "
            f"video's time: at most {n} scenes in all for this {L:.0f} s video, fewer is better (the channel's reference episode has "
            f"about 6 %). Each lasts {lo:g}-{hi:g} s (t_out - t_in) and ANIMATES FOR ALL OF IT (items keep appearing, counting or "
            "moving until t_out; never a still card held on screen). Only for: MAPS (places, borders, routes, with pins and "
            "names), NUMBERS (a counter, a bar or line chart, a comparison of figures the script says), PEOPLE (names with their "
            "role) and COMPARISONS (two or more panels side by side). NEVER a card of a few words: no single word, date, year or "
            "question alone on a dark card (a date or a key word is a key-word label over footage instead)."
            + (" Numbers, names and comparisons are DRAWN OVER REAL FOOTAGE: name such a scene ov_<name>, bg \"none\", with a "
               "translucent dark panel (a rect with alpha 0.6-0.75) behind its text in the lower or side part of the frame, so the "
               "footage stays visible; keep full-frame scenes (bg dark) for maps and charts." if pol.get("over_footage") else "")
            + (" RE-HOOKS (the narrator's own questions) are overlays over the footage (bg \"none\", a translucent panel behind "
               "the text), never full-frame cards." if pol.get("rehooks") == "overlay" else ""))


def timeline_text(L, pol):
    lo, hi = pol["scene_s"]
    return (f" GRAPHICS POLICY (this channel): our graphics (G blocks and the ov_* overlays) at most {pol['max_share']:.0%} of the "
            f"video's time ({pol['max_share'] * L:.0f} s here); a G block lasts no longer than its scene (t_out - t_in) and at most "
            f"{hi:g} s: no graphic held still. Where a planned graphic or archive shot has no scene or no asset, use real footage "
            "(an F block with the clips that exist) or leave the presenter on screen: NEVER fill time with a graphic. Data overlays "
            "ov_* and re-hooks go in overlays (each inside a B-roll block that covers its whole t_in-t_out), not as G blocks.")


def scene_problems(scenes, L, pol):
    probs = []
    lo, hi = pol["scene_s"]
    counted = [s for s in scenes if full_frame(s) or is_overlay_data(s["name"])]
    n = budget(L, pol)
    if len(counted) > n:
        probs.append(f"{len(counted)} graphic scenes (full-frame and ov_*); this channel allows at most {n} for a {L:.0f} s video "
                     f"({pol['max_share']:.0%} of its time): keep the richest maps, figures and comparisons only")
    for s in counted:
        d = s["t_out"] - s["t_in"]
        if not lo - 0.25 <= d <= hi + 0.25:
            probs.append(f"scene {s['name']} lasts {d:.1f} s; a graphic lasts {lo:g}-{hi:g} s and animates for all of it")
    for s in scenes:
        if full_frame(s) and not kind_ok(s) and not s["name"].startswith("rehook"):
            probs.append(f"scene {s['name']} is a card of text only ({words(s)} words): a full-frame scene is a map, numbers, "
                         "people or a comparison; a key word goes as a label over footage")
        if pol.get("rehooks") == "overlay" and s["name"].startswith("rehook") and (s.get("bg") or "dark") != "none":
            probs.append(f"re-hook {s['name']} is a full-frame card; draw it over the footage (bg \"none\", a translucent panel)")
    return probs


def settle_scenes(scenes, L, pol):
    """the last resort in code: text-only full-frame cards left out; re-hook cards drawn over the footage behind a
    translucent panel; scenes beyond the budget left out (the latest first, keeping maps and figures) -> (scenes, notes)"""
    import copy
    out, notes = [], []
    for s in scenes:
        if full_frame(s) and not kind_ok(s) and not s["name"].startswith("rehook"):
            notes.append(f"scene {s['name']} left out: a card of text only")
            continue
        if pol.get("rehooks") == "overlay" and s["name"].startswith("rehook") and (s.get("bg") or "dark") != "none":
            s = copy.deepcopy(s)
            s["bg"] = "none"
            s["items"] = [{"type": "rect", "x": 0, "y": 0, "w": 1920, "h": 1080, "color": "#0B0B0B", "alpha": 0.62, "t0": 0, "panel": True}] + s["items"]
            notes.append(f"re-hook {s['name']} drawn over the footage behind a translucent panel")
        out.append(s)
    n = budget(L, pol)
    counted = [s for s in out if full_frame(s) or is_overlay_data(s["name"])]
    if len(counted) > n:
        rank = sorted(counted, key=lambda s: (bool({i.get("type") for i in s.get("items", [])} & VISUAL), words(s)), reverse=True)
        drop = {s["name"] for s in rank[n:]}
        out = [s for s in out if s["name"] not in drop]
        notes += [f"scene {x} left out: over this channel's graphics budget ({n})" for x in sorted(drop)]
    return out, notes


def share(edl, scenes, d):
    """seconds of our graphics in a cut list: full-frame G shots (news screenshots not counted) and the ov_* overlays'
    time over footage"""
    t = sum(s["nframes"] if "nframes" in s else s["f1"] - s["f0"] for s in edl["shots"]
            if s["kind"] == "gfx" and not s["scene"].startswith("news_")) / FPS
    sc = {x["name"]: x for x in scenes}
    ov = [n for n in d.get("overlays", []) if is_overlay_data(n) or n in set(d.get("rehook_scenes", []))]
    t += sum(sc[n]["t_out"] - sc[n]["t_in"] for n in ov if n in sc)
    return t


def cut_problems(d, edl, scenes, L, pol):
    probs = []
    lo, hi = pol["scene_s"]
    sc = {x["name"]: x for x in scenes}
    t = share(edl, scenes, d)
    if t > pol["max_share"] * L + 0.5:
        probs.append(f"our graphics take {t:.0f} s, {t / L:.0%} of the video; this channel allows at most {pol['max_share']:.0%} "
                     f"({pol['max_share'] * L:.0f} s): fewer G blocks, real footage or the presenter instead")
    for b in d.get("blocks", []):
        if b[0] == "G" and b[1] in sc and not b[1].startswith("news_"):
            dur, scene_d = b[3] - b[2], sc[b[1]]["t_out"] - sc[b[1]]["t_in"]
            if dur > min(scene_d, hi) + 0.35:
                probs.append(f"G block {b[1]} at {b[2]:.1f}-{b[3]:.1f} s lasts {dur:.1f} s; no longer than its scene "
                             f"({scene_d:.1f} s) and {hi:g} s: no graphic held still")
            if pol.get("rehooks") == "overlay" and b[1].startswith("rehook"):
                probs.append(f"re-hook {b[1]} is a G block; put it in overlays over a B-roll block")
    return probs


def repair_blocks(d, scenes, pol):
    """in code before asking again: a G block longer than its scene (or the longest scene length) ends with its scene and
    the next F block starts there (else the presenter fills the rest); a re-hook G block becomes an overlay of the footage
    around it, or is left out -> notes (d changed in place)"""
    notes = []
    lo, hi = pol["scene_s"]
    sc = {x["name"]: x for x in scenes}
    bl = sorted(d.get("blocks", []), key=lambda b: b[2] if b[0] != "INSERT" else b[1])
    keep = []
    for k, b in enumerate(bl):
        if b[0] == "G" and pol.get("rehooks") == "overlay" and b[1].startswith("rehook"):
            nxt = bl[k + 1] if k + 1 < len(bl) else None
            if nxt is not None and nxt[0] == "F" and abs(nxt[2] - b[3]) < 0.05:
                nxt[2] = b[2]
                d.setdefault("overlays", []).append(b[1])
                notes.append(f"re-hook {b[1]}: an overlay over the footage after it, not a card")
            else:
                d["rehook_scenes"] = [x for x in d.get("rehook_scenes", []) if x != b[1]]
                notes.append(f"re-hook {b[1]}: left out (no footage to draw it over)")
            continue
        if b[0] == "G" and b[1] in sc and not b[1].startswith("news_"):
            lim = min(sc[b[1]]["t_out"] - sc[b[1]]["t_in"], hi)
            if b[3] - b[2] > lim + 0.35:
                old = b[3]
                b[3] = round(b[2] + lim, 3)
                nxt = bl[k + 1] if k + 1 < len(bl) else None
                if nxt is not None and nxt[0] == "F" and abs(nxt[2] - old) < 0.05:
                    nxt[2] = b[3]
                    notes.append(f"G block {b[1]}: ends with its scene at {b[3]:.1f} s; the footage after it starts there")
                else:
                    notes.append(f"G block {b[1]}: ends with its scene at {b[3]:.1f} s; the presenter fills to {old:.1f} s")
        keep.append(b)
    d["blocks"] = keep
    # over the share: the graphics with the least to see (and the longest) go first; the footage before (or after) covers
    # their time, else the presenter
    L = max([b[3] for b in d["blocks"] if b[0] != "INSERT"] + [1.0])
    if d.get("length_s"):
        L = d["length_s"]
    cap = pol["max_share"] * L

    def total():
        t = sum(b[3] - b[2] for b in d["blocks"] if b[0] == "G" and not b[1].startswith("news_"))
        ov = [n for n in d.get("overlays", []) if is_overlay_data(n) or n in set(d.get("rehook_scenes", []))]
        return t + sum(sc[n]["t_out"] - sc[n]["t_in"] for n in ov if n in sc)
    order = sorted([b for b in d["blocks"] if b[0] == "G" and not b[1].startswith("news_") and b[1] in sc],
                   key=lambda b: (bool({i.get("type") for i in sc[b[1]].get("items", [])} & VISUAL), -(b[3] - b[2])))
    for g in order:
        if total() <= cap:
            break
        bl = sorted(d["blocks"], key=lambda b: b[2] if b[0] != "INSERT" else b[1])
        k = next(i for i, b in enumerate(bl) if b is g)
        prev = bl[k - 1] if k and bl[k - 1][0] == "F" and abs(bl[k - 1][3] - g[2]) < 0.05 else None
        nxt = bl[k + 1] if k + 1 < len(bl) and bl[k + 1][0] == "F" and abs(bl[k + 1][2] - g[3]) < 0.05 else None
        if prev is not None:
            prev[3] = g[3]
        elif nxt is not None:
            nxt[2] = g[2]
        d["blocks"] = [b for b in d["blocks"] if b is not g]
        notes.append(f"graphic {g[1]} left out (over the {pol['max_share']:.0%} share): " + ("the footage covers its time" if prev is not None or nxt is not None
                                                                                            else "the presenter is on screen there"))
    return notes


def plan_problems(blocks, pol):
    types = [t for b in blocks for t, n in (b.get("material") or {}).items() for _ in range(int(n))]
    g, n = types.count("graphic"), len(types)
    cap = int(math.floor(pol["plan_max_share"] * n))
    return [f"the plan has {g} graphic shots of {n}; this channel plans at most {cap} ({pol['plan_max_share']:.0%}): real "
            "footage or archive instead"] if g > cap else []


def repair_plan(blocks, pol):
    """extra graphic shots counted as stock instead (the block with most graphics first) -> notes"""
    types = [t for b in blocks for t, n in (b.get("material") or {}).items() for _ in range(int(n))]
    over = types.count("graphic") - int(math.floor(pol["plan_max_share"] * len(types)))
    notes = []
    for b in sorted(blocks, key=lambda b: -int((b.get("material") or {}).get("graphic", 0))):
        if over <= 0:
            break
        m = b.get("material") or {}
        k = min(over, int(m.get("graphic", 0)))
        if k:
            m["graphic"] = int(m["graphic"]) - k
            m["stock"] = int(m.get("stock", 0)) + k
            over -= k
            notes.append(f"block {b.get('in')}-{b.get('out')}: {k} graphic shot(s) -> stock footage (the graphics budget)")
    return notes

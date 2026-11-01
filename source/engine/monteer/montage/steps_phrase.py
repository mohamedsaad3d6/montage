"""The phrase montage's steps (owner's decisions of 16 Oct 2026 on Works/output/v6_quality_report.md): the default for new
projects; project option "montage": "classic" keeps the earlier free-form montage (the same-result tests use it).

Brain decisions (each self-contained and checked in code, so the background brain answers them unattended):
  montage/shots       the phrase plan: every shot tied to the phrase it shows, every on-screen item on its word, our
                      graphics designed for the narration (montage/phrases.py)
  sources/assets_<n>  for each footage shot, the candidate that shows its phrase, chosen AFTER LOOKING AT THE THUMBNAILS
                      (one numbered contact sheet per shot; candidates found in code on free, licence-gated sources)
  montage/clip_fx     each downloaded clip's usable window (or reject), after looking at its contact sheet
  ai/pick             the seed of each AI image, judged on whether it shows the idea
Owner's answer 12 of 18 Oct 2026: flags and brand logos allowed in real footage when the profile says so (place.allowed);
drawn images never. Owner's decisions of 16 Oct 2026 on section 6 of the report (montage/place.py): a shot about Egypt shows Egypt (candidates
must name Egypt and no other country; the brain confirms on the thumbnail); no flags; brands as a place of that kind
without logo or name; the same picture (file or subject) at most twice within 75 s, at every stage that assigns one.
Everything else (music cues, AI prompts, the cut list, our graphics, transitions, the sound plan) is built in code by
montage/build.py and stored as decisions made by "code", so the rest of the engine reads them as before.
"""
import hashlib
import time
from pathlib import Path

from ..core.io import load_json, save_json
from . import build as B
from . import phrases as PH
from . import place as PL
from . import targets as TG

SHEET_COLS, CELL_W, CELL_H = 4, 400, 225
BATCH = 12                        # shots per choosing request (12 contact sheets)
SEARCH_THREADS = 4                # shots searched at once (each site keeps its own spacing: sources._turn)


def M(p, *n):
    return p.work.joinpath("montage", *n)


def code_decision(p, step, key, decision, why):
    save_json(p.decisions / step / f"{key}.json", {"step": step, "key": key, "made_by": "code (phrase montage)", "why": why,
                                                   "made_at": time.strftime("%Y-%m-%d %H:%M:%S"), "decision": decision})


def decided(p, step, key, default=None):
    f = p.decisions / step / f"{key}.json"
    return load_json(f)["decision"] if f.exists() else default


def clip_fx_of(p):
    """the clip review as {clip: settings}; anything else in it (a broken answer, 19 Oct 2026: [0, 0, 0.85]) is ignored"""
    fx = decided(p, "montage", "clip_fx", {}) or {}
    return {k: v for k, v in fx.items() if isinstance(v, dict)} if isinstance(fx, dict) else {}


def style(p):
    f = M(p, "style.json")
    if f.exists():
        return load_json(f)
    ch = p.channel
    st, last = B.variety(p, (ch / "style_ledger.json") if ch else M(p, "style_ledger.json"))
    save_json(f, dict(st, compared_with_last=len(last)))
    return st


def plan_of(p, words, L):
    return PH.Plan(decided(p, "montage", "shots"), words, L)


# ---------------------------------------------------------------------------------------------------- plan
def step_plan(p, words, L):
    from .maps import _load
    from .steps import ask
    lt, ni = PH.script_hints(p)
    save_json(M(p, "words.json"), PH.words_file(words, L, lt, ni))
    iso3 = {f["properties"].get("ADM0_A3") or f["properties"].get("ISO_A3") for f in _load("50m")}
    example = {"intro_end": 40, "sections": [{"from": 0, "title": "…", "music": "tense pulsing intro"}],
               "shots": [{"from": 0, "phrase": "…", "type": "stock", "shows": "…", "search": ["gas station"], "ai_prompt": "…"},
                         {"from": 6, "phrase": "…", "type": "graphic", "shows": "…", "graphic": "chain"}],
               "graphics": [{"id": "chain", "kind": "steps", "items": [{"text": "…", "at": 7}]}],
               "onscreen": [{"kind": "word", "text": "…", "at": 3}], "key_facts": [12]}
    example["mix_targets"] = {"base_shots": 2, "stock_max": 0, "archive_min": 1, "news_min": 0, "max_run": 3, "ai_max": 0, "why": "…"}
    from . import own_clips
    own = own_clips.usable(p)
    allow = PL.allowed(p)                  # flags and brand logos in real footage (answer 12 of 18 Oct 2026)
    from .structure import of as structure_of
    S = structure_of(p)                    # the channel's intro and pace (montage/structure.py)
    if S.fast_open is None:
        example["intro_end"] = 0
    from . import general as GEN, learning
    gen_rules = GEN.rules(p)              # «عام» (montage/general.py): real footage first, subjects, its caption bar

    from . import voice_check as VC
    sil = VC.plan_silences(p, words)      # long silences: one shot holds over each (channel profiles only)

    R = TG.rules_of(p)                     # the channel's own footage rules (video first, no drawn images), or None

    def check(dd):
        warn = PH.check(dd, words, L, {n["id"] for n in ni}, iso3, own, allow, S, sil=sil, R=R)
        extra = GEN.phrase_problems(p, dd, PH.Plan(dd, words, L), L) if gen_rules else []
        if sil:                            # owner's answer 2: the owner's own clip over a silence must not loop
            for k, h in VC.held_shots(PH.Plan(dd, words, L), dd["shots"], sil).items():
                s = dd["shots"][k]
                if s["type"] == "own" and (own or {}).get(s.get("clip")):
                    bad = VC.clip_problem(k, h, own[s["clip"]].get("seconds"), f"the owner's clip {s['clip']}")
                    if bad:
                        extra.append(bad)
        if extra:
            raise ValueError("; ".join(extra[:8]))
        return warn
    what = PH.instructions(L, bool(ni), own_clips.plan_text(p), p.instructions, flag_rule=PL.rule_text(p) if any(allow) else None, S=S, R=R)
    what += GEN.plan_text(p, "phrases") + VC.plan_text(sil) + learning.request_text(p, "montage/shots")
    d = ask(p, "montage", "shots", what, example,
            read=[M(p, "words.json")], schema=PH.SCHEMA,
            docs=["monteer/montage/phrases.py"] + (["monteer/montage/general.py"] if gen_rules else []), check=check,
            repair=lambda dd: PH.repair(dd, words, L, bool(ni), R))
    P = PH.Plan(d, words, L)
    share, warn = PH.mix_report(d, bool(ni), R)
    save_json(M(p, "plan_report.json"), {"mix": share, "warnings": warn, "intro_end_s": round(P.intro_end_s, 2), "stats": PH.stats(P),
                                         "style": style(p)})
    print(f"phrase montage: {len(d['shots'])} shots, intro {P.intro_end_s:.1f} s, {PH.stats(P)}; mix {share}; " + ("; ".join(warn) or "mix targets met"))


# ---------------------------------------------------------------------------------------------------- music
def step_music(p, words, L, make):
    d = decided(p, "montage", "shots")
    P = PH.Plan(d, words, L)
    cues = B.cues(d, P, style(p))
    from .structure import of as structure_of
    S = structure_of(p) if p.profile else None
    if S is not None and S.music_where == "none":   # no music under the voice (measured on the channel's own episodes)
        code_decision(p, "music", "cues", [], "the channel has no music under the voice (sound.music.where none)")
        print("music: none for this channel (its music is in its own clips only)")
        return
    t_cold = PH.cold_open_end(P, S) if S is not None and S.music_where == "cold_open_only" else None
    if t_cold is not None:             # music in the cold open only (الحدث الأخير, 4A): no track for a later section
        secs = sorted(d["sections"], key=lambda z: z["from"])
        late = {f"M{j + 1}" for j, sec in enumerate(secs) if j and P.t(sec["from"]) >= t_cold - 0.5}
        cues = [c for c in cues if c["name"] not in late]
    code_decision(p, "music", "cues", cues, "one cue per section of the phrase plan (rule 22)")
    if not p.profile:                  # the classic test projects: every cue made as before
        for c in cues:
            make(c)
        return
    pick_music(p, cues, strip=style(p).get("music_suffix", ""))


def pick_music(p, cues, strip="", log=print):
    """channel episodes (owner's decision of 19 Oct 2026, after the first fast-mode runs): no music is generated (ACE-Step
    is off); each section gets one of the instrumental tracks downloaded once into the music library (music/library.py,
    kind "track": a free licence with its credit line, no word heard), the best mood fit first, each track once while
    there are unused ones. The mix loops or cuts it to the section's length. A cue the episode already has from the
    library is kept; one made earlier by ACE-Step is set aside (<name>.generated_<time>, never deleted)."""
    import os
    from ..music import library as ML
    out = p.asset_dir("music")
    out.mkdir(parents=True, exist_ok=True)
    lib = ML.tracks()
    if not lib:
        raise SystemExit("music: the music library has no approved track (bin/monteer music tracks)")
    mine = [dict(c, prompt=c["prompt"].replace(strip, "") if strip else c["prompt"]) for c in cues]
    want = ML.pick_tracks(mine, lib)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    by = {c["name"]: c for c in cues}
    for name, k in want.items():
        js = out / f"{name}.json"
        j = load_json(js) if js.exists() else {}
        if (out / f"{name}.wav").exists() and j.get("from_library") == k and j.get("prompt") == by[name]["prompt"]:
            continue
        for ext in (".wav", ".json"):
            if (out / f"{name}{ext}").exists():
                os.replace(out / f"{name}{ext}", out / f"{name}.generated_{stamp}{ext}")
        ML.use(k, out, by[name], log)
    save_json(M(p, "music_plan.json"), {k: ["track", v] for k, v in want.items()})
    log(f"music: {len(want)} section(s), {len(set(want.values()))} different track(s) from the library; nothing generated")


# ---------------------------------------------------------------------------------------------------- sources
def short_terms(terms):
    """the brain's search words, plus the first two words of any longer one (stock sites drift on long phrases)"""
    out = []
    for q in terms:
        ws = q.split()
        for v in ([q, " ".join(ws[:2])] if len(ws) > 2 else [q]):
            if v.lower() not in (o.lower() for o in out):
                out.append(v)
    return out[:4]


def cand_code(c):
    """a candidate's picture code (V:, P:, S:), the same in the picks, the repeat rule and the re-plan"""
    from .sources import photos
    if c["kind"] == "stock":
        return f"V:{c['id']}"
    if c["kind"] == "library":
        return c["code"]
    if c.get("src"):
        return f"P:{photos.key_of(c['src'], c['id'])}"
    return "P:c" + hashlib.sha256(c["id"].encode()).hexdigest()[:10]       # a Commons photo of an earlier run (on this Mac)


def video_share_report(p, d, P, picks, R):
    """the footage's screen time by video and photo for a channel with its own video rule -> work/montage/video_share.json,
    said in the log (owner's decision of 20 Oct 2026: video at least 60%)"""
    parts, photos = [], []
    for k, code in picks.items():
        if d["shots"][k]["type"] not in PH.FOOTAGE:
            continue
        a, b = P.span(k)
        kind = "video" if code[:1] in "VS" else "photo"
        parts.append((b - a, kind))
        if kind == "photo":
            photos.append(k)
    sh, probs = TG.video_share(parts, R)
    save_json(M(p, "video_share.json"), {"share": round(sh, 3), "min": R["video_min"], "ok": not probs, "photo_shots": photos})
    print(f"video share: {sh:.0%} of the footage's screen time (this channel wants at least {R['video_min']:.0%})"
          + (f"; photos at shots {photos}" if probs else ""), flush=True)
    return sh, probs


def sb_terms(s):
    """a shot's searches for Storyblocks: its first two search words, years left out of an archive shot's"""
    out = []
    for q in short_terms(s.get("search") or [s["shows"]])[:2]:
        q = q if s["type"] == "stock" else " ".join(w for w in q.split() if not w.isdigit())
        if q and q not in out:
            out.append(q)
    return out


def stock_item(c, why):
    """a picked clip as fetch_all downloads it: Pixabay's by its number, Magnific's by its mg id with its page and author"""
    if c.get("source") == "storyblocks":
        return {"id": c["id"], "title": c.get("title") or c["about"], "for": why, "source": "storyblocks", "page": c.get("page", ""),
                "format": c.get("format", "1080p"), "mb": c.get("mb")}
    if c.get("source") == "magnific":
        return {"id": c["id"], "title": c["about"], "for": why, "source": "magnific", "page": c.get("page", ""), "user": c.get("user", ""),
                "premium": c.get("premium")}
    return {"id": int(c["id"]), "title": c["about"], "for": why, "source": "pixabay"}


def source_of(c):
    """the candidate's source in a few words (the contact sheet's caption and the brain's context)"""
    if c["kind"] == "library":
        return f"library {'clip' if c['code'].startswith('S:') else 'photo'}"
    if c["kind"] == "photo":
        return f"photo, {c.get('source') or 'Wikimedia Commons'}"
    if c.get("source") == "magnific":
        return "stock, Magnific"
    if c.get("source") == "storyblocks":
        return "stock video, Storyblocks (preferred for this channel)"
    return c["kind"].replace("_", " ")


def candidates_for(s, rejected, search, log=None, allow=(False, False), mg=False, sb=False, vf=False, po=False):
    """free, licence-gated candidates for one footage shot; each must hold every main word of its search (decision 2a).
    The sources are Pixabay (videos and photos) and the local library on this Mac only (owner's decision of 19 Oct 2026,
    after the first fast-mode runs: the museum sources, NASA and the Internet Archive's films gave 19 of 184 pictures and
    most of the search time). Archive shots: the local library (no network), then Pixabay's photos, then its videos; a
    shot about Egypt also looks in the library and Pixabay's photos, and keeps only candidates that name Egypt or an
    Egyptian place and no other country; no candidate with a flag or a brand in its words (montage/place.py), unless
    allow (the profile's (flags, brand logos), answer 12 of 18 Oct 2026) lets them in. mg: the channel turned Magnific
    on (sources/magnific.py, 20 Oct 2026): up to 3 of its clips join a stock or archive shot's candidates for each search.
    sb: the channel turned Storyblocks on (sources/storyblocks.py, S3 of 20 Oct 2026): its clips come FIRST (preferred),
    up to 3 for each of the shot's first two searches, from the searches made before (storyblocks.search_many).
    vf: the channel's video-first rule (targets.rules_of, owner's decision of 20 Oct 2026): an archive shot searches the
    stock videos too, and a shot's candidates are its videos only (Storyblocks, Magnific, Pixabay, library clips, in that
    order) whenever it has any; photos only when no video fits.
    po: the episode's «المصادر» is paid only (sources.mode): Storyblocks and Magnific only, no free footage."""
    from .sources import local_library as library, photos
    terms = short_terms(s.get("search") or [s["shows"]])

    def mg_clips(qs, ts):                  # up to 3 on-topic Magnific clips (the search is cached: asking twice is free)
        from .sources import magnific
        return [{"kind": "stock", "id": h["id"], "source": "magnific", "about": h["tags"], "seconds": h["seconds"], "thumb": h["thumb"],
                 "page": h["page"], "user": h["user"], "premium": h["premium"]}
                for h in magnific.small_only(search.on_topic(magnific.search(qs, 40)[0], ts, lambda h: h["tags"]), 3)]
    home = s.get("place") == PL.HOME
    lib = library.search("")
    text = lambda h: h["title"] + " " + (h.get("description") or "")          # noqa: E731
    out = []
    if sb:                                 # the company's Storyblocks clips first (searched before, all shots at once)
        from .sources import storyblocks
        for q in sb_terms(s)[:2]:
            ts = PL.topic_query(s, q)
            out += [{"kind": "stock", "id": h["id"], "source": "storyblocks", "about": h["tags"][:300], "seconds": h["seconds"],
                     "thumb": h["thumb"], "page": h["page"], "title": h["title"], "format": h["format"], "mb": h["mb"]}
                    for h in search.on_topic(storyblocks.cached(q) or [], ts, lambda h: h["tags"])[:3]]
    if po:                                 # «المصادر»: paid only: Magnific's clips too, and no free search at all
        for q in terms[:3]:
            qs = q if s["type"] == "stock" else " ".join(w for w in q.split() if not w.isdigit())
            if mg and qs:
                out += mg_clips(qs, PL.topic_query(s, qs))
        terms = []
    for q in terms[:3]:
        t = PL.topic_query(s, q)
        if s["type"] == "archive" or home:
            out += [{"kind": "library", "id": h["code"], "code": h["code"], "title": h["title"],
                     "about": (h["title"].replace("File:", "") + " " + (h.get("description") or ""))[:140], "licence": h["licence"],
                     "page": h.get("page", ""), "author": h.get("author", ""), "local": str(library.LIB / h["file"]), "thumb": "local"}
                    for h in search.on_topic(lib, t, text)[:3]]
            for src in photos.SOURCES:
                out += [{"kind": "photo", "src": src, "source": h["source"], "id": h["id"], "title": h["title"],
                         "about": text(h)[:140], "licence": h["licence"], "page": h.get("page", ""), "author": h.get("author", ""),
                         "thumb": h["thumb"], **({"full": h["full"]} if h.get("full") else {}),
                         **({"ai_generated": True} if h.get("ai_generated") else {})}
                        for h in search.on_topic(photos.search(src, q), t, text)[:2]]
        qs = q if s["type"] == "stock" else " ".join(w for w in q.split() if not w.isdigit())
        ts = PL.topic_query(s, qs)
        if s["type"] == "stock" or (qs and not out) or (vf and qs):
            got = [{"kind": "stock", "id": str(h["id"]), "about": h["tags"], "seconds": h["seconds"], "thumb": h.get("thumb", ""),
                    "ai_generated": h.get("ai_generated", False)}
                   for h in search.on_topic(search.pixabay(qs, 60)[0], ts, lambda h: h["tags"], tagged=True)[:5]]
            out += got
            if mg and qs:                                  # the channel's paid clips (sources/magnific.py)
                more = mg_clips(qs, ts)
                got, out = got + more, out + more
            if s["type"] == "stock" and not got:          # no clip: a still from Pixabay's photos
                out += [{"kind": "photo", "src": "pixabay", "source": h["source"], "id": h["id"], "title": h["title"], "about": text(h)[:140],
                         "licence": h["licence"], "page": h.get("page", ""), "author": h.get("author", ""), "thumb": h["thumb"],
                         **({"ai_generated": True} if h.get("ai_generated") else {})}
                        for h in search.on_topic(photos.search("pixabay", qs), ts, text)[:2]]
        elif mg and qs:                                    # an archive shot: its moving footage from Magnific too
            out += mg_clips(qs, ts)
        if len(out) >= 12:                  # enough to choose from: the next search words are not needed
            break
    if vf:                                 # video first: the shot's videos only, when it has any
        vids = [c for c in out if c["kind"] == "stock" or (c["kind"] == "library" and c["code"].startswith("S:"))]
        if vids:
            rank = {"storyblocks": 0, "magnific": 1}
            out = sorted(vids, key=lambda c: rank.get(c.get("source"), 2 if c["kind"] == "stock" else 3))
    seen, res = set(), []
    for c in out:
        if (c["kind"], c["id"]) in seen or c["id"] in rejected or not c.get("thumb"):
            continue
        seen.add((c["kind"], c["id"]))
        why = PL.candidate_problem(s, c["id"] + " " + c["about"] if c["kind"] == "photo" and not c.get("src") else c["about"], *allow)
        if why:
            if log is not None:
                log.append({"kind": c["kind"], "id": c["id"], "about": c["about"][:100], "refused": why})
            continue
        res.append(c)
    return res[:8]


_kept_lock = __import__("threading").Lock()


def kept_candidates(p, tag, s, rejected, allow, compute):
    """owner's decision 6a of 19 Oct 2026: the candidates a shot found before are kept while what it searches for is the
    same, so its contact sheet and the brain's request stay the same when the step runs again (the first real test
    asked Claude again after code fixes because a search answered differently a day later). A clip refused since then
    leaves the list. -> work/montage/candidates_kept.json {tag: {"sig", "cands"}}"""
    import json
    from .sources import magnific
    from .sources import storyblocks, mode as src_mode
    srcs = [3] + (["magnific"] if magnific.on(p) else []) + (["storyblocks"] if storyblocks.on(p) else []) + \
        (["video-first"] if TG.video_first(p) else []) + ([f"sources:{src_mode(p)}"] if src_mode(p) != "both" else [])   # 3: Pixabay, the library
    sig = hashlib.sha256(json.dumps([{x: s.get(x) for x in ("type", "shows", "search", "place", "subject")}, list(allow), *srcs],
                                    sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    store = M(p, "candidates_kept.json")
    old = (load_json(store) if store.exists() else {}).get(tag)
    if old and old["sig"] == sig:
        return [c for c in old["cands"] if c["id"] not in rejected]
    c = compute()
    if c:                              # an empty answer (a network failure) is never kept
        with _kept_lock:
            keep = load_json(store) if store.exists() else {}
            keep[tag] = {"sig": sig, "cands": c}
            save_json(store, keep)
    return c


def thumb_file(p, c):
    safe = hashlib.sha256(f"{c['kind']}:{c['id']}".encode()).hexdigest()[:16]
    return M(p, "thumbs", f"{c['kind']}_{safe}.jpg")


def fetch_thumbs(p, cands, curl, ua):
    """small preview images, only for choosing (never shown in the video); a library file's preview is made here"""
    for c in cands:
        f = thumb_file(p, c)
        if f.exists() and f.stat().st_size > 1000:
            continue
        f.parent.mkdir(parents=True, exist_ok=True)
        part = f.with_suffix(".part")
        if c.get("local"):
            local_thumb(c["local"], part)
            if part.exists() and part.stat().st_size > 1000:
                part.replace(f)
            continue
        code, _ = curl(c["thumb"], out=part, ua=ua)
        if code == "200" and part.exists() and part.stat().st_size > 1000:
            part.replace(f)
        elif part.exists():
            part.unlink()


def local_thumb(src, out):
    """a 480 px preview of a picture or of a clip's frame at 1 s, written as JPEG"""
    import subprocess
    from ..core.paths import FFMPEG
    vf = "scale=480:-2"
    if str(src).endswith(".mp4"):
        subprocess.run([str(FFMPEG), "-v", "error", "-y", "-ss", "1", "-i", str(src), "-frames:v", "1", "-vf", vf, "-f", "image2",
                        str(out)], capture_output=True)
        return
    from PIL import Image
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((480, 480))
        im.save(out, "JPEG", quality=85)


def contact_sheet(p, k, cands, numbers=None, name=None):
    """one numbered sheet per shot: what the brain looks at before it chooses (owner's decision 2a); numbers: each
    candidate's own number when only some are shown (the ones still free to use)"""
    return sheet_of([(thumb_file(p, c), source_of(c)) for c in cands], M(p, "thumbs", name or f"shot_{k:03d}.jpg"), numbers)


def sheet_of(items, out, numbers=None):
    """a numbered grid of images: [(image file, small caption)] -> out (numbers: the label of each, default 1, 2, 3 …)"""
    from PIL import Image, ImageDraw, ImageFont
    rows = max(1, -(-len(items) // SHEET_COLS))
    sheet = Image.new("RGB", (SHEET_COLS * CELL_W, rows * (CELL_H + 40)), (24, 22, 20))
    dr = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 30)
    except OSError:
        font = ImageFont.load_default()
    for n, (f, cap) in enumerate(items):
        x, y = (n % SHEET_COLS) * CELL_W, (n // SHEET_COLS) * (CELL_H + 40)
        if Path(f).exists():
            try:
                im = Image.open(f).convert("RGB")
                im.thumbnail((CELL_W - 8, CELL_H - 8))
                sheet.paste(im, (x + (CELL_W - im.width) // 2, y + 40 + (CELL_H - im.height) // 2))
            except OSError:
                pass
        dr.rectangle([x + 4, y + 4, x + 64, y + 38], fill=(224, 176, 74))
        dr.text((x + 14, y + 6), str(numbers[n] if numbers else n + 1), fill=(0, 0, 0), font=font)
        dr.text((x + 74, y + 8), cap, fill=(220, 220, 220), font=font)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, quality=88)
    return out


SCHEMA_PICKS = {"type": "object", "required": ["picks"], "properties": {"picks": {"type": "array", "items": {
    "type": "object", "required": ["shot", "n"], "properties": {"shot": {"type": "integer"}, "n": {"type": "integer"}, "why": {"type": "string"},
                                                                "shows_egypt": {"type": "boolean"}}}}}}
PICK_WHAT = (
    "Choose the picture of each footage shot AFTER LOOKING AT ITS CONTACT SHEET (read every sheet image listed: one per "
    "shot, numbered thumbnails; the context lists each candidate's number, source and tags). Answer n = the number of the "
    "candidate that SHOWS what the shot's phrase says, or 0 when none does (a drawn image or a card is made instead). "
    "TOPIC FIRST: a picture must match the phrase's meaning (a pump for petrol prices, a refinery for refining, an "
    "old photo of car queues for the 1970s lines); a near miss is a 0 (an electric-car charger is not petrol, an oil "
    "spill is not oil supply, a cartoon or 3D render is not a real-world thing). VARIETY SECOND: in the fast intro, prefer "
    "a picture not used by the neighbouring shots when an on-topic one exists, but a repeat of an on-topic picture beats "
    "an off-topic one (the context lists what earlier shots already use). Refuse brand names, logos, readable shop signs "
    "and close-up faces of private people. "
    "OWNER'S DECISIONS: (1) a shot marked place EGY is about Egypt or the Egyptian government: choose only a picture that "
    "shows EGYPT (an Egyptian street, an Egyptian government building or place; Arabic signs, Cairo's look) and answer "
    "shows_egypt: true for it; anything that looks like another country is a 0. NO FLAGS of any country anywhere in the "
    "picture (a flag on a building is a 0). A candidate whose title names a company, store or brand is a 0 even when its "
    "sign is only partly in view; a brand is shown as a place of that kind without logo or name. (2) The same picture may "
    "repeat, but not 3 times within 75 s: the context lists which picture each earlier shot uses and when; treat a "
    "different clip of the same thing (the Earth from space) as the same picture. (Phase 2) MOVING FOOTAGE FIRST: when a "
    "video clip (stock, archive video) and a still photo both show the phrase, choose the clip. FEWER REPEATS: a picture "
    "file already used is a last resort; one file at most twice in the video, its two showings at least 60 s apart. "
    "Answer with JSON only.")
PICK_BAN = ("Refuse brand names, logos, readable shop signs and close-up faces of private people. ",
            " NO FLAGS of any country anywhere in the picture (a flag on a building is a 0). A candidate whose title names a "
            "company, store or brand is a 0 even when its sign is only partly in view; a brand is shown as a place of that "
            "kind without logo or name.")


def pick_what(p):
    """PICK_WHAT for this project: without a profile as it was; when the profile allows flags and brand logos in real
    footage (answer 12 of 18 Oct 2026), the refusals of flags, logos and brands are taken out"""
    flags_ok, brands_ok = PL.allowed(p)
    vf = (" VIDEO FIRST (this channel, owner's decision): when a video clip and a still photo both fit a shot, choose the "
          "video." if TG.video_first(p) else "")
    if not (flags_ok or brands_ok):
        return PICK_WHAT + vf
    out = PICK_WHAT.replace(PICK_BAN[0], "Refuse close-up faces of private people"
                            + ("" if brands_ok else ", brand names, logos and readable shop signs") + ". ")
    return out.replace(PICK_BAN[1], " " + PL.rule_text(p) + ".") + vf


def pick_pictures(p, d, P, cand, sheets, held):
    """the brain chooses each footage shot's picture from its contact sheet, BATCH shots a request -> {shot: candidate n}"""
    from .steps import ask
    from . import voice_check as VC
    chosen = {}
    code_of = lambda k, n: cand_code(cand[k][n - 1])                                     # noqa: E731
    ks = sorted(cand)
    free = bool(p.profile)            # channel episodes (owner's decision of 19 Oct 2026, after the first real test stopped
    kept = load_json(M(p, "picks_kept.json")) if free and M(p, "picks_kept.json").exists() else {}   # here): a candidate already
    for n0 in range(0, len(ks), BATCH):   # used up is not offered; each shows its file code
        part = ks[n0:n0 + BATCH]
        if free:                           # a re-run: each shot's earlier picture, while the engine still accepts it
            from .edits import edits_text
            if not edits_text(p, "sources", f"assets_{n0 // BATCH + 1}"):
                part = keep_earlier(d, P, cand, held, chosen, part, kept)
            if not part:
                continue
        offer, sheet = {k: list(range(1, len(cand[k]) + 1)) for k in part}, dict(sheets)
        if free:
            uses = [(P.span(k)[0], code_of(k, n)) for k, n in chosen.items()]
            for k in part:
                offer[k] = [n for n in offer[k] if PL.file_ok(uses, P.span(k)[0], code_of(k, n))]
                if offer[k] and len(offer[k]) < len(cand[k]):
                    sheet[k] = contact_sheet(p, k, [cand[k][n - 1] for n in offer[k]], offer[k], f"shot_{k:03d}_free.jpg")
            gone = [k for k in part if not offer[k]]
            if gone:
                print(f"sources: shot(s) {gone}: every candidate already used up (twice, or within {PL.FILE_GAP_S:.0f} s); "
                      "no picture here (the re-plan takes them)", flush=True)
            part = [k for k in part if offer[k]]
            if not part:
                continue
        used_at = {}
        for k, n in chosen.items():
            used_at.setdefault(code_of(k, n), []).append(round(P.span(k)[0], 1))
        ctx = {"shots": [{"shot": k, "phrase": d["shots"][k].get("phrase", ""), "shows": d["shots"][k]["shows"], "type": d["shots"][k]["type"],
                          "subject": d["shots"][k].get("subject", ""), "at_s": round(P.span(k)[0], 2),
                          **({"place": "EGY: must show Egypt"} if d["shots"][k].get("place") == PL.HOME else {}),
                          "seconds": round(P.span(k)[1] - P.span(k)[0], 2), "intro": P.span(k)[0] < P.intro_end_s - 0.05,
                          "sheet": str(sheet[k].relative_to(p.folder)),
                          **({"holds_over_silence": held[k]} if k in held else {}),
                          "candidates": [{"n": i + 1, "source": source_of(x), "tags_or_title": x["about"][:140],
                                          **({"file": cand_code(x)} if free else {}),
                                          **({"already_used_at_s": used_at[cand_code(x)]} if free and cand_code(x) in used_at else {}),
                                          **({"ai_generated_stock": True} if x.get("ai_generated") else {})}
                                         for i, x in enumerate(cand[k]) if i + 1 in offer[k]]}
                         for k in part],
               "earlier_shots_use": {str(k): {"picture": code_of(k, chosen[k]), "at_s": round(P.span(k)[0], 2)} for k in chosen}}
        if free:
            ctx["files"] = ("Each candidate shows its file code (\"file\"), the same code as earlier_shots_use; candidates already used "
                            "twice, or within 60 s, are not offered. Two shots of this request may share a file only once, 60 s apart.")

        def check(dd, part=part, offer=offer):
            got = {x["shot"]: x["n"] for x in dd["picks"]}
            miss = [k for k in part if k not in got]
            bad = [k for k in part if k in got and got[k] and got[k] not in offer[k]]
            if miss or bad:
                raise ValueError(f"answer every shot of this request once ({part}); missing {miss}, number not offered {bad}")
            probs = [f"shot {x['shot']} is about Egypt (place EGY): choose a picture that shows Egypt and say shows_egypt: true, or 0"
                     for x in dd["picks"] if x["n"] and d["shots"][x["shot"]].get("place") == PL.HOME and x.get("shows_egypt") is not True]
            uses = [(P.span(k)[0], code_of(k, n)) for k, n in chosen.items()]
            for k in sorted(got):
                if got[k]:
                    if not PL.file_ok(uses, P.span(k)[0], code_of(k, got[k])):
                        probs.append(f"shot {k}: candidate {got[k]} is already used (one picture file at most twice in the video, "
                                     "at least 60 s apart); choose another or 0")
                    uses.append((P.span(k)[0], code_of(k, got[k])))
            for k in sorted(got):              # owner's answer 2: a shot held over a silence never loops a short clip
                if got[k] and k in held and cand[k][got[k] - 1]["kind"] == "stock":
                    bad = VC.clip_problem(k, held[k], cand[k][got[k] - 1].get("seconds"), f"candidate {got[k]}")
                    if bad:
                        probs.append(bad + "; or 0")
            if probs:
                raise ValueError("; ".join(probs))

        def settle(dd, part=part, offer=offer):      # the last resort (ask): a pick that breaks a rule -> no picture (0)
            got = {x["shot"]: x for x in dd["picks"] if x.get("shot") in part}
            uses, out, notes = [(P.span(k)[0], code_of(k, n)) for k, n in chosen.items()], [], []
            for k in part:
                x = dict(got.get(k) or {"shot": k, "n": 0, "why": "not answered"})
                n = x.get("n") or 0
                ok = not n or (n in offer[k] and PL.file_ok(uses, P.span(k)[0], code_of(k, n))
                               and not (d["shots"][k].get("place") == PL.HOME and x.get("shows_egypt") is not True)
                               and not (k in held and cand[k][n - 1]["kind"] == "stock"
                                        and VC.clip_problem(k, held[k], cand[k][n - 1].get("seconds"), "")))
                if not ok:
                    notes.append(f"shot {k}: candidate {n} left out (no picture; the re-plan takes it)")
                    x.update(n=0, why=f"left out by the engine: candidate {n} broke a rule")
                elif n:
                    uses.append((P.span(k)[0], code_of(k, n)))
                out.append(x)
            return dict(dd, picks=out), notes
        r = ask(p, "sources", f"assets_{n0 // BATCH + 1}", pick_what(p) + VC.pick_text({k: held[k] for k in part if k in held}),
                {"picks": [{"shot": part[0], "n": offer[part[0]][0], "why": "…"}]},
                read=[sheet[k] for k in part], extra={"context": ctx}, schema=SCHEMA_PICKS, check=check, settle=settle,
                fallback={"picks": []})           # no answer: every shot of the batch without a picture (the re-plan takes them)
        for x in r["picks"]:
            if x["shot"] in part and x["n"]:
                chosen[x["shot"]] = x["n"]
        if free:                           # each shot's choice by its file code, for the next run (keep_earlier)
            by = {x["shot"]: x for x in r["picks"]}
            for k in part:
                x = by.get(k) or {}
                kept[str(k)] = {"sig": shot_sig(d, P, k), "code": code_of(k, chosen[k]) if k in chosen else None,
                                "seen": [code_of(k, n) for n in offer[k]], "shows_egypt": x.get("shows_egypt") is True,
                                "by_engine": str(x.get("why", "")).startswith(BY_ENGINE)}
            save_json(M(p, "picks_kept.json"), kept)
    return chosen


BY_ENGINE = ("left out by the engine", "not answered")     # a "no picture" the engine set (last resort, fallback): asked again


def shot_sig(d, P, k):
    """what a shot's picture answers to: its plan and its place on the timeline"""
    import json
    s = d["shots"][k]
    return hashlib.sha256(json.dumps([{x: s.get(x) for x in ("type", "shows", "search", "place", "subject", "phrase")},
                                      [round(t, 2) for t in P.span(k)]], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def keep_earlier(d, P, cand, held, chosen, part, kept):
    """a channel episode's re-run (owner's decision of 20 Oct 2026: the run of that morning asked Claude again for all 17
    batches after a code fix, because the clip review had refused 9 clips and each batch's request names the earlier
    batches' choices): a shot keeps its earlier picture, by file code (candidate numbers move when a clip leaves the list),
    while the shot is the same, the file is still a candidate and the rules still accept it (one file at most twice,
    60 s apart; Egypt; a held shot's clip long enough); a shot Claude left without a picture stays so unless a new
    candidate came. -> the shots still to ask (chosen gets the kept ones)"""
    from . import voice_check as VC
    uses = [(P.span(k)[0], cand_code(cand[k][n - 1])) for k, n in chosen.items()]
    ask_now, keep = [], []
    for k in part:
        e = kept.get(str(k)) or {}
        codes = {}
        for n in range(1, len(cand[k]) + 1):
            if PL.file_ok(uses, P.span(k)[0], cand_code(cand[k][n - 1])):
                codes.setdefault(cand_code(cand[k][n - 1]), n)
        same = bool(e) and e.get("sig") == shot_sig(d, P, k)
        if same and e.get("code") is None and not e.get("by_engine") and set(codes) <= set(e.get("seen", [])):
            keep.append(k)
            continue
        n = codes.get(e.get("code")) if same and e.get("code") else None
        if n and not (d["shots"][k].get("place") == PL.HOME and not e.get("shows_egypt")) and \
                not (k in held and cand[k][n - 1]["kind"] == "stock" and VC.clip_problem(k, held[k], cand[k][n - 1].get("seconds"), "")):
            chosen[k] = n
            uses.append((P.span(k)[0], e["code"]))
            keep.append(k)
            continue
        ask_now.append(k)
    if keep:
        print(f"sources: {len(keep)} shot(s) keep the earlier run's choice (the engine still accepts it)"
              + (f"; asked again: {ask_now}" if ask_now else ""), flush=True)
    return ask_now


def step_sources(p, words, L):
    from .sources import UA_API, Ledger, asset_ok, curl, fetch_all, search, sweep
    from .sources import local_library as library
    from .steps import ask
    sweep(p)                              # owner's answer 1a: earlier runs' broken files go to work/assets/set_aside
    d = decided(p, "montage", "shots")
    P = PH.Plan(d, words, L)
    fx = clip_fx_of(p)
    rejected = {k for k, v in fx.items() if isinstance(v, dict) and v.get("reject")}      # seen and refused before
    cand, sheets, refused = {}, {}, {}
    from . import voice_check as VC        # shots held over a long silence (channel profiles; none for the classic tests)
    held = VC.held_shots(P, d["shots"], VC.plan_silences(p, words))
    allow = PL.allowed(p)
    from .sources import magnific
    mg = magnific.on(p)                # the channel's Magnific clips (sources/magnific.py)
    magnific.episode_reading(p, "episode start")     # the credit balance before (usage view: credits spent per episode)
    from .sources import mode as sources_mode
    po = sources_mode(p) == "paid"     # «المصادر» of this episode: paid only
    from .sources import storyblocks
    R = TG.rules_of(p)                 # the channel's own footage rules: video first (or None)
    sb = storyblocks.on(p)             # the company's Storyblocks clips: every shot's searches at once, before (one run per 12)
    if sb:
        storyblocks.search_many([q for s in d["shots"] if s["type"] in ("stock", "archive") for q in sb_terms(s)],
                                p.work / "montage" / "storyblocks_runs", project=p.folder.name)

    def gather(k):                     # one shot's searches and previews (several shots at once: SEARCH_THREADS)
        no = []
        c = kept_candidates(p, f"shot {k}", d["shots"][k], rejected, allow,
                            lambda: candidates_for(d["shots"][k], rejected, search, no, allow, mg=mg, sb=sb, vf=bool(TG.video_first(p)),
                                                   po=po))
        fetch_thumbs(p, c, curl, UA_API)
        return k, [x for x in c if thumb_file(p, x).exists()], no          # the brain must see every candidate
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(SEARCH_THREADS) as ex:
        for k, c, no in ex.map(gather, [k for k, s in enumerate(d["shots"]) if s["type"] in ("stock", "archive")]):
            refused[k] = no
            if c:
                cand[k] = c
                sheets[k] = contact_sheet(p, k, c)
    save_json(M(p, "candidates.json"), {"by_shot": {str(k): v for k, v in cand.items()}, "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                                        "refused_in_code": {str(k): v for k, v in refused.items() if v}})
    chosen = pick_pictures(p, d, P, cand, sheets, held)
    from .edits import pick_overrides            # the owner's «غيّرها» on a picture (edit rounds): after the picks are made
    for k, n in pick_overrides(p).items():
        if k in cand and 1 <= n <= len(cand[k]):
            chosen[k] = n
    stock, stills, libs, picks, thumbs = [], [], set(), {}, {}
    for k, n in chosen.items():
        c = cand[k][n - 1]
        thumbs[k] = str(thumb_file(p, c))
        picks[k] = cand_code(c)
        if c["kind"] == "stock":
            stock.append(stock_item(c, f"shot {k}"))
        elif c["kind"] == "library":
            libs.add(c["code"])
        elif c["kind"] == "photo" and c.get("src"):
            stills.append(c)
        elif c["kind"] == "photo":                                       # a Commons photo of an earlier run: on this Mac only
            stills.append({"key": picks[k][2:], "title": c["id"], "licence": c["licence"], "page": c.get("page", ""), "author": c.get("author", "")})
    fetch_all(p, {"stock": list({z["id"]: z for z in stock}.values()), "photos": list({cand_code(dict(z, kind="photo")) if z.get("src") else z["key"]: z
                                                                                        for z in stills}.values())})
    led = Ledger(p)
    for code in sorted(libs):
        library.use(p, code, led)
    magnific.episode_reading(p, "episode end")       # and after the downloads

    def exists(code):                 # keep only what really arrived (a refused or failed download is never shown)
        kd, key = code.split(":", 1)
        f = {"V": p.asset_dir("stock") / f"{key}.mp4", "P": p.asset_dir("photos") / f"{key}.jpg", "S": p.asset_dir("library") / f"{key}.mp4"}[kd]
        return f.exists() and f.stat().st_size > 20000 and asset_ok(p, code)      # a real picture or video (answer 1a)
    for k, s in enumerate(d["shots"]):          # the owner's own clips (decision 8b): the plan named the clip itself
        if s["type"] == "own" and s.get("clip"):
            picks[k] = f"S:{s['clip']}"
            thumbs[k] = str(p.work / "montage" / "own_clips" / f"{s['clip']}_1.jpg")
    picks = {k: v for k, v in picks.items() if exists(v)}
    if held:                                   # after download: a clip whose length was not known before must not loop
        from .own_clips import duration
        rec = {}
        for k, h in held.items():
            code = picks.get(k)
            if not code:
                rec[str(k)] = dict(h, result="no picture: a card of the words said" if d["shots"][k]["type"] in ("stock", "archive")
                                   else f"a {d['shots'][k]['type']} shot (no clip)")
                continue
            kd, key = code.split(":", 1)
            if kd == "P":
                rec[str(k)] = dict(h, result=f"a photo ({code})")
                continue
            f = {"V": p.asset_dir("stock") / f"{key}.mp4", "S": p.asset_dir("library") / f"{key}.mp4"}[kd]
            secs = round(duration(f) or 0.0, 1)
            bad = VC.clip_problem(k, h, secs, f"clip {code}")
            if bad:
                del picks[k]
                rec[str(k)] = dict(h, result=f"clip {code} lasts {secs:.1f} s, too short (it would loop): left out, a card of the words said")
            else:
                rec[str(k)] = dict(h, result=f"clip {code} ({secs:.1f} s)")
        save_json(M(p, "held_shots.json"), rec)
    save_json(M(p, "picks.json"), {str(k): v for k, v in picks.items()})
    if R and R.get("video_min"):               # the channel's video rule, measured on the picks (said, never a stop)
        video_share_report(p, d, P, picks, R)
    save_json(M(p, "pick_thumbs.json"), {str(k): thumbs[k] for k in picks})
    from . import own_clips
    own = own_clips.usable(p)
    save_json(M(p, "pick_about.json"), {str(k): (cand[k][chosen[k] - 1]["about"] if k in chosen else
                                                 own.get(picks[k][2:], {}).get("shows", "the owner's own clip")) for k in picks})
    print(f"sources: {len(picks)} of {sum(1 for s in d['shots'] if s['type'] in ('stock', 'archive'))} footage shots have a chosen picture "
          f"({len(cand)} had on-topic candidates)")


# ---------------------------------------------------------------------------------------------------- AI images
def usable_picks(p):
    """the chosen pictures minus the clips the review rejected (seen on their contact sheets)"""
    picks = {int(k): v for k, v in load_json(M(p, "picks.json")).items()} if M(p, "picks.json").exists() else {}
    fx = clip_fx_of(p)
    bad = {k for k, v in fx.items() if isinstance(v, dict) and v.get("reject")}
    from .review import BLACK_BELOW, clip_luma          # a nearly black clip is never shown (it falls to a drawn image)
    dark = {v.split(":", 1)[1] for v in picks.values() if v.startswith(("V:", "S:"))
            and (clip_luma(p, v.split(":", 1)[1]) or 255) < BLACK_BELOW}
    from .sources import asset_ok                       # a pick whose file is not a real picture or video counts as missing
    return {k: v for k, v in picks.items() if v.split(":", 1)[1] not in bad | dark and asset_ok(p, v)}


def ai_key(k):
    return f"k{k:03d}"


def ai_prompts(p):
    """drawn images for the plan's ai shots, at most MAX_AI (generic scenes only). A footage shot with no usable picture
    is planned again first (replan_missing: new searches, moving footage first), with a drawn image only as that plan's
    fallback (Phase 2: more moving footage, fewer stills)"""
    d = decided(p, "montage", "shots")
    want = [k for k, s in enumerate(d["shots"]) if s["type"] == "ai"]
    out = {}
    for k in want[:PH.MAX_AI]:
        s = d["shots"][k]
        base = s.get("ai_prompt") or f"{s['shows']}, generic scene"
        look = ("cinematic photo style, generic, no people's faces in close-up" if s["type"] == "stock"
                else "editorial illustration, hand-drawn look, muted colours")      # past or real events: clearly drawn
        out[ai_key(k)] = {"prompt": f"{base}, {look}, no text, no logos, no letters, no flags",
                          "why": f"shot {k} ({s['type']}): «{s.get('phrase', '')}»" + (" (about Egypt: must look like Egypt)" if s.get("place") == PL.HOME else "")}
    keep = {k: v for k, v in (decided(p, "ai", "prompts", {}) or {}).items() if k.startswith("r")}     # the re-plan's own
    if p.profile:                      # channel episodes: the re-plan adds its own again, for this run only (cap 3a)
        keep = {}
    code_decision(p, "ai", "prompts", dict(out, **keep), "the plan's ai shots (generic scenes only); r###: shots planned again")
    return out


def pick_context(p):
    pr = decided(p, "ai", "prompts", {}) or {}
    return {k: {"prompt": v["prompt"], "for": v.get("why", "")} for k, v in pr.items() if not k.startswith("r")}   # r###: re-plans


# ---------------------------------------------------------------------------------------------------- one shot planned again
SCHEMA_REPLAN = {"type": "object", "required": ["shots"], "properties": {"shots": {"type": "array", "items": {
    "type": "object", "required": ["shot", "try", "headline"], "properties": {
        "shot": {"type": "integer"}, "try": {"type": "string", "enum": ["search", "ai", "graphic"]},
        "type": {"type": "string", "enum": ["stock", "archive"]}, "search": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "ai_prompt": {"type": "string"}, "headline": {"type": "string"}, "keyword": {"type": "string"}, "why": {"type": "string"}}}}}}


def why_missing(p, k, s):
    cand = load_json(M(p, "candidates.json"))["by_shot"] if M(p, "candidates.json").exists() else {}
    picks = load_json(M(p, "picks.json")) if M(p, "picks.json").exists() else {}
    if s["type"] == "ai":
        return "its drawn image was refused (it did not show the idea)"
    if str(k) not in cand:
        return "no candidate held the search's words (" + ", ".join(s.get("search") or []) + ")"
    if str(k) not in picks:
        return f"none of its {len(cand[str(k)])} candidates showed the phrase"
    return ("its chosen clip was rejected on sight (dark, watermark or unusable)" if all(PL.allowed(p))
            else "its chosen clip was rejected on sight (dark, logo, flag or unusable)")


PUNCT = "،,؛;:.!؟?«»\"'()…-"
HEADLINE_MAX = 5


def fit_headline(said, headline, keyword="", n=HEADLINE_MAX):
    """the headline card's words, fitted in code (owner's answer 3a of 19 Oct 2026, after a re-plan was sent back three
    times for a long headline): at most n words, contiguous, exactly as the narrator says them in this shot (said), the
    window that shares the most words with the brain's headline (and holds its keyword), preferring one that ends where a
    phrase ends; the keyword is a word of it. -> (headline, keyword)"""
    ws, ends = [], set()
    for raw in said.split():                  # the words without punctuation; where a comma or a stop follows a word
        w = raw.strip(PUNCT)
        if w:
            ws.append(w)
        if ws and raw[-1:] in PUNCT:
            ends.add(len(ws) - 1)
    if not ws:
        return headline, keyword
    ends.add(len(ws) - 1)
    nw = [PH.norm(w) for w in ws]
    want = {PH.norm(w.strip(PUNCT)) for w in headline.split()} - {""}
    kw = PH.norm((keyword or "").strip(PUNCT))
    hit = lambda w: w in want or (len(w) > 2 and w[0] in "وفبلك" and w[1:] in want)   # noqa: E731  (one joined prefix)
    best = None
    for a in range(len(ws)):
        for b in range(a, min(len(ws), a + n)):
            win = nw[a:b + 1]
            score = (kw in win or any(w[1:] == kw for w in win) if kw else True, sum(1 for w in win if hit(w)), b in ends, -(b - a), -a)
            if best is None or score > best[0]:
                best = (score, a, b)
    _, a, b = best
    out = ws[a:b + 1]
    k = next((w for w in out if kw and kw in (PH.norm(w), PH.norm(w)[1:])), None) or \
        max((w for w in out if hit(PH.norm(w))), key=len, default=None) or max(out, key=len)
    return " ".join(out), k


def ai_room(p, d):
    """how many drawn images the re-plan may still add: the plan's ai_max less its own ai shots; a channel episode at most
    AI_TOTAL_MAX in all (owner's decision 3a of 19 Oct 2026)"""
    cap = (d.get("mix_targets") or {}).get("ai_max", 99)
    if p.profile:
        cap = min(cap, PH.AI_TOTAL_MAX)
    R = TG.rules_of(p)
    if R and not R["ai"]:              # the channel uses no drawn images: the re-plan never adds one (headline card instead)
        return 0
    return max(0, cap - sum(1 for s in d["shots"] if s["type"] == "ai"))


def replan_missing(p, ask, words, L, make_images, review):
    """owner's decision 3a (16 Oct 2026): a shot with no fitting picture is planned again, on its own, instead of a plain
    word card: new searches (moving footage first) with a drawn image as their fallback, a drawn image, or our headline
    card in the narrator's own words. Every answer also names a headline (the last resort). -> work/montage/replan.json
    {"shots": {k: {"try", "result"}}, "picks": {k: code}, "ai_pick": {key: {"seed"}}, "graphics": {k: {headline, keyword}}}"""
    from .sources import UA_API, Ledger, asset_ok, curl, fetch_all, search
    d = decided(p, "montage", "shots")
    P = PH.Plan(d, words, L)
    allow = PL.allowed(p)                  # flags and brand logos in real footage (answer 12 of 18 Oct 2026)
    picks = usable_picks(p)
    ai_pick = decided(p, "ai", "pick", {}) or {}
    have = set(picks) | {int(k[1:]) for k in ai_pick if k.startswith("k") and k[1:].isdigit()}
    missing = [k for k, s in enumerate(d["shots"]) if s["type"] in PH.FOOTAGE and k not in have]
    out = {"shots": {}, "picks": {}, "ai_pick": {}, "graphics": {}}
    if not missing:
        code_decision(p, "sources", "replan", {"shots": []}, "every footage shot has its own picture")
        save_json(M(p, "replan.json"), out)
        return out
    span_words = lambda k: " ".join(w["w"] for w in words[d["shots"][k]["from"]:(d["shots"][k + 1]["from"] if k + 1 < len(d["shots"]) else len(words))])  # noqa: E731
    ctx = {"shots": [{"shot": k, "phrase": span_words(k), "at_s": round(P.span(k)[0], 2), "seconds": round(P.span(k)[1] - P.span(k)[0], 2),
                      "first_plan": {x: d["shots"][k].get(x) for x in ("type", "shows", "search", "ai_prompt", "subject", "place") if d["shots"][k].get(x)},
                      "why_no_picture": why_missing(p, k, d["shots"][k])} for k in missing]}

    def check(dd):
        got = {x["shot"]: x for x in dd["shots"]}
        probs = [f"answer shot {k}" for k in missing if k not in got]
        for k, x in got.items():
            probs += shot_problems(k, x)
        if probs:
            raise ValueError("; ".join(probs))

    def settle(dd):                    # the last resort (ask): a shot whose new plan breaks a rule -> our headline card
        got = {x["shot"]: x for x in dd["shots"] if x.get("shot") in missing}
        out, notes = [], []
        for k in missing:
            x = got.get(k)
            if x is None or shot_problems(k, x):
                notes.append(f"shot {k}: " + ("not answered" if x is None else "; ".join(shot_problems(k, x))[:160])
                             + " -> the headline card with the narrator's words")
                x = {"shot": k, "try": "graphic", "headline": "", "keyword": "", "why": "set by the engine (last resort)"}
            out.append(x)
        return dict(dd, shots=out), notes

    def shot_problems(k, x):
        probs = []
        if k not in missing:
            return [f"shot {k} is not one of {missing}"]
        # the headline and its keyword are fitted in code below (owner's answer 3a of 19 Oct 2026): never sent back
        asked = " ".join(x.get("search") or []) + " " + x.get("ai_prompt", "")
        if any(allow):                     # answer 12 of 18 Oct 2026: searches may ask for them; drawn images never
            if PL.search_problem(" ".join(x.get("search") or []), x.get("ai_prompt", ""), *allow):
                probs.append(f"shot {k}: no flag or logo in the ai_prompt, and only what the profile allows in searches")
        elif PL.flag_in(asked) or PL.brand_in(asked):
            probs.append(f"shot {k}: no flag and no brand in searches or prompts")
        if x["try"] == "search" and not x.get("search"):
            probs.append(f"shot {k}: try search needs 1-3 new searches")
        if x["try"] in ("search", "ai") and not x.get("ai_prompt"):
            probs.append(f"shot {k}: give an ai_prompt (a generic scene) as the fallback")
        if d["shots"][k].get("place") == PL.HOME and x.get("search") and any(not PL.egypt_in(q) for q in x["search"]):
            probs.append(f"shot {k} is about Egypt: every search names Egypt or an Egyptian place")
        return probs
    r = ask(p, "sources", "replan", "These shots have no picture: plan each ONE shot again (owner's decision 3a: never a plain word "
            "card). For each, choose how: try = search (1-3 NEW short English searches, different from the first plan, type stock "
            "or archive; MOVING FOOTAGE FIRST: a real clip of the idea, even a simpler or more general one), try = ai (a generic "
            "drawn scene when nothing real can be filmed), or try = graphic (our newspaper-style headline card). Always give "
            "ai_prompt (a generic scene, no text, no flags, no logos) as the fallback of a search, and headline = words the "
            "narrator says in this shot (exactly, as in phrase), with keyword = one word of it: the last resort. The context gives "
            "each shot's phrase, its first plan and why it found no picture. Rules: the right country (place EGY: show Egypt), "
            + ("flags and brand logos only as the profile allows in real footage (" + PL.rule_text(p) + "), " if any(allow) else
               "no flags, no brands, ")
            + "a new picture over a repeat. Answer with JSON only."
            + (" THIS CHANNEL USES NO DRAWN IMAGES and wants VIDEO FIRST: choose try = search (real video) or graphic, never "
               "try = ai; a search that finds nothing ends on the headline card." if TG.video_first(p) and not TG.rules_of(p)["ai"] else
               " THIS CHANNEL USES NO DRAWN IMAGES: never try = ai; a search that finds nothing ends on the headline card."
               if TG.rules_of(p) and not TG.rules_of(p)["ai"] else ""),
            {"shots": [{"shot": missing[0], "try": "search", "type": "stock", "search": ["…"], "ai_prompt": "…", "headline": "…", "keyword": "…", "why": "…"}]},
            extra={"context": ctx}, schema=SCHEMA_REPLAN, check=check, settle=settle,
            fallback={"shots": []})           # no answer: our headline card in the narrator's words for each
    plan = {x["shot"]: x for x in r["shots"]}
    for k, x in plan.items():                 # at most 5 of the narrator's own words in this shot (answer 3a)
        x["headline"], x["keyword"] = fit_headline(span_words(k), x.get("headline", ""), x.get("keyword", ""))
    # 1. new searches -> thumbnails -> the brain chooses (moving first, repeat rule) -> download
    fx = clip_fx_of(p)
    rejected = {k for k, v in fx.items() if isinstance(v, dict) and v.get("reject")}
    cand, sheets = {}, {}
    from .sources import magnific, storyblocks
    from .sources import mode as sources_mode
    mg, sb, R = magnific.on(p), storyblocks.on(p), TG.rules_of(p)      # the channel's sources and video rule, as in the first search
    if sb:
        storyblocks.search_many([q for k, x in plan.items() if x["try"] == "search"
                                 for q in sb_terms(dict(d["shots"][k], type=x.get("type") or "stock", search=x["search"]))],
                                p.work / "montage" / "storyblocks_runs", project=p.folder.name)
    for k, x in plan.items():
        if x["try"] != "search":
            continue
        s2 = dict(d["shots"][k], type=x.get("type") or "stock", search=x["search"])
        c = kept_candidates(p, f"replan {k}", s2, rejected, PL.allowed(p),
                            lambda s2=s2: candidates_for(s2, rejected, search, allow=PL.allowed(p), mg=mg, sb=sb, vf=bool(TG.video_first(p)),
                                                         po=sources_mode(p) == "paid"))
        fetch_thumbs(p, c, curl, UA_API)
        c = [y for y in c if thumb_file(p, y).exists()]
        if p.profile:                  # a channel episode: a picture already used up is not offered (19 Oct 2026)
            c = [y for y in c if PL.file_ok([(P.span(j)[0], u) for j, u in picks.items()], P.span(k)[0], cand_code(y))]
        if c:
            cand[k], sheets[k] = c, sheet_of([(thumb_file(p, y), source_of(y)) for y in c], M(p, "thumbs", f"replan_{k:03d}.jpg"))
    chosen = {}
    if cand:
        uses = [(P.span(k)[0], c) for k, c in picks.items()]

        def code_of(k, n):             # the same codes as the picks (V:, P:, S:), so the repeat rule sees a repeat
            return cand_code(cand[k][n - 1])

        def check2(dd):
            got = {x["shot"]: x["n"] for x in dd["picks"]}
            bad = [k for k in cand if k not in got or not 0 <= got[k] <= len(cand[k])]
            if bad:
                raise ValueError(f"answer shots {sorted(cand)} once each with n from 0 to their number of candidates: {bad}")

        def settle2(dd):               # the last resort (ask): a shot not answered or out of range -> no picture (0)
            got = {x["shot"]: x for x in dd["picks"] if x.get("shot") in cand}
            out = [dict(got[k]) if k in got and 0 <= got[k].get("n", -1) <= len(cand[k]) else
                   {"shot": k, "n": 0, "why": "left out by the engine"} for k in sorted(cand)]
            return dict(dd, picks=out), [f"shot {x['shot']}: no picture" for x in out if x.get("why") == "left out by the engine"]
        rr = ask(p, "sources", "replan_pick", pick_what(p), {"picks": [{"shot": sorted(cand)[0], "n": 1, "why": "…"}]},
                 read=[sheets[k] for k in sorted(cand)], schema=SCHEMA_PICKS, check=check2, settle=settle2, fallback={"picks": []},
                 extra={"context": {"shots": [{"shot": k, "phrase": span_words(k), "shows": d["shots"][k]["shows"], "at_s": round(P.span(k)[0], 2),
                                               **({"place": "EGY: must show Egypt"} if d["shots"][k].get("place") == PL.HOME else {}),
                                               "sheet": str(sheets[k].relative_to(p.folder)),
                                               "candidates": [{"n": i + 1, "source": source_of(y), "tags_or_title": y["about"][:140]} for i, y in enumerate(cand[k])]}
                                              for k in sorted(cand)], "pictures_already_used": sorted({c for c in picks.values()})}})
        for x in rr["picks"]:
            k = x["shot"]
            if x["n"] and k in cand and PL.file_ok([(t, c) for t, c in uses], P.span(k)[0], code_of(k, x["n"])) and \
                    not (d["shots"][k].get("place") == PL.HOME and x.get("shows_egypt") is not True):
                chosen[k] = cand[k][x["n"] - 1]
    stock = [stock_item(c, f"shot {k} (planned again)") for k, c in chosen.items() if c["kind"] == "stock"]
    photos = []
    led = Ledger(p)
    for k, c in chosen.items():
        if c["kind"] == "photo" and c.get("src"):
            from .sources import photos as PHS
            code = PHS.fetch(p, c, led)
            if code:
                out["picks"][k] = code
        elif c["kind"] == "library":
            from .sources import local_library as library
            if library.use(p, c["code"], led):
                out["picks"][k] = c["code"]
        elif c["kind"] == "photo":                         # a Commons photo of an earlier run: on this Mac only
            key = cand_code(c)[2:]
            photos.append({"key": key, "title": c["id"], "licence": c["licence"], "page": c.get("page", ""), "author": c.get("author", "")})
            out["picks"][k] = f"P:{key}"
        elif c["kind"] == "stock":
            out["picks"][k] = f"V:{c['id']}"
    if stock or photos:
        fetch_all(p, {"stock": stock, "photos": photos})
    if any(v[0] in "VS" for v in out["picks"].values()):
        review()                                   # new clips are looked at like the others (window, grade, reject)
    fx = clip_fx_of(p)
    from .review import BLACK_BELOW, clip_luma
    for k, code in list(out["picks"].items()):
        kd, key = code.split(":", 1)
        f = {"V": p.asset_dir("stock") / f"{key}.mp4", "P": p.asset_dir("photos") / f"{key}.jpg", "S": p.asset_dir("library") / f"{key}.mp4"}[kd]
        bad = not f.exists() or not asset_ok(p, code) or (kd in "VS" and ((fx.get(key) or {}).get("reject") or (clip_luma(p, key) or 255) < BLACK_BELOW))
        if bad:
            out["picks"].pop(k)
    for k in out["picks"]:
        out["shots"][k] = {"try": plan[k]["try"], "result": f"a new picture, {out['picks'][k]} (searched for {', '.join(plan[k].get('search') or [])})"}
    # 2. a drawn image where the search found nothing (or the brain chose one), within the plan's ai_max (drawn images are
    #    stills: Phase 2, moving footage first); beyond it, our headline card
    room = ai_room(p, d)
    want_ai = [k for k, x in plan.items() if k not in out["picks"] and x["try"] in ("search", "ai") and x.get("ai_prompt")][:room]
    if want_ai:
        pr = decided(p, "ai", "prompts", {}) or {}
        if p.profile:                  # an earlier re-plan's images are never made again (only this run's want_ai)
            pr = {k: v for k, v in pr.items() if not k.startswith("r")}
        for k in want_ai:
            look = "cinematic photo style, generic" if (plan[k].get("type") or d["shots"][k]["type"]) == "stock" else "editorial illustration, hand-drawn look, muted colours"
            pr[f"r{k:03d}"] = {"prompt": f"{plan[k]['ai_prompt']}, {look}, no text, no logos, no letters, no flags",
                               "why": f"shot {k} planned again: «{span_words(k)}»"}
        code_decision(p, "ai", "prompts", pr, "ai shots, footage shots without a usable picture, and shots planned again (r###)")
        make_images()
        made = sorted(f for k in want_ai for f in p.asset_dir("ai").glob(f"r{k:03d}_s*.png"))
        if made:
            seeds = {}
            for f in made:
                kk, sd = f.stem.rsplit("_s", 1)
                seeds.setdefault(kk, set()).add(int(sd))
            def check3(dd):
                bad = [kk for kk, v in dd.items() if kk not in seeds or v["seed"] not in seeds[kk]]
                if bad:
                    raise ValueError(f"unknown key or seed {bad}; made: { {a: sorted(b) for a, b in seeds.items()} }")

            def settle3(dd):           # the last resort (ask): an unknown key or seed is not used
                bad = [kk for kk, v in dd.items() if kk not in seeds or v.get("seed") not in seeds[kk]]
                return {kk: v for kk, v in dd.items() if kk not in bad}, [f"{kk}: unknown key or seed, not used" for kk in bad]
            ctx3 = {f"r{k:03d}": {"prompt": pr[f"r{k:03d}"]["prompt"], "for": pr[f"r{k:03d}"]["why"]} for k in want_ai}
            from .steps import look_at_drawn, one_version
            if p.profile and one_version(seeds):          # one version each: nothing to pick (owner's decision of 20 Oct 2026)
                ap = look_at_drawn(p, "look_replan", seeds, made, ctx3)
            else:
                ap = ask(p, "ai", "pick_replan", "After looking at every drawn image (read each file): for each key, the seed whose image SHOWS "
                     "what its prompt and phrase ask for. Leave a key out when neither does, or has text, warped hands or faces, a flag, "
                     "a logo or a brand name, or looks like a real news photo.",
                     {"KEY": {"seed": 11, "why": ""}}, read=made, schema={"type": "object", "additionalProperties": {"type": "object",
                     "required": ["seed"], "properties": {"seed": {"type": "integer"}, "why": {"type": "string"}}}},
                     extra={"context": ctx3}, check=check3, settle=settle3,
                     fallback=lambda: {kk: {"seed": min(v), "why": "the first version (no usable answer)"} for kk, v in seeds.items()})
            for kk, v in (ap or {}).items():
                k = int(kk[1:])
                out["ai_pick"][kk] = v
                out["picks"][k] = f"A:{kk}"
                out["shots"][k] = {"try": plan[k]["try"], "result": f"a drawn image, {kk}" + (" (the new searches found no fitting clip)" if plan[k]["try"] == "search" else "")}
    # 3. the last resort: our headline card in the narrator's words, only where it keeps headline cards 30 s apart (owner's
    #    decision 4a); else the shot is left to the reuse fallback (a picture already in the video, under the repeat rule)
    placed = []
    for k, x in sorted(plan.items()):
        if k in out["picks"]:
            continue
        t = P.span(k)[0]
        if all(abs(t - u) >= PH.HEADLINE_GAP_S for u in PH.headline_times(d, P, placed)):
            placed.append(t)
            out["graphics"][k] = {"headline": x["headline"], "keyword": x.get("keyword", "")}
            out["shots"][k] = {"try": x["try"], "result": f"our headline card «{x['headline']}» (no new picture fitted)"}
        else:
            out["shots"][k] = {"try": x["try"], "result": "no new picture, and a headline card here would be within 30 s of another: "
                                                          "left to the reuse fallback"}
    save_json(M(p, "replan.json"), {k: ({str(a): b for a, b in v.items()} if isinstance(v, dict) else v) for k, v in out.items()})
    print(f"planned again: {len(missing)} shots -> " + "; ".join(f"{k}: {v['result']}" for k, v in sorted(out["shots"].items())))
    return out


def assigned(p, d, P):
    """{shot: picture code} for every footage shot that has one now (chosen, drawn, reused), and the uses that count for the
    repeat limit: [(time, "pic:<code>"), (time, "subject:<subject of the shot the picture was chosen for>")]"""
    picks = usable_picks(p)
    for key in (decided(p, "ai", "pick", {}) or {}):
        if key.startswith("k") and key[1:].isdigit() and int(key[1:]) not in picks:
            picks[int(key[1:])] = f"A:{key}"
    if M(p, "replan.json").exists():                      # a shot planned again (decision 3a): its new picture
        from .sources import asset_ok
        for k, code in load_json(M(p, "replan.json")).get("picks", {}).items():
            if asset_ok(p, code):                         # a broken download is never shown (answer 1a)
                picks.setdefault(int(k), code)
    origin = {}
    for k, code in sorted(picks.items()):
        origin.setdefault(code, k)
    if M(p, "reuse.json").exists():
        for k, code in load_json(M(p, "reuse.json")).items():
            picks.setdefault(int(k), code)
    return picks, uses_of(d, P, picks, origin)


def uses_of(d, P, picks, origin):
    out = []
    for k, code in sorted(picks.items()):
        t = P.span(k)[0]
        out.append((t, f"pic:{code}"))
        out.append((t, PL.subject_use(d["shots"][origin.get(code, k)])))
    for k, s in enumerate(d["shots"]):
        if s["type"] == "graphic":
            out.append((P.span(k)[0], f"graphic:{s.get('graphic')}"))
    return out


def reuse_fallback(p, ask, words, L):
    """shots still without a picture (no on-topic footage, and the brain refused the drawn image): the brain looks at the
    pictures already in the video and picks the one that fits each shot's phrase, or none (a word card then). Owner's
    decision 2a: on topic first, variety second; a repeat of an on-topic picture beats an off-topic one. Owner's decisions
    of 16 Oct (section 6): never a third showing of one picture or subject within 75 s, and a shot about Egypt only gets a
    picture that shows Egypt (one chosen for another Egypt shot, or one whose words name no other country)."""
    d = decided(p, "montage", "shots")
    P = PH.Plan(d, words, L)
    if M(p, "reuse.json").exists():
        M(p, "reuse.json").unlink()                            # asked afresh below from what is in the video now
    picks, uses = assigned(p, d, P)
    settled = {int(k) for k in load_json(M(p, "replan.json")).get("graphics", {})} if M(p, "replan.json").exists() else set()
    missing = [k for k, s in enumerate(d["shots"]) if s["type"] in PH.FOOTAGE and k not in picks and k not in settled]
    if not missing:
        code_decision(p, "sources", "reuse", {"picks": []}, "every footage shot has its own picture (or was planned again)")
        return {}
    thumbs = {int(k): v for k, v in load_json(M(p, "pick_thumbs.json")).items()} if M(p, "pick_thumbs.json").exists() else {}
    about = {int(k): v for k, v in load_json(M(p, "pick_about.json")).items()} if M(p, "pick_about.json").exists() else {}
    ai_pick = decided(p, "ai", "pick", {}) or {}
    pool = []                                                  # (code, image, used for shot k)
    for k, code in sorted(picks.items()):
        if code.startswith("A:") or code in [x[0] for x in pool] or not thumbs.get(k):
            continue
        pool.append((code, thumbs[k], k))
    rp = load_json(M(p, "replan.json")).get("ai_pick", {}) if M(p, "replan.json").exists() else {}
    for key, v in sorted(list(ai_pick.items()) + list(rp.items())):
        if key[:1] in "kr" and key[1:].isdigit():
            pool.append((f"A:{key}", str(p.asset_dir("ai") / f"{key}_s{v['seed']}.png"), int(key[1:])))
    if not pool:
        return {}

    def subj(k0):
        return PL.subject_use(d["shots"][k0])

    def allowed(k, i, used):
        code, _, k0 = pool[i]
        t = P.span(k)[0]
        if not PL.file_ok(used, t, f"pic:{code}") or PL.too_many(used, t, subj(k0)):
            return False
        if d["shots"][k].get("place") == PL.HOME and d["shots"][k0].get("place") != PL.HOME:
            return not PL.foreign_in(about.get(k0, "")) and not code.startswith("A:")
        return True
    sheet = sheet_of([(img, f"shot {k}") for _, img, k in pool], M(p, "thumbs", "reuse.jpg"))
    ctx = {"shots_without_a_picture": [{"shot": k, "phrase": d["shots"][k].get("phrase", ""), "shows": d["shots"][k]["shows"],
                                        "at_s": round(P.span(k)[0], 2),
                                        **({"place": "EGY: only a picture that shows Egypt"} if d["shots"][k].get("place") == PL.HOME else {}),
                                        "allowed_n": [i + 1 for i in range(len(pool)) if allowed(k, i, uses)]} for k in missing],
           "pictures_in_the_video": [{"n": i + 1, "used_for_shot": k, "phrase": d["shots"][k].get("phrase", ""),
                                      "subject": d["shots"][k].get("subject", ""), "at_s": round(P.span(k)[0], 2)}
                                     for i, (_, _, k) in enumerate(pool)]}

    def check(dd):
        bad = [x for x in dd["picks"] if x["shot"] not in missing or not 0 <= x["n"] <= len(pool)]
        if bad:
            raise ValueError(f"only shots {missing}, n from 0 to {len(pool)}: {bad[:4]}")
        used, probs = list(uses), []
        for x in sorted(dd["picks"], key=lambda z: z["shot"]):
            if x["n"]:
                if not allowed(x["shot"], x["n"] - 1, used):
                    probs.append(f"shot {x['shot']}: picture {x['n']} is not allowed (a third showing within 75 s, or not Egypt "
                                 "for a shot about Egypt); choose from its allowed_n as it stands after your other picks, or 0")
                code, _, k0 = pool[x["n"] - 1]
                used += [(P.span(x["shot"])[0], f"pic:{code}"), (P.span(x["shot"])[0], subj(k0))]
        if probs:
            raise ValueError("; ".join(probs))

    def settle(dd):                    # the last resort (ask): a picture not allowed for its shot -> 0 (the card)
        used, out, notes = list(uses), [], []
        for x in sorted(dd["picks"], key=lambda z: z.get("shot", 0)):
            if x.get("shot") not in missing:
                notes.append(f"shot {x.get('shot')}: not one of the shots asked, left out")
                continue
            n = x.get("n") or 0
            if n and not (0 < n <= len(pool) and allowed(x["shot"], n - 1, used)):
                notes.append(f"shot {x['shot']}: picture {n} not allowed, left out (the card)")
                x = dict(x, n=0, why="left out by the engine")
                n = 0
            if n:
                code, _, k0 = pool[n - 1]
                used += [(P.span(x["shot"])[0], f"pic:{code}"), (P.span(x["shot"])[0], subj(k0))]
            out.append(x)
        return dict(dd, picks=out), notes
    r = ask(p, "sources", "reuse", "Some shots have no picture of their own. Look at the sheet of the pictures already in this video "
            "(numbered; the context says which shot each one is used for). For each shot without a picture, give n = the picture "
            "that best shows its phrase, or 0 if none "
            "shows it (a card with the said words is shown instead). Topic first. Owner's decisions: the same picture, or the "
            "same thing seen, at most twice within 75 s, and one picture file at most twice in the video, 60 s apart (allowed_n "
            "lists what each shot may still use); a shot about Egypt "
            "only gets a picture that shows Egypt" + ("" if PL.allowed(p)[0] else "; no flags") + ". Answer with JSON only.",
            {"picks": [{"shot": missing[0], "n": 1, "why": "…"}]}, read=[sheet], extra={"context": ctx}, schema=SCHEMA_PICKS, check=check,
            settle=settle, fallback={"picks": []})     # no answer: no picture reused (the card with the said words)
    out = {x["shot"]: pool[x["n"] - 1][0] for x in r["picks"] if x["n"]}
    save_json(M(p, "reuse.json"), {str(k): v for k, v in out.items()})
    return out


# ---------------------------------------------------------------------------------------------------- timeline
def with_replan(p, d, ai_pick):
    """the plan as shown: shots settled by the re-plan with our headline card become that graphic; the re-plan's drawn
    images join the AI picks"""
    import copy
    rp = load_json(M(p, "replan.json")) if M(p, "replan.json").exists() else {}
    d = copy.deepcopy(d)
    for k, g in rp.get("graphics", {}).items():
        gid = f"r{int(k):03d}"
        d["shots"][int(k)].update(type="graphic", graphic=gid)
        d.setdefault("graphics", []).append({"id": gid, "kind": "headline", "headline": g["headline"], "keyword": g.get("keyword", "")})
    return d, dict(ai_pick or {}, **rp.get("ai_pick", {}))


def script_spelling(p, d, words, L):
    """must-do c: every on-screen text in the approved script's spelling (montage/scripttext.py); the anchors stay on
    whisper's words. -> (the plan as shown, [(was, shown)] changes)"""
    import copy
    from .scripttext import Aligner
    al = Aligner(p, words)
    if not al.active:
        return d, []
    d = copy.deepcopy(d)
    P = PH.Plan(d, words, L)
    changes = []

    def at_of(text):
        return next((i for i in range(len(words)) if P.said_at(text, i)), None)

    def fix(obj, key, at):
        if obj.get(key):
            new = al.shown(obj[key], at if at is not None else at_of(obj[key]))
            if new != obj[key]:
                changes.append((obj[key], new))
                obj[key] = new
    for o in d.get("onscreen", []):
        fix(o, "text", o["at"])
    for g in d.get("graphics", []):
        for it in ([g["title"]] if g.get("title") else []) + g.get("items", []):
            fix(it, "text", it["at"])
        for pl in g.get("places", []):
            fix(pl, "name", pl["at"])
        for k in ("label", "headline", "line"):
            fix(g, k, None)
        if g.get("keyword") and g.get("headline"):           # the keyword follows its headline's spelling
            from ..cut.common import normalize_ar
            g["keyword"] = next((w for w in g["headline"].split() if normalize_ar(w) == normalize_ar(g["keyword"])), g["keyword"])
    return d, changes


def step_timeline(p, words, L, clip_fx, ai_pick, out_edl):
    from . import graphics, timeline
    d, ai_pick = with_replan(p, decided(p, "montage", "shots"), ai_pick)
    d, spelled = script_spelling(p, d, words, L)
    P = PH.Plan(d, words, L)
    picks, _ = assigned(p, d, P)                           # chosen, then drawn, then a picture already in the video
    origin = {}
    for k, code in sorted(picks.items()):
        if not (M(p, "reuse.json").exists() and str(k) in load_json(M(p, "reuse.json"))):
            origin.setdefault(code, k)
    dropped = []
    while True:                                            # owner's decision 2: never a third showing within 75 s (a guard:
        us = uses_of(d, P, picks, origin)                                              # the earlier steps already keep to it)
        reps = [(k, [t for t, _ in xs]) for k, xs in PL.repeats([(t, key, t) for t, key in us])] + \
            [(k, ts) for k, ts in PL.file_problems([(t, key) for t, key in us if key.startswith("pic:")])]
        hit = next(((key, ts) for key, ts in reps if not key.startswith("graphic:")), None)
        if not hit:
            break
        t_last = hit[1][-1]
        k = next(k for k in sorted(picks) if abs(P.span(k)[0] - t_last) < 1e-6)
        dropped.append(f"shot {k}: {picks.pop(k)} would break the repeat rule for {hit[0]}")
    ni = PH.script_hints(p)[1]
    st = style(p)
    tl, scenes, sound, trans, report = B.build(p, d, words, L, picks, ni, st, p.asset_dir("textures") / "paper.png")
    graphics.check(scenes)
    code_decision(p, "graphics", "scenes", scenes, "built from the phrase plan")
    edl = timeline.build(p, tl, scenes, words, clip_fx, ai_pick, overlay_delay=True)
    sound["intro_clicks"] = B.apply_transitions(edl, trans, tl["intro_end_s"])
    code_decision(p, "montage", "timeline", tl, "built from the phrase plan")
    code_decision(p, "montage", "sound", sound, "built from the phrase plan (rules 18 and 22)")
    if p.opt("parallax", True):                            # drawn stills move in 2.5D (monteer/ai/parallax.py); real photos never
        for n, s in enumerate(s for s in edl["shots"] if s["kind"] == "ai"):
            side = 1 if n % 2 else -1
            s["parallax_side"] = side
            s["parallax"] = str(M(p, "parallax", f"{Path(s['src']).stem}_{s['nframes']}_{s.get('zoom') or 'drift'}_{side:+d}.mp4"))
    save_json(out_edl, edl)
    lens = [round((s["f1"] - s["f0"]) / 24, 2) for s in edl["shots"]]
    intro = [x for s, x in zip(edl["shots"], lens) if s["f1"] / 24 <= tl["intro_end_s"] + 0.05]
    report.update(intro_shots=len(intro), intro_shot_lengths=intro, shot_lengths=lens, transitions=sum(1 for s in edl["shots"] if s.get("transition")),
                  edl_shots=len(edl["shots"]), overlays=len(tl["overlays"]), repeat_guard_dropped=dropped,
                  repeats_over_limit=[[key, [round(t, 1) for t, _ in xs]] for key, xs in PL.repeats([(t, key, t) for t, key in uses_of(d, P, picks, origin)])],
                  places={str(k): s.get("place", "") for k, s in enumerate(d["shots"]) if s.get("place")},
                  script_spelling=[{"heard": a, "shown": b} for a, b in spelled])
    save_json(M(p, "build_report.json"), report)
    print(f"phrase montage: {len(edl['shots'])} shots, intro {tl['intro_end_s']:.1f} s in {len(intro)} shots, "
          f"{report['transitions']} transitions; types {report['by_type']}; fallbacks {len(report['fallbacks'])}")
    return edl


__all__ = ["step_plan", "step_music", "step_sources", "ai_prompts", "step_timeline", "decided", "style", "pick_context"]

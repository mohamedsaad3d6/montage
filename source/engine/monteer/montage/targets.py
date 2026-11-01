"""Material mix and key-word labels as checks the plan must meet (owner's decisions 2 and 3 of 16 Oct 2026 on
Works/output/agent_readiness_report.md). Both video types use this file; each counts on its own base.

Decision 3 (material mix): the approved targets of 15 Oct (engine_plan_materials.md decision 3) per video type:
  archive at least 15%, documented news at least 10%, generic stock at most 40%, no type more than 3 shots in a row.
  - audio only (صوت بس): counted over ALL the plan's shots (every second is a picture: stock, archive, ai, graphic, news);
  - with presenter (بمذيع): counted over the B-ROLL shots only (the presenter is not a material type); a presenter
    shot ends a run.
  The brain COMPUTES the targets for its video (shot counts from the percentages and its own number of shots) and gives
  them with its plan; code recomputes them, and the plan must equal them and meet them, or the brain is asked again.
  The one exception, set in code: documented news needs the script tool's news items; with none, news_min is 0.
  A channel with the video rule (rules_of, الحدث الأخير and اقتصاد احمس): no stock cap and NO ARCHIVE MINIMUM (owner's
  decision of 21 Oct 2026, after an episode stopped on "0 archive shots of 93; at least 14": its archive shots had become
  Storyblocks/Magnific video, counted as stock, and no free archive photo was found); archive is used where real film or
  photos of a past event exist, else a video of today stands in for it.
Decision 2 (key-word labels, rule 11): about 1.3-1.8 a minute: between floor(1.3 x minutes) and ceil(1.8 x minutes)
  (at least 1 from 40 s on), re-hooks not counted.
"""
import math

ARCHIVE_MIN, NEWS_MIN, STOCK_MAX, MAX_RUN = 0.15, 0.10, 0.40, 3
AI_MAX = 0.15              # Phase 2 (owner: more moving footage, fewer stills): drawn images at most 15% of the counted shots
LABELS_PER_MIN = (1.3, 1.8)
TYPES = ("stock", "archive", "ai", "graphic", "news", "own")     # own: the owner's clips, neither stock nor archive

SCHEMA = {"type": "object", "required": ["base_shots", "stock_max", "archive_min", "news_min", "max_run", "ai_max"], "properties": {
    "base_shots": {"type": "integer"}, "stock_max": {"type": "integer"}, "archive_min": {"type": "integer"},
    "news_min": {"type": "integer"}, "max_run": {"type": "integer"}, "ai_max": {"type": "integer"}, "why": {"type": "string"}}}


def rules_of(p):
    """a channel's own footage rules (owner's decision of 20 Oct 2026 for الحدث الأخير and اقتصاد احمس: "montage.footage"
    {"video_min_share": 0.6, "ai_images": false}) -> {"video_min": share, "ai": bool}, or None (every other channel and the
    classic projects: the rules as they were, 40% stock cap included)"""
    if not getattr(p, "profile", None):
        return None
    try:
        f = p.profile_montage().get("footage") or {}
    except Exception:  # noqa: BLE001
        return None
    if f.get("video_min_share") is None and f.get("ai_images") is not False:
        return None
    g = p.profile_montage().get("graphics")
    return {"video_min": float(f.get("video_min_share") or 0), "ai": f.get("ai_images") is not False,
            **({"stock_runs": True} if isinstance(g, dict) and g else {})}


def video_first(p):
    """the channel's video rule (rules_of with a video share), or None: no drawn images alone keeps the stock cap"""
    R = rules_of(p)
    return R if R and R.get("video_min") else None


NO_AI = "ai_max = 0 (THIS CHANNEL USES NO DRAWN IMAGES: never type ai)"


def rule_text(kind, R=None):
    if R and R.get("video_min"):
        return video_first_text(kind, R)
    if R and not R["ai"]:              # no drawn images, the rest of the rule as it was (owner's (e) of 20 Oct 2026)
        return rule_text(kind).replace("ai_max = floor(0.15 x base_shots) (drawn images)", NO_AI)
    base = ("all the plan's shots (stock, archive, ai, graphic, news)" if kind == "phrases"
            else "the B-roll shots only (the presenter is not counted; a presenter shot ends a run)")
    return (f"MATERIAL MIX (owner's decision: a check the plan must meet). Count {base}: base_shots = that number. "
            f"Compute the targets: stock_max = floor(0.40 x base_shots); archive_min = ceil(0.15 x base_shots); news_min = "
            f"ceil(0.10 x base_shots) when there are documented news items, else 0; max_run = 3 (no material type more than 3 "
            f"shots in a row); ai_max = floor(0.15 x base_shots) (drawn images). Give them as mix_targets (with a short why) "
            f"and plan the shots so they are met.\n"
            f"MOVING FOOTAGE FIRST, FEWER REPEATS (owner, Phase 2): use moving clips instead of still photos wherever a real "
            f"thing can be filmed: stock footage for today's real things (up to stock_max), archive for past events, years "
            f"and documents (US federal films move; photos only when no film exists); a drawn image only where nothing real "
            f"can be filmed (at most ai_max); our graphics for numbers, places, lists and stages. A new picture beats a "
            f"repeat: one picture file at most twice in the whole video, its two showings at least 60 s apart.")


def video_first_text(kind, R):
    """the mix rule for a channel with its own footage rules (rules_of): no stock cap; video the majority; drawn images
    only when the channel allows them"""
    base = ("all the plan's shots (stock, archive, ai, graphic, news)" if kind == "phrases"
            else "the B-roll shots only (the presenter is not counted; a presenter shot ends a run)")
    ai = "ai_max = floor(0.15 x base_shots) (drawn images)" if R["ai"] else NO_AI
    return (f"MATERIAL MIX (owner's decision: a check the plan must meet). Count {base}: base_shots = that number. "
            f"Compute the targets: stock_max = base_shots (THIS CHANNEL HAS NO STOCK CAP); archive_min = 0 (THIS CHANNEL HAS NO "
            f"ARCHIVE MINIMUM: an archive shot whose past event has no real film or photo becomes a video of today); "
            f"news_min = ceil(0.10 x base_shots) when there are documented news items, else 0; max_run = 3 (no material type "
            f"more than 3 shots in a row); {ai}. Give them as mix_targets (with a short why) and plan the shots so they are met.\n"
            f"VIDEO IS THE MAJORITY (this channel, owner's decision): at least {R['video_min']:.0%} of the footage's screen time "
            f"is VIDEO. Plan stock shots for today's real things and archive shots for past events that real FILM exists for "
            f"(archive shots look for video first; a still photo only when no video fits); our graphics for numbers, places, "
            f"lists and stages. A new picture beats a repeat: one picture file at most twice in the whole video, its two "
            f"showings at least 60 s apart.")


def targets(n, has_news, R=None):
    eps = 1e-9
    out = {"base_shots": n, "stock_max": math.floor(STOCK_MAX * n + eps), "archive_min": math.ceil(ARCHIVE_MIN * n - eps),
           "news_min": math.ceil(NEWS_MIN * n - eps) if has_news else 0, "max_run": MAX_RUN, "ai_max": math.floor(AI_MAX * n + eps)}
    if R:                              # the channel's own footage rules: no stock cap (video rule); no drawn images when it says so
        if R.get("video_min"):         # video first: no stock cap and no archive minimum (owner, 21 Oct 2026)
            out["stock_max"] = n
            out["archive_min"] = 0
        if not R["ai"]:
            out["ai_max"] = 0
    return out


def runs(types):
    """the longest run of one material type: [(type, length, first index)]; None in the list ends a run (presenter)"""
    best, cur, start = (None, 0, 0), 0, 0
    for i, t in enumerate(types):
        if t is not None and i and types[i - 1] == t:
            cur += 1
        else:
            cur, start = (1, i) if t is not None else (0, i)
        if t is not None and cur > best[1]:
            best = (t, cur, start)
    return best


def check(types, given, has_news, where="the plan", R=None):
    """types: the material type of each counted shot in order (None = a presenter shot, which ends a run); given: the
    brain's mix_targets; R: the channel's own footage rules (rules_of). -> [problems]"""
    counted = [t for t in types if t is not None]
    want = targets(len(counted), has_news, R)
    probs = []
    if given is not None:
        wrong = {k: (given.get(k), v) for k, v in want.items() if given.get(k) != v}
        if wrong:
            probs.append(f"mix_targets are not computed as the rule says for {len(counted)} counted shots: "
                         + ", ".join(f"{k} {a} should be {b}" for k, (a, b) in wrong.items()))
    n = {t: sum(1 for x in counted if x == t) for t in TYPES}
    if n["stock"] > want["stock_max"]:
        probs.append(f"{where} has {n['stock']} stock shots of {len(counted)}; at most {want['stock_max']} (40%)")
    if n["archive"] < want["archive_min"]:
        probs.append(f"{where} has {n['archive']} archive shots of {len(counted)}; at least {want['archive_min']} (15%)")
    if n["ai"] > want["ai_max"]:
        probs.append(f"{where} has {n['ai']} drawn images of {len(counted)}; " + ("this channel uses no drawn images (owner's "
                     "decision): use real footage or our graphics" if R and not R["ai"] else f"at most {want['ai_max']} (15%: moving footage first)"))
    if n["news"] < want["news_min"]:
        probs.append(f"{where} has {n['news']} documented-news shots of {len(counted)}; at least {want['news_min']} (10%)")
    # a channel with its graphics policy (owner's decisions of 22 Oct 2026: few graphics, real footage first; its archive is
    # mostly news-style stock): its stock footage may run longer; graphics, archive and the rest at most MAX_RUN in a row
    t, length, i = runs([None if (x == "stock" and R and R.get("stock_runs")) else x for x in types])
    if length > MAX_RUN:
        probs.append(f"{where} has {length} {t} shots in a row (from shot {i}); at most {MAX_RUN} of one type in a row")
    return probs


SMALL = 3                  # owner (20 Oct 2026): an overrun of up to this many shots is fixed in code, never asked again


def repair(types, has_news, prefer=None, ordered=True, limit=SMALL, R=None):
    """a small overrun of the material mix fixed in code (owner's decision of 20 Oct 2026, after a plan was refused for 125
    stock shots of 310, at most 124, and asking again cost 35 minutes): stock over its maximum or archive under its minimum
    by at most `limit` shots -> that many stock shots become archive (in the order `prefer` gives, else latest first; when
    `ordered`, never making a run longer than MAX_RUN). -> the indices to change (empty when the mix is met), or None when
    the overrun is bigger or no swap keeps the runs"""
    counted = [t for t in types if t is not None]
    want = targets(len(counted), has_news, R)
    need = max(counted.count("stock") - want["stock_max"], want["archive_min"] - counted.count("archive"), 0)
    if need > limit:
        return None
    out, changed = list(types), []
    for i in (prefer if prefer is not None else reversed(range(len(out)))):
        if len(changed) == need:
            break
        if out[i] != "stock":
            continue
        trial = out[:i] + ["archive"] + out[i + 1:]
        if not ordered or runs(trial)[1] <= MAX_RUN:
            out, changed = trial, changed + [i]
    return changed if len(changed) == need else None


def computed(given, n, has_news, R=None):
    """the brain's mix_targets with the numbers code computes for n counted shots (its why kept) -> (targets, [what changed])"""
    want = targets(n, has_news, R)
    given = dict(given or {})
    wrong = [f"{k} {given.get(k)}->{v}" for k, v in want.items() if given.get(k) != v]
    return dict(given, **want), wrong


def video_share(parts, R, where="the footage"):
    """parts: [(seconds, kind)] of the footage on screen, kind "video" or "photo" -> (share of video, [problems]) for a
    channel with its own footage rules (owner's decision of 20 Oct 2026: video at least R["video_min"] of the screen time)"""
    total = sum(s for s, _ in parts)
    vid = sum(s for s, k in parts if k == "video")
    sh = vid / total if total else 1.0
    if R and R.get("video_min") and sh + 1e-9 < R["video_min"]:
        return sh, [f"{where} is {sh:.0%} video by screen time ({vid:.0f} of {total:.0f} s); this channel wants at least {R['video_min']:.0%}"]
    return sh, []


def share(types):
    counted = [t for t in types if t is not None]
    m = max(1, len(counted))
    return {t: round(sum(1 for x in counted if x == t) / m, 3) for t in TYPES}


def label_range(length_s):
    m = length_s / 60
    lo = max(1, math.floor(LABELS_PER_MIN[0] * m)) if length_s >= 40 else 0
    hi = max(1, math.ceil(LABELS_PER_MIN[1] * m))
    return lo, hi


def label_text(length_s):
    lo, hi = label_range(length_s)
    return (f"KEY-WORD LABELS (rule 11, owner's decision): about 1.3-1.8 a minute; for this {length_s:.0f} s video between "
            f"{lo} and {hi} in all (re-hooks are not counted)")


def check_labels(n, length_s):
    lo, hi = label_range(length_s)
    return [] if lo <= n <= hi else [f"{n} key-word labels; rule 11 asks about 1.3-1.8 a minute: between {lo} and {hi} "
                                     f"for {length_s:.0f} s"]

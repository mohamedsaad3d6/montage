"""The audio-only narration as whisper heard it (owner's answers 3 and 4 of 18 Oct 2026, after the repeated log lines):

  retakes(words, segments)   likely narrator retakes left in the mp3: the same words said again right after (a run of 3+
                             words said twice in a row), or a sentence restarted (a segment whose words are nearly all in
                             the one before or after it, within 3 s). Listed with their times in the video's report, so
                             the owner can fix the mp3; the voice is never cut (the audio-only type never edits it).
  silences(words)            stretches over SILENCE_S with no word (e.g. 14.5 s of digital silence at 429.5 s in the
                             panel's «بمجرد أن تفهم المال…»). With a channel profile the plan is told about them and one
                             shot may hold over each (its length counted without the silence), so the AI is not refused
                             over and over; the report notes them. The classic same-result projects (no profile) keep their
                             plan request and checks exactly.
"""
from ..core.io import load_json

SILENCE_S = 6.0
RETAKE_GAP_S = 3.0
NEAR = 0.8                     # share of the shorter segment's words found in its neighbour


def _toks(text):
    from ..cut.common import normalize_ar
    return [t for t in (normalize_ar(w) for w in str(text).split()) if t and len(t) >= 2]


def mmss(t):
    return f"{int(t // 60)}:{t % 60:04.1f}"


def silences(words, min_s=SILENCE_S):
    """[(start s, end s)] with no word for longer than min_s (inside the narration, not before its first word)"""
    out = []
    for a, b in zip(words, words[1:]):
        end = min(a["e"], a["s"] + 1.5)          # a word's end never runs into the silence by more than its own length
        if b["s"] - end > min_s:
            out.append((round(end, 2), round(b["s"], 2)))
    return out


def retakes(words, segments=()):
    """[{"first_s", "again_s", "text", "again", "how"}] in time order"""
    out = []
    n = [w.get("n") or w["w"] for w in words]
    i = 0
    while i < len(n):                            # the same 3-12 words said twice in a row
        hit = None
        for L in range(12, 2, -1):
            if i + 2 * L <= len(n) and n[i:i + L] == n[i + L:i + 2 * L] and words[i + L]["s"] - words[i + L - 1]["e"] <= RETAKE_GAP_S + 2:
                hit = L
                break
        if hit:
            out.append({"first_s": round(words[i]["s"], 2), "again_s": round(words[i + hit]["s"], 2),
                        "text": " ".join(w["w"] for w in words[i:i + hit]), "again": " ".join(w["w"] for w in words[i + hit:i + 2 * hit]),
                        "how": "said twice in a row"})
            i += 2 * hit
        else:
            i += 1
    segs = [s for s in segments if s.get("text")]
    for a, b in zip(segs, segs[1:]):             # a sentence restarted: one segment's words nearly all in its neighbour
        ta, tb = _toks(a["text"]), _toks(b["text"])
        if min(len(ta), len(tb)) < 3 or b["s"] - a["e"] > RETAKE_GAP_S:
            continue
        short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
        if sum(1 for t in set(short) if t in set(long_)) / len(set(short)) >= NEAR:
            if not any(abs(r["again_s"] - b["s"]) < 2.5 or a["s"] - 0.5 <= r["first_s"] <= b["e"] for r in out):
                out.append({"first_s": round(a["s"], 2), "again_s": round(b["s"], 2), "text": a["text"], "again": b["text"],
                            "how": "a sentence said again (restarted)"})
    return sorted(out, key=lambda r: r["first_s"])


def asr(p):
    from .steps import V
    f = V(p, "asr_large-v3.json")
    return load_json(f) if f.exists() else None


def log_lines(p, words, segments):
    """after the transcription (audio only): one line each for the likely retakes and the long silences"""
    out = []
    rt, si = retakes(words, segments), silences(words)
    if rt:
        out.append(f"possible narrator retakes: {len(rt)}, at " + ", ".join(mmss(r["again_s"]) for r in rt[:12])
                   + " (the video's report lists them; the voice is never cut)")
    if si:
        out.append(f"long silences (no words over {SILENCE_S:g} s): " + ", ".join(f"{mmss(a)}-{mmss(b)} ({b - a:.1f} s)" for a, b in si)
                   + ("; one shot holds over each" if p.profile else ""))
    return out


# ---------------------------------------------------------------------------------------------------- the plan (profiles)
def plan_silences(p, words):
    """the long silences the plan may hold one shot over: channel profiles only (the classic tests keep their request)"""
    return silences(words) if p.profile else []


def plan_text(sil):
    if not sil:
        return ""
    return ("\nLONG SILENCES in this narration (no words): " + ", ".join(f"{a:.1f}-{b:.1f} s" for a, b in sil) + ". Cover each with "
            "ONE shot that starts before it and holds through it: a footage shot (choose a clip at least that long; a shorter clip "
            "would loop), a photo (it moves slowly), or a graphic such as a headline card with the next section's first words. "
            "Its length is counted without the silence, so the usual shot lengths still apply to the spoken part.")


def quiet(a, b, sil):
    """seconds of [a, b] inside the long silences"""
    return sum(max(0.0, min(b, y) - max(a, x)) for x, y in sil)


TRIM_S = 0.7                   # a clip's usable part: its first 0.4 s and last 0.3 s are not shown (montage/timeline.py)


def held_shots(P, shots, sil):
    """{shot index: {"silence_s", "shot_s", "clip_must_last_s"}} for the shots that hold over a long silence (owner's
    answer 2: such a shot uses a clip at least that long, or a photo or a graphic, never a clip that would loop)"""
    out = {}
    for k in range(len(shots)):
        a, b = P.span(k)
        q = quiet(a, b, sil)
        if q >= 1.0:
            out[k] = {"silence_s": round(q, 1), "shot_s": round(b - a, 1), "clip_must_last_s": round(b - a + TRIM_S, 1)}
    return out


def clip_problem(k, h, seconds, what="its clip"):
    """the reason a clip cannot hold shot k over its silence, or None (unknown length: None, checked after download)"""
    if seconds is None or seconds >= h["clip_must_last_s"]:
        return None
    return (f"shot {k} holds over a {h['silence_s']:.1f} s silence and lasts {h['shot_s']:.1f} s: {what} lasts {seconds:.1f} s and "
            f"would loop; use a clip of at least {h['clip_must_last_s']:.1f} s, a photo, or a graphic")


def pick_text(held):
    if not held:
        return ""
    return (" SHOTS HELD OVER A LONG SILENCE (context: holds_over_silence): choose a photo, or a clip at least clip_must_last_s "
            "long (a shorter clip would loop), or 0.")


# ---------------------------------------------------------------------------------------------------- the report
def report_lines(p):
    if p.mode != "voice_only":
        return []
    d = asr(p)
    if not d:
        return []
    rt, si = retakes(d["words"], d.get("segments", [])), silences(d["words"])
    out = ["", "## The narration (audio only)", ""]
    if not rt and not si:
        return out + ["- no likely retake and no silence over 6 s", ""]
    if rt:
        out.append(f"### Possible narrator retakes ({len(rt)}): listen and fix the mp3 if they are mistakes (the voice is never cut)")
        out.append("")
        for r in rt:
            out.append(f"- {mmss(r['first_s'])} «{r['text']}» — again at {mmss(r['again_s'])} «{r['again']}» ({r['how']})")
        out.append("")
    if si:
        out.append(f"### Long silences (no words over {SILENCE_S:g} s)")
        out.append("")
        from .steps import M
        hf = M(p, "held_shots.json")
        held = load_json(hf) if hf.exists() else {}
        for a, b in si:
            out.append(f"- {mmss(a)}-{mmss(b)} ({b - a:.1f} s)" + (": one shot holds over it (its length counted without the silence)"
                                                                     if p.profile else ""))
        for k, h in sorted(held.items(), key=lambda kv: int(kv[0])):
            out.append(f"  - shot {k} ({h['shot_s']:.1f} s over {h['silence_s']:.1f} s of silence): {h.get('result', 'not picked yet')}")
        out.append("")
    return out


__all__ = ["retakes", "silences", "log_lines", "plan_silences", "plan_text", "quiet", "report_lines", "mmss"]

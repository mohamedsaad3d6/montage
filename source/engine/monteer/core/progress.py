"""The progress page's numbers and lines (owner's requests of 20 Oct 2026), for core/summary.py:

  this run only      a step shows «خلصت» only when this run finished it or found it up to date (runner.py writes
                     run/current_video_run.json at the start and "checked" on an up-to-date step); a «done» left from
                     an earlier run (e.g. a 130-190 s preview) is shown as still to do until this run reaches it
  Egyptian Arabic    each step's latest line in plain Arabic (ar_line); a line it does not know: what the step is doing
  smooth percentage  each step weighs its expected time; the running step counts its real work where it can (whisper's
                     percent, the graphics scenes drawn, the pieces rendered), else the time it has run
  time left          from the steps' measured times on this Mac (every project's run/record.json, seconds per minute of
                     narration, the median), updated as the run goes; «فاضل حوالي … دقيقة»
"""
import re
import statistics
import time
from datetime import datetime, timedelta
from pathlib import Path

from .io import load_json

AR_DIGITS = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def ar(n):
    return str(n).translate(AR_DIGITS)


# ---------------------------------------------------------------------------------------------------- this run only
def run_started(p, stage="video"):
    f = p.run / f"current_{stage}_run.json"
    try:
        return load_json(f).get("started") if f.exists() else None
    except (ValueError, OSError):
        return None


def fresh(r, started):
    """this run finished the step or found it up to date (or it is not for this project)"""
    if not started or str(r.get("status", "")).startswith("skipped"):
        return True
    return max(str(r.get("at", "")), str(r.get("checked", ""))) >= started


def this_run(rec, started):
    return {k: v for k, v in rec.items() if fresh(v, started)}


# ---------------------------------------------------------------------------------------------------- Egyptian Arabic
STEP_AR = {
    "sync": "بيظبط الصوت على الفيديو", "transcribe": "بيفرّغ الكلام", "literal_words": "بيقارن الكلام بالسكريبت",
    "script": "بيقرا السكريبت", "voice": "بيجهّز الصوت", "voice_words": "بيفرّغ الكلام كلمة كلمة بوقتها",
    "cut": "بيقطّع التسجيل", "cut_verify": "بيراجع التقطيع", "cut_draft": "بينضّف السكوت والنَّفَس",
    "cut_final": "بيطلّع التقطيع النهائي", "cut_report": "بيكتب تقرير التقطيع", "clips": "بيبص على كليباتك",
    "news": "بياخد صور صفحات الأخبار", "learn": "بيراجع دروس الحلقات اللي فاتت", "plan": "بيعمل خطة المونتاج",
    "questions": "أسئلة الخطة", "music": "بيختار المزيكا", "sources": "بيدوّر على الصور واللقطات ويختارها",
    "ai_images": "بيرسم الصور ويراجع الكليبات", "textures": "بيجهّز خلفيات الورق", "sfx": "بيعمل المؤثرات الصوتية",
    "review": "بيراجع الكليبات", "timeline": "بيبني قايمة التقطيع", "graphics": "بيرسم الجرافيك",
    "parallax": "بيحرّك الصور المرسومة", "shots": "بيعمل اللقطات واحدة واحدة", "join": "بيجمّع اللقطات",
    "mix": "بيعمل الصوت: الكلام والمزيكا والمؤثرات", "final": "بيطلّع الفيديو النهائي", "selfcheck": "بيراجع الفيديو بنفسه",
    "credits": "بيكتب المصادر والرخص", "observe": "بيسجّل الحلقة للتعلّم",
}
REQ_AR = [("sources/assets", "اختيار الصور"), ("sources/search", "كلمات البحث"), ("sources/replan", "خطة جديدة للقطات الناقصة"),
          ("sources/reuse", "صورة تتعاد"), ("sources/photo_review", "مراجعة الصور"), ("sources/popups", "صور الـpop-ups"),
          ("ai/prompts", "وصف الصور المرسومة"), ("ai/look", "فحص الصور المرسومة"), ("ai/pick", "اختيار الصور المرسومة"),
          ("montage/shots", "خطة اللقطات"), ("montage/plan", "خطة المونتاج"), ("montage/timeline", "قايمة التقطيع"),
          ("montage/clip_fx", "مراجعة الكليبات"), ("montage/sound", "خطة الصوت"), ("montage/questions", "أسئلة الخطة"),
          ("montage/own_clips", "كليباتك"), ("music/cues", "المزيكا"), ("graphics/scenes", "مشاهد الجرافيك"), ("edits/", "التعديلات")]


def req_ar(what):
    return next((a for k, a in REQ_AR if what.startswith(k)), what)


LINES = [
    (r"^asking the brain \(Claude\): (\S+)", lambda m: f"بيسأل Claude: {req_ar(m[1])}"),
    (r"^the brain answered (\S+) in (\d+) min (\d+) s", lambda m: f"Claude جاوب على {req_ar(m[1])} في {ar(m[2])} دقيقة و{ar(m[3])} ثانية"),
    (r"^the brain's answer to (\S+) was sent back", lambda m: f"المحرك رجّع إجابة Claude على {req_ar(m[1])} عشان تتصلح"),
    (r"^the subscription's limit was reached", lambda m: "وصلنا لحد الاشتراك، وهيكمّل لوحده"),
    (r"^whisper: (\d+)%", lambda m: f"التفريغ: {ar(m[1])}٪"),
    (r"^whisper: (\d+) segments, (\d+) words", lambda m: f"التفريغ خلص: {ar(m[2])} كلمة"),
    (r"^graphics: (\S+) \((\d+) frames\)", lambda m: f"بيرسم الجرافيك: {m[1]}"),
    (r"^pop-up art: (\d+)", lambda m: f"رسم {ar(m[1])} مشهد من الـpop-ups"),
    (r"^parallax: (\d+) made, (\d+) unchanged", lambda m: f"اتحرّك {ar(m[1])} صورة، و{ar(m[2])} كانت جاهزة"),
    (r"^parallax: ", lambda m: "بيحرّك الصور المرسومة"),
    (r"^pixabay \d+", lambda m: "بينزّل لقطات من Pixabay"),
    (r"^photo \S+: left out", lambda m: "صورة اتسابت: التنزيل مانفعش"),
    (r"^photo \S+", lambda m: "بينزّل صور"),
    (r"^clip review: (\d+) new clip\(s\) looked at, (\d+) in all", lambda m: f"راجع {ar(m[1])} كليب جديد (الإجمالي {ar(m[2])})"),
    (r"^(\d+) clips, (\d+) contact sheets", lambda m: f"{ar(m[1])} كليب في {ar(m[2])} صفحة صور"),
    (r"^ai images: (\d+) of (\d+)", lambda m: f"الصور المرسومة: {ar(m[1])} من {ar(m[2])} اتستخدمت"),
    (r"^sources: (\d+) of (\d+) footage shots have a chosen picture", lambda m: f"{ar(m[1])} من {ar(m[2])} لقطة ليها صورة"),
    (r"^sources: (\d+) shot\(s\) keep the earlier run's choice", lambda m: f"{ar(m[1])} لقطة فضلت بصورتها من المرة اللي فاتت"),
    (r"^planned again: (\d+) shots", lambda m: f"اتعملت خطة جديدة لـ{ar(m[1])} لقطة ملقتش صورة"),
    (r"^pieces: (\d+) rendered, (\d+) unchanged", lambda m: f"اتعمل {ar(m[1])} لقطة، و{ar(m[2])} كانت جاهزة"),
    (r"^phrase montage: (\d+) shots", lambda m: f"قايمة التقطيع: {ar(m[1])} لقطة"),
    (r"^music: none", lambda m: "مفيش مزيكا تحت الكلام في القناة دي"),
    (r"^music: ", lambda m: "المزيكا: بيختار التراكات من المكتبة"),
    (r"^news: (\d+) of (\d+)", lambda m: f"الأخبار: {ar(m[1])} من {ar(m[2])} صفحة اتصوّرت"),
    (r"^report: ", lambda m: "تقرير الفيديو اتكتب"),
    (r"^learning: ", lambda m: "الحلقة اتسجّلت للتعلّم"),
    (r"^\S+: up to date", lambda m: "جاهزة من قبل كده"),
]
LINES = [(re.compile(a), f) for a, f in LINES]


def ar_line(line, step):
    """the step's latest line in plain Egyptian Arabic; a line not known here: what the step is doing"""
    s = (line or "").strip()
    for rx, f in LINES:
        m = rx.match(s)
        if m:
            return f(m)
    return STEP_AR.get(step, "شغّالة") if s else ""


# ---------------------------------------------------------------------------------------------------- the time a step takes
# seconds per minute of narration, measured on the episode of 20 Oct 2026 (16 min, this Mac, fast path): used for a step
# no project here has a time for yet
DEFAULT_S_PER_MIN = {"voice": 0.5, "voice_words": 70.0, "clips": 0.1, "news": 2.0, "learn": 0.5, "plan": 25.0, "questions": 0.1,
                     "sources": 92.0, "ai_images": 135.0, "textures": 0.1, "sfx": 0.3, "review": 0.5, "timeline": 1.5,
                     "graphics": 46.0, "parallax": 9.7, "shots": 55.0, "join": 2.3, "mix": 1.3, "final": 27.0, "selfcheck": 7.5,
                     "credits": 0.1, "observe": 0.1, "sync": 3.0, "transcribe": 70.0, "literal_words": 1.0, "script": 1.0,
                     "cut": 20.0, "cut_verify": 2.0, "cut_draft": 10.0, "cut_final": 10.0, "cut_report": 1.0}
_HIST = {}


def narration_min(folder):
    """the narration's length in minutes (the 16 kHz copy, or the cut's 48 kHz sound), or None"""
    folder = Path(folder)
    for f, bps in ((folder / "work" / "voice" / "audio16.wav", 32000), (folder / "work" / "cut_audio48.wav", 288000)):
        if f.exists() and f.stat().st_size > 100000:
            return (f.stat().st_size - 44) / bps / 60
    return None


def history(root, ttl=120):
    """{step: [seconds per narration minute]} from every project's record under root (and its Trash)"""
    root = Path(root)
    hit = _HIST.get(str(root))
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    out = {}
    for rec in list(root.glob("*/run/record.json")) + list(root.glob(".trash/*/run/record.json")):
        mins = narration_min(rec.parent.parent)
        if not mins:
            continue
        try:
            r = load_json(rec)
        except (ValueError, OSError):
            continue
        for k, v in r.items():
            if v.get("status") == "done" and not v.get("adopted") and float(v.get("seconds") or 0) > 0:
                out.setdefault(k, []).append(float(v["seconds"]) / mins)
    _HIST[str(root)] = (time.time(), out)
    return out


def expected_s(step, mins, hist):
    xs = hist.get(step)
    rate = statistics.median(xs) if xs else DEFAULT_S_PER_MIN.get(step, 1.0)
    return max(1.0, rate * (mins or 15.0))


# ---------------------------------------------------------------------------------------------------- the running step
TS = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\] (\S+): running —")


def started_at(log, step, now=None):
    """when this step started (from its «running —» line), as seconds ago, or None"""
    now = now or datetime.now()
    for ln in reversed(log):
        m = TS.match(ln)
        if m and m[4] == step:
            t = now.replace(hour=int(m[1]), minute=int(m[2]), second=int(m[3]), microsecond=0)
            if t > now + timedelta(seconds=5):
                t -= timedelta(days=1)
            return (now - t).total_seconds()
    return None


def work_done(p, step, detail):
    """the share of the running step's real work that is done (0-1), or None when it has no counter"""
    from ..montage.steps import M
    try:
        if step in ("voice_words", "transcribe"):
            m = re.match(r"whisper: (\d+)%", detail or "")
            return int(m[1]) / 100 if m else None
        if step == "graphics":
            f = p.decisions / "graphics" / "scenes.json"
            names = [x["name"] for x in load_json(f).get("decision", [])] if f.exists() else []
            fr = M(p, "gfx", "frames")
            return sum((fr / f".{n}.done").exists() for n in names) / len(names) if names else None
        if step == "shots":
            e = M(p, "edl.json")
            n = len(load_json(e)["shots"]) if e.exists() else 0
            return len(list(M(p, "seg").glob("*.done"))) / n if n else None
    except (ValueError, OSError, KeyError, TypeError):
        return None
    return None


def estimate(p, rec_now, log, running_now, steps_all, details):
    """-> (progress 0-1, seconds left or None): every step of this run weighed by its expected time"""
    mins = narration_min(p.folder)
    hist = history(p.folder.parent)
    total = done = left = 0.0
    for st in steps_all:
        if p.mode not in st.modes or st.alongside_until:          # a step alongside overlaps the others: not timed
            continue
        r = rec_now.get(st.name, {})
        if str(r.get("status", "")).startswith("skipped"):
            continue
        w = expected_s(st.name, mins, hist)
        total += w
        if r.get("status") == "done":
            done += w
        elif st.name in running_now:
            ago = started_at(log, st.name) or 0.0
            f = work_done(p, st.name, details.get(st.name))
            if f is None:
                f = min(0.9, ago / w)
                rest = max(w - ago, w * 0.1)
            else:
                f = max(0.0, min(0.97, f))
                rest = ago * (1 - f) / f if f > 0.05 else max(w - ago, w * 0.1)
            done += w * f
            left += rest
        else:
            left += w
    return (done / total if total else 0.0), (left if running_now else None)


def eta_words(secs):
    if secs is None:
        return None
    m = int(round(secs / 60))
    if m < 1:
        return {"ar": "فاضل أقل من دقيقة", "en": "Less than a minute left"}
    if m >= 90:
        h, mm = divmod(m, 60)
        return {"ar": f"فاضل حوالي {ar(h)} ساعة" + (f" و{ar(mm)} دقيقة" if mm else ""), "en": f"About {h} h {mm} min left"}
    return {"ar": f"فاضل حوالي {ar(m)} دقيقة", "en": f"About {m} min left"}


__all__ = ["run_started", "this_run", "ar_line", "estimate", "eta_words", "history", "expected_s", "narration_min"]

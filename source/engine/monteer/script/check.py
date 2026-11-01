"""The script stage's first step: is everything in place? Writes nothing but the log."""
from ..core import apikeys, brain, guard, localbrain
from ..core.paths import CORE_PY
from . import sources, style
from .common import S, channel_dir, topic


def step_check(p):
    guard.refuse_if_keys_inside()
    t = topic(p)
    ch = channel_dir(p)
    srcs = sources.load(ch)
    on = [s for s in srcs if s.get("on")]
    print(f"topic: {t['topic']} (minutes: {t.get('minutes') or 'channel default'}; today {t['today']})")
    print(f"channel: {ch}; sources on: {len(on)} of {len(srcs)}")
    st, _ = style.status(ch)
    print(f"style guide: {st}")
    if st == "missing":
        raise SystemExit(f"القناة مالهاش دليل أسلوب: اكتبه في صفحة القناة، أو اتعلّمه من سكريبتاتها بالأمر "
                         f"bin/monteer script learn-style \"{ch}\" --from \"<Works folder>\"")
    b = brain.brain_name(p)
    print(f"brain: {b}" + (" (the FREE LOCAL MODEL: lower quality, labelled everywhere)" if b == "local" else "")
          + (" (paid API brain; if it fails, the free local model takes over small requests only; an outline or a draft"
             " stops the run: report decision 1a)" if b == "api" else ""))
    if b == "claude-bg":
        from ..core import claudebrain
        ok, why = claudebrain.status()
        print("background brain: " + why)
        if not ok:
            raise SystemExit(f"STOP: العقل (Claude Code) مش جاهز على الماك ده: {why}")
    if b in ("local", "api"):
        ok, why = localbrain.available()
        print("local model: " + ("ready" if ok else f"NOT ready — {why}"))
        if b == "local" and not ok:
            raise SystemExit(f"النموذج المحلي مش جاهز: {why}")
    print("keys file:", apikeys.status(), "| core python:", CORE_PY)
    S(p, "research", "texts").mkdir(parents=True, exist_ok=True)
    S(p, "drafts").mkdir(parents=True, exist_ok=True)

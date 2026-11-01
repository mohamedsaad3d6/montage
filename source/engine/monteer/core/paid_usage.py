"""«استخدام الخدمات المدفوعة» (owner's (d) of 20 Oct 2026): Magnific and Storyblocks use by episode, day and month,
against each plan's limits (Magnific 100 downloads a day through the API; Storyblocks at most 60 clips an episode), from
their use logs (DATA/usage/*.jsonl), each episode's own cut list (how many of the downloaded clips the video uses) and
Magnific's credit balance (read-only account_balance readings: at the start and end of an episode's sources step, and
from the page at most once an hour).

  summary(folders) -> {"magnific": {...}, "storyblocks": {...}}
"""
import json
import time
from pathlib import Path

from .io import load_json


def _day(at):
    return (at or "")[:10]


def _used(folder, prefix):
    """how many different clips of this source the episode's video uses (its cut list), or None before there is one"""
    for f in (Path(folder) / "work" / "montage" / "edl.json", Path(folder) / "output" / "edl.json"):
        if f.exists():
            try:
                shots = load_json(f).get("shots", [])
            except (ValueError, OSError):
                return None
            return len({s["asset"].split("|")[0] for s in shots if str(s.get("asset", "")).startswith(f"V:{prefix}")})
    return None


def _series(rows, what, days=30):
    today = time.time()
    out = []
    for k in range(days - 1, -1, -1):
        d = time.strftime("%Y-%m-%d", time.localtime(today - k * 86400))
        out.append({"day": d, **{w: sum(1 for r in rows if _day(r.get("at")) == d and what[w](r)) for w in what}})
    return out


def _months(rows, what):
    ms = sorted({(r.get("at") or "")[:7] for r in rows if r.get("at")}, reverse=True)
    return [{"month": m, **{w: sum(1 for r in rows if (r.get("at") or "").startswith(m) and what[w](r)) for w in what}} for m in ms]


def _episodes(rows, folders, prefix, what, cap=None):
    by = {}
    for r in rows:
        ep = r.get("project") or ""
        if not ep:
            continue
        e = by.setdefault(ep, {w: 0 for w in what})
        for w in what:
            e[w] += int(bool(what[w](r)))
    names = {Path(f).name: Path(f) for f in folders}
    out = []
    for ep, e in by.items():
        f = names.get(ep)
        name = ep
        if f and (f / "project.json").exists():
            try:
                name = json.loads((f / "project.json").read_text()).get("name", ep)
            except ValueError:
                pass
        out.append(dict(e, episode=ep, name=name, used_in_video=_used(f, prefix) if f else None, **({"cap": cap} if cap else {}),
                        last=max((r.get("at", "") for r in rows if r.get("project") == ep), default="")))
    return sorted(out, key=lambda x: x["last"], reverse=True)


def summary(folders):
    from . import apikeys
    from ..montage.sources import magnific as MG, storyblocks as SB
    folders = list(folders)
    today, month = time.strftime("%Y-%m-%d"), time.strftime("%Y-%m")
    mg = MG.usage()
    mw = {"downloads": lambda r: r.get("what") == "download" and r.get("ok"), "searches": lambda r: r.get("what") == "search",
          "refused_size": lambda r: r.get("what") == "refused-size", "failed": lambda r: r.get("what") == "download" and not r.get("ok")}
    bal = MG.balances()
    ep_bal = {}
    for b in bal:                      # credits spent in an episode: its first reading less its last
        if b.get("project") and b.get("available") is not None:
            ep_bal.setdefault(b["project"], []).append(b["available"])
    m_eps = _episodes(mg, folders, "mg", mw)
    for e in m_eps:
        v = ep_bal.get(e["episode"])
        e["credits_spent"] = round(v[0] - v[-1], 2) if v and len(v) > 1 else None
    sb = SB.usage()
    sw = {"downloads": lambda r: r.get("what") == "download" and r.get("ok"), "searches": lambda r: r.get("what") == "search",
          "refused_size": lambda r: r.get("what") == "refused-size", "failed": lambda r: r.get("what") == "download" and not r.get("ok"),
          "audit": lambda r: r.get("what") == "download-run" and r.get("extra")}
    licensed = {}
    for r in sb:
        if r.get("what") == "download-run":
            licensed[r.get("project", "")] = licensed.get(r.get("project", ""), 0) + len(r.get("asked") or [])
    s_eps = _episodes(sb, folders, "sb", sw, cap=SB.CAP_PER_EPISODE)
    for e in s_eps:
        e["licensed_calls"] = licensed.get(e["episode"], 0)
    count = lambda rows, w, pre: sum(1 for r in rows if (r.get("at") or "").startswith(pre) and w(r))     # noqa: E731
    return {
        "magnific": {"connected": bool(apikeys.get(MG.KEY)), "limit_per_day": MG.DAILY_CAP, "size_limit_mb": MG.MAX_MB,
                     "today": {w: count(mg, mw[w], today) for w in mw}, "month": {w: count(mg, mw[w], month) for w in mw},
                     "days": _series(mg, mw), "months": _months(mg, mw), "episodes": m_eps,
                     "balance": bal[-1] if bal else None, "balance_readings": bal[-20:], "balance_due": MG.balance_due()},
        "storyblocks": {"used": bool(sb), "cap_per_episode": SB.CAP_PER_EPISODE, "size_limit_mb": SB.MAX_MB,
                        "today": {w: count(sb, sw[w], today) for w in sw}, "month": {w: count(sb, sw[w], month) for w in sw},
                        "days": _series(sb, sw), "months": _months(sb, sw), "episodes": s_eps}}

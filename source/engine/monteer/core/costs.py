"""The Costs screen's figures (web panel phase 8), from every episode's own decision records: the brain's work by month
and in the last 5 hours and 7 days (the subscription's own limits are counted in those windows; Claude Code does not tell
the engine how much of them is used, so the brain's time there is shown as a guide), the API equivalent (shown only: the
work runs on the owner's subscription, nothing is charged), paid services (none: 0) and local tools (0).

  summary(folders) -> {months: [{month, decisions, brain_s, tokens, api_equivalent_usd, local}], recent: {h5, d7},
                       by_brain: {claude, local, person}}
"""
import time
from pathlib import Path

from .io import load_json


def records(folder):
    d = Path(folder) / "decisions"
    if not d.exists():
        return
    for f in d.rglob("*.json"):
        if ".replaced_" in f.name or f.name.endswith(".request.json"):
            continue
        try:
            r = load_json(f)
        except (ValueError, OSError):
            continue
        if isinstance(r, dict) and "decision" in r:
            yield r


def summary(folders):
    months, recent = {}, {"h5": {"decisions": 0, "brain_s": 0.0}, "d7": {"decisions": 0, "brain_s": 0.0}}
    by = {"claude": 0, "local": 0, "person": 0, "code": 0}
    now = time.time()
    for folder in folders:
        for r in records(folder):
            mb = str(r.get("made_by", ""))
            kind = "claude" if mb.startswith("claude-code-bg") else "local" if mb.startswith("local") else "code" if mb.startswith("code") else "person"
            by[kind] += 1
            if kind in ("code",):
                continue
            u = r.get("usage") or {}
            at = r.get("made_at") or ""
            m = at[:7] if len(at) >= 7 else "?"
            row = months.setdefault(m, {"month": m, "decisions": 0, "brain_s": 0.0, "tokens": 0, "api_equivalent_usd": 0.0, "local": 0})
            secs = float(u.get("seconds") or r.get("seconds") or 0)
            row["decisions"] += 1
            row["brain_s"] += secs
            row["tokens"] += int(u.get("context_tokens") or 0) + int(u.get("output_tokens") or 0)
            row["api_equivalent_usd"] += float(u.get("api_equivalent_usd") or 0)
            row["local"] += kind == "local"
            try:
                ts = time.mktime(time.strptime(at, "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                continue
            for k, win in (("h5", 5 * 3600), ("d7", 7 * 86400)):
                if now - ts <= win and kind == "claude":
                    recent[k]["decisions"] += 1
                    recent[k]["brain_s"] += secs
    out = sorted(months.values(), key=lambda x: x["month"], reverse=True)
    for x in out:
        x["brain_s"] = round(x["brain_s"], 1)
        x["api_equivalent_usd"] = round(x["api_equivalent_usd"], 2)
    for k in recent:
        recent[k]["brain_s"] = round(recent[k]["brain_s"], 1)
    mg, sb = magnific(), storyblocks()
    return {"months": out, "recent": recent, "by_brain": by, "paid_services": int(mg["connected"]) + int(sb["used"]), "local_tools": 0,
            "magnific": mg, "storyblocks": sb}


def storyblocks():
    """Storyblocks' use (sources/storyblocks.py, its use log): licensed downloads this month and today, by episode, against
    the per-episode cap; searches; any AUDIT (a link asked beyond the list)"""
    from ..montage.sources import storyblocks as SB
    month, today = time.strftime("%Y-%m"), time.strftime("%Y-%m-%d")
    u = SB.usage()
    dl = [x for x in u if x.get("what") == "download" and x.get("ok")]
    by_ep = {}
    for x in dl:
        if x.get("at", "").startswith(month):
            by_ep[x.get("project", "")] = by_ep.get(x.get("project", ""), 0) + 1
    return {"used": bool(u), "searches_month": sum(int(x.get("queries", 0)) for x in u if x.get("what") == "search" and x.get("at", "").startswith(month)),
            "downloads_month": sum(1 for x in dl if x.get("at", "").startswith(month)),
            "downloads_today": sum(1 for x in dl if x.get("at", "").startswith(today)), "cap_per_episode": SB.CAP_PER_EPISODE,
            "by_episode": by_ep, "licensed_calls_month": sum(len(x.get("asked") or []) for x in u if x.get("what") == "download-run" and x.get("at", "").startswith(month)),
            "audit": sum(1 for x in u if x.get("what") == "download-run" and x.get("extra")),
            "failed": sum(1 for x in u if x.get("what") == "download" and not x.get("ok"))}


def magnific():
    """Magnific's use (sources/magnific.py, its use log): searches and downloads this month and today against the daily
    cap, by episode, and the credit headers its replies gave (Magnific's own figures; the engine never guesses a price)"""
    from . import apikeys
    from ..montage.sources import magnific as MG
    month, today = time.strftime("%Y-%m"), time.strftime("%Y-%m-%d")
    u = MG.usage()
    dl = [x for x in u if x.get("what") == "download" and x.get("ok")]
    by_ep = {}
    for x in dl:
        if x.get("at", "").startswith(month):
            by_ep[x.get("project", "")] = by_ep.get(x.get("project", ""), 0) + 1
    last_heads = next((x["headers"] for x in reversed(u) if x.get("headers")), {})
    return {"connected": bool(apikeys.get(MG.KEY)), "searches_month": sum(1 for x in u if x.get("what") == "search" and x.get("at", "").startswith(month)),
            "downloads_month": sum(1 for x in dl if x.get("at", "").startswith(month)),
            "downloads_today": sum(1 for x in dl if x.get("at", "").startswith(today)), "daily_cap": MG.DAILY_CAP,
            "by_episode": by_ep, "credit_headers": last_heads, "failed": sum(1 for x in u if x.get("what") == "download" and not x.get("ok"))}


__all__ = ["summary"]

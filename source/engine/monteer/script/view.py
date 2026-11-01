"""The script writer's screens in the web panel (phase 6): one project's script as data, read-only (it never changes a
project). Built on the script tool's own files (monteer/script/common.py lists them).

  data(p) -> {stage, run, topic, channel, cards, outline, draft, approval, local, review}
    stage      topic -> research -> outline (stops for the owner's yes) -> draft -> review -> approved
    run        running or not, the step and its last lines, waiting for the owner's yes on the outline
    cards      the fact cards: what each says, the exact passage, the outlet, the date, the link (dropped ones counted)
    outline    the outline, whether it has the owner's yes (for this very outline), the notes given so far
    draft      the latest checked draft: each line with its type, its cards, and the checks' errors / warnings / labels;
               the script's totals (words against the target, errors, lines written by the local model)
    approval   approved (by, when, which version) and still valid; or cancelled by a later edit (when, why); a newer draft
               than the approved one also shows the approval as no longer current
    local      the brain this Mac can use: only the free local model -> it cannot write the outline or the draft
"""


from ..core.io import load_json
from .common import S, latest_version, sha


def channel_info(p):
    from . import style
    ch = p.channel
    out = {"profile": p.profile, "folder": str(ch) if ch else None, "style": None, "default_minutes": None, "wpm": None}
    if ch:
        st, _ = style.status(ch)
        out["style"] = st
        prof = ch / "style" / "style_profile.json"
        if prof.exists():
            ln = load_json(prof).get("length") or {}
            out["default_minutes"], out["wpm"] = ln.get("default_minutes"), ln.get("script_words_per_minute")
    return out


def stage_of(p):
    if S(p, "approved.json").exists():
        return "approved"
    v = latest_version(p)
    if v:
        return "review"
    if S(p, "drafts").exists() and any(S(p, "drafts").glob("*.raw.json")):
        return "draft"
    if S(p, "outline.json").exists():
        o = load_json(S(p, "outline.json"))
        ok = S(p, "outline_ok.json")
        return "draft" if ok.exists() and load_json(ok)["sha"] == sha(o["outline"]) else "outline"
    if S(p, "facts.json").exists() or S(p, "research").exists():
        return "research"
    return "topic"


def run_state(p):
    from ..core.runctl import lock_pid
    from ..core.summary import last_lines
    rec = load_json(p.run / "script_record.json") if (p.run / "script_record.json").exists() else {}
    log = last_lines(p.run / "script_log.txt", 40)
    waiting = load_json(p.run / "waiting.json") if (p.run / "waiting.json").exists() else []
    running = bool(lock_pid(p.folder))
    step = next((ln.split("] ", 1)[-1].split(":", 1)[0] for ln in reversed(log) if ": running —" in ln), None) if running else None
    failed = next((k for k, v in rec.items() if str(v.get("status", "")).startswith("failed")), None)
    return {"running": running, "step": step, "failed": failed, "log": log[-15:],
            "waiting_outline": any(w.get("key") == "outline" for w in waiting) and not running,
            "waiting_brain": [w for w in waiting if w.get("key") != "outline"] if not running else []}


def cards_of(p):
    f = S(p, "facts.json")
    if not f.exists():
        return {"ok": [], "dropped": 0}
    cs = load_json(f)["cards"]
    keep = ("id", "kind", "statement", "passage", "outlet", "pub_date", "url", "source_kind", "quote_ar", "speaker", "disputed", "period")
    return {"ok": [{k: c.get(k) for k in keep} for c in cs if c.get("status") == "ok"], "dropped": sum(1 for c in cs if c.get("status") != "ok")}


def outline_of(p):
    f = S(p, "outline.json")
    if not f.exists():
        return None
    o = load_json(f)
    ok = load_json(S(p, "outline_ok.json")) if S(p, "outline_ok.json").exists() else None
    notes = load_json(S(p, "outline_notes.json")).get("notes", []) if S(p, "outline_notes.json").exists() else []
    return {"outline": o["outline"], "target_words": o.get("target_words"), "minutes": o.get("minutes"), "made_by": o.get("made_by", ""),
            "ok": ok if ok and ok.get("sha") == sha(o["outline"]) else None, "notes": notes}


def draft_of(p):
    v = latest_version(p)
    if not v:
        return None
    dr = load_json(S(p, "drafts", f"v{v}.json"))
    ck = load_json(S(p, "drafts", f"v{v}.checks.json")) if S(p, "drafts", f"v{v}.checks.json").exists() else {"lines": {}, "script": {}, "totals": {}}
    items = []
    for x in dr["items"]:
        if x["kind"] == "line":
            items.append({"kind": "line", "id": x["id"], "part": x.get("part"), "text": x["text"], "type": x.get("type"), "cards": x.get("cards", []),
                          "commentary": x.get("commentary", False), "made_by": x.get("made_by", ""), "edited": bool(x.get("edited")),
                          "checks": ck["lines"].get(x["id"], [])})
        else:
            items.append({"kind": x["kind"], "text": x.get("text", "")})
    rv = S(p, "drafts", f"v{v}.review.json")
    docx = S(p, f"review_v{v}.docx")
    pending = S(p, "panel_edits.json").exists() or (rv.exists() and docx.exists() and load_json(rv)["sha"] != sha(docx.read_bytes()))
    return {"version": v, "title": dr.get("title", ""), "items": items, "script": ck.get("script", {}), "totals": ck.get("totals", {}),
            "review_docx": docx.name if docx.exists() else None, "edits_pending": pending, "edits": dr.get("edits", [])}


def approval_of(p):
    a = S(p, "approved.json")
    if a.exists():
        ap = load_json(a)
        v = latest_version(p)
        current = v == ap.get("version")
        return {"state": "approved" if current else "stale", "by": ap["by"], "at": ap["at"], "version": ap.get("version"),
                "why": None if current else f"draft v{v} is newer than the approved v{ap.get('version')}"}
    gone = sorted(S(p).glob("approved_cancelled_*.json")) if S(p).exists() else []
    if gone:
        c = load_json(gone[-1])
        return {"state": "cancelled", "by": c.get("by"), "at": c.get("at"), "version": c.get("version"),
                "cancelled_at": c.get("cancelled_at") or gone[-1].stem.split("_")[-2], "why": c.get("cancelled_why") or "a later edit"}
    return {"state": "none"}


def local_only():
    """True when this Mac's brain can only be the free local model (Claude Code missing or signed out)"""
    from ..core.claudebrain import status
    try:
        ok, _ = status()
    except Exception:  # noqa: BLE001
        ok = False
    return not ok


def data(p, check_brain=True):
    t = load_json(S(p, "topic.json")) if S(p, "topic.json").exists() else {}
    dr = draft_of(p)
    return {"stage": stage_of(p), "run": run_state(p), "topic": t, "channel": channel_info(p), "type": p.mode, "cards": cards_of(p),
            "outline": outline_of(p), "draft": dr, "approval": approval_of(p),
            "local": {"only_local": local_only() if check_brain else None,
                      "local_lines": (dr or {}).get("script", {}).get("local_lines", 0)}}


__all__ = ["data", "channel_info", "stage_of"]

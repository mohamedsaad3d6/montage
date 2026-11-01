"""The owner's line edits made in the web panel (phase 6), beside the Word round trip: they become the next draft through
the same import step (monteer/script/approve.py step_import): the approval is cancelled, edited lines that hold numbers
are given their cards, the checks run again and a new review copy is written.

  save(p, edits, by)   edits: [{"id": "L004", "text": "…"} | {"id": "L004", "delete": true} | {"id": "L004", "type": "map"}
                       | {"after": "L004", "text": "…", "type"?: "story"}] on the latest checked draft -> script/panel_edits.json
                       (pending); the panel then runs the script stage
  read(p)              in step_import: the pending edits -> (the next raw draft, the list of changes), or None
"""
import time

from ..core.io import load_json, save_json
from .common import S, latest_version

TYPES = ("archive", "news", "stock", "story", "map", "numbers")


def save(p, edits, by="owner (panel)"):
    v = latest_version(p)
    if not v:
        raise ValueError("لسه مفيش مسودة اتراجعت")
    dr = load_json(S(p, "drafts", f"v{v}.json"))
    ids = {x["id"] for x in dr["items"] if x["kind"] == "line"}
    clean = []
    for e in edits:
        ref = e.get("id") or e.get("after")
        if ref not in ids:
            raise ValueError(f"مفيش سطر {ref} في المسودة v{v}")
        if e.get("type") and e["type"] not in TYPES:
            raise ValueError(f"نوع سطر مش معروف: {e['type']}")
        if "after" in e and not (e.get("text") or "").strip():
            raise ValueError(f"السطر الجديد بعد {ref} فاضي")
        clean.append({k: (v_.strip() if isinstance(v_, str) else v_) for k, v_ in e.items() if k in ("id", "after", "text", "delete", "type")})
    if not clean:
        raise ValueError("مفيش تعديل")
    save_json(S(p, "panel_edits.json"), {"base_version": v, "by": by, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "edits": clean})
    return len(clean)


def read(p):
    f = S(p, "panel_edits.json")
    if not f.exists():
        return None
    pe = load_json(f)
    v = latest_version(p)
    f.rename(S(p, f"panel_edits_v{pe['base_version']}_{time.strftime('%Y%m%d-%H%M%S')}.json"))   # used once
    if pe["base_version"] != v:
        print(f"panel edits were made on draft v{pe['base_version']}, but the latest is v{v}: not applied (edit again)")
        return None
    dr = load_json(S(p, "drafts", f"v{v}.json"))
    by_id = {}
    for e in pe["edits"]:                        # several edits of one line (its text, then its type) are merged
        if e.get("id"):
            by_id.setdefault(e["id"], {}).update(e)
    after = {}
    for e in pe["edits"]:
        if e.get("after"):
            after.setdefault(e["after"], []).append(e)
    nxt = max([int(x["id"][1:]) for x in dr["items"] if x["kind"] == "line"] + [0])
    items, changed = [], []
    for x in dr["items"]:
        if x["kind"] != "line":
            items.append(x)
            continue
        e = by_id.get(x["id"], {})
        if e.get("delete"):
            changed.append(f"{x['id']}: deleted")
        else:
            y = dict(x)
            if e.get("text") and e["text"] != x["text"]:
                y.update(text=e["text"], edited=True)
                changed.append(f"{x['id']}: text edited")
            if e.get("type") and e["type"] != x["type"]:
                y["type"] = e["type"]
                changed.append(f"{x['id']}: type -> {e['type']}")
            items.append(y)
        for a in after.get(x["id"], []):
            nxt += 1
            items.append({"kind": "line", "id": f"L{nxt:03d}", "part": x.get("part"), "text": a["text"], "type": a.get("type") or "story",
                          "cards": [], "commentary": True, "names": [], "news": None, "made_by": "edited by hand", "edited": True, "new": True})
            changed.append(f"L{nxt:03d}: new line")
    if not changed:
        return None
    nd = dict(dr, version=v + 1, items=items, made_at=time.strftime("%Y-%m-%d %H:%M:%S"), from_review="the panel", from_panel=True,
              edits=changed)
    for k in ("verified_at", "revise_rounds"):
        nd.pop(k, None)
    return nd, changed


__all__ = ["save", "read"]

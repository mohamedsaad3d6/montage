"""The rulebook (web panel phase 9, and its "later" part: editing with review): the editing rules as data, read from the
rule files themselves (rules/rules_01_17.md, rules/rules_18_24.md), so the panel and the brain read the same text.

  rules()      [{n, title, text, where (as the rule names it), group, file, applied_in (code files that name the rule)}]
               and the other sections (the standing decisions, the channel profiles' table) as text
  propose(n, new_text, by)    an edit of one rule's text -> rules/proposals/<id>.json "proposed" (nothing changes yet)
  approve(id, by)             the owner's approval: the rule's text is replaced in its file (only if it is still the
                              text the edit started from) and rules/CHANGES.md records who, when and what
  reject(id, by, why)         the edit is set aside
A changed rule reaches every project: the rules are part of each judgement step's fingerprint (montage/steps.py
rules_sig), so those steps run again; a request whose words did not change keeps its decision.
"""
import difflib
import re
import time

from .io import load_json, save_json, write_text
from .paths import ENGINE

RULES = ENGINE / "rules"
FILES = ("rules_01_17.md", "rules_18_24.md")
PROPOSALS = RULES / "proposals"
CHANGES = RULES / "CHANGES.md"
WHERE = re.compile(r"\[([^\[\]]{3,})\]")


def _applied(n, cache={}):
    """the engine's code files that name rule n (e.g. «rule 11», «(rule 18», «rules 18-24» counts for 18 to 24)"""
    if not cache:
        for f in sorted((ENGINE / "monteer").rglob("*.py")):
            if f.name == "rulebook.py":
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            hits = {int(x) for x in re.findall(r"\brules? (\d{1,2})\b", text)}
            for a, b in re.findall(r"\brules (\d{1,2})[-–](\d{1,2})\b", text):
                hits |= set(range(int(a), int(b) + 1))
            for h in hits:
                cache.setdefault(h, []).append(str(f.relative_to(ENGINE)))
    return cache.get(n, [])


def rules():
    out, sections = [], []
    for name in FILES:
        lines = (RULES / name).read_text(encoding="utf-8").splitlines()
        group, cur, sec = None, None, None
        for ln in lines:
            m2 = re.match(r"^## (\d{1,2})\. (.+)$", ln)
            m1 = re.match(r"^(\d{1,2})\. (.+)$", ln)
            if m2:                                   # rules 18-24: a section each
                cur = {"n": int(m2.group(1)), "title": m2.group(2).strip(), "text": "", "group": "18-24", "file": name, "head": ln}
                out.append(cur)
                sec = None
                continue
            if ln.startswith("## "):
                group, cur = ln[3:].strip(), None
                sec = {"title": group, "file": name, "text": ""} if name == "rules_18_24.md" else None
                if sec:
                    sections.append(sec)
                continue
            if m1 and name == "rules_01_17.md":      # rules 1-17: a numbered item each
                body = m1.group(2).strip()
                t = re.match(r"^\*{1,2}(.+?)\*{1,2}\s*(.*)$", body)
                cur = {"n": int(m1.group(1)), "title": (t.group(1) if t else body[:60]).strip(" .*()"), "text": ln, "group": group,
                       "file": name, "item": True}
                out.append(cur)
                continue
            if sec is not None:
                sec["text"] += ln + "\n"
            elif cur is not None:
                cur["text"] += ("\n" if cur["text"] else "") + ln
    for r in out:
        r["text"] = r["text"].strip()
        r["where"] = "; ".join(c.strip() for c in WHERE.findall(r["text"]) if re.search(r"\.py|/|montage|cut|profile|render", c))
        r["applied_in"] = _applied(r["n"])
        r.pop("head", None)
    for s in sections:
        s["text"] = s["text"].strip()
    return {"rules": sorted(out, key=lambda r: r["n"]), "sections": sections}


def _rule(n):
    r = next((x for x in rules()["rules"] if x["n"] == int(n)), None)
    if not r:
        raise ValueError(f"no rule {n}")
    return r


def propose(n, new_text, by):
    r = _rule(n)
    new_text = (new_text or "").strip()
    if not new_text or new_text == r["text"]:
        raise ValueError("write the rule's new text")
    if r.get("item") and not re.match(rf"^{r['n']}\. ", new_text):
        raise ValueError(f"rule {n} keeps its number at the start («{n}. …»)")
    if not (by or "").strip():
        raise ValueError("an edit carries the person's name")
    PROPOSALS.mkdir(parents=True, exist_ok=True)
    pid = time.strftime("%Y%m%d-%H%M%S") + f"_r{r['n']}"
    rec = {"id": pid, "rule": r["n"], "file": r["file"], "old": r["text"], "new": new_text, "by": by.strip(),
           "at": time.strftime("%Y-%m-%d %H:%M:%S"), "status": "proposed",
           "diff": list(difflib.unified_diff(r["text"].splitlines(), new_text.splitlines(), "now", "proposed", lineterm=""))}
    save_json(PROPOSALS / f"{pid}.json", rec)
    return rec


def proposals():
    return [load_json(f) for f in sorted(PROPOSALS.glob("*.json"), reverse=True)] if PROPOSALS.exists() else []


def approve(pid, by):
    f = PROPOSALS / f"{pid}.json"
    if not f.exists():
        raise ValueError("no such edit")
    rec = load_json(f)
    if rec["status"] != "proposed":
        raise ValueError(f"this edit is {rec['status']}")
    if not (by or "").strip():
        raise ValueError("an approval carries the person's name")
    path = RULES / rec["file"]
    text = path.read_text(encoding="utf-8")
    if text.count(rec["old"]) != 1:
        raise ValueError("the rule changed since this edit was written: write the edit again")
    write_text(path, text.replace(rec["old"], rec["new"]))
    rec.update(status="applied", approved_by=by.strip(), approved_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    save_json(f, rec)
    log = CHANGES.read_text(encoding="utf-8") if CHANGES.exists() else "# Rule changes\n\nEvery change to the rules, approved by the owner in the panel.\n"
    write_text(CHANGES, log + f"\n## Rule {rec['rule']} — {rec['approved_at']} — approved by {rec['approved_by']} (written by {rec['by']})\n\n"
               + "```diff\n" + "\n".join(rec["diff"]) + "\n```\n")
    return rec


def reject(pid, by, why=""):
    f = PROPOSALS / f"{pid}.json"
    if not f.exists():
        raise ValueError("no such edit")
    rec = load_json(f)
    if rec["status"] != "proposed":
        raise ValueError(f"this edit is {rec['status']}")
    rec.update(status="rejected", rejected_by=(by or "").strip(), rejected_at=time.strftime("%Y-%m-%d %H:%M:%S"), why=(why or "")[:500])
    save_json(f, rec)
    return rec


__all__ = ["rules", "propose", "approve", "reject", "proposals"]

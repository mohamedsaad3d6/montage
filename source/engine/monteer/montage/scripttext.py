"""On-screen text from the approved script, not from whisper's transcript (must-do c of Works/output/agent_readiness_report.md,
owner's Phase 2 of 16 Oct 2026). Whisper mishears («نتيجها» for «ناتجها», «الفيدة» for «الفايدة»); the plan's anchors stay on
whisper's words (they carry the times), but what is SHOWN is the script's own spelling of the same words.

  script_tokens(p)        the approved script's words in order, as written (the script tool's script/lines.json, else the
                          project's inputs.script, .docx or (audio type) .txt; stage directions and Latin glosses left
                          out); [] when there is none
  Aligner(p, words)       whisper word index -> the script's word (difflib on the normalised words, in order)
     .shown(text, at)     the script's spelling of the said words starting at whisper index `at`, when every one of them
                          is matched to consecutive script words; else the text as it was
  vocabulary(p)           the normalised words of the script (the presenter type checks its graphics' words against it)
"""
import difflib
import re
from pathlib import Path

from ..core.io import load_json
from ..cut.common import normalize_ar

PUNCT = re.compile(r"[«»\"'“”‘’()\[\]{}:;,.!?؟،؛…\-–—]")


def _clean(w):
    return PUNCT.sub("", w).strip()


def script_tokens(p):
    lines = p.folder / "script" / "lines.json"
    if lines.exists():
        text = " ".join(x["text"] for x in load_json(lines)["lines"])
    else:
        src = p.input("script") if hasattr(p, "input") else None
        if not src or Path(src).suffix.lower() not in (".docx", ".txt") or not p.resolve(src).exists():
            return []
        from ..cut.script_text import docx_paragraphs, is_stage_direction, strip_latin_glosses
        f = p.resolve(src)
        paras = docx_paragraphs(f) if f.suffix.lower() == ".docx" else \
            [x.strip() for x in f.read_text(encoding="utf-8-sig", errors="replace").splitlines() if x.strip()]
        text = " ".join(strip_latin_glosses(x) for x in paras if not is_stage_direction(x))
    return [t for t in (_clean(w) for w in text.split()) if t]


class Aligner:
    def __init__(self, p, words):
        self.st = script_tokens(p)
        self.map = {}
        if not self.st:
            return
        a = [normalize_ar(t) for t in self.st]
        b = [w.get("n") or normalize_ar(w["w"]) for w in words]
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        for i, j, n in sm.get_matching_blocks():
            for k in range(n):
                self.map[j + k] = i + k
        # near misses inside a replaced stretch of the same length (whisper's misspelling of one word): matched in order
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "replace" and i2 - i1 == j2 - j1:
                for k in range(i2 - i1):
                    if difflib.SequenceMatcher(None, a[i1 + k], b[j1 + k]).ratio() >= 0.6:
                        self.map[j1 + k] = i1 + k

    @property
    def active(self):
        return bool(self.map)

    def shown(self, text, at):
        n = len(text.split())
        if not self.map or at is None or n == 0:
            return text
        idx = [self.map.get(at + k) for k in range(n)]
        if any(x is None for x in idx) or any(b != a + 1 for a, b in zip(idx, idx[1:])):
            return text
        return " ".join(self.st[x] for x in idx)


def vocabulary(p):
    sc = p.work / "script.json"
    if sc.exists():
        return {normalize_ar(w) for w in load_json(sc)["words"]}
    return {normalize_ar(t) for t in script_tokens(p)}


PREFIX = ("و", "ف", "ب", "ل", "ال", "وال", "بال", "لل", "فال")


def country_names_ar():
    """Arabic country names from the map data (a map's own labels are places, not speech)"""
    from ..montage.maps import _load
    return {normalize_ar(f["properties"].get("NAME_AR") or "") for f in _load("50m")} - {""}


def not_in_script(text, vocab, also=frozenset()):
    """the Arabic words of a text that the script does not hold, with or without a joined prefix (و، ال، ب ...); numbers,
    Latin and the words in `also` are not checked"""
    out = []
    for w in (_clean(x) for x in (text or "").split()):
        if not w or not re.search(r"[؀-ۿ]", w) or re.search(r"\d", w):
            continue
        n = normalize_ar(w)
        bare = {n} | {n[len(pre):] for pre in PREFIX if n.startswith(pre) and len(n) - len(pre) > 2}
        if bare & (set(vocab) | set(also)) or any(pre + b in vocab for b in bare for pre in PREFIX):
            continue
        out.append(w)
    return out

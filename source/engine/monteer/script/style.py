"""Learn the channel's style once, from its past scripts and the transcripts of what was actually recorded.

    bin/monteer script learn-style "<channel>" --from "<Works folder>"     measures + a style-guide request to the brain
    bin/monteer script style-approve "<channel>" --name "<who>"            your approval of the guide (edit it first if you like)

Reads only (never writes) the Works folder: project */*.docx (the scripts) and output/style_study/work/p*/ (the style
study's transcripts: cut length, words, ad-libs). Writes into <channel>/style/:
  style_profile.json   measured in code: length, pace, sentences, questions, numbers, catchphrases, glosses …
  style_guide.md       written by the brain from the scripts + the measures; yours to edit and approve
  examples.json        short excerpts of the channel's own scripts per move (checked word-for-word against the scripts)
  approved.json        who approved the guide, when, and its fingerprint (an edit after approval shows as "edited")
  edits.json           how drafts were changed before approval (each approval adds the pairs): later drafts read them
"""
import re
import statistics
from collections import Counter
from pathlib import Path

from ..core import brain
from ..core.io import load_json, save_json, write_text
from ..cut.script_text import docx_paragraphs, is_stage_direction, split_sentences
from .common import now, sha, style_dir
from .text import contains, nfkc, norm, numbers

COLLOQUIAL = ["ده", "دي", "دول", "اللي", "مش", "عشان", "ازاي", "ليه", "كده", "بقي", "دلوقتي", "يعني", "فيه", "بتاع", "اوي", "خالص", "برضه"]


class ChannelCtx:
    """what the brain needs of a "project" when the decision belongs to a channel (the style guide)"""

    def __init__(self, folder):
        self.folder = Path(folder).expanduser().resolve()
        self.decisions = style_dir(self.folder) / "decisions"
        self.options = {}
        self.name = self.folder.name

    def opt(self, k, default=None):
        return default


def find_scripts(works):
    out = []
    for d in sorted(Path(works).glob("project *")):
        for f in sorted(d.glob("*.docx")):
            if not f.name.startswith("~$"):
                out.append((d.name, f))
    return out


def measure(name, path):
    paras = [nfkc(p) for p in docx_paragraphs(path)]
    title, body = paras[0], paras[1:]
    stage = [p for p in body if is_stage_direction(p)]
    spoken = [p for p in body if not is_stage_direction(p)]
    text = "\n".join(spoken)
    sents = [s for p in spoken for s in split_sentences(p)]
    w = len(norm(text).split())
    sw = [len(norm(s).split()) for s in sents if norm(s)]
    toks = norm(text).split()
    cnt = Counter(toks)
    return {"project": name, "file": path.name, "title": title, "words": w, "paragraphs": len(spoken),
            "sentences": len(sents), "sentence_words_median": statistics.median(sw) if sw else 0,
            "sentence_words_p90": sorted(sw)[int(0.9 * (len(sw) - 1))] if sw else 0,
            "paragraph_words_median": statistics.median([len(norm(p).split()) for p in spoken]) if spoken else 0,
            "questions_per_1000_words": round(1000 * text.count("؟") / max(w, 1), 1),
            "numbers_per_1000_words": round(1000 * len(numbers(text)) / max(w, 1), 1),
            "stage_directions": len(stage), "pronunciation_notes": text.count("النطق"),
            "latin_glosses": len(re.findall(r"\(\s*[A-Za-z][^)]*\)", text)) + len(re.findall(r"[A-Za-z]{3,}", text)) // 4,
            "part_headers": sum(1 for p in body if re.match(r"^\(?\s*(الجزء|المحور|الفصل)", p)),
            "colloquial_per_1000_words": round(1000 * sum(cnt[c] for c in COLLOQUIAL) / max(w, 1), 1),
            "_text": text, "_stage": stage}


def ngrams(texts, n_min=2, n_max=4, min_scripts=3):
    per, total = Counter(), Counter()
    for t in texts:
        ws = norm(t).split()
        seen = set()
        for n in range(n_min, n_max + 1):
            for i in range(len(ws) - n + 1):
                g = " ".join(ws[i:i + n])
                total[g] += 1
                seen.add(g)
        for g in seen:
            per[g] += 1
    stop = {"في", "من", "علي", "على", "الي", "إلى", "ان", "إن", "و", "ده", "دي", "اللي", "مش", "هو", "هي", "كان", "عن", "مع", "لو", "ما"}
    keep = [(g, total[g], per[g]) for g in total if per[g] >= min_scripts and total[g] >= 5 and not all(x in stop for x in g.split())]
    keep.sort(key=lambda x: -x[1] * len(x[0].split()))
    out = []
    for g, c, s in keep:
        if not any(g in o[0] for o in out):
            out.append((g, c, s))
        if len(out) >= 30:
            break
    return [{"phrase": g, "count": c, "in_scripts": s} for g, c, s in out]


def transcripts(works):
    """per project: cut minutes, words heard, ad-libs (from the style study), so the length target is what is SAID"""
    out = []
    for f in sorted(Path(works, "output", "style_study", "work").glob("p*/script_vs_cut.json")):
        d = load_json(f)
        try:
            spoken_script = d["cut_words"] - d.get("adlib_words", 0)
            out.append({"project": f.parent.name, "cut_minutes": round(d["cut_minutes"], 2), "cut_words": d["cut_words"],
                        "adlib_words": d.get("adlib_words", 0), "script_words_per_minute": round(spoken_script / d["cut_minutes"], 1),
                        "script_words_recorded_pct": d.get("script_words_recorded_pct")})
        except (KeyError, TypeError, ZeroDivisionError):
            continue
    return out


GUIDE_SCHEMA = {"type": "object", "required": ["guide_md", "excerpts", "never"], "properties": {
    "guide_md": {"type": "string"},
    "excerpts": {"type": "array", "maxItems": 24, "items": {"type": "object", "required": ["move", "text", "from"], "properties": {
        "move": {"type": "string", "enum": ["opening", "scene", "number", "jargon", "official_vs_hidden", "transition", "question", "quote", "close"]},
        "text": {"type": "string"}, "from": {"type": "string"}}}},
    "never": {"type": "array", "items": {"type": "string"}}}}


def learn(channel, works):
    ch = ChannelCtx(channel)
    sd = style_dir(ch.folder)
    scripts = find_scripts(works)
    if not scripts:
        raise SystemExit(f"مالقيتش سكريبتات في {works}/project */*.docx")
    ms = [measure(n, f) for n, f in scripts]
    tr = transcripts(works)
    rate = statistics.mean(t["script_words_per_minute"] for t in tr) if tr else 125.0
    minutes = statistics.mean(t["cut_minutes"] for t in tr) if tr else 20.0
    keys = [k for k in ms[0] if not k.startswith("_") and isinstance(ms[0][k], (int, float))]
    profile = {"made_at": now(), "from": str(works), "scripts": [{k: v for k, v in m.items() if not k.startswith("_")} for m in ms],
               "transcripts": tr,
               "summary": {k: round(statistics.median(m[k] for m in ms), 1) for k in keys},
               "length": {"default_minutes": round(minutes, 1), "script_words_per_minute": round(rate, 1),
                          "default_words": int(round(minutes * rate, -1)),
                          "how": "mean cut length of the recorded episodes x script words spoken per minute (transcript words minus ad-libs)"},
               "catchphrases": ngrams([m["_text"] for m in ms]),
               "stage_direction_examples": [s for m in ms for s in m["_stage"]][:8]}
    save_json(sd / "style_profile.json", profile)
    inputs = {"measures": {k: profile[k] for k in ("summary", "length", "catchphrases", "stage_direction_examples")},
              "scripts": [{"project": m["project"], "title": m["title"], "text": m["_text"]} for m in ms]}
    instructions = (
        "You are writing the STYLE GUIDE of an Arabic YouTube channel (economics, money, geopolitics; Egyptian-Arabic "
        "narration by one presenter) from its past scripts and the measures made in code. The guide is used to write new "
        "scripts in the same voice, and the channel owner approves it. Write guide_md in Markdown (English headings and "
        "explanations; Arabic examples): the voice and register (how colloquial, where Modern Standard Arabic appears), how "
        "the presenter addresses the viewer, the structure of an episode (cold open, scenes, parts, transitions, ending), "
        "how numbers and jargon are explained, how foreign names are written (Arabic + Latin + pronunciation), how stage "
        "directions are written, rhythm (sentence length from the measures), recurring phrases (use the measured "
        "catchphrases; say how often is natural), and what to avoid. Base every point on the scripts; quote short examples. "
        "excerpts: 12-24 short passages (1-3 sentences) copied EXACTLY from the scripts, one 'move' each. never: things "
        "the channel never does. Answer with JSON only.")
    req = {"what": "the channel's style guide", "instructions": instructions, "inputs": inputs, "answer_schema": GUIDE_SCHEMA,
           "local_max_tokens": 8000}
    d = brain.decide(ch, "style", "guide", req)
    rec = brain.record(ch, "style", "guide") or {}
    full = "\n".join(m["_text"] for m in ms)
    good, bad = [], []
    for e in d["excerpts"]:
        (good if contains(full, e["text"]) else bad).append(e)
    save_json(sd / "examples.json", {"excerpts": good, "rejected_not_word_for_word": bad})
    head = (f"<!-- style guide — made {now()} by {rec.get('made_by', '?')} from {len(ms)} scripts; status: DRAFT until "
            f"`bin/monteer script style-approve` -->\n\n")
    meas = (f"\n\n## Measured in code (style_profile.json)\n\n"
            f"- Default length: **{profile['length']['default_minutes']} min** ≈ **{profile['length']['default_words']} script words** "
            f"({profile['length']['script_words_per_minute']} script words per minute of recording).\n"
            + "".join(f"- {k.replace('_', ' ')}: {v}\n" for k, v in profile["summary"].items())
            + "\n## Never\n\n" + "".join(f"- {x}\n" for x in d.get("never", [])))
    write_text(sd / "style_guide.md", head + d["guide_md"].strip() + meas)
    if not (sd / "edits.json").exists():
        save_json(sd / "edits.json", {"pairs": []})
    return profile, good, bad


def status(channel):
    sd = style_dir(channel)
    g = sd / "style_guide.md"
    if not g.exists():
        return "missing", None
    a = sd / "approved.json"
    if not a.exists():
        return "draft (not approved yet)", None
    ap = load_json(a)
    if ap["sha"] != sha(g.read_text(encoding="utf-8")):
        return f"edited after approval by {ap['by']} ({ap['at']}): approve again", ap
    return f"approved by {ap['by']} ({ap['at']})", ap


def approve(channel, name):
    g = style_dir(channel) / "style_guide.md"
    text = g.read_text(encoding="utf-8").replace("status: DRAFT until `bin/monteer script style-approve`", f"status: approved by {name}")
    write_text(g, text)
    save_json(style_dir(channel) / "approved.json", {"by": name, "at": now(), "sha": sha(text)})


def for_writer(channel):
    """what every outline/draft request gets: the guide, the measures, the excerpts, the latest edit pairs"""
    sd = style_dir(channel)
    if not (sd / "style_guide.md").exists():
        raise SystemExit(f"لسه مفيش دليل أسلوب للقناة: اكتبه في صفحة القناة، أو اتعلّمه من سكريبتاتها بالأمر "
                         f"bin/monteer script learn-style \"{channel}\" --from \"<Works folder>\"")
    prof = load_json(sd / "style_profile.json")
    ex = load_json(sd / "examples.json")["excerpts"] if (sd / "examples.json").exists() else []
    edits = load_json(sd / "edits.json")["pairs"][-15:] if (sd / "edits.json").exists() else []
    return {"guide": (sd / "style_guide.md").read_text(encoding="utf-8"), "measures": prof["summary"], "length": prof["length"],
            "catchphrases": prof["catchphrases"][:15], "excerpts": ex, "earlier_edits": edits, "status": status(channel)[0]}

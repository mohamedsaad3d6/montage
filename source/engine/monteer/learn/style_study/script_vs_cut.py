"""Layer A, content side: the reference editor's cut against the episode's script (measurement only).

    <core python> -m monteer.learn.style_study.script_vs_cut <pair dir>

Inputs in <pair dir>/: script.docx and the cut's transcript (asr_cut.json: words with n, s, e; made from the
whisper output by this script if only whisper_cut_turbo.json exists).
The engine's script aligner (monteer.cut.align.dp_align) walks the transcript through the script. Then:
  script sentences dropped       fewer than half of their words heard in the cut
  words added (ad-libs)          runs of 3+ transcript words that match no script word
  repeats                        script words heard more than once (a second take left in, or a callback)
With asr_raw.json (the raw recording's transcript) in the folder, script lines never recorded are left out.
Writes <pair dir>/script_vs_cut.json.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from ...cut.align import INSERT, dp_align, similarity
from ...cut.asr import tokens_to_words
from ...cut.common import normalize_ar, tc
from ..episode import bind


def script(path):
    # monteer.cut.script_text builds its paths at import: point them at this pair folder first (nothing is written)
    bind(Path(path).parent, script=path)
    from ...cut.script_text import docx_paragraphs, is_stage_direction, split_sentences, strip_latin_glosses
    # one episode's docx stores Arabic as presentation forms (U+FExx); NFKC turns them into plain letters
    import unicodedata
    paras = [unicodedata.normalize("NFKC", p) for p in docx_paragraphs(path)]
    sentences = []
    for para in paras[1:]:
        if not is_stage_direction(para):
            sentences += split_sentences(strip_latin_glosses(para))
    words, sent = [], []
    for i, s in enumerate(sentences):
        for w in normalize_ar(s).split():
            words.append(w)
            sent.append(i)
    return paras[0], sentences, words, sent


def main(p):
    d = Path(p)
    p = d.name
    asr = d / "asr_cut.json"
    if not asr.exists():
        raw = json.load(open(d / "whisper_cut_turbo.json", encoding="utf-8"))
        json.dump({"words": tokens_to_words(raw)}, open(asr, "w"), ensure_ascii=False)
    tw = json.load(open(asr, encoding="utf-8"))["words"]
    title, sentences, sw, sent = script(d / "script.docx")
    tn = [w["n"] for w in tw]
    ms = similarity(tn, sw)
    path = dp_align(ms)
    heard = np.zeros(len(sw), int)
    matched = np.zeros(len(tw), bool)
    for i, (t, j) in enumerate(path):
        if t != INSERT and j >= 0 and ms[i, j] > 0:
            heard[j] += 1
            matched[i] = True
    # with the raw recording's transcript (reference episodes A and B): which script lines were never recorded
    raw_heard = None
    if (d / "asr_raw.json").exists():
        rw = json.load(open(d / "asr_raw.json", encoding="utf-8"))["words"]
        rms = similarity([w["n"] for w in rw], sw)
        raw_heard = np.zeros(len(sw), int)
        for i, (t, j) in enumerate(dp_align(rms)):
            if t != INSERT and j >= 0 and rms[i, j] > 0:
                raw_heard[j] += 1
    dropped = []
    for k, s in enumerate(sentences):
        idx = [j for j in range(len(sw)) if sent[j] == k]
        frac = float((heard[idx] > 0).mean())
        if raw_heard is not None and float((raw_heard[idx] > 0).mean()) < 0.5:
            continue  # never recorded: not a cutting decision
        if frac < 0.5:
            # where it would have been: time of the nearest heard script word before it
            before = [i for i, (t, j) in enumerate(path) if matched[i] and j < idx[0]]
            at = tw[before[-1]]["e"] if before else 0.0
            dropped.append({"sentence": k, "words": len(idx), "heard_frac": round(frac, 2), "text": s, "cut_tc": tc(at)})
    adlib, run = [], []
    for i, w in enumerate(tw + [None]):
        if w is not None and not matched[i]:
            run.append(i)
            continue
        if len(run) >= 3:
            adlib.append({"cut_tc": tc(tw[run[0]]["s"]), "s": tw[run[0]]["s"], "e": tw[run[-1]]["e"],
                          "words": len(run), "text": " ".join(tw[k]["w"] for k in run)})
        run = []
    n_sw = len(sw)
    rec = (raw_heard > 0) if raw_heard is not None else np.ones(len(sw), bool)
    # the script's last block, never reached in the cut, is reported apart (a part saved for another episode)
    tail_start = len(sentences)
    while tail_start > 0 and any(x["sentence"] == tail_start - 1 for x in dropped):
        tail_start -= 1
    tail = [x for x in dropped if x["sentence"] >= tail_start]
    if len(tail) >= 5:
        dropped = [x for x in dropped if x["sentence"] < tail_start]
    else:
        tail = []
    res = {"title": title, "script_sentences": len(sentences), "script_words": n_sw,
           "cut_words": len(tw), "cut_minutes": round(tw[-1]["e"] / 60, 2),
           "script_words_heard_pct": round(100 * float((heard > 0).mean()), 1),
           "raw_transcript_used": raw_heard is not None,
           "script_words_recorded_pct": round(100 * float(rec.mean()), 1),
           "script_tail_not_in_cut": {"sentences": len(tail), "words": int(sum(x["words"] for x in tail)),
                                      "from_sentence": tail[0]["sentence"] if tail else None},
           "sentences_dropped": len(dropped), "dropped_words": int(sum(x["words"] for x in dropped)),
           "transcript_words_off_script_pct": round(100 * float((~matched).mean()), 1),
           "adlib_runs": len(adlib), "adlib_words": int(sum(a["words"] for a in adlib)),
           "adlib_seconds": round(sum(a["e"] - a["s"] for a in adlib), 1),
           "script_words_heard_twice": int((heard > 1).sum()),
           "dropped": dropped, "adlib": adlib}
    json.dump(res, open(d / "script_vs_cut.json", "w"), ensure_ascii=False, indent=1)
    print(p, {k: v for k, v in res.items() if k not in ("dropped", "adlib", "title")})


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="The editor's cut against the episode's script.")
    ap.add_argument("pair", help="pair folder (script.docx, asr_cut.json or whisper_cut_turbo.json); script_vs_cut.json is written there")
    main(ap.parse_args().pair)

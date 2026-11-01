"""Stage 3: whisper.cpp transcription with word timestamps.

Writes work/asr_<name>_<model>.json : {"words": [{"w": raw text, "n": normalized, "s", "e", "p"}], "seconds": runtime}
"""
import json
import shutil
import time

from .common import MODELS, WORK, cached, load_json, normalize_ar, save_json

DTW_PRESET = {"large-v3": "large.v3", "large-v3-turbo": "large.v3.turbo"}


def whisper_bin():
    for b in ("whisper-cli", "whisper-cpp", "main"):
        if shutil.which(b):
            return b
    raise SystemExit("whisper.cpp binary not found")


def tokens_to_words(data):
    words = []
    for seg in data["transcription"]:
        for tok in seg.get("tokens", []):
            text = tok["text"]
            if text.startswith("[_") or not text.strip():
                continue
            t0 = tok["offsets"]["from"] / 1000.0
            t1 = tok["offsets"]["to"] / 1000.0
            dtw = tok.get("t_dtw", -1)
            ts = dtw / 100.0 if dtw is not None and dtw >= 0 else t0
            if text.startswith(" ") or not words:
                words.append({"w": text.strip(), "s": ts, "e": t1, "ps": [tok.get("p", 1.0)]})
            else:
                words[-1]["w"] += text
                words[-1]["e"] = max(words[-1]["e"], t1)
                words[-1]["ps"].append(tok.get("p", 1.0))
    out = []
    for i, w in enumerate(words):
        n = normalize_ar(w["w"])
        if not n:
            continue
        p = min(w["ps"])
        out.append({"w": w["w"], "n": n, "s": w["s"], "e": w["e"], "p": round(float(p), 3)})
    # DTW gives token onsets; a word ends no later than the next word's onset
    for a, b in zip(out, out[1:]):
        if b["s"] > a["s"]:
            a["e"] = min(max(a["e"], a["s"] + 0.08), b["s"])
        a["e"] = max(a["e"], a["s"] + 0.05)
    return out


def transcribe(wav, name, model="large-v3", threads=8, force=False):
    dst = WORK / f"asr_{name}_{model}.json"
    if cached(dst) and not force:
        return load_json(dst)
    stem = WORK / f"whisper_{name}_{model}"
    t = time.time()
    from ..core import whisper_run          # its own printout to a file, progress and one summary line in the log
    pr = whisper_run.run([whisper_bin(), "-m", MODELS / f"ggml-{model}.bin", "-f", wav, "-l", "ar",
                          "-t", threads, "-mc", "0", "-ojf", "-of", stem, "-dtw", DTW_PRESET[model], "-nfa", "-np"], stem)
    secs = time.time() - t
    with open(f"{stem}.json", encoding="utf-8") as f:
        data = json.load(f)
    res = {"model": model, "seconds": secs, "words": tokens_to_words(data)}
    save_json(dst, res)
    print(whisper_run.summary(data, len(res["words"]), pr))
    print(f"asr {name}/{model}: {len(res['words'])} words in {secs / 60:.1f} min")
    return res

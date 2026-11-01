"""Vocals / words check for generated music (runs in ACE-Step's environment: torch + transformers).

    work/music_gen/ace_step/.venv/bin/python -I engine/music_tools/vocal_check.py file.wav

Two checks:
  1. Sound classifier (AST fine-tuned on AudioSet, BSD-3, local copy in work/music_gen/vocal_check/): over 10 s windows
     (5 s hop), the highest score of any voice class (speech, singing, choir, rapping, humming, ...).
     REJECT if it is above VOICE_MAX.
  2. Speech recognition (whisper large-v3-turbo, already on this Mac): confident real words. Whisper also invents
     words on pure music (it "heard" "we'll be right back" in our synthetic bed), so words alone don't decide:
     REJECT if it hears WORDS_MAX+ words AND the classifier hears something voice-like (above VOICE_HINT).
Prints one JSON line: {"vocals": bool, "reasons": [...], "voice_score": ..., "top_voice_labels": [...], "words": [...]}.
Thresholds were set on known clean and known vocal test files (see output/music_gen/report_music_step.md).
"""
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import torch
from transformers import ASTFeatureExtractor, ASTForAudioClassification

from monteer.core.paths import AST as AST_DIR, FFMPEG, WHISPER_CLI, WHISPER_MODEL

FF = str(FFMPEG)
WHISPER = str(WHISPER_CLI)
WMODEL = str(WHISPER_MODEL["large-v3-turbo"])

VOICE_LABELS = ["Speech", "Male speech, man speaking", "Female speech, woman speaking", "Child speech, kid speaking",
                "Conversation", "Narration, monologue", "Babbling", "Speech synthesizer", "Shout", "Yell", "Whispering",
                "Singing", "Choir", "Yodeling", "Chant", "Male singing", "Female singing", "Child singing",
                "Synthetic singing", "Rapping", "Humming", "Vocal music", "A capella", "Beatboxing"]
VOICE_MAX = 0.05          # reject if any voice class scores above this in any 10 s window
VOICE_HINT = 0.02         # ... and words only count when the classifier is above this
WORDS_MAX = 3             # reject if whisper hears this many real words (after removing its usual inventions)
WORD_PROB = 0.50          # ... each with at least this confidence
HALLUCINATIONS = {"thank", "you", "thanks", "for", "watching", "music", "bye", "so", "the", "subtitles", "by",
                  "amara", "org", "please", "subscribe", "and", "a", "uh", "um", "oh", "ah", "hmm", "mm",
                  "شكرا", "موسيقى", "ترجمة", "اشتركوا", "في", "القناة"}


def load16k(path):
    raw = subprocess.run([FF, "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def classifier(x):
    fe = ASTFeatureExtractor.from_pretrained(AST_DIR)
    model = ASTForAudioClassification.from_pretrained(AST_DIR).eval()
    labels = model.config.id2label
    idx = [i for i, n in labels.items() if n in VOICE_LABELS]
    win, hop = 160000, 80000
    starts = list(range(0, max(1, len(x) - win + hop), hop))
    best = {}
    with torch.no_grad():
        for s in starts:
            seg = x[s:s + win]
            if len(seg) < 16000:
                continue
            p = torch.sigmoid(model(**fe(seg, sampling_rate=16000, return_tensors="pt")).logits)[0]
            for i in idx:
                v = float(p[i])
                if v > best.get(labels[i], (0, 0))[0]:
                    best[labels[i]] = (v, s / 16000)
    top = sorted(best.items(), key=lambda kv: -kv[1][0])[:4]
    return (top[0][1][0] if top else 0.0), [{"label": k, "score": round(v, 3), "at_s": t} for k, (v, t) in top]


def heard_words(x):
    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "a.wav"
        import wave
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())
        subprocess.run([WHISPER, "-m", WMODEL, "-f", str(wav), "-l", "auto", "-ojf", "-of", str(Path(d) / "a"),
                        "-np", "-t", "8"], capture_output=True, check=True)
        js = json.load(open(Path(d) / "a.json", encoding="utf-8", errors="replace"))
    # whisper gives sub-word tokens: a token starting with a space starts a new word; a word counts if all of its
    # tokens are confident and it isn't one of whisper's usual inventions on music
    out = []
    for seg in js.get("transcription", []):
        cur, probs = "", []
        for tok in seg.get("tokens", []) + [{"text": " ", "p": 1.0}]:
            t = tok.get("text", "")
            if t.startswith("[_") or t.startswith("<|"):
                continue
            if t.startswith(" ") and cur:
                w = re.sub(r"\W", "", cur.lower())
                if w and w not in HALLUCINATIONS and min(probs) >= WORD_PROB:
                    out.append(w)
                cur, probs = "", []
            cur += t
            probs.append(tok.get("p", 0))
    return out


def check(path):
    x = load16k(path)
    score, top = classifier(x)
    words = heard_words(x)
    reasons = []
    if score > VOICE_MAX:
        reasons.append(f"voice detected: {top[0]['label']} {top[0]['score']:.2f} at {top[0]['at_s']:.0f} s")
    if len(words) >= WORDS_MAX and score > VOICE_HINT:
        reasons.append(f"words heard: {' '.join(words[:12])}")
    return {"vocals": bool(reasons), "reasons": reasons, "voice_score": round(score, 3), "top_voice_labels": top,
            "words": words, "thresholds": {"voice_max": VOICE_MAX, "voice_hint": VOICE_HINT, "words_max": WORDS_MAX, "word_prob": WORD_PROB}}


if __name__ == "__main__":
    for f in sys.argv[1:]:
        print(json.dumps(dict(check(f), file=f), ensure_ascii=False), flush=True)

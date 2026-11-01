"""Literal transcription with an Egyptian-Arabic wav2vec2 CTC model (no language model, so stammers and
repeated words stay in), with word times from the CTC frames (20 ms).

    <ml env python> -m monteer.cut.ctc_words in.wav out.json [t0 t1]      (the literal-words step runs this)

Writes {"words": [{"w", "s", "e"}]} in seconds of the input file.
"""
import json
import sys

import numpy as np
import torch
from scipy.io import wavfile
from transformers import Wav2Vec2ForCTC, Wav2Vec2Processor

from ..core.io import atomic
from ..core.paths import WAV2VEC2_EGYPTIAN

MODEL = "IbrahimAmin/egyptian-arabic-wav2vec2-xlsr-53"   # local copy: monteer_data/models/wav2vec2-egyptian
CHUNK, OVER = 20.0, 2.0
FRAME = 0.02


def main():
    src, dst = sys.argv[1], sys.argv[2]
    sr, x = wavfile.read(src)
    x = x.astype(np.float32) / 32768.0
    t0 = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    t1 = float(sys.argv[4]) if len(sys.argv) > 4 else len(x) / sr
    proc = Wav2Vec2Processor.from_pretrained(str(WAV2VEC2_EGYPTIAN))
    model = Wav2Vec2ForCTC.from_pretrained(str(WAV2VEC2_EGYPTIAN)).eval()
    torch.set_num_threads(8)
    vocab = {v: k for k, v in proc.tokenizer.get_vocab().items()}
    blank = proc.tokenizer.pad_token_id
    space = proc.tokenizer.word_delimiter_token_id
    words = []
    c = t0
    while c < t1:
        a, b = max(t0, c - OVER), min(t1, c + CHUNK + OVER)
        seg = x[int(a * sr): int(b * sr)]
        iv = proc(seg, sampling_rate=sr, return_tensors="pt").input_values
        with torch.no_grad():
            ids = model(iv).logits.argmax(-1)[0].numpy()
        # collapse CTC frames into characters with times, then words
        new, cur, prev = [], None, None
        for f, i in enumerate(ids):
            t = a + f * FRAME
            if i != prev and i not in (blank, space):
                ch = vocab[int(i)]
                if cur is not None and t - cur["e"] > 0.3:  # a long pause ends a word even without a space
                    new.append(cur)
                    cur = None
                if cur is None:
                    cur = {"w": ch, "s": t, "e": t + FRAME}
                else:
                    cur["w"] += ch
                    cur["e"] = t + FRAME
            elif i == prev and cur is not None and i not in (blank, space):
                cur["e"] = t + FRAME
            if i == space and cur is not None:
                new.append(cur)
                cur = None
            prev = i
        if cur is not None:
            new.append(cur)
        # keep only this chunk's words centred in its core (the overlap belongs to the neighbours)
        lo, hi = c, c + CHUNK
        words += [w for w in new if lo <= (w["s"] + w["e"]) / 2 < hi]
        c += CHUNK
        print(f"{c:.0f}/{t1:.0f}", end="\r", flush=True)
    words.sort(key=lambda w: w["s"])
    with atomic(dst) as tmp, open(tmp, "w", encoding="utf-8") as f:
        json.dump({"model": MODEL, "words": words}, f, ensure_ascii=False, indent=0)
    print(f"\n{len(words)} words")


if __name__ == "__main__":
    main()

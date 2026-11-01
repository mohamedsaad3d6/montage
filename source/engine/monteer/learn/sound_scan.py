"""What is in a recording's sound besides the voice? The AudioSet classifier (AST, local copy in monteer_data) over
windows of --window seconds every --hop seconds: the music score and the top labels of each window.

    <ml python> -m monteer.learn.sound_scan <audio16.wav> --out <sound_classes.json> [--window 10 --hop 30]

The two scans used so far: coarse  --window 10 --hop 30   (the default; top 4 labels, every window printed)
                           fine    --window 4 --hop 2 --top 6 --drop-speech --quiet
The wav must be 16 kHz mono 16-bit PCM.
"""
import argparse
import json

import numpy as np
import torch
from transformers import ASTFeatureExtractor, ASTForAudioClassification

from ..core.paths import AST

MUSIC = ("Music", "Musical instrument", "Background music", "Theme music")
SPEECH = ("Speech", "Narration, monologue", "Male speech, man speaking", "Speech synthesizer")


def main():
    ap = argparse.ArgumentParser(description="AudioSet labels of a recording's sound, window by window.")
    ap.add_argument("wav", help="16 kHz mono 16-bit wav")
    ap.add_argument("--out", required=True, help="output JSON file")
    ap.add_argument("--window", type=int, default=10, help="window length, s (default 10)")
    ap.add_argument("--hop", type=int, default=30, help="step between windows, s (default 30)")
    ap.add_argument("--top", type=int, default=4, help="labels kept per window (default 4)")
    ap.add_argument("--drop-speech", action="store_true", help="leave the speech labels out of the top labels")
    ap.add_argument("--quiet", action="store_true", help="print only windows with music > 0.1 or a label > 0.2")
    opt = ap.parse_args()
    torch.set_num_threads(2)
    x = np.fromfile(opt.wav, dtype=np.int16, offset=44).astype(np.float32) / 32768
    fe = ASTFeatureExtractor.from_pretrained(AST)
    m = ASTForAudioClassification.from_pretrained(AST).eval()
    lab = m.config.id2label
    out = []
    for t in range(0, int(len(x) / 16000) - opt.window, opt.hop):
        with torch.no_grad():
            p = torch.sigmoid(m(**fe(x[t * 16000:(t + opt.window) * 16000], sampling_rate=16000, return_tensors="pt")).logits)[0].numpy()
        top = [(lab[i], round(float(p[i]), 3)) for i in p.argsort()[::-1][:opt.top]
               if not (opt.drop_speech and lab[i] in SPEECH)]
        mus = round(float(max(p[i] for i, l in lab.items() if l in MUSIC)), 3)
        out.append({"t": t, "music": mus, "top": top})
        if not opt.quiet or mus > 0.1 or any(v > 0.2 for _, v in top):
            print(t, mus, top, flush=True)
    json.dump(out, open(opt.out, "w"), ensure_ascii=False, indent=0)


if __name__ == "__main__":
    main()

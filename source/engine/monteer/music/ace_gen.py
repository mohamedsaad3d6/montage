"""ACE-Step v1 3.5B generator for the music step (runs in ACE-Step's own environment, CPU, float32).

    <ml python> -m monteer.music.ace_gen \
        --seconds 70 --steps 27 --seed 42 --prompt "..." --out raw.wav

Prints one JSON line: load/generate time, peak memory, output file. Called by monteer/music/music.py.
"""
import argparse
import json
import resource
import time
from pathlib import Path

import torch
import torch.nn as nn

from monteer.core.paths import ACE_STEP as CKPT

# --- PyTorch 2.2.2 is the last build for Intel Macs; two things ACE-Step expects from newer versions:
if not hasattr(nn, "RMSNorm"):          # nn.RMSNorm arrived in torch 2.4
    class RMSNorm(nn.Module):
        def __init__(self, normalized_shape, eps=None, elementwise_affine=True, device=None, dtype=None):
            super().__init__()
            self.normalized_shape = (normalized_shape,) if isinstance(normalized_shape, int) else tuple(normalized_shape)
            self.eps = eps
            self.weight = nn.Parameter(torch.ones(self.normalized_shape, device=device, dtype=dtype)) if elementwise_affine else None

        def forward(self, x):
            dims = tuple(range(-len(self.normalized_shape), 0))
            eps = self.eps if self.eps is not None else torch.finfo(x.dtype).eps
            y = x * torch.rsqrt(x.pow(2).mean(dims, keepdim=True) + eps)
            return y * self.weight if self.weight is not None else y
    nn.RMSNorm = RMSNorm

from diffusers.models.modeling_utils import ModelMixin  # noqa: E402

# weight_norm layers can't be built on 'meta' tensors in torch 2.2, so diffusers must load the normal way
_fp = ModelMixin.from_pretrained.__func__
ModelMixin.from_pretrained = classmethod(lambda cls, *a, **k: _fp(cls, *a, **{"low_cpu_mem_usage": False, **k}))
from acestep.pipeline_ace_step import ACEStepPipeline  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, required=True)
    ap.add_argument("--steps", type=int, default=27)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lyrics", default="[instrumental]", help="only for testing the vocals check")
    a = ap.parse_args()
    t0 = time.time()
    pipe = ACEStepPipeline(checkpoint_dir=str(CKPT), dtype="float32")
    pipe.device = torch.device("cpu")   # CPU on purpose: this Mac also shows its AMD GPU as 'mps', untested with ACE-Step
    pipe.load_checkpoint(pipe.checkpoint_dir)
    t1 = time.time()
    pipe(format="wav", audio_duration=a.seconds, prompt=a.prompt, lyrics=a.lyrics, infer_step=a.steps,
         guidance_scale=15.0, scheduler_type="euler", cfg_type="apg", omega_scale=10.0, manual_seeds=[a.seed],
         guidance_interval=0.5, guidance_interval_decay=0.0, min_guidance_scale=3.0, use_erg_tag=True,
         use_erg_lyric=False, use_erg_diffusion=True, oss_steps=None, save_path=a.out)
    t2 = time.time()
    side = Path(a.out).with_name(Path(a.out).stem + "_input_params.json")   # ACE-Step writes this next to the wav
    if side.exists():
        side.unlink()
    print(json.dumps({"load_s": round(t1 - t0, 1), "generate_s": round(t2 - t1, 1),
                      "peak_rss_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**30, 2),
                      "file": a.out}))


if __name__ == "__main__":
    main()

"""AI stills for generic scenes only (never a specific real event), made on this Mac with SDXL-Lightning (4 steps).

    <ml python> -m monteer.ai.images "<project>"        (the ai_images step runs this)
Model: ByteDance/SDXL-Lightning 4-step UNet + stabilityai/stable-diffusion-xl-base-1.0 text encoders and VAE, both
CreativeML OpenRAIL++-M (free, commercial use allowed, no claim on the output; use restrictions in Attachment A).
Runs on the CPU in float32 (~95-116 s per 1344x768 image, ~26 GB peak memory).
Prompts: decision ai/prompts {"KEY": {"prompt", "why"}}; seeds: options.ai_seeds (default [11, 23]; a channel episode
[11] only, owner's decision 2a of 19 Oct 2026: one version, the pick still checks it).
Writes <assets ai>/<KEY>_s<seed>.png and ai_images.json. Resume: an image that exists is not made again.
Never at the same time as the music's ACE-Step (core/heavy.py, phase D): the images wait for a music take already going,
then go first.
"""
import json
import sys
import time

import torch
from diffusers import EulerDiscreteScheduler, StableDiffusionXLPipeline, UNet2DConditionModel
from safetensors.torch import load_file

from ..core.io import save_json
from ..core.paths import SDXL_BASE, SDXL_LIGHTNING
from ..core.project import Project

W, H = 1344, 768          # SDXL's native 16:9 size


def main():
    p = Project(sys.argv[1])
    prompts = json.load(open(p.decisions / "ai" / "prompts.json"))["decision"]
    from . import seeds as seeds_of
    seeds = seeds_of(p)
    out = p.asset_dir("ai")
    out.mkdir(parents=True, exist_ok=True)
    made_with = {}                                   # the prompt each existing image was made from (an image is remade when
    if (out / "ai_images.json").exists():            # its key's prompt has changed, never kept from an older prompt)
        for im in json.load(open(out / "ai_images.json")).get("images", []):
            made_with[(im["key"], im["seed"])] = im["prompt"]
    todo = [(k, s) for k in prompts for s in seeds
            if not (out / f"{k}_s{s}.png").exists() or made_with.get((k, s), prompts[k]["prompt"]) != prompts[k]["prompt"]]
    if not todo:
        print("ai images: all present")
        return
    from ..core import heavy
    with heavy.hold("drawn images", first=True, log=lambda s: print(s, flush=True)):   # never with the music (phase D)
        make(prompts, todo, out)


def make(prompts, todo, out):
    torch.set_grad_enabled(False)
    t0 = time.time()
    unet = UNet2DConditionModel.from_config(UNet2DConditionModel.load_config(SDXL_BASE / "unet"))
    unet.load_state_dict({k: v.float() for k, v in load_file(str(SDXL_LIGHTNING / "sdxl_lightning_4step_unet.safetensors")).items()})
    pipe = StableDiffusionXLPipeline.from_pretrained(SDXL_BASE, unet=unet, torch_dtype=torch.float32, variant="fp16", use_safetensors=True)
    pipe.scheduler = EulerDiscreteScheduler.from_config(pipe.scheduler.config, timestep_spacing="trailing")
    pipe.set_progress_bar_config(disable=True)
    logp = out / "ai_images.json"
    log = json.load(open(logp)) if logp.exists() else {"model": "SDXL-Lightning 4-step UNet (ByteDance) + SDXL 1.0 base text encoders/VAE",
                                                        "licence": "CreativeML OpenRAIL++-M", "images": []}
    log["load_s"] = round(time.time() - t0, 1)
    for k, seed in todo:
        t = time.time()
        img = pipe(prompts[k]["prompt"], num_inference_steps=4, guidance_scale=0.0, width=W, height=H,
                   generator=torch.Generator().manual_seed(seed)).images[0]
        f = out / f"{k}_s{seed}.png"
        tmp = out / f".{k}_s{seed}.part.png"
        img.save(tmp)
        tmp.replace(f)
        log["images"] = [im for im in log["images"] if (im["key"], im["seed"]) != (k, seed)]
        log["images"].append({"key": k, "seed": seed, "file": str(f), "size": [W, H], "steps": 4, "seconds": round(time.time() - t, 1),
                              "prompt": prompts[k]["prompt"], "why": prompts[k].get("why", "")})
        print(k, seed, round(time.time() - t, 1), "s", flush=True)
        save_json(logp, log)


if __name__ == "__main__":
    main()

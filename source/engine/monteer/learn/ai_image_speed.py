"""How fast could a free local image model run on this Intel Mac (CPU)? Measured WITHOUT downloading any model:
the networks are built from their official config files (a few KB) with random weights. Speed doesn't depend on the
weight values, so one denoising step and one image decode take the same time as with the real model.

    <ml python> -m monteer.learn.ai_image_speed --configs <configs dir> --out <ai_image_speed.json>

<configs dir> holds sd15/ and sdxl/, each with unet/config.json and vae/config.json (the models' official configs).
Needs torch + diffusers (the ml environment); nothing is downloaded or installed. Takes minutes (CPU).
"""
import argparse
import json
import resource
import time
from pathlib import Path

import torch
from diffusers import AutoencoderKL, UNet2DConditionModel

CFG = None   # set from --configs
torch.manual_seed(0)
torch.set_grad_enabled(False)


def timed(fn, n=3):
    fn()                                   # warm-up
    t = time.time()
    for _ in range(n):
        fn()
    return (time.time() - t) / n


def unet_step(name, px, batch, ctx_dim, xl):
    unet = UNet2DConditionModel.from_config(UNet2DConditionModel.load_config(CFG / name / "unet")).eval()
    params = sum(p.numel() for p in unet.parameters()) / 1e9
    lat = torch.randn(batch, 4, px // 8, px // 8)
    ctx = torch.randn(batch, 77, ctx_dim)
    kw = {"added_cond_kwargs": {"text_embeds": torch.randn(batch, 1280), "time_ids": torch.randn(batch, 6)}} if xl else {}
    s = timed(lambda: unet(lat, torch.tensor([500] * batch), encoder_hidden_states=ctx, **kw))
    del unet
    return round(s, 2), round(params, 2)


def vae_decode(name, px):
    vae = AutoencoderKL.from_config(AutoencoderKL.load_config(CFG / name / "vae")).eval()
    lat = torch.randn(1, 4, px // 8, px // 8)
    s = timed(lambda: vae.decode(lat), n=1)
    del vae
    return round(s, 2)


def main():
    global CFG
    ap = argparse.ArgumentParser(description="CPU speed of SD 1.5 / SDXL from their config files (random weights).")
    ap.add_argument("--configs", required=True, help="folder with sd15/{unet,vae} and sdxl/{unet,vae} config files")
    ap.add_argument("--out", required=True, help="output JSON file")
    opt = ap.parse_args()
    CFG = Path(opt.configs)
    res = {"threads": torch.get_num_threads(), "dtype": "float32", "device": "cpu"}
    s, p = unet_step("sd15", 512, 2, 768, False)
    res["sd15_512_step_cfg_s"], res["sd15_unet_params_b"] = s, p
    res["sd15_512_vae_decode_s"] = vae_decode("sd15", 512)
    s, p = unet_step("sdxl", 1024, 2, 2048, True)
    res["sdxl_1024_step_cfg_s"], res["sdxl_unet_params_b"] = s, p
    res["sdxl_1024_step_nocfg_s"] = unet_step("sdxl", 1024, 1, 2048, True)[0]
    res["sdxl_1024_vae_decode_s"] = vae_decode("sdxl", 1024)
    s, _ = unet_step("sdxl", 768, 2, 2048, True)
    res["sdxl_768_step_cfg_s"] = s
    res["peak_rss_gb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**30, 1)
    # one image = steps x step time + decode (+ ~1-3 s text encoding, not counted)
    res["estimate_per_image_s"] = {
        "SD 1.5, 512x512, 25 steps": round(25 * res["sd15_512_step_cfg_s"] + res["sd15_512_vae_decode_s"]),
        "SDXL base, 1024x1024, 30 steps": round(30 * res["sdxl_1024_step_cfg_s"] + res["sdxl_1024_vae_decode_s"]),
        "SDXL base, 768x768, 30 steps": round(30 * res["sdxl_768_step_cfg_s"] + res["sdxl_1024_vae_decode_s"] * 0.56),
        "SDXL-Lightning (4 steps, no CFG), 1024x1024": round(4 * res["sdxl_1024_step_nocfg_s"] + res["sdxl_1024_vae_decode_s"]),
    }
    json.dump(res, open(opt.out, "w"), indent=1)
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()

"""Our graphics: the scene list (decision graphics/scenes) -> PNG frames per scene, with the one renderer (bin gfx).

Resume: a scene whose definition is unchanged and whose frames are complete is not drawn again. Each scene is drawn into a
temporary folder and renamed when complete, so a crash never leaves a half scene that looks finished.
Text that still crosses the safe area (or its own band) after fitting is printed by the renderer ("fit: …") and kept in
gfx/text_fit.json per scene (owner's answer 4a of 19 Oct 2026); the report lists it.
Scenes use "renderer": "classic" for the classic drawing set (see gfx/gfx.swift); the default set uses the scene's own
"font" (a file name under monteer_data/assets/fonts, chosen by the variety rules), else the channel profile's font, else Cairo.
"""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

from ..core.paths import CAIRO_FONT, FONTS, GFX


def scene_sig(sc):
    return hashlib.sha256(json.dumps(sc, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def font_of(sc, font):
    own = FONTS / sc["font"] if sc.get("font") else None
    return str(own) if own and own.exists() else font


def render(scenes, frames_dir, font=None, only=None, log=print):
    frames_dir = Path(frames_dir)
    frames_dir.mkdir(parents=True, exist_ok=True)
    font = str(font or CAIRO_FONT)
    drawn = kept = 0
    fit_file = frames_dir.parent / "text_fit.json"
    fits = json.loads(fit_file.read_text()) if fit_file.exists() else {}
    for sc in scenes:
        name = sc["name"]
        if only and name not in only:
            continue
        final = frames_dir / name
        stamp = frames_dir / f".{name}.done"
        body = {k: v for k, v in sc.items() if k != "out"}
        sig = scene_sig(body)
        if final.is_dir() and stamp.exists() and stamp.read_text() == sig and len(list(final.glob("*.png"))) == sc["frames"]:
            kept += 1
            continue
        tmpdir = frames_dir / f".{name}.part"
        if tmpdir.exists():
            shutil.rmtree(tmpdir)
        tmpdir.mkdir()
        one = dict(body, out=str(tmpdir / "%05d.png"))
        spec = frames_dir / f".{name}.json"
        spec.write_text(json.dumps([one], ensure_ascii=False))
        cmd = [str(GFX), "--classic", str(spec)] if sc.get("renderer") == "classic" else [str(GFX), str(spec), font_of(sc, font)]
        r = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, text=True)
        over = [ln[5:].strip() for ln in r.stdout.splitlines() if ln.startswith("fit: ")]
        fits.pop(name, None)
        if over:
            fits[name] = over
            for ln in over:
                log(f"graphics: text outside its band: {ln}")
        if final.exists():
            shutil.rmtree(final)
        os.replace(tmpdir, final)
        spec.unlink()
        stamp.write_text(sig)
        drawn += 1
        log(f"graphics: {name} ({sc['frames']} frames)")
    fits = {k: v for k, v in fits.items() if any(sc["name"] == k for sc in scenes)}
    fit_file.write_text(json.dumps(fits, ensure_ascii=False, indent=1))
    log(f"graphics: {drawn} drawn, {kept} unchanged" + (f"; text outside its band in {len(fits)} scene(s)" if fits else ""))


def check(scenes, font=None):
    """the engine can use this scene list: unique names, frames match t_in/t_out at 24 fps, and the renderer reads it
    (run with a filter that draws nothing). Raises with the reason."""
    import tempfile
    names = [sc["name"] for sc in scenes]
    dup = {n for n in names if names.count(n) > 1}
    if dup:
        raise ValueError(f"scene names used twice: {sorted(dup)}")
    for sc in scenes:
        want = round((sc["t_out"] - sc["t_in"]) * 24)
        if abs(sc["frames"] - want) > 1:
            raise ValueError(f"scene {sc['name']}: frames {sc['frames']} but (t_out - t_in) * 24 = {want}")
    with tempfile.TemporaryDirectory() as d:
        for kind in ("main",):             # the classic set has no filter (it would draw everything): shape checks only
            group = [dict(sc, out=str(Path(d) / (sc["name"] + "_%05d.png"))) for sc in scenes if (sc.get("renderer") == "classic") == (kind == "classic")]
            if not group:
                continue
            spec = Path(d) / f"{kind}.json"
            spec.write_text(json.dumps(group, ensure_ascii=False))
            cmd = [str(GFX), "--classic", str(spec), "__check_only_draws_nothing__"] if kind == "classic" else \
                  [str(GFX), str(spec), str(font or CAIRO_FONT), "__check_only_draws_nothing__"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                raise ValueError(f"the renderer cannot read the {kind} scenes: {(r.stderr or r.stdout)[-600:]}")

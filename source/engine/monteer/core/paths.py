"""Where everything lives. The engine folder holds code only; everything else is found from here.

    AI agent/engine/          this code (git)
    AI agent/monteer_data/    tools, Python environments, models, caches   (MONTEER_DATA overrides)
    ~/.config/monteer/keys.json   API keys, filled in by the user           (MONTEER_KEYS overrides)
    <project folder>/         one video: project.json, decisions/, work/, output/, run/
"""
import os,sys,shutil
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[2]
PKG = ENGINE / "monteer"
RULES = ENGINE / "rules"
SETUP = ENGINE / "setup"

DATA = Path(os.environ.get("MONTEER_DATA", ENGINE.parent / "monteer_data")).expanduser().resolve()
# the channel profiles, one folder per channel (owner's answer 1 of 18 Oct 2026; monteer/core/profile.py)
CHANNELS = Path(os.environ.get("MONTEER_CHANNELS", ENGINE.parent / "channels")).expanduser().resolve()
KEYS = Path(os.environ.get("MONTEER_KEYS", "~/.config/monteer/keys.json")).expanduser()

TOOLS = DATA / "tools"
BIN = TOOLS / "bin"                     # ffmpeg, ffprobe, whisper-cli, gfx, faces, pick
FFMPEG = Path(os.environ.get("MONTAJ_FFMPEG") or shutil.which("ffmpeg") or BIN / "ffmpeg")
FFPROBE = Path(os.environ.get("MONTAJ_FFPROBE") or shutil.which("ffprobe") or BIN / "ffprobe")
WHISPER_CLI = Path(os.environ.get("MONTAJ_WHISPER-CLI") or shutil.which("whisper-cli") or BIN / "whisper-cli")
GFX = BIN / "gfx"                        # the one graphics renderer (compiled by setup)
FACES = BIN / "faces"                    # face finder for punch-in checks (compiled by setup)
PICK = BIN / "pick"                      # the web panel's file window (compiled by setup)
LLAMA_BIN = TOOLS / "llama" / "bin"      # llama-server + its own ggml libraries (kept apart from whisper's)
LLAMA_SERVER = LLAMA_BIN / "llama-server"
UV = TOOLS / "uv" / "uv"
ENVS = DATA / "envs"
CORE_PY = ENVS / "core" / "bin" / "python"
ML_PY = Path(os.environ.get("MONTAJ_ML_PYTHON",sys.executable))
MODELS = DATA / "models"
ASSETS = DATA / "assets"                 # fonts, map outlines (downloaded by setup)
FONTS = ASSETS / "fonts"
MAPS = ASSETS / "natural_earth"
CACHE = DATA / "cache"


def model(*parts):
    return MODELS.joinpath(*parts)


WHISPER_MODEL = {"large-v3": model("whisper", "ggml-large-v3.bin"),
                 "large-v3-turbo": model("whisper", "ggml-large-v3-turbo.bin")}
WAV2VEC2_EGYPTIAN = Path(os.environ.get("MONTAJ_CTC_MODEL",model("wav2vec2-egyptian")))
AST = model("ast-audioset")
ACE_STEP = model("ace-step", "ACE-Step-v1-3.5B")
SDXL_LIGHTNING = model("sdxl", "SDXL-Lightning")
SDXL_BASE = model("sdxl", "sdxl-base-1.0")
LOCAL_LLM = model("llm", "Qwen3-8B-Q4_K_M.gguf")   # the script tool's free local fallback brain
CAIRO_FONT = FONTS / "Cairo[slnt,wght].ttf"


def tool_env():
    """Environment for every child process: our tools first on PATH, every cache inside monteer_data,
    no telemetry, no implicit tokens, no network for model loading (models are local after setup)."""
    env = dict(os.environ)
    env["PATH"] = str(BIN) + os.pathsep + env.get("PATH", "")
    env.update(HF_HOME=str(CACHE / "hf"), HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
               HF_HUB_DISABLE_IMPLICIT_TOKEN="1", TORCH_HOME=str(CACHE / "torch"), XDG_CACHE_HOME=str(CACHE / "xdg"),
               UV_CACHE_DIR=str(CACHE / "uv"), PYTHONDONTWRITEBYTECODE="1", MPLCONFIGDIR=str(CACHE / "matplotlib"),
               NUMBA_CACHE_DIR=str(CACHE / "numba"))
    return env


os.environ["PATH"] = str(BIN) + os.pathsep + os.environ.get("PATH", "")

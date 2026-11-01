"""First-run setup: everything the engine needs that is not code, into monteer_data/ (never into the engine folder).

    ./monteer setup [--local-source "<old Works folder>"] [--download MODEL_ID ...] [--only PART ...]

Parts, in order (each is skipped when already complete and verified):
  uv        the Python installer (one file)
  python    Python 3.11 (uv-managed, inside monteer_data)
  envs      two environments: "core" (cut, montage, mix) and "ml" (music, AI images, literal words, classifier)
  ffmpeg    ffmpeg + ffprobe (static builds)
  whisper   whisper.cpp built from source at a pinned commit
  llama     llama.cpp's llama-server built from source at a pinned release (the script tool's free local fallback brain)
  models    every model file of setup/models.json, checked by SHA-256
  assets    fonts and map outlines of setup/tools.json, checked by SHA-256
  swift     the graphics renderer, the face finder and the panel's file window, compiled
  yt-dlp    for the learning tools only
With --local-source, a file is copied from the old folder when its SHA-256 matches (on the same disk the copy is an
APFS clone: instant and no extra space). Anything else is downloaded. --download forces a real download for the
listed model ids even when a local copy exists (used to test the first-run download).
Runs with the Mac's own python3 (the environments don't exist yet). Downloads send a neutral User-Agent and no token.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

from .paths import (BIN, CACHE, CORE_PY, DATA, ENGINE, ENVS, ML_PY, MODELS, SETUP, TOOLS, UV, ASSETS, FFMPEG, FFPROBE,
                    WHISPER_CLI, GFX, FACES, PICK, LLAMA_BIN, LLAMA_SERVER)

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) monteer-setup"
PYVER = "3.11.17"
RECORD = DATA / "setup_record.json"


def log(*a):
    print(f"[setup {time.strftime('%H:%M:%S')}]", *a, flush=True)


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def uv_env():
    e = dict(os.environ)
    e.update(UV_CACHE_DIR=str(CACHE / "uv"), UV_PYTHON_INSTALL_DIR=str(TOOLS / "python"), UV_PYTHON_PREFERENCE="only-managed",
             UV_PYTHON_INSTALL_BIN="0", UV_PYTHON_INSTALL_REGISTRY="0", UV_NO_CONFIG="1", PIP_DISABLE_PIP_VERSION_CHECK="1")
    return e


def download(url, dest, expect_sha=None):
    """download to a temporary name, check SHA-256, then rename (a half download never looks finished)"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.download")
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                got, last = 0, time.time()
                while True:
                    b = r.read(1 << 22)
                    if not b:
                        break
                    f.write(b)
                    got += len(b)
                    if time.time() - last > 20:
                        log(f"   {dest.name}: {got >> 20} / {total >> 20} MB")
                        last = time.time()
            break
        except Exception as ex:  # noqa: BLE001  (network errors of every kind: retry)
            log(f"   download failed ({ex}); retry {attempt + 1}/3 in {10 * (attempt + 1)} s")
            time.sleep(10 * (attempt + 1))
    else:
        raise SystemExit(f"could not download {url}")
    if expect_sha and sha256(tmp) != expect_sha:
        tmp.unlink()
        raise SystemExit(f"SHA-256 mismatch for {url}: the file is not the expected one, not used")
    os.replace(tmp, dest)
    return dest


def clone_copy(src, dest):
    """copy-on-write clone on APFS (cp -c), a normal copy elsewhere; to a temporary name, then rename"""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.copy")
    if subprocess.run(["cp", "-c", str(src), str(tmp)], capture_output=True).returncode != 0:
        shutil.copy2(src, tmp)
    os.replace(tmp, dest)


def fetch(dest, sha, url, local=None, force_download=False):
    """make `dest` hold the file with this SHA-256: already there -> keep; local copy -> clone; else download"""
    dest = Path(dest)
    if dest.exists() and sha256(dest) == sha:
        return "present"
    if local and not force_download and Path(local).exists():
        if sha256(local) == sha:
            clone_copy(local, dest)
            if sha256(dest) == sha:
                return "copied"
        log(f"   local copy {local} does not match; downloading instead")
    download(url, dest, sha)
    return "downloaded"


# ---------------------------------------------------------------------------------------------------- parts
def part_uv(tools, src, a):
    t = tools["uv"]
    if UV.exists() and sha256(UV) == t["sha256"]:
        return "present"
    local = src / t["local_source"] if src else None
    if local and local.exists() and sha256(local) == t["sha256"]:
        clone_copy(local, UV)
        UV.chmod(0o755)
        return "copied"
    with tempfile.TemporaryDirectory() as d:
        tgz = download(t["url"], Path(d) / "uv.tgz")
        with tarfile.open(tgz) as tf:
            m = tf.getmember(t["member"])
            m.name = "uv"
            tf.extract(m, d)
        if sha256(Path(d) / "uv") != t["sha256"]:
            raise SystemExit("uv: SHA-256 mismatch after download")
        clone_copy(Path(d) / "uv", UV)
    UV.chmod(0o755)
    return "downloaded"


def part_python(tools, src, a):
    r = subprocess.run([str(UV), "python", "find", PYVER], env=uv_env(), capture_output=True, text=True)
    if r.returncode == 0 and str(TOOLS / "python") in r.stdout:
        return "present"
    subprocess.run([str(UV), "python", "install", PYVER], env=uv_env(), check=True)
    return "installed"


def part_envs(tools, src, a):
    out = []
    for name, py, req in (("core", CORE_PY, "requirements-core.txt"), ("ml", ML_PY, "requirements-ml.txt")):
        stamp = ENVS / name / ".monteer_requirements"
        want = (SETUP / req).read_text()
        if py.exists() and stamp.exists() and stamp.read_text() == want:
            out.append(f"{name}: present")
            continue
        subprocess.run([str(UV), "venv", "--python", PYVER, "--allow-existing", str(ENVS / name)], env=uv_env(), check=True)
        # the ml list is a complete freeze of the environment that made the earlier music and images (ACE-Step's own
        # metadata asks for py3langid 0.3.0 but ran with 0.2.2 there), so it is installed exactly, without re-resolving
        nodeps = ["--no-deps"] if name == "ml" else []
        subprocess.run([str(UV), "pip", "install", "--python", str(py)] + nodeps + ["-r", str(SETUP / req)], env=uv_env(), check=True)
        stamp.write_text(want)
        out.append(f"{name}: installed")
    return ", ".join(out)


def part_ffmpeg(tools, src, a):
    res = []
    for name, target in (("ffmpeg", FFMPEG), ("ffprobe", FFPROBE)):
        t = tools[name]
        z = CACHE / "downloads" / f"{name}-{t['version']}.zip"
        how = fetch(z, t["sha256"], t["url"], src / t["local_source"] if src else None)
        stamp = target.with_name(f".{name}.sha")
        if not (target.exists() and stamp.exists() and stamp.read_text() == t["sha256"]):
            with zipfile.ZipFile(z) as zf, tempfile.TemporaryDirectory() as d:
                zf.extract(t["member"], d)
                clone_copy(Path(d) / t["member"], target)
            target.chmod(0o755)
            stamp.write_text(t["sha256"])
        res.append(f"{name} {how}")
    return ", ".join(res)


def part_whisper(tools, src, a):
    t = tools["whisper.cpp"]
    srcdir = TOOLS / "whisper.cpp"
    stamp = BIN / ".whisper.commit"
    want = t["commit"] + " " + " ".join(t["cmake"])
    if WHISPER_CLI.exists() and stamp.exists() and stamp.read_text() == want:
        return "present"
    if not (srcdir / ".git").exists():
        subprocess.run(["git", "clone", "--quiet", t["repo"], str(srcdir)], check=True)
    subprocess.run(["git", "-C", str(srcdir), "fetch", "--quiet", "origin", t["commit"]], check=False)
    subprocess.run(["git", "-C", str(srcdir), "checkout", "--quiet", t["commit"]], check=True)
    build = srcdir / "build"
    if build.exists():
        shutil.rmtree(build)                       # a clean build: settings never carry over from an earlier one
    for old in BIN.glob("lib*.dylib"):
        old.unlink()
    subprocess.run(["cmake", "-S", str(srcdir), "-B", str(build)] + t["cmake"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["cmake", "--build", str(build), "--config", "Release", "-j", "8", "--target", "whisper-cli"], check=True,
                   stdout=subprocess.DEVNULL)
    BIN.mkdir(parents=True, exist_ok=True)
    for f in (build / "bin").iterdir():           # whisper-cli and its libraries side by side (@loader_path)
        if f.name == "whisper-cli" or f.suffix == ".dylib":
            dst = BIN / f.name
            if dst.exists() or dst.is_symlink():
                dst.unlink()
            if f.is_symlink():
                os.symlink(os.readlink(f), dst)
            else:
                shutil.copy2(f, dst)
    for f in (build / "src").glob("libwhisper*.dylib"):
        dst = BIN / f.name
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        os.symlink(os.readlink(f), dst) if f.is_symlink() else shutil.copy2(f, dst)
    for f in (build / "ggml" / "src").rglob("libggml*.dylib"):
        dst = BIN / f.name
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        os.symlink(os.readlink(f), dst) if f.is_symlink() else shutil.copy2(f, dst)
    r = subprocess.run([str(WHISPER_CLI), "--help"], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("whisper-cli was built but does not start:\n" + r.stderr[-800:])
    stamp.write_text(want)
    return "built"


def part_llama(tools, src, a):
    """llama-server and its libraries in their own folder (tools/llama/bin), so they never mix with whisper's ggml libraries"""
    t = tools["llama.cpp"]
    srcdir = TOOLS / "llama.cpp"
    stamp = LLAMA_BIN / ".llama.commit"
    want = t["commit"] + " " + " ".join(t["cmake"])
    if LLAMA_SERVER.exists() and stamp.exists() and stamp.read_text() == want:
        return "present"
    if not (srcdir / ".git").exists():
        subprocess.run(["git", "clone", "--quiet", "--filter=blob:none", t["repo"], str(srcdir)], check=True)
    subprocess.run(["git", "-C", str(srcdir), "fetch", "--quiet", "origin", t["commit"]], check=False)
    subprocess.run(["git", "-C", str(srcdir), "checkout", "--quiet", t["commit"]], check=True)
    build = srcdir / "build"
    if build.exists():
        shutil.rmtree(build)
    subprocess.run(["cmake", "-S", str(srcdir), "-B", str(build)] + t["cmake"], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["cmake", "--build", str(build), "--config", "Release", "-j", "8", "--target"] + t["targets"], check=True,
                   stdout=subprocess.DEVNULL)
    if LLAMA_BIN.exists():
        shutil.rmtree(LLAMA_BIN)
    LLAMA_BIN.mkdir(parents=True)
    for f in (build / "bin").iterdir():
        if f.name in t["targets"] or f.suffix == ".dylib":
            os.symlink(os.readlink(f), LLAMA_BIN / f.name) if f.is_symlink() else shutil.copy2(f, LLAMA_BIN / f.name)
    for f in list((build / "src").glob("libllama*.dylib")) + list((build / "ggml" / "src").rglob("libggml*.dylib")) \
            + list((build / "tools" / "mtmd").glob("libmtmd*.dylib")):
        dst = LLAMA_BIN / f.name
        if not (dst.exists() or dst.is_symlink()):
            os.symlink(os.readlink(f), dst) if f.is_symlink() else shutil.copy2(f, dst)
    r = subprocess.run([str(LLAMA_SERVER), "--version"], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("llama-server was built but does not start:\n" + r.stderr[-800:])
    stamp.write_text(want)
    return f"built ({t['release']})"


def part_models(tools, src, a):
    man = json.loads((SETUP / "models.json").read_text())["models"]
    res = []
    for mid, m in man.items():
        force = mid in (a.download or [])
        counts = {}
        for f in m["files"]:
            local = (src / m["local_source"] / f["path"]) if src and m.get("local_source") else None
            how = fetch(MODELS / m["dest"] / f["path"], f["sha256"], f["url"], local, force_download=force)
            counts[how] = counts.get(how, 0) + 1
            if how != "present":
                log(f"   {mid}/{f['path']}: {how} ({f['size'] >> 20} MB)")
        res.append(f"{mid}: " + ", ".join(f"{v} {k}" for k, v in counts.items()))
    return "; ".join(res)


def part_assets(tools, src, a):
    res = []
    for rel, t in tools["assets"].items():
        how = fetch(ASSETS / rel, t["sha256"], t["url"], (src / t["local_source"]) if src and t.get("local_source") else None)
        res.append(f"{rel} {how}")
    return ", ".join(res)


SWIFT = {"gfx": (ENGINE / "monteer" / "gfx" / "gfx.swift", GFX), "faces": (ENGINE / "monteer" / "gfx" / "faces.swift", FACES),
         "pick": (ENGINE / "monteer" / "panel" / "pick.swift", PICK)}


def build_swift(name):
    """compile one Swift tool when it is missing or its source changed -> "present" / "compiled" (the panel calls it too)"""
    sw, target = SWIFT[name]
    stamp = target.with_name(f".{name}.sha")
    h = sha256(sw)
    if target.exists() and stamp.exists() and stamp.read_text() == h:
        return "present"
    BIN.mkdir(parents=True, exist_ok=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{name}.build")
    subprocess.run(["swiftc", "-O", str(sw), "-o", str(tmp)], check=True, env=dict(os.environ, TMPDIR=str(CACHE)))
    os.replace(tmp, target)
    stamp.write_text(h)
    return "compiled"


def part_swift(tools, src, a):
    return ", ".join(f"{name} {build_swift(name)}" for name in SWIFT)


def part_ytdlp(tools, src, a):
    """yt-dlp, for the learning tools only (a style study downloads a channel's published videos)"""
    t = tools["yt-dlp"]
    how = fetch(BIN / "yt-dlp", t["sha256"], t["url"], (src / t["local_source"]) if src and t.get("local_source") else None)
    (BIN / "yt-dlp").chmod(0o755)
    return how


PARTS = [("uv", part_uv), ("python", part_python), ("envs", part_envs), ("ffmpeg", part_ffmpeg), ("whisper", part_whisper),
         ("llama", part_llama), ("models", part_models), ("assets", part_assets), ("swift", part_swift), ("yt-dlp", part_ytdlp)]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="monteer setup")
    ap.add_argument("cmd", nargs="?")
    ap.add_argument("--local-source", help="an old Works folder: files whose SHA-256 matches are copied instead of downloaded")
    ap.add_argument("--download", nargs="*", help="model ids to download for real even if a local copy exists")
    ap.add_argument("--only", nargs="*", help="run only these parts")
    a = ap.parse_args(argv)
    src = Path(a.local_source).expanduser().resolve() if a.local_source else None
    tools = json.loads((SETUP / "tools.json").read_text())
    for d in (TOOLS, BIN, ENVS, MODELS, ASSETS, CACHE):
        d.mkdir(parents=True, exist_ok=True)
    rec = json.loads(RECORD.read_text()) if RECORD.exists() else {}
    log(f"monteer_data: {DATA}")
    for name, fn in PARTS:
        if a.only and name not in a.only:
            continue
        t0 = time.time()
        log(f"{name} ...")
        res = fn(tools, src, a)
        secs = round(time.time() - t0, 1)
        rec[name] = {"result": res, "seconds": secs, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        RECORD.write_text(json.dumps(rec, indent=1))
        log(f"{name}: {res} ({secs} s)")
    log("setup complete")


if __name__ == "__main__":
    main(sys.argv[1:])

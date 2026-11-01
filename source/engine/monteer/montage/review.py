"""Contact sheets for looking at every downloaded clip before use: 3 frames each (15 %, 50 %, 85 %), labelled id@time,
6 clips per sheet. -> <out>/stock_NN.jpg (rows are kept, so a rerun only adds new clips)."""
import subprocess
from pathlib import Path

from ..core.paths import FFMPEG, FFPROBE

FF, FP = str(FFMPEG), str(FFPROBE)
LABEL_FONT = "/System/Library/Fonts/Helvetica.ttc"


def contact_sheets(clips_dir, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in sorted(Path(clips_dir).glob("*.mp4")):
        k = p.stem
        row = out / f"row_{k}.jpg"
        if not row.exists():
            d = float(subprocess.run([FP, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                                     capture_output=True, text=True).stdout or 0)
            if d <= 0:
                continue
            ins, fc = [], []
            for i, f in enumerate((0.15, 0.5, 0.85)):
                t = d * f
                ins += ["-ss", f"{t:.2f}", "-i", str(p)]
                fc.append(f"[{i}:v]scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:-1:-1,drawtext=fontfile={LABEL_FONT}:"
                          f"text='{k} @{t:.0f}s/{d:.0f}':fontsize=26:fontcolor=yellow:box=1:boxcolor=black@0.6:x=6:y=6[v{i}]")
            fc.append("[v0][v1][v2]hstack=3")
            subprocess.run([FF, "-v", "error", "-y"] + ins + ["-filter_complex", ";".join(fc), "-frames:v", "1", str(row)], stderr=subprocess.DEVNULL)
        rows.append(row)
    sheets = []
    for j in range(0, len(rows), 6):
        grp = rows[j:j + 6]
        ins = sum([["-i", str(r)] for r in grp], [])
        sheet = out / f"stock_{j // 6:02d}.jpg"
        subprocess.run([FF, "-v", "error", "-y"] + ins + ["-filter_complex", "".join(f"[{i}]" for i in range(len(grp))) + f"vstack={len(grp)}"
                        if len(grp) > 1 else "null", "-frames:v", "1", "-q:v", "4", str(sheet)])
        sheets.append(sheet)
    print(len(rows), "clips,", len(sheets), "contact sheets")
    return sheets


def sheet_rows(rows, stem):
    """some clips' rows (three frames each) as sheets of up to 6 rows -> [sheet files <stem>_<n>.jpg]"""
    stem = Path(stem)
    stem.parent.mkdir(parents=True, exist_ok=True)
    sheets = []
    for j in range(0, len(rows), 6):
        grp = rows[j:j + 6]
        sheet = stem.parent / f"{stem.name}_{j // 6}.jpg"
        if not sheet.exists():
            ins = sum([["-i", str(r)] for r in grp], [])
            subprocess.run([FF, "-v", "error", "-y"] + ins + ["-filter_complex", "".join(f"[{i}]" for i in range(len(grp))) + f"vstack={len(grp)}"
                            if len(grp) > 1 else "null", "-frames:v", "1", "-q:v", "4", str(sheet)])
        sheets.append(sheet)
    return sheets


BLACK_BELOW = 25.0          # a clip whose own mean luma is under this is nearly black: never used (new montages)


def clip_luma(p, key, cache=None):
    """a downloaded clip's own mean luma (0-255, 2 frames a second on a small scale), cached in work/montage/clip_luma.json"""
    import json
    import subprocess
    from ..core.paths import FFMPEG
    cache_f = p.work / "montage" / "clip_luma.json"
    c = cache if cache is not None else (json.loads(cache_f.read_text()) if cache_f.exists() else {})
    if key not in c:
        f = next((d / f"{key}.mp4" for d in (p.asset_dir("stock"), p.asset_dir("library")) if (d / f"{key}.mp4").exists()), None)
        if f is None:
            return None
        r = subprocess.run([str(FFMPEG), "-v", "error", "-i", str(f), "-vf", "fps=2,scale=96:54,format=gray", "-f", "rawvideo", "-"],
                           capture_output=True).stdout
        c[key] = round(sum(r) / max(1, len(r)), 1)
        if cache is None:
            cache_f.parent.mkdir(parents=True, exist_ok=True)
            cache_f.write_text(json.dumps(c, indent=1))
    return c[key]


def safe_grades(p, clip_fx, dark_below=70.0):
    """the clip review's "dark" grade (brightness -0.06, gamma 0.80, vignette) on a clip that is already dark turns it
    almost black (v12: a storm clip of mean luma 48 came out at 3): such clips get "mild" instead. The clip's own mean
    luma (0-255, on a small scale) is measured once and cached in work/montage/clip_luma.json. New montages only."""
    import json
    import subprocess
    from ..core.paths import FFMPEG
    cache_f = p.work / "montage" / "clip_luma.json"
    cache = json.loads(cache_f.read_text()) if cache_f.exists() else {}
    out = {}
    for key, fx in (clip_fx if isinstance(clip_fx, dict) else {}).items():
        fx = dict(fx) if isinstance(fx, dict) else fx
        if isinstance(fx, dict) and fx.get("grade") == "dark":
            if key not in cache:
                f = next((d / f"{key}.mp4" for d in (p.asset_dir("stock"), p.asset_dir("library")) if (d / f"{key}.mp4").exists()), None)
                if f is None:
                    out[key] = fx
                    continue
                r = subprocess.run([str(FFMPEG), "-v", "error", "-i", str(f), "-vf", "fps=2,scale=96:54,format=gray", "-f", "rawvideo", "-"],
                                   capture_output=True).stdout
                cache[key] = round(sum(r) / max(1, len(r)), 1)
            if cache[key] < dark_below:
                fx["grade"] = "mild"
                fx["grade_note"] = f"'dark' asked, but the clip's own mean luma is {cache[key]}: mild instead"
        out[key] = fx
    cache_f.parent.mkdir(parents=True, exist_ok=True)
    cache_f.write_text(json.dumps(cache, indent=1))
    return out

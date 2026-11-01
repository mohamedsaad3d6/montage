"""Stage 7b: render the EDL. Video from the raw camera file, audio from the synced external mic.

Renders in chunks (video-only H.264 + PCM wav per chunk), concatenates the chunks losslessly,
then muxes and encodes AAC once so there are no per-chunk AAC priming gaps.

`inserts` adds black picture + silence after a source time (e.g. a slot the editor fills later
with the channel intro): [{"after": src_seconds, "dur": seconds}].
`fades` gives some piece edges a longer audio fade than FADE: [{"t": src_seconds, "side": "in"|"out",
"d": seconds, "at": src_seconds}] (breath.py). With "at", a fade-out ends there and the audio is silent
from there to the piece end (a fade-in starts there, silent before): the picture still cuts on a frame.
"""
import hashlib
import os

from .common import EDIT_VIDEO, FPS, RAW_VIDEO, WORK, run
from .sync import SYNC48

CHUNK = 60
FADE = 0.01
CHUNK_DIR = WORK / "render"


def filter_script(items):
    lines, vl, al = [], [], []
    for k, it in enumerate(items):
        if "gap" in it:
            d = it["gap"]
            lines.append(f"color=c=black:s=1920x1080:r={FPS}:d={d:.6f},format=yuv420p,setsar=1[v{k}];")
            lines.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={d:.6f}[a{k}];")
        else:
            s, e = it["seg"]
            d = e - s
            lines.append(f"[0:v]trim=start={s:.6f}:end={e:.6f},setpts=PTS-STARTPTS,setsar=1[v{k}];")
            fi, fo = it.get("fade_in", FADE), it.get("fade_out", FADE)
            si = max(0.0, it.get("fade_in_at", s) - s)
            so = max(0.0, min(d, it.get("fade_out_at", e) - s) - fo)
            lines.append(f"[1:a]atrim=start={s:.6f}:end={e:.6f},asetpts=PTS-STARTPTS,"
                         f"afade=t=in:st={si:.6f}:d={fi},afade=t=out:st={so:.6f}:d={fo}[a{k}];")
        vl.append(f"[v{k}]")
        al.append(f"[a{k}]")
    lines.append(f"{''.join(vl)}concat=n={len(items)}:v=1:a=0[vout];")
    lines.append(f"{''.join(al)}concat=n={len(items)}:v=0:a=1[aout]")
    return "\n".join(lines)


def items_of(keep, inserts=(), fades=()):
    """the cut's pieces in order: {"seg": [s, e], fade_in?, fade_in_at?, fade_out?, fade_out_at?} and {"gap": seconds}"""
    items = []
    for s, e in keep:
        it = {"seg": [s, e]}
        for f in fades:
            if f["side"] == "in" and abs(f["t"] - s) < 1e-3:
                it["fade_in"] = f.get("d", FADE)
                it["fade_in_at"] = f.get("at", s)
            elif f["side"] == "out" and abs(f["t"] - e) < 1e-3:
                it["fade_out"] = f.get("d", FADE)
                it["fade_out_at"] = f.get("at", e)
        items.append(it)
        items += [{"gap": i["dur"]} for i in inserts if abs(i["after"] - e) < 0.05]
    return items


def audio_lines(items, src="[0:a]"):
    """the audio half of filter_script: the same trims and fades, from another track on the raw timeline"""
    lines, al = [], []
    for k, it in enumerate(items):
        if "gap" in it:
            lines.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={it['gap']:.6f}[a{k}];")
        else:
            s, e = it["seg"]
            d = e - s
            fi, fo = it.get("fade_in", FADE), it.get("fade_out", FADE)
            si = max(0.0, it.get("fade_in_at", s) - s)
            so = max(0.0, min(d, it.get("fade_out_at", e) - s) - fo)
            lines.append(f"{src}atrim=start={s:.6f}:end={e:.6f},asetpts=PTS-STARTPTS,"
                         f"afade=t=in:st={si:.6f}:d={fi},afade=t=out:st={so:.6f}:d={fo}[a{k}];")
        al.append(f"[a{k}]")
    lines.append(f"{''.join(al)}concat=n={len(items)}:v=0:a=1[aout]")
    return "\n".join(lines)


def render_audio(keep, src_wav, out_wav, work, inserts=(), fades=()):
    """the cut's sound made from another track on the raw timeline (src_wav: 48 kHz stereo, e.g. the camera voice cleaned
    before the cut): exactly the cut's pieces, trims and fades, chunk by chunk as render() does, at 24 bit"""
    work.mkdir(parents=True, exist_ok=True)
    items = items_of(keep, inserts, fades)
    parts = []
    for ci in range(0, len(items), CHUNK):
        chunk = items[ci: ci + CHUNK]
        segs = [it["seg"] for it in chunk if "seg" in it]
        t0 = max(0.0, segs[0][0] - 2.0) if segs else 0.0
        fs, a = work / f"a{ci // CHUNK:03d}.txt", work / f"a{ci // CHUNK:03d}.wav"
        fs.write_text(audio_lines(chunk))
        cmd = ["ffmpeg", "-y", "-v", "error", "-copyts"]
        if segs:                       # input seek + copyts keeps absolute timestamps, so trim times are source seconds
            cmd += ["-ss", f"{t0:.3f}", "-to", f"{segs[-1][1] + 1:.3f}"]
        run(cmd + ["-i", src_wav, "-/filter_complex", fs, "-map", "[aout]", "-c:a", "pcm_s24le", "-ar", "48000", a])
        parts.append(a)
    (work / "a.txt").write_text("".join(f"file '{p}'\n" for p in parts))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", work / "a.txt", "-c:a", "pcm_s24le", out_wav])
    return out_wav


def render(keep, out_path=EDIT_VIDEO, crf=18, preset="medium", inserts=(), fades=()):
    CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    items = items_of(keep, inserts, fades)
    vlist, alist = [], []
    for ci in range(0, len(items), CHUNK):
        chunk = items[ci: ci + CHUNK]
        segs = [it["seg"] for it in chunk if "seg" in it]
        t0 = max(0.0, segs[0][0] - 2.0)
        fs = CHUNK_DIR / f"c{ci // CHUNK:03d}.txt"
        script = filter_script(chunk)
        v, a = CHUNK_DIR / f"c{ci // CHUNK:03d}.mp4", CHUNK_DIR / f"c{ci // CHUNK:03d}.wav"
        # resume: a chunk whose inputs, filter and settings are unchanged is not rendered again
        stamp = CHUNK_DIR / f"c{ci // CHUNK:03d}.done"
        sig = hashlib.sha256(f"{script}|{t0:.3f}|{segs[-1][1]:.3f}|{RAW_VIDEO}|{crf}|{preset}".encode()).hexdigest()
        if not (v.exists() and a.exists() and stamp.exists() and stamp.read_text() == sig):
            fs.write_text(script)
            tv, ta = v.with_name(f".{v.stem}.part.mp4"), a.with_name(f".{a.stem}.part.wav")
            # input seek + copyts keeps absolute timestamps, so trim times are source seconds
            run(["ffmpeg", "-y", "-v", "error", "-copyts",
                 "-ss", f"{t0:.3f}", "-to", f"{segs[-1][1] + 1:.3f}", "-i", RAW_VIDEO,
                 "-ss", f"{t0:.3f}", "-to", f"{segs[-1][1] + 1:.3f}", "-i", SYNC48,
                 "-/filter_complex", fs, "-map", "[vout]",
                 "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
                 "-r", str(FPS), "-an", tv,
                 "-map", "[aout]", "-vn", "-c:a", "pcm_s16le", "-ar", "48000", ta])
            os.replace(tv, v)
            os.replace(ta, a)
            stamp.write_text(sig)
        vlist.append(v)
        alist.append(a)
    (CHUNK_DIR / "v.txt").write_text("".join(f"file '{p}'\n" for p in vlist))
    (CHUNK_DIR / "a.txt").write_text("".join(f"file '{p}'\n" for p in alist))
    # write next to the target and rename: an earlier version hard-linked to out_path stays untouched
    tmp = f"{out_path}.part.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", CHUNK_DIR / "v.txt",
         "-f", "concat", "-safe", "0", "-i", CHUNK_DIR / "a.txt",
         "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", tmp])
    os.replace(tmp, out_path)
    return out_path

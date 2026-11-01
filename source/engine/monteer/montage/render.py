"""Render the montage from its cut list: every shot to its own exact-length piece, then one join, then the final encode.

Shot kinds:
  gfx         our graphics: PNG frames from the graphics step (a scene can be entered at any moment of it)
  video       stock/library footage: usable window, crop, blur, grade, push-in/pull-out, grain, overlays
  photo / ai  stills: cover crop, slow drift or push, archive grade + paper overlay for history photos, the rule-19 entry
              (slides in from the top while going from blurred to sharp), grain, overlays
  insert      an earlier rendered block (inputs.insert: {"edl": its render_edl.json, "segments": its pieces folder}),
              re-graded with grain on its footage, photos and site shots; joined, then taken from the matching frame
  presenter   the cut (talking head) at a source time, full frame, punched in (crop) or slowly pushed in; in the pop-up
              layout only (montage/steps_popups.py): in black and white ("bw") and with pop-ups as overlays
  black_beat  the cut's own black slot frames (same as presenter without a crop)
Resume: a piece whose command is unchanged and whose frame count is right is not rendered again; pieces are written
under a temporary name and renamed when complete. Every piece carries BT.709 colour tags so the join is a plain copy.
"""
import hashlib
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..core.io import atomic
from ..core.paths import FFMPEG, FFPROBE
from .look import GRADE_ARCHIVE, GRAIN, PAPER_OPACITY

FF, FP = str(FFMPEG), str(FFPROBE)
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", "-r", "24", "-an"]
TAIL = "setsar=1,format=yuv420p,setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709"
GRADE = {"mild": "eq=brightness=-0.03:saturation=0.92:gamma=0.92", "dark": "eq=brightness=-0.06:saturation=0.85:gamma=0.80,vignette=PI/4.5",
         "none": "null"}
ENTRY_S = 0.45                                     # rule 19: slide in from the top while going from blurred to sharp
# transitions on cuts (the phrase montage): drawn on the INCOMING shot's first frames, so every piece keeps its
# exact length and the join stays a plain copy. zoom: settles from 118% to 100% in 7 frames; flash: a white flash fading
# in 4 frames; slide: slides in from the right edge in 0.3 s; zoomflash: both (section changes).
TRANS = {"zoom": "scale=w='trunc(1920*(1+0.18*max(0\\,1-n/7))/2)*2':h=-2:eval=frame,crop=1920:1080",
         "flash": "eq=brightness='0.55*max(0\\,1-t/0.17)':eval=frame",
         "slide": "pad=3840:1080:1920:0:color=0x0B0907,crop=1920:1080:x='1920*(1-pow(max(0\\,1-t/0.3)\\,3))':y=0"}
TRANS["zoomflash"] = TRANS["zoom"] + "," + TRANS["flash"]


def tr(s):
    """the transition filter for a shot, or '' """
    return (TRANS[s["transition"]] + ",") if s.get("transition") in TRANS else ""


def push(n, mode):
    """zoompan expression over n frames: slow push-in (tension), pull-out (end) or a gentle default drift for stills"""
    if mode == "in":
        z = f"1+0.12*on/{max(1, n - 1)}"
    elif mode == "out":
        z = f"1.14-0.14*on/{max(1, n - 1)}"
    else:
        z = f"1+0.06*on/{max(1, n - 1)}"
    return f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1920x1080:fps=24"


class Renderer:
    def __init__(self, seg_dir, gfx_dir, tex_dir, insert=None, presenter_video=None):
        self.SEG, self.GFX, self.TEX = Path(seg_dir), Path(gfx_dir), Path(tex_dir)
        self.insert = insert or {}
        self.presenter_video = presenter_video

    def overlay_inputs(self, s, base_label, nin):
        ins, fc, last = [], [], base_label
        ovs = [o for o in s.get("overlays", []) if o["start_frame"] < len(list((self.GFX / o["name"]).glob("*.png")))]
        for j, o in enumerate(ovs):
            ins += ["-framerate", "24", "-start_number", str(o["start_frame"]), "-i", str(self.GFX / o["name"] / "%05d.png")]
            delay = f",tpad=start={o['delay_frames']}:color=0x00000000" if o.get("delay_frames") else ""   # on its word (phrase montage)
            fc.append(f"[{nin + j}:v]format=rgba{delay}[o{j}];[{last}][o{j}]overlay=0:0:eof_action=pass[ov{j}]")
            last = f"ov{j}"
        return ins, fc, last

    def seg_cmd(self, i, s, out):
        n = s["nframes"]
        out = str(out)
        pad = f"tpad=stop_mode=clone:stop_duration={n / 24 + 1:.2f}"
        if s["kind"] == "gfx":
            sc_t = s["src_t"] if s.get("src_t") is not None else s["f0"] / 24
            start = max(0, int(round((sc_t - s["scene_t_in"]) * 24)))
            nfr = len(list((self.GFX / s["scene"]).glob("*.png")))
            start = min(start, max(0, nfr - 1))
            slow_in = (f"scale=w='trunc(1920*(1+{s['push']}*n/{max(1, n - 1)})/2)*2':h=-2:eval=frame,crop=1920:1080,"
                    if s.get("push") else "")      # a slow push-in over the shot (news screenshots, montage/news.py)
            bw = "hue=s=0," if s.get("bw") else ""      # inside اقتصاد احمس's black-and-white open (audio only)
            return [FF, "-v", "error", "-y", "-framerate", "24", "-start_number", str(start), "-i", str(self.GFX / s["scene"] / "%05d.png"),
                    "-frames:v", str(n), "-vf", f"format=rgb24,{pad},{slow_in}{bw}{tr(s)}{TAIL}"] + ENC + [out]
        if s["kind"] in ("presenter", "black_beat"):
            vf = []
            if s["kind"] == "presenter" and s.get("push_to"):
                p = s["push_to"]
                z = 1920 / p["w"]
                vf.append(f"scale=3840:2160,zoompan=z='1+{z - 1:.5f}*on/{max(1, n - 1)}':x='{2 * p['x']}*on/{max(1, n - 1)}':"
                          f"y='{2 * p['y']}*on/{max(1, n - 1)}':d=1:s=1920x1080:fps=24")
            elif s["kind"] == "presenter" and s.get("zoom", 1) > 1:
                c = s["crop"]
                vf.append(f"crop={c['w']}:{c['h']}:{c['x']}:{c['y']},scale=1920:1080:flags=lanczos")
            if s.get("bw"):                    # اقتصاد احمس's black-and-white open (a channel profile; never otherwise)
                vf.append("hue=s=0")
            if s.get("overlays"):              # pop-ups beside the presenter (montage/steps_popups.py; only that layout)
                oi, ofc, last = self.overlay_inputs(s, "b", 1)
                fc = [f"[0:v]{','.join(vf + [pad])}[b]"] + ofc + [f"[{last}]{tr(s)}{TAIL}[v]"]
                return [FF, "-v", "error", "-y", "-ss", "%.4f" % (s["cut_in"] - 0.001), "-i", str(self.presenter_video)] + oi + \
                    ["-filter_complex", ";".join(fc), "-map", "[v]", "-frames:v", str(n)] + ENC + [out]
            vf += [pad, tr(s) + TAIL]          # a transition only when the presenter type marked one (none in the classic)
            return [FF, "-v", "error", "-y", "-ss", "%.4f" % (s["cut_in"] - 0.001), "-i", str(self.presenter_video), "-frames:v", str(n),
                    "-vf", ",".join(vf)] + ENC + [out]
        if s["kind"] == "video":
            fx = s.get("fx", {})
            vf = ["fps=24"]
            if fx.get("crop"):
                vf.append(crop_filter(s["src"], *fx["crop"]))
            vf.append("scale=1920:1080:force_original_aspect_ratio=increase:flags=lanczos,crop=1920:1080,setsar=1")
            if fx.get("blur"):
                vf.append(f"gblur=sigma={fx['blur']}")
            if s.get("zoom"):
                vf.append("scale=3840:2160," + push(n, s["zoom"]))
            vf.append(GRADE[fx.get("grade", "mild")])
            if s.get("bw"):                    # اقتصاد احمس's black-and-white open, audio only (a channel profile; never otherwise)
                vf.append("hue=s=0")
            vf.append(GRAIN)
            vf.append(pad)
            loop = ["-stream_loop", "-1"] if s["src_in"] + n / 24 > s.get("src_dur", 1e9) - 0.1 else []
            ins = ["-ss", f"{s['src_in']:.3f}"] + loop + ["-i", s["src"]]
            oi, ofc, last = self.overlay_inputs(s, "b", 1)
            fc = [f"[0:v]{','.join(vf)}[b]"] + ofc + [f"[{last}]{tr(s)}{TAIL}[v]"]
            return [FF, "-v", "error", "-y"] + ins + oi + ["-filter_complex", ";".join(fc), "-map", "[v]", "-frames:v", str(n)] + ENC + [out]
        # stills: archive photos and AI images
        hist = s.get("paper")
        ins = ["-loop", "1", "-framerate", "24", "-i", s["src"], "-loop", "1", "-framerate", "24", "-i", str(self.TEX / "paper_overlay.png")]
        nin = 2
        base = f"[0:v]scale=3840:2160:force_original_aspect_ratio=increase:flags=lanczos,crop=3840:2160,setsar=1,{push(n, s.get('zoom'))}"
        if s.get("parallax") and Path(s["parallax"]).exists():     # a drawn still with its depth-parallax clip (the move is in it)
            ins[:6] = ["-i", s["parallax"]]
            base = f"[0:v]fps=24,scale=1920:1080,setsar=1,{pad}"
        base += f",{GRADE_ARCHIVE}" if hist else f",{GRADE['mild']}"
        if s.get("framed"):                    # under the framed copy (اقتصاد احمس audio only): the photo blurred and darker
            base += ",gblur=sigma=30,eq=brightness=-0.22"
        if s.get("bw"):                        # its black-and-white open (audio only)
            base += ",hue=s=0"
        fc = []
        if s.get("entry"):
            if hist:
                ins += ["-loop", "1", "-framerate", "24", "-i", str(self.TEX / "paper.png")]
                bg = f"[{nin}:v]scale=1920:1080,setsar=1[bg]"
            else:
                ins += ["-f", "lavfi", "-i", "color=c=0x0B0907:s=1920x1080:r=24"]
                bg = f"[{nin}:v]setsar=1[bg]"
            nin += 1
            fc += [f"{base},split[s][b]", "[b]gblur=sigma=28[bl]",
                   f"[bl][s]blend=all_expr='A*(1-clip(T/{ENTRY_S},0,1))+B*clip(T/{ENTRY_S},0,1)'[ph]", bg,
                   f"[bg][ph]overlay=x=0:y='-H*pow(1-min(t/{ENTRY_S},1),3)':shortest=0[e]"]
            cur = "e"
        else:
            fc.append(f"{base}[e]")
            cur = "e"
        if hist:
            fc.append(f"[{cur}]format=gbrp[pa];[1:v]format=gbrp[pp];[pa][pp]blend=all_mode=softlight:all_opacity={PAPER_OPACITY},vignette=PI/5[h]")
            cur = "h"
        fc.append(f"[{cur}]format=yuv420p,{GRAIN}[g]")
        oi, ofc, last = self.overlay_inputs(s, "g", nin)
        fc += ofc + [f"[{last}]{tr(s)}{TAIL}[v]"]
        return [FF, "-v", "error", "-y"] + ins + oi + ["-filter_complex", ";".join(fc), "-map", "[v]", "-frames:v", str(n)] + ENC + [out]

    def insert_cmds(self, i, s, work):
        """the inserted block: its pieces re-graded (grain on footage/photos/site shots), joined, then from the matching frame"""
        edl1 = json.load(open(self.insert["edl"]))
        pdir = Path(work) / "insert"
        pdir.mkdir(parents=True, exist_ok=True)
        cmds, files = [], []
        for sh in edl1["shots"]:
            src = Path(self.insert["segments"]) / f"{sh['n']:02d}.mp4"
            dst = pdir / f"{sh['n']:02d}.mp4"
            files.append(dst)
            vf = GRAIN if sh["kind"] in ("video", "still", "site") else "null"
            cmds.append([FF, "-v", "error", "-y", "-i", str(src), "-vf", f"{vf},{TAIL}"] + ENC + [str(dst)])
        lst = pdir / "list.txt"
        lst.write_text("".join(f"file '{f}'\n" for f in files))
        full = pdir / "insert_full.mp4"
        join = [FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(full)]
        final = [FF, "-v", "error", "-y", "-i", str(full), "-vf",
                 f"trim=start_frame={s['offset_frames']},setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=2,{TAIL}",
                 "-frames:v", str(s["nframes"])] + ENC
        return cmds + [join], final


def dims(path, cache={}):
    """(width, height) of a video's first stream, or None"""
    if path not in cache:
        r = subprocess.run([FP, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0",
                            str(path)], capture_output=True, text=True)
        try:
            cache[path] = tuple(int(v) for v in r.stdout.strip().split(",")[:2])
        except ValueError:
            cache[path] = None
    return cache[path]


def crop_filter(src, x, y, w):
    """the review's 16:9 window (x, y as shares of the frame, w as a share of the width). A clip wider than 16:9 made the
    window taller than the clip (the first real test: 2720×1434 and 3412×1440 failed): then the window is the largest
    16:9 one that fits, kept as close to the review's spot as the frame allows. A window that fits is written as before."""
    d = dims(src)
    if not d or (d[0] * w * 9 / 16 + d[1] * y <= d[1] and d[0] * (x + w) <= d[0] + 0.5):
        return f"crop=iw*{w}:iw*{w}*9/16:iw*{x}:ih*{y}"
    W, H = d
    cw = min(W * w, H * 16 / 9)
    cw = int(cw) // 2 * 2
    ch = int(cw * 9 / 16) // 2 * 2
    cx = int(min(max(0, W * x), W - cw))
    cy = int(min(max(0, H * y), H - ch))
    return f"crop={cw}:{ch}:{cx}:{cy}"


PIECE_TIMEOUT_S = 300                 # owner's answer 2a of 19 Oct 2026: a piece never runs without end


def piece_timeout(s):
    return PIECE_TIMEOUT_S + s.get("nframes", 0) * 0.5      # longer shots get a little more time


def precheck(r, edl, only=None):
    """every shot's material, before anything is rendered (owner's answer 5a of 19 Oct 2026: all problems at once instead
    of one failed piece at a time): the file is there and is what it should be, the graphic's frames exist, a clip's crop
    fits. -> [(shot, time s, problem)]"""
    from .sources import picture_kind, video_ok
    out = []
    for i, s in enumerate(edl["shots"]):
        if only is not None and i not in only:
            continue
        t = round(s.get("f0", 0) / 24, 1)
        k = s["kind"]
        if k == "gfx":
            if not list((r.GFX / s["scene"]).glob("*.png")):
                out.append((i, t, f"graphic {s['scene']}: no frames drawn"))
        elif k in ("photo", "ai", "still", "site"):
            src = s.get("src", "")
            kind = picture_kind(src) if src and Path(src).exists() else None
            if not src or not Path(src).exists():
                out.append((i, t, f"picture missing: {src}"))
            elif kind is None or kind == "GIF":         # a GIF cannot be read as a still (the test's shot 16)
                out.append((i, t, f"not a usable picture ({kind or 'not an image'}): {src}"))
            if s.get("parallax") and not Path(s["parallax"]).exists():
                out.append((i, t, f"depth clip missing: {s['parallax']}"))
        elif k == "video":
            if not s.get("src") or not video_ok(s["src"]):
                out.append((i, t, f"not a playable video: {s.get('src')}"))
        elif k in ("presenter", "black_beat"):
            if not r.presenter_video or not Path(r.presenter_video).exists():
                out.append((i, t, f"presenter video missing: {r.presenter_video}"))
        for o in s.get("overlays", []):
            if not list((r.GFX / o["name"]).glob("*.png")):
                out.append((i, t, f"overlay {o['name']}: no frames drawn"))
    return out


def count_frames(p):
    return int(subprocess.run([FP, "-v", "error", "-count_packets", "-select_streams", "v:0", "-show_entries", "stream=nb_read_packets",
                               "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout.strip().strip(",") or 0)


def inputs_sig(r, s):
    """what a piece is made from besides its command: each graphic's own stamp (a graphic redrawn under the same name)
    and each picture file's size and time (an image remade under the same name). Without this a piece whose command did
    not change was kept with the old picture (v13: a resized headline card). Empty for a piece that uses neither."""
    out = []
    for n in ([s["scene"]] if s["kind"] == "gfx" else []) + [o["name"] for o in s.get("overlays", [])]:
        st = Path(r.GFX) / f".{n}.done"
        out.append([n, st.read_text() if st.exists() else ""])
    for f in (s.get("src"), s.get("parallax")):
        if f and Path(f).exists():
            st = Path(f).stat()
            out.append([str(f), st.st_size, st.st_mtime_ns])
    return out


def segments(r, edl, work, only=None, threads=6, log=print):
    """render every shot (or the indices in `only`) -> r.SEG/NNNN.mp4; returns the list of failures"""
    r.SEG.mkdir(parents=True, exist_ok=True)
    jobs, skipped = [], 0
    for i, s in enumerate(edl["shots"]):
        if only is not None and i not in only:
            continue
        out = r.SEG / f"{i:04d}.mp4"
        stamp = r.SEG / f"{i:04d}.done"
        if s["kind"] == "insert":
            cmds, final = r.insert_cmds(i, s, work)
            sig = hashlib.sha256(json.dumps([cmds, final, s]).encode()).hexdigest()
            if out.exists() and stamp.exists() and stamp.read_text() == sig:
                skipped += 1
                continue
            for c in cmds:
                subprocess.run(c, check=True)
            with atomic(out) as tmp:
                subprocess.run(final + [str(tmp)], check=True)
            stamp.write_text(sig)
            continue
        tmp = r.SEG / f".{i:04d}.part.mp4"
        cmd = r.seg_cmd(i, s, tmp)
        sig = hashlib.sha256(json.dumps([cmd, inputs_sig(r, s)] if inputs_sig(r, s) else cmd).encode()).hexdigest()
        if out.exists() and stamp.exists() and stamp.read_text() == sig:
            skipped += 1
            continue
        jobs.append((i, cmd, tmp, out, stamp, sig, piece_timeout(s)))

    def run(job):
        i, cmd, tmp, out, stamp, sig, limit = job
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=limit)
        except subprocess.TimeoutExpired:          # stopped after its time (answer 2a); the other pieces go on
            return i, 124, f"stopped after {limit:.0f} s: the piece did not finish (its material may be broken)"
        if p.returncode == 0:
            os.replace(tmp, out)
            stamp.write_text(sig)
        return i, p.returncode, p.stderr[-500:]
    bad = []
    with ThreadPoolExecutor(threads) as ex:
        for i, rc, err in ex.map(run, jobs):
            if rc:
                bad.append((i, err))
    log(f"pieces: {len(jobs)} rendered, {skipped} unchanged (resumed), {len(bad)} failed")
    for b in bad[:8]:
        log(b)
    return bad


def join(r, edl, out):
    bad = []
    for i, s in enumerate(edl["shots"]):
        got = count_frames(r.SEG / f"{i:04d}.mp4")
        if got != s["nframes"]:
            bad.append((i, got, s["nframes"]))
    if bad:
        raise SystemExit(f"frame count mismatch: {bad[:10]}")
    lst = Path(out).with_suffix(".txt")
    lst.write_text("".join(f"file '{r.SEG / ('%04d.mp4' % i)}'\n" for i in range(len(edl["shots"]))))
    with atomic(out) as tmp:
        subprocess.run([FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(tmp)], check=True)
    print("video frames", count_frames(out), "expected", edl["total_frames"])


def final(video, mix_wav, out, crf=20, overlays=(), preset="medium"):
    """the finished video; never overwrites. overlays: channel-profile corner images [{"file", "x", "y", "from", "to"}].
    preset: x264's speed (a channel episode: "fast", owner's decision 10 of 19 Oct 2026; the classic tests: "medium")"""
    out = Path(out)
    if out.exists():
        raise SystemExit(f"{out} exists: outputs are never overwritten; set options.version to a new number")
    cmd = [FF, "-v", "error", "-y", "-i", str(video), "-i", str(mix_wav)]
    if overlays:
        fc, last = [], "0:v"
        for k, o in enumerate(overlays):
            cmd += ["-loop", "1", "-framerate", "24", "-i", o["file"]]
            fc.append(f"[{last}][{k + 2}:v]overlay={o['x']}:{o['y']}:shortest=1:enable='between(t,{o.get('from', 0)},{o.get('to', 1e9)})'[o{k}]")
            last = f"o{k}"
        fc.append(f"[{last}]format=yuv420p[vout]")
        cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "1:a"]
    else:
        cmd += ["-map", "0:v", "-map", "1:a"]
    cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-r", "24",
            "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart"]
    with atomic(out) as tmp:
        subprocess.run(cmd + [str(tmp)], check=True)
    print("written", out)


def final_spliced(video, audio_wav, out, pieces, crf=20, overlays=(), hide=(), preset="medium"):
    """the finished video with the channel's own clips put in (montage/structure.py): pieces in order, each
    ("main", f0, f1[, fade]) = frames f0..f1 of the joined montage (its last `fade` frames fading to black), or
    ("clip", file, nframes); audio_wav is the whole finished
    sound (already put together). The corner overlays are hidden during the clips: hide = [(from s, to s)] on the finished
    timeline. Never overwrites."""
    out = Path(out)
    if out.exists():
        raise SystemExit(f"{out} exists: outputs are never overwritten; set options.version to a new number")
    cmd = [FF, "-v", "error", "-y", "-i", str(video)]
    fc, labels, k_in = [], [], 1
    for j, pc in enumerate(pieces):
        if pc[0] == "main":
            fade = (f"fade=t=out:start_frame={pc[2] - pc[1] - pc[3]}:nb_frames={pc[3]}," if len(pc) > 3 and pc[3] else "")   # into a clip that asks for it
            fc.append(f"[0:v]trim=start_frame={pc[1]}:end_frame={pc[2]},setpts=PTS-STARTPTS,{fade}{TAIL}[p{j}]")
        else:
            cmd += ["-i", str(pc[1])]
            fc.append(f"[{k_in}:v]fps=24,scale=1920:1080:force_original_aspect_ratio=decrease:flags=lanczos,"
                      f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,tpad=stop_mode=clone:stop_duration=1,trim=end_frame={pc[2]},"
                      f"setpts=PTS-STARTPTS,{TAIL}[p{j}]")
            k_in += 1
        labels.append(f"[p{j}]")
    fc.append("".join(labels) + f"concat=n={len(pieces)}:v=1:a=0[cat]")
    cmd += ["-i", str(audio_wav)]
    a_in = k_in
    k_in += 1
    last = "cat"
    off = "*".join(f"not(between(t,{a:.4f},{b - 0.001:.4f}))" for a, b in hide) or "1"
    for k, o in enumerate(overlays):
        cmd += ["-loop", "1", "-framerate", "24", "-i", o["file"]]
        fc.append(f"[{last}][{k_in}:v]overlay={o['x']}:{o['y']}:shortest=1:"
                  f"enable='between(t,{o.get('from', 0)},{o.get('to', 1e9)})*{off}'[o{k}]")
        last = f"o{k}"
        k_in += 1
    fc.append(f"[{last}]format=yuv420p[vout]")
    cmd += ["-filter_complex", ";".join(fc), "-map", "[vout]", "-map", f"{a_in}:a",
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-r", "24",
            "-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart"]
    with atomic(out) as tmp:
        subprocess.run(cmd + [str(tmp)], check=True)
    print("written", out, "with", sum(1 for pc in pieces if pc[0] == "clip"), "channel clip(s)")

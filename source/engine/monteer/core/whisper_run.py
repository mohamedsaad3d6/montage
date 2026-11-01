"""Running whisper.cpp (whisper-cli) for the engine's transcriptions (owner's answers of 18 Oct 2026 on the repeated log
lines): its own printout goes to a file beside its JSON, never into the run log, and the run log gets its progress
("whisper: 35%") every few minutes and one summary line at the end.

Why: with word timings (-dtw) whisper-cli prints its segments through a faulty loop in whisper.cpp (src/whisper.cpp,
the DTW block): each call reprints the last 1, 2, 3 … segments and the printing stops after the second 30 s window.
The JSON it saves is complete and correct; only that printout is wrong. It is kept in the file, for reference.

  run(cmd, stem, log=say)     cmd: whisper-cli's arguments (with -of stem); -pp is added for the progress. Writes
                              <stem>_printout.txt (its stdout) and <stem>_messages.txt (its other messages); raises
                              CalledProcessError on failure, after logging its last messages.
  summary(data, n_words)      "whisper: N segments, M words, up to T s" of whisper's JSON
"""
import subprocess
import time
from pathlib import Path

EVERY_S = 150                 # a progress line at most every 2.5 minutes (and the first one when it starts moving)


def say(s):
    print(s, flush=True)          # the step's output is a file: flushed, so the panel sees it at once


def run(cmd, stem, log=say, every_s=EVERY_S):
    stem = Path(stem)
    cmd = [str(c) for c in cmd] + ["-pp"]
    out, msg = Path(f"{stem}_printout.txt"), Path(f"{stem}_messages.txt")
    last_t, last_pc, tail = None, -1, []
    with open(out, "w", encoding="utf-8") as fo, open(msg, "w", encoding="utf-8") as fm:
        pr = subprocess.Popen(cmd, stdout=fo, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        for ln in pr.stderr:
            if "progress =" in ln:
                try:
                    pc = int(ln.rsplit("=", 1)[1].strip().rstrip("%"))
                except ValueError:
                    continue
                now = time.time()
                if pc > last_pc and (last_t is None or now - last_t >= every_s or pc >= 100):
                    log(f"whisper: {pc}%")
                    last_t, last_pc = now, pc
                continue
            fm.write(ln)
            tail = (tail + [ln.rstrip()])[-15:]
        rc = pr.wait()
    if rc != 0:
        log(f"whisper stopped with exit {rc}; its last messages ({msg.name}):")
        for x in tail:
            log("   " + x)
        raise subprocess.CalledProcessError(rc, cmd)
    return out


def summary(data, n_words, printout=None):
    """the one line the run log gets: segments, words and how far the transcript reaches"""
    tr = data.get("transcription", [])
    last = tr[-1]["offsets"]["to"] / 1000 if tr else 0.0
    return (f"whisper: {len(tr)} segments, {n_words} words, up to {last:.1f} s"
            + (f" (its own printout: {Path(printout).name})" if printout else ""))


__all__ = ["run", "summary"]

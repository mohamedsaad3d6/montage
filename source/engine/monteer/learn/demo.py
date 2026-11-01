"""Build a side-by-side comparison page: the reference editor's cut vs our auto cut of the same raw recording, with
the headline numbers read from the cut's report.md (nothing typed in by hand). Writes <out>/index.html; the videos
are linked by relative path, and <out>/editor.jpg / auto.jpg are used as posters when present.

    <core python> -m monteer.learn.demo --report <report.md> --editor-cut <editor video> --auto-cut <auto video> --out <dir>

report.md must have the editor-comparison rows (Duration with the editor's length, "Raw camera recording (input)",
"jump cuts", "Editor's material the auto edit contains", "Auto edit material also in the editor's cut").
"""
import argparse
import os
import re
from pathlib import Path
from urllib.parse import quote


def numbers(report):
    md = Path(report).read_text(encoding="utf-8")
    dur = re.search(r"^\| Duration \| \*\*([\d:.]+)\*\* \(\d+ s\) \| ([\d:.]+) \(", md, re.M)
    raw = re.search(r"^\| Raw camera recording \(input\) \| ([\d:.]+) ", md, re.M)
    cuts = re.search(r"\*\*(\d+) jump cuts\*\*", md)
    final = re.search(r"^\| Editor's material the auto edit contains \|.*\| \*\*([\d.]+%)\*\* \|", md, re.M)
    final2 = re.search(r"^\| Auto edit material also in the editor's cut \|.*\| \*\*([\d.]+%)\*\* \|", md, re.M)
    for name, m in (("duration", dur), ("raw", raw), ("cuts", cuts), ("agreement", final), ("agreement2", final2)):
        if not m:
            raise SystemExit(f"report.md: could not find {name}")
    mmss = lambda t: f"{int(t.split(':')[0])}:{round(float(t.split(':')[1])):02d}"
    return {"auto": mmss(dur[1]), "editor": mmss(dur[2]), "raw": mmss(raw[1]), "cuts": cuts[1],
            "ref_in_auto": final[1], "auto_in_ref": final2[1]}


def src(path, page_dir):
    """The video's path relative to the page's folder, URL-quoted."""
    return quote(os.path.relpath(Path(path).resolve(), Path(page_dir).resolve()))


PAGE = """<!doctype html>
<html lang="ar" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>المونتاج الآلي</title>
<style>
  :root {{ --bg:#101214; --panel:#1a1d21; --line:#2b3036; --text:#eef0f2; --muted:#9aa3ad; --accent:#e8b04a; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text);
         font-family:"Geeza Pro","SF Arabic","Noto Naskh Arabic",-apple-system,sans-serif; }}
  main {{ max-width:1500px; margin:0 auto; padding:28px 24px 40px; }}
  h1 {{ font-size:26px; margin:0 0 4px; font-weight:700; }}
  .sub {{ color:var(--muted); margin:0 0 22px; font-size:16px; }}
  .videos {{ display:grid; grid-template-columns:1fr 1fr; gap:18px; }}
  figure {{ margin:0; background:var(--panel); border:1px solid var(--line); border-radius:12px; overflow:hidden; }}
  figcaption {{ display:flex; justify-content:space-between; align-items:center; padding:12px 16px; font-size:18px; font-weight:700; }}
  figure.auto figcaption .tag {{ color:var(--accent); }}
  video {{ display:block; width:100%; aspect-ratio:16/9; background:#000; }}
  .sound {{ font:inherit; font-size:14px; font-weight:400; color:var(--muted); background:none;
           border:1px solid var(--line); border-radius:999px; padding:4px 12px; cursor:pointer; }}
  .sound[aria-pressed="true"] {{ color:var(--text); border-color:var(--accent); }}
  .bar {{ display:flex; align-items:center; gap:12px; padding:12px 16px; direction:ltr; }}
  .pp {{ font:inherit; font-size:15px; width:38px; height:38px; flex:none; border-radius:50%; border:1px solid var(--line);
        background:#24282d; color:var(--text); cursor:pointer; }}
  .pp:hover {{ border-color:var(--accent); }}
  input[type=range] {{ flex:1; min-width:0; accent-color:var(--accent); height:20px; cursor:pointer; }}
  input[type=range]:disabled {{ cursor:default; }}
  .time {{ flex:none; color:var(--muted); font-size:14px; font-variant-numeric:tabular-nums; min-width:96px; text-align:center; }}
  body[data-mode="both"] figure .bar {{ opacity:.35; }}
  #sharedbar {{ display:none; max-width:900px; margin:0 auto 26px; background:var(--panel); border:1px solid var(--line); border-radius:12px; }}
  body[data-mode="both"] #sharedbar {{ display:flex; }}
  .controls {{ display:flex; justify-content:center; margin:22px 0 14px; }}
  #play {{ font:inherit; font-size:20px; font-weight:700; background:var(--accent); color:#1b1406; border:0;
          border-radius:999px; padding:12px 44px; cursor:pointer; min-width:220px; }}
  .stats {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; }}
  .stat {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:16px; text-align:center; }}
  .stat b {{ display:block; font-size:30px; direction:ltr; font-variant-numeric:tabular-nums; }}
  .stat span {{ display:block; color:var(--muted); font-size:15px; margin-top:6px; line-height:1.5; }}
  .note {{ text-align:center; margin:24px 0 0; font-size:19px; }}
  body:not([data-mode="both"]) .controls {{ margin-bottom:26px; }}
  @media (max-width:900px) {{ .videos {{ grid-template-columns:1fr; }} .stats {{ grid-template-columns:repeat(2,1fr); }} }}
</style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <p class="sub">نفس التسجيل الخام: مونتاج المحرر مقابل المونتاج الآلي</p>

  <div class="videos">
    <figure>
      <figcaption><span>مونتاج المحرر</span><button class="sound" data-for="editor" aria-pressed="false">الصوت</button></figcaption>
      <video id="editor" src="{editor_src}" poster="editor.jpg" preload="auto" playsinline muted></video>
      <div class="bar"><button class="pp" data-for="editor" aria-label="تشغيل مونتاج المحرر">▶</button>
        <input class="seek" data-for="editor" type="range" min="0" max="0" step="0.1" value="0" aria-label="زمن مونتاج المحرر">
        <span class="time" data-for="editor">0:00 / 0:00</span></div>
    </figure>
    <figure class="auto">
      <figcaption><span class="tag">المونتاج الآلي</span><button class="sound" data-for="auto" aria-pressed="true">الصوت</button></figcaption>
      <video id="auto" src="{auto_src}" poster="auto.jpg" preload="auto" playsinline></video>
      <div class="bar"><button class="pp" data-for="auto" aria-label="تشغيل المونتاج الآلي">▶</button>
        <input class="seek" data-for="auto" type="range" min="0" max="0" step="0.1" value="0" aria-label="زمن المونتاج الآلي">
        <span class="time" data-for="auto">0:00 / 0:00</span></div>
    </figure>
  </div>

  <div class="controls"><button id="play">▶ تشغيل الاثنين معًا</button></div>
  <div id="sharedbar" class="bar"><input id="shared" type="range" min="0" max="0" step="0.1" value="0" aria-label="زمن مشترك للفيديوهين">
    <span class="time" id="sharedtime">0:00 / 0:00</span></div>

  <div class="stats">
    <div class="stat"><b>{raw}</b><span>طول التسجيل الخام</span></div>
    <div class="stat"><b>{editor}</b><span>طول مونتاج المحرر</span></div>
    <div class="stat"><b>{auto}</b><span>طول المونتاج الآلي</span></div>
    <div class="stat"><b>{cuts}</b><span>عدد القطعات في المونتاج الآلي</span></div>
    <div class="stat"><b>{ref_in_auto}</b><span>مما أبقاه المحرر موجود في المونتاج الآلي</span></div>
    <div class="stat"><b>{auto_in_ref}</b><span>مما أبقاه المونتاج الآلي موجود عند المحرر</span></div>
  </div>

  <p class="note">المونتاج الآلي تم بالكامل دون أي تدخل بشري في التحرير.</p>
</main>
<script>
  const V = {{ editor: document.getElementById("editor"), auto: document.getElementById("auto") }};
  const vids = Object.values(V);
  const btn = document.getElementById("play");
  const shared = document.getElementById("shared");
  const sharedTime = document.getElementById("sharedtime");
  const dragging = new Set();  // time bars the user is holding
  let mode = "";  // "both", "editor", "auto" or "" before anything is played

  const fmt = (t, round) => {{ t = isFinite(t) ? (round ? Math.round : Math.floor)(t) : 0;
    return Math.floor(t / 60) + ":" + String(t % 60).padStart(2, "0"); }};
  const dur = v => isFinite(v.duration) ? v.duration : 0;
  const longest = () => Math.max(...vids.map(dur));
  const sharedPos = () => Math.max(...vids.map(v => v.currentTime));
  const playing = v => !v.paused && !v.ended;
  const q = (sel, id) => document.querySelector(sel + '[data-for="' + id + '"]');

  function setMode(m) {{
    mode = m;
    document.body.dataset.mode = m;
    document.querySelectorAll("figure .seek").forEach(s => s.disabled = m === "both");
  }}
  // one soundtrack at a time: two voices at once are unintelligible
  function hear(id) {{
    vids.forEach(v => v.muted = v.id !== id);
    document.querySelectorAll(".sound").forEach(o => o.setAttribute("aria-pressed", o.dataset.for === id));
  }}
  function render() {{
    for (const [id, v] of Object.entries(V)) {{
      const seek = q(".seek", id);
      seek.max = dur(v);
      if (!dragging.has(seek)) seek.value = v.currentTime;
      q(".time", id).textContent = fmt(v.currentTime) + " / " + fmt(dur(v), true);
      q(".pp", id).textContent = playing(v) ? "❚❚" : "▶";
    }}
    shared.max = longest();
    if (!dragging.has(shared)) shared.value = sharedPos();
    sharedTime.textContent = fmt(sharedPos()) + " / " + fmt(longest(), true);
    btn.textContent = mode === "both" && vids.some(playing) ? "❚❚ إيقاف مؤقت" : "▶ تشغيل الاثنين معًا";
  }}
  function seekBoth(t) {{ vids.forEach(v => v.currentTime = Math.min(t, dur(v))); }}

  // play both: one shared clock for the two videos
  btn.addEventListener("click", () => {{
    if (mode === "both" && vids.some(playing)) {{ vids.forEach(v => v.pause()); return; }}
    // start both from where the video watched last is (resume in place when already in both mode)
    const t = mode === "both" ? sharedPos() : mode ? V[mode].currentTime : 0;
    setMode("both");
    seekBoth(t >= longest() - 0.1 ? 0 : t);
    vids.forEach(v => {{ if (v.currentTime < dur(v) - 0.05) v.play(); }});
  }});
  // play one video alone: pause the other and hear this one
  document.querySelectorAll(".pp").forEach(b => b.addEventListener("click", () => {{
    const v = V[b.dataset.for];
    if (playing(v) && mode !== "both") {{ v.pause(); return; }}
    vids.forEach(o => {{ if (o !== v) o.pause(); }});
    setMode(v.id);
    hear(v.id);
    if (v.ended) v.currentTime = 0;
    v.play();
  }}));
  document.querySelectorAll(".sound").forEach(b => b.addEventListener("click", () => hear(b.dataset.for)));

  // time bars: drag to jump
  document.querySelectorAll("input[type=range]").forEach(s => {{
    s.addEventListener("pointerdown", () => dragging.add(s));
    s.addEventListener("change", () => {{ dragging.delete(s); render(); }});
    s.addEventListener("input", () => {{
      if (s === shared) seekBoth(Number(s.value)); else V[s.dataset.for].currentTime = Number(s.value);
    }});
  }});
  window.addEventListener("pointerup", () => dragging.clear());

  vids.forEach(v => ["timeupdate", "play", "pause", "ended", "loadedmetadata", "seeked"].forEach(e => v.addEventListener(e, render)));
  render();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="Side-by-side page: the reference editor's cut vs our auto cut.")
    ap.add_argument("--report", required=True, help="the auto cut's report.md (with the editor comparison)")
    ap.add_argument("--editor-cut", required=True, help="the reference editor's cut (video)")
    ap.add_argument("--auto-cut", required=True, help="our auto cut (video)")
    ap.add_argument("--out", required=True, help="folder for index.html (and editor.jpg / auto.jpg posters)")
    ap.add_argument("--title", help="page heading (default: the page title)")
    opt = ap.parse_args()
    out = Path(opt.out)
    out.mkdir(parents=True, exist_ok=True)
    n = numbers(opt.report)
    title = opt.title or re.search("<title>(.*?)</title>", PAGE)[1]
    html = PAGE.format(editor_src=src(opt.editor_cut, out), auto_src=src(opt.auto_cut, out), title=title, **n)
    (out / "index.html").write_text(html, encoding="utf-8")
    print("wrote", out / "index.html", n)


if __name__ == "__main__":
    main()

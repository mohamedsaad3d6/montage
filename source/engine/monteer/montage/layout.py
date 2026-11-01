"""Our graphics' layout, checked in code (owner's fix 7 of 21 Oct 2026, after the first camera episode's «إنفاق حكومي للفرد»
had its label «أيرلندا الشمالية» under its bar and «نسبة العجز» its «أعلى بكتير» under a bar's rounded end, and the
spending bars had no numbers at all).

  text against shapes   every text's box against every box (rect) and bar (a line of width >= BAR_W), and against the other
                        texts. A bar is drawn with ROUND ends (gfx.swift setLineCap(.round)): it reaches width/2 beyond its
                        two points. A text inside a box, or inside a bar's body (a value on its bar), is fine; touching one
                        is not; a text and a bar keep GAP px between them (RTL labels: a right-aligned label ends at its x
                        and grows to the left, so its left edge keeps GAP from the bar's end).
  bars and numbers      a scene with two or more bars is a bar chart: each bar has a number beside or on it (within NEAR px)
                        that the script says; with none, the graphic must be another kind (a list, two big words, a card).

Texts are measured by the renderer itself (one probe frame per text, its "fit" report gives the drawn extent), so the boxes
are the drawn ones, Arabic shaping and the font's weight included.
"""
import json
import re
import subprocess
import tempfile
from pathlib import Path

from ..core.paths import CAIRO_FONT, GFX

BAR_W = 20            # px: a line this thick is a bar
GAP = 12              # px between a text and a bar or a box edge
NEAR = 140            # px: a bar's number is this close to it
TEXTS = ("text", "kwtext", "counter")
DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def text_of(it):
    s = it.get("text") or ""
    if it.get("type") == "counter":
        s = s.replace("%d", str(int(round(it.get("to", 0)))))
    return s


def measure(scenes, font=None):
    """the drawn horizontal extent of every text item -> {(scene name, item index): (x0, x1, lines)}"""
    from .graphics import font_of
    font = str(font or CAIRO_FONT)
    probes, keys = {}, {}
    for sc in scenes:
        for k, it in enumerate(sc.get("items", [])):
            if it.get("type") in TEXTS and text_of(it).strip():
                name = f"p{len(keys)}"
                one = {kk: v for kk, v in it.items() if kk not in ("fit", "t1", "t2", "slide", "pop")}
                one.update(type="text", text=text_of(it), t0=-1.0, fit=[960, 960])
                probes.setdefault(font_of(sc, font), []).append({"name": name, "t_in": 0, "t_out": 1 / 24, "frames": 1, "bg": "dark", "items": [one]})
                keys[name] = (sc["name"], k)
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        for f, scs in probes.items():
            for sc in scs:
                sc["out"] = str(Path(tmp) / (sc["name"] + "_%05d.png"))
            spec = Path(tmp) / "probe.json"
            spec.write_text(json.dumps(scs, ensure_ascii=False))
            r = subprocess.run([str(GFX), str(spec), f], capture_output=True, text=True)
            for ln in r.stdout.splitlines():
                m = re.match(r"fit: (p\d+) (-?\d+)-(-?\d+) ", ln)
                if m and m.group(1) in keys:
                    x0, x1 = int(m.group(2)), int(m.group(3))
                    k = keys[m.group(1)]
                    a, b, n = out.get(k, (x0, x1, 0))
                    out[k] = (min(a, x0), max(b, x1), n + 1)
    return out


def boxes(sc, widths):
    """the scene's text boxes [(index, (x0, y0, x1, y1), text)] (y: the visual centre +- about 0.62 of the size a line)"""
    out = []
    for k, it in enumerate(sc.get("items", [])):
        if (sc["name"], k) not in widths:
            continue
        x0, x1, lines = widths[(sc["name"], k)]
        size, y = float(it.get("size", 60)), float(it.get("y", 540))
        half = 0.62 * size if lines <= 1 else 0.6 * size + 0.62 * size
        out.append((k, (x0, y - half, x1, y + half), text_of(it)))
    return out


def shapes(sc):
    """the scene's boxes [(index, (x0, y0, x1, y1))] and bars [(index, (x, y), (x1, y1), radius)]"""
    rects, bars = [], []
    for k, it in enumerate(sc.get("items", [])):
        if it.get("type") == "rect" and all(v in it for v in ("x", "y", "w", "h")):
            rects.append((k, (it["x"], it["y"], it["x"] + it["w"], it["y"] + it["h"])))
        elif it.get("type") == "line" and float(it.get("width", 8)) >= BAR_W and all(v in it for v in ("x", "y", "x1", "y1")):
            bars.append((k, (it["x"], it["y"]), (it["x1"], it["y1"]), float(it["width"]) / 2))
    return rects, bars


def _pt_seg(p, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((p[0] - ax) * dx + (p[1] - ay) * dy) / (dx * dx + dy * dy)))
    return ((p[0] - ax - t * dx) ** 2 + (p[1] - ay - t * dy) ** 2) ** 0.5


def _box_seg(box, a, b):
    """the shortest distance between an axis-aligned box and a segment (0 when they cross)"""
    x0, y0, x1, y1 = box
    inside = lambda p: x0 <= p[0] <= x1 and y0 <= p[1] <= y1     # noqa: E731
    if inside(a) or inside(b):
        return 0.0
    edges = [((x0, y0), (x1, y0)), ((x1, y0), (x1, y1)), ((x1, y1), (x0, y1)), ((x0, y1), (x0, y0))]

    def cross(p1, p2, p3, p4):
        d = lambda u, v, w: (w[0] - u[0]) * (v[1] - u[1]) - (w[1] - u[1]) * (v[0] - u[0])   # noqa: E731
        return (d(p3, p4, p1) * d(p3, p4, p2) < 0) and (d(p1, p2, p3) * d(p1, p2, p4) < 0)
    if any(cross(a, b, e0, e1) for e0, e1 in edges):
        return 0.0
    return min([_pt_seg(c, a, b) for c in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))] + [_pt_seg(p, e0, e1) for p in (a, b) for e0, e1 in edges])


def _overlap(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def _inside(a, b, tol=2):
    return a[0] >= b[0] - tol and a[1] >= b[1] - tol and a[2] <= b[2] + tol and a[3] <= b[3] + tol


def script_numbers(texts):
    """every number the script says (written with digits), as plain digits"""
    out = set()
    for t in texts:
        for m in re.findall(r"\d+(?:[.,]\d+)?", (t or "").translate(DIGITS)):
            out.add(m.replace(",", "."))
    return out


def scene_problems(sc, widths, said):
    probs = []
    tb = boxes(sc, widths)
    rects, bars = shapes(sc)
    name = sc["name"]
    for i, (k, b, t) in enumerate(tb):
        for k2, b2, t2 in tb[i + 1:]:
            if _overlap(b, b2) > 0.1 * min((b[2] - b[0]) * (b[3] - b[1]), (b2[2] - b2[0]) * (b2[3] - b2[1])):
                probs.append(f"«{t}» and «{t2}» overlap")
        for kr, r in rects:
            if _overlap(b, r) > 0 and not _inside(b, r) and not _inside(r, b):
                probs.append(f"«{t}» runs over the edge of the box at x {r[0]:.0f}-{r[2]:.0f}, y {r[1]:.0f}-{r[3]:.0f}")
        for kb, p0, p1, rad in bars:
            body = (min(p0[0], p1[0]), min(p0[1], p1[1]) - rad, max(p0[0], p1[0]), max(p0[1], p1[1]) + rad) if p0[1] == p1[1] else \
                   (min(p0[0], p1[0]) - rad, min(p0[1], p1[1]), max(p0[0], p1[0]) + rad, max(p0[1], p1[1]))
            if _inside(b, body):
                continue                   # a value written on its bar
            d = _box_seg(b, p0, p1)
            if d < rad + GAP:
                probs.append(f"«{t}» is {max(0.0, d - rad):.0f} px from the bar {p0}->{p1} (width {2 * rad:.0f}; its rounded ends reach "
                             f"{rad:.0f} px beyond its points): keep {GAP} px between them")
    if len(bars) >= 2:                     # a bar chart: each bar its number, as the script says it
        nums = [(b, re.findall(r"\d+(?:[.,]\d+)?", t.translate(DIGITS))) for _, b, t in tb]
        for kb, p0, p1, rad in bars:
            near = [n.replace(",", ".") for b, ns in nums for n in ns if _box_seg(b, p0, p1) <= rad + NEAR]
            if not near:
                probs.append(f"the bar {p0}->{p1} has no number: a bar chart shows each bar's number as the script says it; "
                             "with no numbers in the script, use another graphic (a list, two big words, a comparison card)")
            elif not any(n in said for n in near):
                probs.append(f"the bar {p0}->{p1} shows {', '.join(near)}, a number the script does not say")
    return [f"{name}: {x}" for x in probs]


def problems(scenes, font=None, said=()):
    """the scene list's layout problems [str] (empty when every scene is clean)"""
    widths = measure(scenes, font)
    out = []
    for sc in scenes:
        out += scene_problems(sc, widths, set(said))
    return out


def bad_scenes(scenes, font=None, said=()):
    """the names of the scenes with a layout problem"""
    return sorted({x.split(":", 1)[0] for x in problems(scenes, font, said)})


REQUEST = ("LAYOUT (owner's decision; checked in code): a bar is a line of width >= 20 drawn with ROUND ends that reach width/2 "
           "beyond its two points; keep at least 12 px between any text and a bar, and keep a text either fully inside a box or "
           "clear of its edges; texts never overlap. Arabic labels are right to left: a label with \"align\": \"right\" ends at its "
           "x and grows to the left, so place it 12 px plus the bar's half width to the right of the bar's end. A BAR CHART (two "
           "or more bars) shows each bar's NUMBER as the script says it, on or beside its bar; when the script gives no numbers "
           "for the things compared, do not draw bars: use another graphic (a list, two big words, a comparison card).")

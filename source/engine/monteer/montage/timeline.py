"""The montage cut list: the plan's timeline (a judgement decision) -> work/montage/edl.json, every shot with its frames,
source, effects and overlays.

Rules (rules 19-24):
  - a cut lands 2 frames before the nearest word start within 0.6 s (24 fps grid);
  - a photo entry lands on one of the source's own camera clicks when one is within 0.5 s (one frame before it);
  - our graphics play at the times they were designed for;
  - footage fills the rest at each block's pace, cutting at word starts, the block's assets in turn;
  - a clip continues where it last stopped (inside its usable window), so a repeat shows new frames;
  - overlays (labels, key words) go on footage/photos only; paper texture on the photos the plan marks as history;
    with overlay_delay (the phrase montage), an overlay that starts inside a shot waits for its own time (delay_frames),
    so on-screen text appears on its word instead of at the shot's first frame.

The timeline decision (decisions/montage/timeline.json -> "decision"):
  {"length_s": total length,
   "blocks": [["F", [assets], start, end, pace?]          footage, photos, AI images
              ["G", scene, start, end, scene_time?]         one of our graphics (scene_time: show it from that moment)
              ["INSERT", start, end, {"offset_s": s}]],     an earlier rendered block (inputs.insert_edl, see render.py)
   "overlays": [scene names],  "strong_clicks": [s, ...],  "paper_photos": [photo keys]}
Asset codes (a channel episode with presenter may add @<sentence index> to give the sentence a picture shows: V:sb1@45):
             V:<stock id>  S:<library clip>  P:<photo key>  PE:<photo key, with the rule-19 entry>  A:<AI image key>
             AE:<AI image key, with entry>;  suffix |in (push-in) or |out (pull-out); for اقتصاد احمس audio only
             (owner's decision 6A): |bw (the black-and-white open) and |framed_<n> (the photo framed by that scene).
Where they live: project assets "stock", "library", "photos", "ai" (project.json "assets").
Other decisions read: montage/clip_fx (usable window, crop, grade per clip), montage/ai_pick (chosen seed per AI image),
graphics/scenes (each scene's t_in/t_out).
"""
import json
import subprocess

from ..core.io import save_json
from ..core.paths import FFPROBE

FPS = 24


def tag_of(asset):
    """"V:sb1@45|in" -> ("V:sb1|in", 45); an asset with no "@<sentence>" -> (asset, None)"""
    import re
    m = re.search(r"@(\d+)", asset)
    return (asset[:m.start()] + asset[m.end():], int(m.group(1))) if m else (asset, None)


class Timeline:
    def __init__(self, p, decision, scenes, words, clip_fx=None, ai_pick=None, overlay_delay=False, sentences=None, sentence_ids=None):
        self.p = p
        self.SENT = sentences          # the presenter type: sentence starts (s); footage changes at each one (Ramadan)
        self.SENT_IDS = sentence_ids   # their indices ("i" in sentences.json): an asset written V:<id>@<i> shows sentence i
        self.overlay_delay = overlay_delay
        self.d = decision
        self.LEN = decision["length_s"]
        self.STARTS = [w["s"] for w in words]
        self.SCENES = {s["name"]: s for s in scenes}
        self.STRONG_CLICKS = decision.get("strong_clicks", [])
        self.PAPER = set(decision.get("paper_photos", []))
        self.CLIP_FX = clip_fx or {}
        self.AI_PICK = ai_pick or {}
        self._dur = {}
        self.PHOTO_MOVES = False       # owner's fix 1 of 22 Oct 2026: a channel's archive photos move slowly (in, then out, …)
        try:
            self.PHOTO_MOVES = bool(getattr(p, "profile", None)) and bool(
                ((p.profile_montage().get("sources") or {}).get("archive") or {}).get("photo_moves"))
        except Exception:  # noqa: BLE001
            pass
        self._moves = 0
        self.LABELS = None             # the channel's labels (montage/labels.py): on time inside a shot, over the presenter too
        try:
            from .labels import of as _labels_of
            self.LABELS = _labels_of(p)
        except Exception:  # noqa: BLE001
            pass

    def fr(self, t):
        return int(round(t * FPS))

    def sentence_at(self, frame):
        """the index of the sentence a piece starting at this frame belongs to (its start may sit 2 frames early, on the cut)"""
        if not self.SENT or not self.SENT_IDS:
            return None
        t = frame / FPS + 0.15
        k = max((j for j, s0 in enumerate(self.SENT) if s0 <= t), default=0)
        return self.SENT_IDS[k]

    def snap(self, t):
        """a cut: 2 frames before the nearest word start within 0.6 s (else the time itself), in frames"""
        ck = [c for c in self.STRONG_CLICKS if abs(c - t) <= 0.5]
        if ck:                      # a photo entry lands on the source's own camera click
            return self.fr(min(ck, key=lambda c: abs(c - t))) - 1
        near = [s for s in self.STARTS if abs(s - t) <= 0.6]
        if not near:
            return self.fr(t)
        s = min(near, key=lambda x: abs(x - t))
        return max(0, self.fr(s) - 2)

    def clip_path(self, a):
        kind, key = a.split(":", 1)
        key = key.split("|")[0]
        if kind == "V":
            return self.p.asset_dir("stock") / f"{key}.mp4"
        if kind == "S":
            return self.p.asset_dir("library") / f"{key}.mp4"
        if kind in ("P", "PE"):
            return self.p.asset_dir("photos") / f"{key}.jpg"
        if kind in ("A", "AE"):
            seed = self.AI_PICK.get(key, {}).get("seed", 11)
            return self.p.asset_dir("ai") / f"{key}_s{seed}.png"
        raise ValueError(a)

    def duration(self, p):
        if p not in self._dur:
            r = subprocess.run([str(FFPROBE), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                               capture_output=True, text=True).stdout.strip()
            self._dur[p] = float(r) if r else 0.0
        return self._dur[p]

    def pace_cuts(self, f0, f1, pace):
        """split [f0, f1) into shots of about 'pace', cutting at word starts"""
        fr, snap = self.fr, self.snap
        cuts = [f0]
        while True:
            nxt = cuts[-1] + fr(pace)
            if nxt >= f1 - fr(pace * 0.6):
                break
            c = snap(nxt / FPS)
            if c <= cuts[-1] + fr(0.9) or c >= f1 - fr(0.9):
                c = nxt
            cuts.append(c)
        cuts.append(f1)
        return cuts

    def build(self):
        fr, snap, LEN = self.fr, self.snap, self.LEN
        cursor = {}
        shots = []
        for el in self.d["blocks"]:
            kind = el[0]
            if kind == "INSERT":
                f0, f1 = snap(el[1]), snap(el[2])
                # the inserted block's own video starts at offset_s of this timeline: take it from the matching frame
                off = el[3]["offset_s"]
                shots.append({"kind": "insert", "f0": f0, "f1": f1, "offset_frames": int(round((f0 / FPS - off) * FPS))})
                continue
            a, b = el[2], el[3]
            f0 = fr(a) if a in (0.0,) else snap(a)
            f1 = fr(LEN) if b == LEN else snap(b)
            if kind == "G":
                sc = self.SCENES[el[1]]
                src_t = el[4] if len(el) > 4 else None
                shots.append({"kind": "gfx", "scene": el[1], "f0": f0, "f1": f1, "scene_t_in": sc["t_in"], "src_t": src_t,
                              **({"push": sc["push"]} if sc.get("push") else {}),       # a scene that asks for a push-in
                              **({"bw": True} if sc.get("bw") else {})})                # inside a black-and-white open
                continue
            assets, pace = el[1], (el[4] if len(el) > 4 else 3.0)
            if self.SENT is None:
                cuts = self.pace_cuts(f0, f1, pace)
            else:                      # a new picture at each sentence start; a long sentence split by pace on words
                edges = [f0] + [c for c in (snap(t) for t in self.SENT) if f0 + fr(0.9) <= c <= f1 - fr(0.9)] + [f1]
                edges = sorted(set(edges))
                cuts = [f0]
                for x0, x1 in zip(edges, edges[1:]):
                    cuts += self.pace_cuts(x0, x1, pace)[1:] if x1 - x0 > fr(pace * 1.6) else [x1]
                cuts = [c for k, c in enumerate(cuts) if k == 0 or c == f1 or c - cuts[k - 1] >= fr(0.9)]
                if len(cuts) > 2 and cuts[-1] - cuts[-2] < fr(0.9):
                    del cuts[-2]
            tags = [tag_of(a) for a in assets]
            by_sent, plain, seen_s, k_plain = {}, [a for a, t in zip(assets, tags) if t[1] is None], {}, 0
            for a, (clean, n) in zip(assets, tags):
                if n is not None:
                    by_sent.setdefault(n, []).append(clean)
            for i in range(len(cuts) - 1):
                sent = self.sentence_at(cuts[i]) if by_sent else None
                if not by_sent:                # no sentence tags: the listed assets in turn (as always)
                    asset = assets[i % len(assets)]
                elif sent in by_sent:          # owner's fix 2 of 21 Oct 2026: the picture chosen for this sentence
                    asset = by_sent[sent][seen_s.get(sent, 0) % len(by_sent[sent])]
                    seen_s[sent] = seen_s.get(sent, 0) + 1
                elif plain:
                    asset = plain[k_plain % len(plain)]
                    k_plain += 1
                else:
                    asset = tags[i % len(tags)][0]
                base, *mods = asset.split("|")
                k, key = base.split(":", 1)
                s = {"kind": {"V": "video", "S": "video", "P": "photo", "PE": "photo", "A": "ai", "AE": "ai"}[k], "asset": base,
                     "f0": cuts[i], "f1": cuts[i + 1], "src": str(self.clip_path(base)), "entry": k in ("PE", "AE"),
                     "zoom": "in" if "in" in mods else ("out" if "out" in mods else None),
                     "paper": k in ("P", "PE") and key in self.PAPER}
                if self.PHOTO_MOVES and s["kind"] == "photo" and s["zoom"] is None and not s["entry"]:
                    s["zoom"] = "in" if self._moves % 2 == 0 else "out"      # a slow push-in, then a slow pull-out
                    self._moves += 1
                if by_sent:
                    s["sentence"], s["tagged"] = sent, sent in by_sent
                if "bw" in mods:
                    s["bw"] = True
                framed = next((m for m in mods if m.startswith("framed_")), None)
                if framed:
                    s["framed"] = framed
                if s["kind"] == "video":
                    d = self.duration(self.clip_path(base))
                    fx = self.CLIP_FX.get(key, {})
                    lo, hi = fx.get("win", (0.4, max(0.5, d - 0.3)))
                    n = (s["f1"] - s["f0"]) / FPS
                    c = cursor.get(key, lo)
                    if c + n > hi:
                        c = lo
                    s["src_in"] = round(c, 3)
                    cursor[key] = c + n + 0.4
                    s["fx"] = {k2: v for k2, v in fx.items() if k2 != "win"}
                    s["src_dur"] = d
                shots.append(s)
        if self.p.mode == "talking_head":            # the presenter fills every stretch the plan leaves free (rule 7)
            from .presenter import fill
            shots += fill(self.p, shots, fr(LEN))
        # contiguous and complete
        shots.sort(key=lambda s: s["f0"])
        for i in range(1, len(shots)):
            if shots[i]["f0"] != shots[i - 1]["f1"]:
                raise SystemExit(f"gap/overlap at shot {i}: {shots[i - 1]['f1']} -> {shots[i]['f0']} "
                                 f"({shots[i - 1].get('asset') or shots[i - 1].get('scene')} / {shots[i].get('asset') or shots[i].get('scene')})")
        assert shots[0]["f0"] == 0 and shots[-1]["f1"] == fr(LEN), (shots[0]["f0"], shots[-1]["f1"])
        # overlays on footage only
        ov = [(n, fr(self.SCENES[n]["t_in"]), fr(self.SCENES[n]["t_out"])) for n in self.d.get("overlays", [])]
        on_kinds = ("video", "photo", "ai") + (("presenter",) if self.LABELS and self.LABELS.get("over_presenter") else ())
        for s in shots:
            s["nframes"] = s["f1"] - s["f0"]
            if s["kind"] in on_kinds:
                s["overlays"] = [{"name": n, "start_frame": max(0, s["f0"] - a)} for n, a, b in ov if a < s["f1"] and s["f0"] < b]
                if self.overlay_delay or self.LABELS:   # a label starting inside the shot waits for its own time (owner, 22 Oct)
                    for o, (n, a, b) in zip(s["overlays"], [x for x in ov if x[1] < s["f1"] and s["f0"] < x[2]]):
                        if a > s["f0"]:
                            o["delay_frames"] = a - s["f0"]
            if s.get("framed"):                  # the framed copy belongs to this photo shot only, under its labels
                s["overlays"].insert(0, {"name": s["framed"], "start_frame": 0})
        # where each photo entry lands: on a source click (no sound added) or not (our camera sound, if a pause allows)
        for s in shots:
            if s.get("entry"):
                t = s["f0"] / FPS
                s["on_click"] = any(abs(t - c) <= 0.3 for c in self.STRONG_CLICKS)
        return {"fps": FPS, "total_frames": fr(LEN), "shots": shots}


def build(p, decision, scenes, words, clip_fx=None, ai_pick=None, out=None, overlay_delay=False, sentences=None, sentence_ids=None):
    edl = Timeline(p, decision, scenes, words, clip_fx, ai_pick, overlay_delay, sentences, sentence_ids).build()
    if out:
        save_json(out, edl)
    kinds = {}
    for s in edl["shots"]:
        kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
    print("shots", len(edl["shots"]), kinds, "entries", sum(1 for s in edl["shots"] if s.get("entry")),
          "on clicks", sum(1 for s in edl["shots"] if s.get("on_click")))
    return edl


__all__ = ["build", "Timeline", "json"]

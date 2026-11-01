"""Join the frame-by-frame visual check (visual.json, one frame per 10 s, done by eye) with the automatic
channel numbers (channel.json, from channel_summary) into one table per video. -> channel_table.json / channel_table.csv

    <core python> -m monteer.learn.style_study.channel_combine --channel <channel dir> --out <dir>

Reads <channel dir>/feat/<id>/visual.json and <out>/channel.json; writes the tables into <out>.
The visual check was validated on the four episodes where the truth is known (presenter share within
3 points of the measured value).
"""
import argparse
import csv
import json
from pathlib import Path


def sec(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def main():
    ap = argparse.ArgumentParser(description="Join the visual check with the automatic channel numbers.")
    ap.add_argument("--channel", required=True, help="channel download folder (feat/<id>/visual.json)")
    ap.add_argument("--out", required=True, help="folder with channel.json; the tables are written here")
    opt = ap.parse_args()
    outdir, FEAT = Path(opt.out), Path(opt.channel) / "feat"
    auto = {r["id"]: r for r in json.load(open(outdir / "channel.json"))}
    rows = []
    for vid, a in auto.items():
        if a.get("vertical"):
            continue
        r = dict(a)
        vf = FEAT / vid / "visual.json"
        if vf.exists():
            v = json.load(open(vf))
            fr = v["frames"]
            n = len(fr)
            k = lambda f: f["kind"]  # noqa: E731
            pres = [f for f in fr if k(f) in ("P", "PG")]
            first = next((sec(f["t"]) for f in fr if k(f) in ("P", "PG")), None)
            body = [f for f in fr if sec(f["t"]) >= 180 and k(f) != "E"]
            intro = [f for f in fr if sec(f["t"]) < 180]
            share = lambda fs, kinds: round(100 * sum(1 for f in fs if k(f) in kinds) / max(1, len(fs)), 0)  # noqa: E731
            r.update({
                "v_frames": n,
                "v_presenter_pct": share(fr, ("P", "PG")),
                "v_presenter_pct_first3min": share(intro, ("P", "PG")),
                "v_presenter_pct_after3min": share(body, ("P", "PG")),
                "v_broll_pct": share(fr, ("B",)), "v_graphics_pct": share(fr, ("G",)),
                "v_screenshot_pct": share(fr, ("S",)), "v_textcard_pct": share(fr, ("T",)),
                "v_first_presenter_s": first,
                "v_label_frames_pct": round(100 * sum(f["label"] for f in fr) / n, 0),
                "v_caption_frames_pct": round(100 * sum(f["caption"] for f in fr) / n, 0),
                "v_text_frames_pct": round(100 * sum(f["text"] for f in fr) / n, 0),
                "v_notes": v.get("notes", ""),
            })
        rows.append(r)
    rows.sort(key=lambda r: r["date"], reverse=True)
    json.dump(rows, open(outdir / "channel_table.json", "w"), ensure_ascii=False, indent=1)
    keys = [k for k in rows[0] if k not in ("v_notes", "title")] + ["title"]
    with open(outdir / "channel_table.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(r["date"], r["id"], r.get("minutes"), "pres", r.get("v_presenter_pct"), "first", r.get("v_first_presenter_s"),
              "cuts/min", r["hard_cuts_per_min"], "zoom/min", r.get("zoom_change_cuts_per_min"),
              "labels/min", r.get("labels_per_min"), "music%", r.get("music_blocks_pct_first3min"), r.get("music_blocks_pct_after3min"))


if __name__ == "__main__":
    main()

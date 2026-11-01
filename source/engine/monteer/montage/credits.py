"""output/credits.md: every asset the finished video uses, with its source and licence, built from the provenance records
(work/montage/assets.json), the AI image log, the music step's reports and the sound-effect list. A used asset with no
provenance record is listed under "MISSING RECORD" (the self-check fails on it).

The lines the description must carry (CC BY photos) come first. No web address of a news outlet is ever printed here
for the description; page addresses of photo sources are kept for our own records.
"""
import json
import time

from ..core.io import load_json, write_text


def write(p):
    from .steps import M, decision
    edl = load_json(M(p, "edl.json"))
    rec = load_json(M(p, "assets.json")) if M(p, "assets.json").exists() else {}
    used = {}
    for s in edl["shots"]:
        if "asset" in s:
            k, key = s["asset"].split(":", 1)
            k = {"PE": "P", "AE": "A"}.get(k, k)
            used.setdefault(k, set()).add(key)
    L = [f"# Credits: «{p.name}»", "", f"Every picture, sound and font in the video, with its source and licence. Made {time.strftime('%d %b %Y')}.", "",
         "## Credit lines to put in the video description (required)", ""]
    missing = []
    pops = load_json(M(p, "popups.json"))["placed"] if M(p, "popups.json").exists() else []    # اقتصاد احمس's pop-ups
    pop_keys = []
    for x in pops:
        pic = x.get("picture", "")
        key = (f"FLAG:{pic.rsplit('flag_', 1)[1][:3]}" if "/flag_" in pic else f"MAP:{pic.rsplit('map_', 1)[1][:3]}" if "/map_" in pic
               else f"P:{x['name'].replace('pop_', 'pop')}" if x["kind"] == "photo" else None)
        pop_keys.append((x, key))
    for k in sorted(used.get("P", set()) | {key[2:] for _, key in pop_keys if key and key.startswith("P:")}):
        r = rec.get(f"P:{k}")
        if r and r["licence"].upper().startswith("CC BY"):
            L.append(f"- Photo: «{r['title'].replace('File:', '').rsplit('.', 1)[0]}» by {r.get('author', '')}, {r['licence']}, via {r['source']}")
    for k in sorted(used.get("V", set())):          # Magnific's free clips name their author (its licence asks for it)
        r = rec.get(f"V:{k}")
        if r and r.get("licence", "").startswith("Magnific Free"):
            L.append(f"- Video: «{r.get('title', '')}» by {r.get('author') or 'its author'}, via Magnific")
    mus = []                          # the music's cues (set-aside ones are not in the video)
    for f in sorted(p.asset_dir("music").glob("*.json")) if p.asset_dir("music").exists() else []:
        if "." not in f.stem:
            mus.append((f.stem, json.load(open(f))))
    for credit in dict.fromkeys(j["credit"] for _, j in mus if j.get("generator") == "library-track" and j.get("credit")):
        L.append(f"- Music: {credit}")     # a downloaded track's own credit line (CC BY asks for it in the description)
    L += ["", "## Stock video", "", "| Id | Title | Source | Licence |", "|---|---|---|---|"]
    for kind in ("V", "S"):
        for k in sorted(used.get(kind, set())):
            r = rec.get(f"{kind}:{k}")
            if not r:
                missing.append(f"{kind}:{k}")
                continue
            L.append(f"| {k} | {r.get('title', '')} | {r.get('source', '')} {r.get('page', '')} | {r['licence']} |")
    L += ["", "## Archive photos", "", "| Key | Photo | Author | Licence |", "|---|---|---|---|"]
    for k in sorted(used.get("P", set())):
        r = rec.get(f"P:{k}")
        if not r:
            missing.append(f"P:{k}")
            continue
        L.append(f"| {k} | [{r['title'].replace('File:', '')}]({r.get('page', '')}) | {r.get('author', '')} | {r['licence']} |")
    if pops:
        L += ["", "## Pop-ups beside the presenter", "", "| At | Kind | Picture | Source | Licence |", "|---|---|---|---|---|"]
        for x, key in pop_keys:
            r = rec.get(key) if key else None
            if x["kind"] == "news":
                L.append(f"| {x['from']:.1f} s | news | a screenshot of the item's own public page (montage/news.py) | the outlet's page | quoted news |")
                continue
            if not r:
                missing.append(key or x["name"])
                continue
            L.append(f"| {x['from']:.1f} s | {x['kind']} | {r.get('title', '').replace('File:', '')} | {r.get('source', '')} | {r['licence']} |")
    ai = p.asset_dir("ai") / "ai_images.json"
    log = load_json(ai) if ai.exists() else {"images": []}
    pick = decision(p, "ai", "pick", {})
    L += ["", "## AI images (made on this Mac with SDXL-Lightning; CreativeML OpenRAIL++-M: commercial use allowed, no rights claimed on the output)", "",
          "Generic scenes only — never pictures of specific real events.", "", "| Key | Prompt |", "|---|---|"]
    for k in sorted(used.get("A", set())):
        seed = pick.get(k, {}).get("seed", 11)
        img = next((i for i in log["images"] if i["key"] == k and i["seed"] == seed), None)
        L.append(f"| {k} (seed {seed}) | {img['prompt'] if img else 'MISSING RECORD'} |")
        if not img:
            missing.append(f"A:{k}")
    tracks = [(n, j) for n, j in mus if j.get("generator") == "library-track"]
    if tracks:                        # a channel episode: downloaded tracks (19 Oct 2026), each with its licence
        L += ["", "## Music (downloaded instrumental tracks, free licences; each passed the vocals check)", "",
              "| Cue | Track | Author | Source | Licence |", "|---|---|---|---|---|"]
        for n, j in tracks:
            L.append(f"| {n} | {j.get('title', '')} | {j.get('author', '')} | {j.get('source', '')} {j.get('page', '')} | {j.get('licence', '')} |")
    if len(tracks) < len(mus) or not mus:
        L += ["", "## Music (ACE-Step v1-3.5B on this Mac, Apache 2.0; each cue passed the vocals check)", "", "| Cue | Prompt | Voice score |", "|---|---|---|"]
        for n, j in mus:
            if j.get("generator") == "library-track":
                continue
            t = j["takes"][-1] if j.get("takes") else {}
            L.append(f"| {n} | {j.get('prompt', '')} | {t.get('vocal_check', {}).get('voice_score')} |")
    L += ["", "## Sound effects", "", "All made in code (monteer/montage/sfx.py): our own work, no licence needed.", "",
          "## Graphics, maps, fonts", "", "- Our own graphics (no news outlet's name, logo or design imitated). Fonts: SIL Open Font License 1.1.",
          "- Maps drawn from Natural Earth country outlines: public domain.", "- Paper texture and film grain: made in code.", ""]
    if missing:
        L += ["## MISSING RECORD", "", "These assets are used but have no provenance record; do not publish until they do:", ""] + [f"- {m}" for m in missing]
    write_text(p.output / "credits.md", "\n".join(L) + "\n")
    print("credits:", {k: len(v) for k, v in used.items()}, "missing records:", len(missing))
    return missing

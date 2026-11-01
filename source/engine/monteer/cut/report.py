"""The cut report: output/report.md from the cut step's data (the cut, its reasons, the places worth checking by ear,
measured transcription accuracy)."""
from collections import Counter

import re

import numpy as np

from . import accuracy
from . import compare
from . import script_text
from . import sync
from .align import select_takes
from .asr import transcribe
from .common import EDIT_VIDEO, NAME, KEEP_OUTRO, OUT, RAW_VIDEO, REF_VIDEO, WORK, ffprobe_duration, load_json, save_json, tc
from .run import MODEL, to_cam, unsure_list
from .silence import frame_db, speech_seconds

GAP_TEXT_MIN = 1


CHECK_LABELS = {
    "take": "Take choice: an earlier take matched the script better than the one kept. Listen to both.",
    "adlib": "Long off-script stretch kept inside a take. Is it a deliberate ad-lib or a slip?",
    "gap": "Speech the first transcription pass skipped, kept after a second pass. Make sure it isn't a retake.",
    "gapre": "Repeated line: the later take was kept and the earlier attempt cut. Listen for a doubled or "
             "missing word at the join.",
    "weak": "Kept take matches the script weakly. Check the delivery and that it's the right line.",
    "offcut": "Off-script stretch cut between takes. Could be a deliberate line.",
    "outro": "Start of the kept channel outro. Make sure nothing before it is crew talk.",
}


def check_by_ear(unsure, gap_keep, to_out, n=10, taken=()):
    """Rank unsure spots by how much a wrong call would hurt a published cut."""
    cands = []
    for u in unsure:
        why, L = u["why"], u["src_end"] - u["src"]
        if why.startswith("cut take matched"):
            a, b = [float(x) for x in re.findall(r"\(([-\d.]+)\)", why)[:2]]
            cands.append((3 + 4 * (a - b) + min(L, 10) / 5, "take", u))
        elif why.startswith("kept take matches the script weakly"):
            cands.append((3 + min(L, 20) / 5, "weak", u))
        elif why.startswith("kept") and "not in the script" in why:
            cands.append((1.5 + int(why.split()[1]) / 6, "adlib", u))
        elif why.startswith("start of the kept channel outro"):
            cands.append((3.5, "outro", u))
        elif why.startswith("cut") and "off-script" in why:
            cands.append((1 + int(why.split()[1]) / 8, "offcut", u))
    for g in gap_keep:
        if "earlier attempt cut" in g["why"]:
            # the join between the kept take and what came before is the risky part
            n_extra = max(0, len(g["text"].split()) - 3)
            cands.append((2.5 + min(g["src_end"] - g["src"], 6) / 3 - n_extra * 0.1, "gapre", g))
        else:
            cands.append((2 + min(g["src_end"] - g["src"], 6) / 2, "gap", g))
    cands.sort(key=lambda c: -c[0])
    out, seen = [], list(taken)
    for sc, kind, u in cands:
        if any(abs(to_out(u["src"]) - t) < 8 for t in seen):
            continue  # one entry per neighbourhood of the edit
        seen.append(to_out(u["src"]))
        out.append((kind, u))
        if len(out) == n:
            break
    return sorted(out, key=lambda x: x[1]["src"])


def still_suspected(keep, to_out):
    """the verify pass's suspects it left alone that are still in the finished cut -> [{out, src, text}]"""
    f = WORK / "verify_unconfirmed.json"
    if not f.exists():
        return []
    out = []
    for x in load_json(f):
        if any(s <= x["src"] < e for s, e in keep):
            out.append({"out": to_out(x["src"]), "src": x["src"], "text": x["text"]})
    return sorted(out, key=lambda r: r["out"])


def main():
    script = script_text.build()
    info = sync.build()
    words = to_cam(transcribe(sync.EXT16, "ext", MODEL)["words"], info["segments"])
    sel = select_takes(words, script, speech=speech_seconds(frame_db()), keep_outro=KEEP_OUTRO)
    edl = load_json(OUT / "edl.json")
    keep, cuts = edl["keep"], edl["cuts"]
    out_dur = ffprobe_duration(EDIT_VIDEO)
    raw_dur = ffprobe_duration(RAW_VIDEO)
    to_out = __import__("monteer.cut.edl", fromlist=["map_to_output"]).map_to_output(keep)
    data = load_json(WORK / "report_data.json")
    gap_rows = [u for u in data["unsure"] if u["why"].startswith("speech-level gap")]
    gap_keep = [g for g in gap_rows if g["kept"]]
    n_gap_cut = len(gap_rows) - len(gap_keep)
    unsure, missing = unsure_list(words, sel, script, [])
    seen, dedup = set(), []
    for u in unsure:
        key = (round(u["src"], 1), u["why"].split("(")[0])
        if key not in seen:
            seen.add(key)
            dedup.append(u)
    unsure = dedup
    ear = load_json(WORK / "ear_flags.json") if (WORK / "ear_flags.json").exists() else []
    vcut = load_json(WORK / "verify_cuts.json") if (WORK / "verify_cuts.json").exists() else []

    # script after the last recorded line is not part of this episode
    cov = Counter(script["sent_of_word"][j] for j in sel["covered_script_words"])
    last_sent = max(cov) if cov else -1
    not_rec = [s for s in missing if s > last_sent]
    missing_rec = [s for s in missing if s <= last_sent]
    not_rec_words = sum(1 for x in script["sent_of_word"] if x > last_sent)
    lost = set(missing_rec)                 # the Result screen's «script words lost» tile (owner's answer 2 of phase 4)
    save_json(WORK / "cut_lost.json", {"script_words_lost": sum(1 for x in script["sent_of_word"] if x in lost),
                                       "lines_lost": [{"n": s_, "text": script["sentences"][s_]} for s_ in missing_rec],
                                       "not_recorded_words": not_rec_words})

    by_reason = Counter(c["reason"] for c in cuts)
    secs_reason = Counter()
    for c in cuts:
        secs_reason[c["reason"]] += c["removed_s"]

    L = []
    a = L.append
    a(f"# مونتير / Monteer — cut report ({NAME})\n")
    a(f"**Output:** `output/{EDIT_VIDEO.name}` — 1920×1080, 24 fps, H.264 + AAC, the recording's own "
      "(already synced) external-mic audio. No human reference edit exists for this episode.\n")
    a("## 1. Result\n")
    a("| | Duration |\n|---|---|")
    a(f"| Raw recording (input) | {tc(raw_dur)} ({raw_dur:.0f} s) |")
    a(f"| **Auto edit** | **{tc(out_dur)}** ({out_dur:.0f} s), {out_dur / raw_dur:.0%} of the raw |\n")
    a("Rules: last take wins; lines stay in script order; in-take ad-libs kept; "
      "silences and breaths cut at −32 dB; the spoken channel outro after the last script line is kept.\n")

    a("## 2. Cuts and why\n")
    a(f"**{len(cuts)} jump cuts** ({len(keep)} kept segments), plus the head and tail outside the first and "
      "last kept segment.\n")
    a("| Reason | Cuts | Time removed |\n|---|---:|---:|")
    labels = {"silence": "Silence / breath below −32 dB (≥0.35 s, 80 ms padding)",
              "retake": "Wrong or repeated take (script comparison, stammered restarts, verification pass)",
              "off-script": "Off-script chatter between takes / false starts / off-camera words",
              "non-speech gap": "Non-speech noise inside a take", "breath": "Breath above −32 dB",
              "no speech": "No speech between takes"}
    for r, n in by_reason.most_common():
        a(f"| {labels.get(r, r)} | {n} | {secs_reason[r]:.0f} s |")
    a("")

    a("## 3. Not recorded (not part of this episode)\n")
    if not_rec:
        a(f"The recording stops after script line #{last_sent}. The rest of the script ({len(not_rec)} lines, "
          f"{not_rec_words} words) was not recorded and is "
          f"treated as not part of this episode. It starts with: «{script['sentences'][not_rec[0]][:80]}».\n")
    if missing_rec:
        a("Script lines inside the recorded part that were not found in the recording "
          "(numbered headings are normally not read aloud):\n")
        for s_ in missing_rec:
            a(f"- #{s_}: {script['sentences'][s_][:100]}")
        a("")

    a("## 4. The 10 spots most worth checking by ear\n")
    a("Output = position in the auto edit; source = position in the raw recording.\n")
    a("| # | Output | Source | What to listen for | Words (ASR) |\n|---|---|---|---|---|")
    top = [("ear", f) for f in ear] + check_by_ear(unsure, gap_keep, to_out, n=10 - len(ear),
                                                   taken=[to_out(f["src"]) for f in ear])
    top.sort(key=lambda x: x[1]["src"])
    for k, (kind, u) in enumerate(top, 1):
        label = u["why"] if kind == "ear" else CHECK_LABELS[kind]
        a(f"| {k} | {tc(to_out(u['src']))} | {tc(u['src'])} | {label} | {u.get('text', '')[:80]} |")
    a("")

    a("## 5. Every place I was unsure\n")
    a("| Output | Source | Kept? | Why unsure | Words (ASR) |\n|---|---|---|---|---|")
    rows = [(u["src"], u["kept"], u["why"], u["text"]) for u in unsure]
    for g in gap_keep:
        why = ("repeated line: kept this later take, cut the earlier attempt just before it; listen for a "
               "doubled or missing word at the join") if "earlier attempt cut" in g["why"] else \
              "speech the first ASR pass skipped; re-transcribed and kept (not a repeat of a neighbouring line)"
        rows.append((g["src"], True, why, g["text"]))
    for f in ear:
        rows.append((f["src"], True, f["why"], f["text"]))
    for src, kept, why, text in sorted(rows, key=lambda r: r[0]):
        a(f"| {tc(to_out(src))} | {tc(src)} | {'kept' if kept else 'cut'} | {why} | {text[:90]} |")
    a(f"\n{len(rows)} places in total. Also re-checked and cut: {n_gap_cut} skipped-speech gaps that repeated "
      "the following line (earlier attempts the first pass missed) or held no words. Full list: "
      "`work/gap_verdicts.json`.\n")
    if vcut:
        a(f"**Verification pass on the finished edit.** I transcribed the edit with both models and looked for "
          f"repeats still in it. {len(vcut)} spots were confirmed on a short clip and cut: false starts the "
          "first pass had hidden inside one long word, plus one off-camera «أيوة». Suspected repeats a "
          "clip did not confirm were left alone, so one model's mistake can't cut real content. Cut list: "
          "`work/verify_cuts.json`.\n")
        for s0, s1, t in vcut:
            a(f"- {tc(s0)} source: «{t}»")
        a("")

    left = still_suspected(keep, to_out)
    if left:                           # owner's fix 6 of 21 Oct 2026: what the verify pass left alone, to check by ear
        a("## 5b. Repeats still suspected (left in: the short-clip check did not hear them twice)\n")
        a("| Output | Source | Words (ASR) |\n|---|---|---|")
        for x in left:
            a(f"| {tc(x['out'])} | {tc(x['src'])} | {x['text']} |")
        a("")

    a("## 6. How accurate is Egyptian Arabic transcription on this audio? (measured)\n")
    acc = data.get("asr_accuracy", {})
    a("No human reference edit exists, so I transcribed the finished auto edit (only kept takes, in script "
      "order) and scored it against the script. Long one-sided runs (≥6 words) are excluded.\n")
    a("| Model | WER vs script | WER, lenient spelling | CER |\n|---|---:|---:|---:|")
    for m in (MODEL, "large-v3-turbo"):
        if m in acc:
            n_ = acc[m]["normalized"]
            a(f"| {m} | {n_['wer']:.1%} | {n_['wer_lenient']:.1%} | {n_['cer']:.1%} |")
    man = WORK / "manual_sample.json"
    if man.exists():
        mm = load_json(man)
        tot = mm["words"]
        a(f"\nWER vs script overstates the ASR error because the presenter paraphrases. I hand-classified "
          f"every error in {len(mm['windows'])} sample minutes ({tot} recognised words, windows at "
          f"{', '.join(mm['windows'])} of the auto edit):\n")
        a("| Error type | Count | Share of words |\n|---|---:|---:|")
        for key, label in (("real", "Real recognition error"), ("spelling", "Spelling / format only"),
                           ("paraphrase", "Presenter said something different from the script")):
            ex = mm.get("examples", {}).get(key, "")
            a(f"| {label}{' (' + ex + ')' if ex else ''} | {mm[key]} | {mm[key] / tot:.0%} |")
        a(f"\n**Bottom line:** true word error rate ≈ **{mm['real'] / tot:.0%}** "
          f"(≈{(mm['real'] + mm['spelling']) / tot:.0%} counting spelling/format). {mm.get('note', '')}\n")
    (OUT / "report.md").write_text("\n".join(L), encoding="utf-8")
    print("wrote", OUT / "report.md")


if __name__ == "__main__":
    main()

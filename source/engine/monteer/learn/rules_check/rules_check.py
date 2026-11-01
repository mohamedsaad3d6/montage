"""Measurement only: do the style rules (monteer.cut.style) learnt on reference episode B carry over to reference
episode A?

Applies the rules to episode A's final cut (<edits>/edl.json, untouched) and scores the final cut and the rules version
against the reference editor's cut, re-mapped with the same method as episode B's (editor_compare: map_audio, map_fix,
refine_video -> <out>/editor_keep.json). Then adds the breath rules (monteer.cut.breath) and measures breaths at the
joins and in pauses with the same join measurement as episode B (monteer.learn.joins).
Writes only inside --out (rules_scores.json, rules_breath.json, breath detector cache).

    <core python> -m monteer.learn.rules_check.rules_check --work <episode A work> --edits <episode A output> --out <rules_check dir>

--work holds asr_ext_large-v3.json, sync.json, sync_ext16.wav and script.docx; --out holds asr_ext_ctc.json (CTC words
of the synced audio, from map_reference.sh) and editor_keep.json.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from ..episode import bind, frame_db

def main():
    ap = argparse.ArgumentParser(description="Do the style and breath rules carry over to reference episode A?")
    ap.add_argument("--work", required=True, help="episode A work folder (asr_ext_large-v3.json, sync.json, sync_ext16.wav, script.docx)")
    ap.add_argument("--edits", required=True, help="episode A output folder with the final cut's edl.json")
    ap.add_argument("--out", required=True, help="rules_check folder (asr_ext_ctc.json, editor_keep.json); results go here")
    ap.add_argument("--script", help="script .docx (default <work>/script.docx)")
    ap.add_argument("--dur", type=float, default=3230.0, help="raw recording length in seconds (default: episode A's)")
    opt = ap.parse_args()
    WORK = bind(opt.work, opt.edits, opt.script)
    OUT, D = Path(opt.edits), Path(opt.out)
    # the cut modules read their paths at import, so they are imported after bind()
    from ...cut import breath, fixloop, script_text, selfcheck, style
    from ...cut.common import load_json, tc
    from ...cut.run import to_cam
    from ...cut.sync import SYNC16
    from ..editor_compare import analyze, score
    from ..joins import joins as JM
    from ..joins import sim_rules as SR
    analyze.DUR = opt.dur
    db = frame_db(SYNC16)
    ctc = selfcheck.with_norm(load_json(D / "asr_ext_ctc.json")["words"])
    wsp = to_cam(load_json(WORK / "asr_ext_large-v3.json")["words"], load_json(WORK / "sync.json")["segments"])
    final = load_json(OUT / "edl.json")["keep"]
    styled, rep = style.apply_style(final, db, ctc, log=print, wsp=wsp)
    rules = style.snap(style.guard(final, styled, ctc, db=db, wsp=wsp))
    scr = script_text.build()["words"]
    lost = fixloop.coverage(final, wsp, ctc, scr) - fixloop.coverage(rules, wsp, ctc, scr)
    print(f"rules: {tc(sum(e - s for s, e in rules))} (final {tc(sum(e - s for s, e in final))}), "
          f"script words lost: {[scr[j] for j in sorted(lost)]}")
    ref = load_json(D / "editor_keep.json")
    # only what the editor took from the raw (the editor's intro / outro graphics and music are not raw material)
    R = [dict(s, src_s=s["src_audio_s"], src_e=s["src_audio_e"]) for s in ref if s["audio_ncc"] >= 0.5]
    cover = np.zeros(len(db), bool)
    for w in ctc + wsp:
        cover[max(0, int((w["s"] - 0.06) / 0.01)): int((w["e"] + 0.06) / 0.01)] = True
    cs = sorted(ctc, key=lambda w: w["s"])
    ev = []
    for s, e in analyze.runs((db > -55) & ~cover):
        if 0.1 <= e - s <= 1.5:
            b = [w for w in cs if w["e"] <= s + 0.01][-1:]
            a = [w for w in cs if w["s"] >= e - 0.01][:1]
            if b and a:
                ev.append((s, e, b[0], a[0]))
    res = {"style_report": rep, "script_words_lost": [scr[j] for j in sorted(lost)],
           "editor_raw_material_s": sum(s["src_e"] - s["src_s"] for s in R)}
    for name, keep in (("final", final), ("rules", rules)):
        res[name] = score.score(analyze.segs_from_keep(keep), R, ctc, wsp, db, {}, ev)
    res["editor"] = score.score(R, R, ctc, wsp, db, {}, ev)
    json.dump(res, open(D / "rules_scores.json", "w"), ensure_ascii=False, indent=1, default=float)
    # breath rules on top of the rules version
    M = breath.prepare(SYNC16, ctc, cache_dir=D, log=print)
    cleaned, brep = breath.clean(rules, M, ctc=ctc, log=print)
    rules_b = style.snap(style.guard(rules, cleaned, ctc, db=db, wsp=wsp))
    fades = [f for f in brep["soft_fades"] if any(abs((s if f["side"] == "in" else e) - f["t"]) < 1e-3 for s, e in rules_b)]
    lost_b = fixloop.coverage(final, wsp, ctc, scr) - fixloop.coverage(rules_b, wsp, ctc, scr)
    print(f"rules + breath: {tc(sum(e - s for s, e in rules_b))}, script words lost vs final: {[scr[j] for j in sorted(lost_b)]}")
    res["rules_breath"] = score.score(analyze.segs_from_keep(rules_b), R, ctc, wsp, db, {}, ev)
    W, B, O = M["W"], M["B"], M["O"]
    lost_words = {}
    for name, keep in (("final", final), ("rules", rules), ("rules_breath", rules_b)):
        lost_words[name] = [w["w"] for w in ctc if style.kept_frac(final, w["s"], w["e"]) >= .5 and style.kept_frac(keep, w["s"], w["e"]) < .5]
    br = {"script_words_lost_rules_breath": [scr[j] for j in sorted(lost_b)], "breath_rules": {k: brep[k] for k in ("R1", "R2", "R3")},
          "literal_words_lost_vs_final": lost_words, "summary": {}}
    editor = [[s["src_s"], s["src_e"]] for s in R]
    for name, keep, mute in (("final", final, []), ("rules", rules, []), ("rules_breath", rules_b, JM.muted({"fades": fades})),
                             ("editor", editor, [])):
        Wm, Bm, Om = W.copy(), B.copy(), O.copy()
        for a, b in mute:
            for m in (Wm, Bm, Om):
                m[int(round(a / 0.01)):int(round(b / 0.01))] = False
        sm = JM.summary(JM.measure(keep, M["F"], Wm, Bm, Om), name)
        sm["inside_pause_breaths"] = SR.inside_breaths(keep, Wm, Bm, M["db"])
        sm["raw_kept_s"] = sum(e - s for s, e in keep)
        br["summary"][name] = sm
        print(f"{name:13} joins {sm['joins']:4}  breath in pause {sm['separate breath kept']:2}  cut through {sm['breath cut through']:3}  "
              f"tail/lead-in {sm['breath tail on word']:3}  inside-pause breaths {sm['inside_pause_breaths']:3}  clipped {sm['word_clipped_loud']:3}  "
              f"on-word {sm['edge_on_word_sound_<30ms_silence']:3}  gap median {sm['gap']['median']:.0f} p10 {sm['gap']['p10']:.0f} p90 {sm['gap']['p90']:.0f}")
    json.dump(br, open(D / "rules_breath.json", "w"), ensure_ascii=False, indent=1, default=float)
    json.dump(res, open(D / "rules_scores.json", "w"), ensure_ascii=False, indent=1, default=float)
    keys = [k for k in res["final"] if not isinstance(res["final"][k], (list, dict))]
    for k in keys:
        print(f"{k:32}" + "".join(f"{res[v][k]:>12.3f}" if isinstance(res[v][k], float) else f"{res[v][k]:>12}"
                                  for v in ("final", "rules", "rules_breath", "editor")))


if __name__ == "__main__":
    main()

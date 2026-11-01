"""Take fixes for a channel episode (owner's decisions of 22 Oct 2026, after «المملكة المتحدة تنهار» v2: «last take wins» kept
an incomplete last take and cut the party's name «شين فين»; a later take started mid-phrase and cut «مش إن», turning a
sentence's meaning round; stammer fragments stayed in («هدف– هتدفعوا», «ومش… وميشيل», «حلق… الحلقة»)).

  complete_takes(words, sel)   when a cut take of a stretch matched the script clearly better (0.85 or more, and 0.25 above)
                               than the kept one, the complete take is kept and the kept one cut (answer 3a: keep the most
                               complete take) - only when nothing else of the script lies between the two (the order stays)
  lost_words(words, sel)       script words missing between two kept words of one sentence, said in a cut stretch exactly
                               there (between them in time): put back («لندن | مش إن | في أحزاب»)
  stammers(keep, ctc, vocab)   a kept word of the literal model that is no script word, starts like the next kept word and
                               comes less than 1 s before it: a stammer, cut («هدف هتدفعوا», «ومش وميشيل», «حلق … حلقة»)

Each returns fixes in the shape of work/manual_fixes.json ({"op", "spans", "reason", "why", "text"}); run.py applies them
before the hand fixes. The classic projects never call this.
"""
from rapidfuzz import fuzz

from .common import normalize_ar

STRONG, MARGIN = 0.85, 0.25
NEAR_TAKES_S = 60.0        # s: the complete take and the replaced one at most this far apart
ATTEMPT_GAP = 0.8          # s: a pause longer than this between two words of a take starts a new attempt
STAMMER_GAP = 1.0


def complete_takes(words, sel):
    d = sel["decisions"]
    kept_score = {x["j"]: x["score"] for x in d if x["keep"] and x["j"] >= 0}
    out = []
    for r in sel["runs"]:
        idx = [k for k in r["words"] if not d[k]["keep"] and d[k]["reason"].startswith("retake: ") and "take " in d[k]["reason"]]
        groups = {}
        for k in idx:
            groups.setdefault(d[k]["reason"].split("take ")[-1], []).append(k)
        for grp0 in groups.values():
            grp0 = sorted(grp0, key=lambda k: words[k]["s"])
            attempts, cur = [], []    # one continuous attempt (words less than ATTEMPT_GAP apart): «والتمويل…» said 4 times
            for k in grp0:
                if cur and words[k]["s"] - words[cur[-1]]["e"] > ATTEMPT_GAP:
                    attempts.append(cur)
                    cur = []
                cur.append(k)
            if cur:
                attempts.append(cur)
            js_all = {d[k]["j"] for k in grp0 if d[k]["j"] >= 0}
            best = max(attempts, key=lambda a: (len({d[k]["j"] for k in a}), words[a[-1]]["s"]))   # the fullest, the latest
            if len({d[k]["j"] for k in best}) < 0.9 * len(js_all):
                continue
            grp = best
            if len(grp) < 3:
                continue
            js = {d[k]["j"] for k in grp if d[k]["j"] >= 0}
            cut_s = sum(d[k]["score"] or 0 for k in grp) / len(grp)
            kept_s = sum(kept_score.get(d[k]["j"], -0.5) for k in grp) / len(grp)
            if cut_s < STRONG or cut_s < kept_s + MARGIN:
                continue
            kept = sorted(k for k in range(len(d)) if d[k]["keep"] and d[k]["j"] in js)
            if not kept:
                continue
            c0, c1 = words[grp[0]]["s"], words[grp[-1]]["e"]
            k0, k1 = words[kept[0]]["s"], words[kept[-1]]["e"]
            sents = {d[k]["sent"] for k in grp if d[k].get("sent") is not None}
            last = kept[-1]                # the replaced attempt to its end: its words that follow without a pause, in the same
            while last + 1 < len(d) and d[last + 1]["keep"] and (d[last + 1]["j"] < 0 or d[last + 1].get("sent") in sents) \
                    and words[last + 1]["s"] - words[last]["e"] <= ATTEMPT_GAP:     # sentence («هيتقدملنا إيه»)
                last += 1
            k1 = words[last]["e"]
            if abs(c0 - k0) > NEAR_TAKES_S or k1 - k0 > max(6.0, 2.5 * (c1 - c0)):
                continue               # two takes of one line are close together and alike in length (never a cut of minutes)
            lo, hi = (c1, k0) if c1 <= k0 else (k1, c0)
            between = [k for k in range(len(d)) if d[k]["keep"] and lo < words[k]["s"] < hi and d[k]["j"] >= 0 and d[k]["j"] not in js]
            if between or (c0 < k1 and k0 < c1):
                continue
            text_c = " ".join(words[k]["w"] for k in grp)
            text_k = " ".join(words[k]["w"] for k in kept)
            out.append({"op": "keep", "spans": [[round(c0 - 0.05, 3), round(c1 + 0.08, 3)]], "reason": "complete take",
                        "why": f"the complete take ({cut_s:.2f}) kept instead of the incomplete one ({kept_s:.2f})", "text": text_c})
            out.append({"op": "cut", "spans": [[round(k0 - 0.05, 3), round(k1 + 0.05, 3)]], "reason": "retake",
                        "why": f"an incomplete take ({kept_s:.2f}); the complete one ({cut_s:.2f}) is kept", "text": text_k})
    return out


def lost_words(words, sel):
    d = sel["decisions"]
    kept = sorted((k for k in range(len(d)) if d[k]["keep"] and d[k]["j"] >= 0), key=lambda k: words[k]["s"])
    out = []
    for a, b in zip(kept, kept[1:]):
        ja, jb = d[a]["j"], d[b]["j"]
        if d[a]["sent"] != d[b]["sent"] or not 2 <= jb - ja <= 5:
            continue
        missing = set(range(ja + 1, jb))
        cands = [k for k in range(len(d)) if not d[k]["keep"] and d[k]["j"] in missing
                 and words[a]["e"] <= words[k]["s"] and words[k]["e"] <= words[b]["s"]]
        if {d[k]["j"] for k in cands} != missing:
            continue
        cands.sort(key=lambda k: words[k]["s"])
        out.append({"op": "keep", "spans": [[round(words[cands[0]]["s"] - 0.05, 3), round(words[cands[-1]]["e"] + 0.05, 3)]],
                    "reason": "script words", "why": "script words the cut had lost between two kept words, put back",
                    "text": " ".join(words[k]["w"] for k in cands)})
    return out


def is_stammer(w, nxt, vocab):
    """a broken-off start of the next word: shorter than it, and like its own start («هدف»/«هتدفعوا», «ومش»/«وميشيل»); a
    whole word the literal model only misspelled («سال سياسي», «المرة دي», «وأهلا وسهلا») is none"""
    a, b = normalize_ar(w), normalize_ar(nxt)
    if len(a) < 2 or a == b or a in vocab or not b or a[0] != b[0] or len(b) <= len(a):
        return False
    return b.startswith(a) or fuzz.ratio(a, b[:len(a) + 1]) >= 70


def stammers(keep, ctc, vocab, protect=()):
    """protect: spans decided by hand (never cut here)"""
    inside = lambda w: any(s - 0.02 <= w["s"] and w["e"] <= e + 0.02 for s, e in keep) and \
        not any(a - 0.05 <= w["s"] <= b + 0.05 for a, b in protect)                       # noqa: E731
    kw = sorted((w for w in ctc if inside(w)), key=lambda w: w["s"])
    out = []
    for w, nxt in zip(kw, kw[1:]):
        if nxt["s"] - w["e"] < STAMMER_GAP and is_stammer(w["w"], nxt["w"], vocab):
            out.append({"op": "cut", "spans": [[round(w["s"] - 0.04, 3), round(min(nxt["s"] - 0.02, w["e"] + 0.12), 3)]],
                        "reason": "retake", "why": f"a stammer «{w['w']}» before «{nxt['w']}»", "text": w["w"]})
    return out

"""Measure Egyptian Arabic ASR accuracy on the reference cut against the script.

The script is an imperfect ground truth: the presenter ad-libs and the editor dropped lines.
So we align, then exclude long runs (>= EXCL words) that exist on only one side, and report:
  - strict WER on normalized words,
  - lenient WER (a substitution counts as correct when the spellings are >= 80% similar:
    dialect spelling variants such as برا/برة, ايديك/إيدك),
  - CER on the retained text,
and dump the aligned diff of sampled windows for manual error classification.
"""
import random
import re

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from .common import WORK, normalize_ar

EXCL = 6


def light_norm(text):
    """'Raw' level: only punctuation and diacritics removed, spelling kept."""
    t = re.sub(r"[ً-ْـ]", "", text)
    t = re.sub(r"[^\w\s%]", " ", t)
    return t.split()


def aligned_pairs(ref, hyp):
    pairs, i, j = [], 0, 0
    for op in Levenshtein.editops(ref, hyp):
        while i < op.src_pos and j < op.dest_pos:
            pairs.append((i, j))
            i += 1
            j += 1
        if op.tag == "replace":
            pairs.append((i, j)); i += 1; j += 1
        elif op.tag == "delete":
            pairs.append((i, None)); i += 1
        else:
            pairs.append((None, j)); j += 1
    while i < len(ref) and j < len(hyp):
        pairs.append((i, j)); i += 1; j += 1
    pairs += [(k, None) for k in range(i, len(ref))] + [(None, k) for k in range(j, len(hyp))]
    return pairs


def exclude_runs(pairs):
    """Mark long one-sided runs (editor cut a line / presenter ad-lib) as excluded."""
    excl = [False] * len(pairs)
    k = 0
    while k < len(pairs):
        kind = "del" if pairs[k][1] is None else "ins" if pairs[k][0] is None else None
        if kind is None:
            k += 1
            continue
        u = k
        while u + 1 < len(pairs) and (pairs[u + 1][1] is None if kind == "del" else pairs[u + 1][0] is None):
            u += 1
        if u - k + 1 >= EXCL:
            for q in range(k, u + 1):
                excl[q] = True
        k = u + 1
    return excl


def score(ref, hyp):
    pairs = aligned_pairs(ref, hyp)
    excl = exclude_runs(pairs)
    S = D = I = C = Sl = 0
    rs, hs = [], []
    for (i, j), x in zip(pairs, excl):
        if x:
            continue
        if i is not None and j is not None:
            if ref[i] == hyp[j]:
                C += 1
            else:
                S += 1
                if fuzz.ratio(ref[i], hyp[j]) >= 80:
                    Sl += 1
        elif j is None:
            D += 1
        else:
            I += 1
        if i is not None:
            rs.append(ref[i])
        if j is not None:
            hs.append(hyp[j])
    N = C + S + D
    r_str, h_str = " ".join(rs), " ".join(hs)
    return {"N": N, "C": C, "S": S, "D": D, "I": I,
            "wer": (S + D + I) / N, "wer_lenient": (S - Sl + D + I) / N,
            "cer": Levenshtein.distance(r_str, h_str) / max(1, len(r_str)),
            "excluded_script_words": sum(1 for (i, j), x in zip(pairs, excl) if x and i is not None),
            "excluded_asr_words": sum(1 for (i, j), x in zip(pairs, excl) if x and j is not None),
            "pairs": pairs, "excl": excl}


def evaluate(script, asr_words, raw_script_text):
    hyp_n = [w["n"] for w in asr_words]
    norm = score(script["words"], hyp_n)
    raw_ref = [w for s in script["sentences"] for w in light_norm(s)]
    raw_hyp = [w for x in asr_words for w in light_norm(x["w"])]
    raw = score(raw_ref, raw_hyp)
    return {"normalized": {k: v for k, v in norm.items() if k not in ("pairs", "excl")},
            "raw": {k: v for k, v in raw.items() if k not in ("pairs", "excl")},
            "_pairs": norm["pairs"], "_excl": norm["excl"]}


def sample_diff(script, asr_words, pairs, excl, windows=3, win_s=60, seed=7):
    """Write aligned diffs of random 60 s windows (reference-cut time) for manual review."""
    random.seed(seed)
    dur = asr_words[-1]["e"]
    starts = sorted(random.sample(range(30, int(dur) - win_s - 30, 10), windows))
    lines = []
    for st in starts:
        lines.append(f"\n=== window {st}-{st + win_s}s ===")
        inside = False  # deletions belong to the window when the last recognised word did
        for (i, j), x in zip(pairs, excl):
            if j is not None:
                inside = st <= asr_words[j]["s"] < st + win_s
            if not inside:
                continue
            if j is None:
                lines.append(f"  DEL  {script['words'][i]}" + ("   [excluded]" if x else ""))
                continue
            r = script["words"][i] if i is not None else ""
            h = asr_words[j]["n"]
            tag = "ok " if r == h else "INS" if i is None else "SUB"
            lines.append(f"  {tag}  {r:<18} | {h:<18} p={asr_words[j]['p']:.2f}" + ("   [excluded]" if x else ""))
    path = WORK / "asr_sample_diff.txt"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path, starts

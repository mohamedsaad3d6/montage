"""Stage 5: take selection by aligning the transcript to the script.

A single DP walks the transcript word by word. Each word is either matched to a script
word or marked as an insertion. Between matches the script position can advance (normal
reading), skip forward (a missed word or ASR drop), or jump backwards (a retake).
Contiguous stretches between backward jumps are "runs" (takes). Each script word is then
owned by one take, chosen by best_take_owner so kept pieces stay in script order: the LAST take
that says it (default), or the one that says it best (v2). The same words in every other take are cut.
"""
import re

import numpy as np
from rapidfuzz import fuzz, process

# DP costs (score units; a perfect word match is +1)
INS = 0.5          # transcript word not in the script
SKIP = 0.4         # per script word skipped going forward
SKIP_CAP = 4.0     # max cost of a long forward jump
RESTART = 2.0      # going back in the script (a retake)
MATCH_FLOOR = 65   # similarity (0-100) that scores 0
OWN_GAP = 3        # script words a take may skip and still own
INTERRUPT_GAP = 4.0  # seconds of silence inside an off-script stretch that make it an interruption

CONT, SKIP_LIN, SKIP_FAR, BACK, START, INSERT = range(6)


# the script writes small numbers as digits, the presenter says them (normalized spelling, ة→ه)
NUMBER_WORDS = {
    "1": "واحد واحده", "2": "اتنين اثنين اتنان", "3": "تلات تلاته ثلاث ثلاثه تلت تلاث تلاثه", "4": "اربع اربعه",
    "5": "خمس خمسه", "6": "ست سته", "7": "سبع سبعه", "8": "تمن تمانيه ثمانيه ثمان", "9": "تسع تسعه",
    "10": "عشر عشره",
}
_NUM = {w: d for d, ws in NUMBER_WORDS.items() for w in ws.split()}


def similarity(t_words, s_words):
    sim = process.cdist(t_words, s_words, scorer=fuzz.ratio, workers=-1, dtype=np.uint8)
    num = [i for i, w in enumerate(t_words) if w in _NUM]  # a spoken number matches as said or as its digit
    if num:
        sim[num] = np.maximum(sim[num], process.cdist([_NUM[t_words[i]] for i in num], s_words,
                                                      scorer=fuzz.ratio, workers=-1, dtype=np.uint8))
    return np.clip((sim.astype(np.float32) - MATCH_FLOOR) / (100 - MATCH_FLOOR), -1, 1)


def _prefix_max(v):
    acc = np.maximum.accumulate(v)
    idx = np.arange(len(v))
    arg = np.maximum.accumulate(np.where(v >= acc, idx, 0))
    return acc, arg


def dp_align(ms):
    n, m = ms.shape
    jj = np.arange(m, dtype=np.float32)
    tb_type = np.zeros((n, m), dtype=np.int8)
    tb_src = np.zeros((n, m), dtype=np.int32)
    start_cost = np.minimum(SKIP * jj, SKIP_CAP)
    B = np.full(m, -np.inf, dtype=np.float32)
    start_score = 0.0
    neg = np.float32(-np.inf)
    for i in range(n):
        cands = []
        # continue reading: from j-1
        cont = np.concatenate([[neg], B[:-1]])
        cands.append((cont, CONT, np.arange(m) - 1))
        # forward skip, linear cost: max_{j'<=j-2} B[j'] + SKIP*j'  - SKIP*(j-1)
        acc, arg = _prefix_max(B + SKIP * jj)
        lin = np.concatenate([[neg, neg], acc[:-2]]) - SKIP * (jj - 1)
        cands.append((lin, SKIP_LIN, np.concatenate([[0, 0], arg[:-2]])))
        acc2, arg2 = _prefix_max(B)
        far = np.concatenate([[neg, neg], acc2[:-2]]) - SKIP_CAP
        cands.append((far, SKIP_FAR, np.concatenate([[0, 0], arg2[:-2]])))
        # backward jump (retake): max_{j'>=j} B[j'] - RESTART
        r = B[::-1]
        racc, rarg = _prefix_max(r)
        back = racc[::-1] - RESTART
        cands.append((back, BACK, (m - 1 - rarg)[::-1]))
        cands.append((start_score - start_cost, START, np.full(m, -1)))
        stack = np.stack([c[0] for c in cands])
        best = np.argmax(stack, axis=0)
        prev = stack[best, np.arange(m)]
        M = ms[i] + prev
        I = B - INS
        use_ins = I > M
        newB = np.where(use_ins, I, M).astype(np.float32)
        types = np.array([c[1] for c in cands], dtype=np.int8)[best]
        srcs = np.stack([c[2] for c in cands])[best, np.arange(m)]
        tb_type[i] = np.where(use_ins, INSERT, types)
        tb_src[i] = np.where(use_ins, np.arange(m), srcs)
        start_score -= 0.1  # pre-roll chatter before the first scripted word
        B = newB
    # traceback
    j = int(np.argmax(B))
    path = [None] * n
    for i in range(n - 1, -1, -1):
        t = int(tb_type[i, j])
        path[i] = (t, j)
        if t == START:
            for k in range(i - 1, -1, -1):
                path[k] = (START, -1)  # pre-roll: nothing matched yet
            break
        j = int(tb_src[i, j])
    return path


STRAY_SCORE = 0.5   # outro boundary: a last "script" word matching worse than this ...
STRAY_GAP = 1.0     # ... with a pause this long on either side is a stray word
REPEAT_WINDOW = 12.0  # seconds: a phrase said again within this window replaces the earlier attempt
REPEAT_MAX_BETWEEN = 12  # kept words allowed between the two attempts


def _same(a, b):
    return a == b or (len(a) > 2 and len(b) > 2 and fuzz.ratio(a, b) >= 85)


def cut_self_repeats(t_words, keep, reason, word_type, word_j, immediate_only=frozenset()):
    """Stammered restarts that are not in the script ("هي بتقتحم... هي بتقتحم إمبراطورية") are
    inserts, so take selection keeps them. Cut every earlier attempt of a phrase that is said
    again right after, keeping the last. Only when the earlier attempt is off-script (or maps
    to the same script words), so lines the script itself repeats are never touched."""
    kept = [i for i in range(len(keep)) if keep[i]]
    pos = 0
    while pos < len(kept):
        i = kept[pos]
        hit = None
        for n in (4, 3, 2, 1):
            if pos + n > len(kept):
                continue
            gram = kept[pos: pos + n]
            if n == 1 and len(t_words[i]["n"]) < 3:
                continue
            for q in range(pos + n, min(len(kept) - n + 1, pos + n + REPEAT_MAX_BETWEEN + 1)):
                if n == 1 and q != pos + 1:
                    break  # single words only when immediately repeated ("نووي نووي")
                cand = kept[q: q + n]
                if t_words[cand[0]]["s"] - t_words[i]["s"] > REPEAT_WINDOW:
                    break
                if i in immediate_only and q != pos + n:
                    break  # in the outro only a straight false start ("انا انا") is cleaned up
                if all(_same(t_words[a]["n"], t_words[b]["n"]) for a, b in zip(gram, cand)):
                    earlier = kept[pos:q]
                    offscript = i in immediate_only or any(word_type[k] == "insert" for k in gram) or \
                        [word_j[k] for k in gram] == [word_j[k] for k in cand]
                    if offscript:
                        hit = earlier
                    break
            if hit:
                break
        if hit:
            for k in hit:
                keep[k] = False
                reason[k] = "retake: phrase repeated right after (stammer)"
            pos += len(hit)
        else:
            pos += 1


TAKE_RULE = "last"  # "last": last take, in script order (final); "best": best script match (v2);
                    # "v1": last take by plain ownership, order not enforced

# best-take choice (scores per script word, same units as the DP)
MISS = 0.5          # the chosen take does not say this script word
SWITCH = 0.3        # cutting to another take at a sentence boundary
SWITCH_MID = 0.6    # cutting to another take mid-sentence (harder to hide)
INS_PEN = 0.2       # per off-script word (stammer, filler; 2+ in a row) before this word, max 1.0
FLUB = 0.3          # last 2 words before the presenter broke off and restarted
DROP_SCORE = 0.6    # a word missing from a take's transcript where its audio has speech: the
                    # ASR most likely dropped it (it often skips repeated phrases), not the presenter
DROP_SECS = 0.08    # speech seconds per missing word for that
LAST_WINS = 3.0     # per word, to the last take under "last": more than any match difference
LATER_BONUS = 0.15  # per word, to the last take under "best"
GOOD_MATCH = 0.3    # similarity (scaled, ≈ fuzz ratio 75) for a word to count as really read
LOST_LINE = 0.5     # a script line with less than this share kept (good matches) is treated as lost ...
FULL_READ = 0.7     # ... and restored from the last take that reads at least this share of it well: an earlier take must match clearly better to
                    # replace it; on a tie the presenter likely redid it for delivery ASR can't hear


def best_take_owner(runs, word_j, word_type, ms, script, t_words=None, speech=None, later_bonus=LATER_BONUS):
    """Choose one take per script word with a Viterbi pass over script words.

    States are takes (runs, in time order). The path may stay in a take or move to a LATER take,
    never back, so the kept pieces stay in script order when played in source-time order.
    Each take scores how well it says each word; switching takes costs a cut."""
    m, R = len(script["words"]), len(runs)
    sent = np.asarray(script["sent_of_word"])
    emit = np.full((R, m), -MISS, dtype=np.float32)
    said = np.full((R, m), -1, dtype=np.int64)
    for r in runs:
        matched, ins_before, ins = [], {}, 0
        for i in r["words"]:
            if word_type[i] == "match":
                matched.append(i)
                ins_before[i], ins = ins, 0
            else:
                ins += 1
        tail = set(matched[-2:]) if r["id"] < R - 1 else set()
        for a, b in zip([None] + matched, matched):
            k = word_j[b] - word_j[a] - 1 if a is not None else 0
            extra = ins_before[b]
            if k >= 1:
                # off-script words where script words are missing are most likely those words,
                # misheard; what is still missing may be a dropped word if the audio has speech
                filled = min(k, extra)
                extra -= filled
                left = k - filled
                if k <= 6 and (left == 0 or (speech is not None and
                                             speech(t_words[a]["e"], t_words[b]["s"]) >= DROP_SECS * left)):
                    gap = slice(word_j[a] + 1, word_j[b])
                    emit[r["id"], gap] = np.maximum(emit[r["id"], gap], DROP_SCORE)
            j = word_j[b]
            pen = INS_PEN * extra if extra >= 2 else 0.0  # one stray word is usually ASR noise
            v = ms[b, j] - min(1.0, pen) - (FLUB if b in tail else 0.0)
            if v > emit[r["id"], j] or said[r["id"], j] < 0:
                emit[r["id"], j], said[r["id"], j] = v, b
    last = np.full(m, -1)
    for r in runs:
        last[said[r["id"]] >= 0] = r["id"]
    emit[last[last >= 0], np.nonzero(last >= 0)[0]] += later_bonus

    V = emit[:, 0].copy()
    back = np.zeros((m, R), dtype=np.int32)
    back[0] = np.arange(R)
    for j in range(1, m):
        cost = SWITCH if sent[j] != sent[j - 1] else SWITCH_MID
        pm, arg = _prefix_max(V)  # best earlier-or-same take
        prev_best = np.concatenate([[-np.inf], pm[:-1]]) - cost
        prev_arg = np.concatenate([[0], arg[:-1]])
        stay = V >= prev_best
        back[j] = np.where(stay, np.arange(R), prev_arg)
        V = np.where(stay, V, prev_best) + emit[:, j]
    path = np.empty(m, dtype=np.int64)
    path[-1] = int(np.argmax(V))
    for j in range(m - 1, 0, -1):
        path[j - 1] = back[j, path[j]]
    owner = np.where(said[path, np.arange(m)] >= 0, path, -1)
    return owner, path, emit, said


def restore_lost_lines(t_words, script, ms, runs, word_type, word_j, word_run, keep, reason):
    """Safety net: a script line whose kept words barely read it (a later fragment that shares a word
    or two claimed it) is restored from the last take that reads it well, when that keeps script order."""
    sent = script["sent_of_word"]
    by_sent = {}
    for j, sn in enumerate(sent):
        by_sent.setdefault(sn, []).append(j)
    matched = [i for i in range(len(t_words)) if word_type[i] == "match"]
    for sn, js in by_sent.items():
        if len(js) < 4:
            continue  # headings and one-word lines
        jset = set(js)
        good = lambda i: ms[i, word_j[i]] >= GOOD_MATCH
        kept_good = {word_j[i] for i in matched if keep[i] and word_j[i] in jset and good(i)}
        if len(kept_good) >= LOST_LINE * len(js):
            continue
        best = None
        for r in runs:
            mine = [i for i in r["matched"] if word_j[i] in jset]
            if len({word_j[i] for i in mine if good(i)}) >= FULL_READ * len(js):
                best = (r, mine)  # runs are in time order: the last full reading wins
        if best is None:
            continue
        r, mine = best
        t0, t1 = t_words[mine[0]]["s"], t_words[mine[-1]]["e"]
        # script order is judged on real readings only; weak claims around the line go with it
        near = set(range(js[0] - 3, js[-1] + 4))
        before = [i for i in matched if keep[i] and good(i) and word_j[i] < js[0]]
        after = [i for i in matched if keep[i] and good(i) and word_j[i] > js[-1]]
        if (before and t_words[max(before)]["e"] > t0) or (after and t_words[min(after)]["s"] < t1):
            continue  # restoring would break script order
        for i in matched:
            if word_j[i] in jset and word_run[i] == r["id"]:
                keep[i], reason[i] = True, ""
            elif keep[i] and word_run[i] != r["id"] and (word_j[i] in jset or (word_j[i] in near and not good(i))):
                keep[i], reason[i] = False, f"retake: line read fully in take {r['id']}"


SLOT_UTTER = 0.8     # s of silence between two utterances of the presenter's own words
SLOT_GAP = 2.0       # s: his final take goes on through pauses up to this long


def keep_slot(t_words, keep, reason, word_type, word_j, sent_of_word, after):
    """the presenter's own words where the script leaves them a place after sentence `after` («[حضّر مشروبك — بكلام
    المذيع]», owner's fix 5 of 21 Oct 2026; the first episode cut his whole intro as off-script). Between the kept end of
    that sentence and the next kept script word, the words not kept are his attempts; his FINAL take starts at the last
    utterance that begins like an earlier one (a restart) and goes on through pauses up to SLOT_GAP s. Those words are
    kept, whatever the matcher made of them (his «انا محمد رمضان … الموضوع الاقتصادي» had matched the script's closing)."""
    from rapidfuzz import fuzz
    n = len(t_words)
    sent = lambda i: sent_of_word[word_j[i]] if word_type[i] == "match" and word_j[i] >= 0 else None   # noqa: E731
    ia = max((i for i in range(n) if keep[i] and sent(i) is not None and sent(i) <= after), default=-1 if after < 0 else None)
    if ia is None:
        return []
    ib = next((i for i in range(ia + 1, n) if keep[i] and sent(i) is not None and sent(i) > after), n)
    free = [i for i in range(ia + 1, ib) if not keep[i]]
    if not free:
        return []
    utters, cur = [], [free[0]]
    for i in free[1:]:
        if i == cur[-1] + 1 and t_words[i]["s"] - t_words[cur[-1]]["e"] <= SLOT_UTTER:
            cur.append(i)
        else:
            utters.append(cur)
            cur = [i]
    utters.append(cur)
    start = 0
    for k, u in enumerate(utters):
        if len(u) < 2:
            continue
        head = f"{t_words[u[0]]['n']} {t_words[u[1]]['n']}"
        before = [i for v in utters[:k] for i in v]
        if any(fuzz.ratio(head, f"{t_words[a]['n']} {t_words[b]['n']}") >= 80 for a, b in zip(before, before[1:])):
            start = k                  # a restart: the takes before it are left out
    take = list(utters[start])
    for u in utters[start + 1:]:
        if u[0] == take[-1] + 1 and t_words[u[0]]["s"] - t_words[take[-1]]["e"] <= SLOT_GAP:
            take += u
        else:
            break
    for i in take:
        keep[i], reason[i] = True, ""
    return take


DRINK = re.compile("شروب")          # «مشروبك», «اشرب مشروبك», «المشروب الرسمي» as whisper writes them


def drink_after(t_words, keep, word_type, word_j, sent_of_word):
    """a script with no placeholder (owner's 1a of 21 Oct 2026): his first off-script «…شروب…» in the first 60 % of the
    recording marks his own lines; -> the script sentence they follow (the last kept one before them), or None"""
    n = len(t_words)
    end = t_words[-1]["e"] if n else 0
    for i in range(n):
        if t_words[i]["s"] > 0.6 * end:
            return None
        if not keep[i] and DRINK.search(t_words[i]["n"]):
            before = [sent_of_word[word_j[k]] for k in range(i) if keep[k] and word_type[k] == "match" and word_j[k] >= 0]
            return before[-1] if before else None
    return None


def select_takes(t_words, script, ms=None, rule=None, speech=None, keep_outro=False):
    """t_words: list of dicts with 'n' (normalized). Returns per-word decisions + runs."""
    rule = rule or TAKE_RULE
    s_words = script["words"]
    if ms is None:
        ms = similarity([w["n"] for w in t_words], s_words)
    path = dp_align(ms)
    n = len(t_words)

    # split into runs (takes)
    runs, cur = [], None
    word_run, word_j, word_type = [-1] * n, [-1] * n, [None] * n
    for i, (t, j) in enumerate(path):
        if t == START and j == -1:
            word_type[i] = "preroll"
            continue
        if t in (BACK, START) or cur is None:
            cur = {"id": len(runs), "words": [], "matched": []}
            runs.append(cur)
        if t == INSERT:
            word_type[i] = "insert"
        else:
            word_type[i] = "match"
            word_j[i] = j
            cur["matched"].append(i)
        cur["words"].append(i)
        word_run[i] = cur["id"]
    for r in runs:
        js = [word_j[i] for i in r["matched"]]
        r["j0"], r["j1"] = (min(js), max(js)) if js else (None, None)
        r["score"] = float(np.mean([ms[i, word_j[i]] for i in r["matched"]])) if js else 0.0

    # ownership: last run that actually spoke each script word. A run owns the words it matched
    # plus gaps of <= OWN_GAP script words between consecutive matches (an ASR drop or a skipped
    # word), never the whole span of a long forward jump.
    owner = np.full(len(s_words), -1)
    for r in runs:
        js = sorted(word_j[i] for i in r["matched"])
        for a, b in zip(js, js[1:] + [js[-1]] if js else []):
            owner[a] = r["id"]
            if 0 < b - a <= OWN_GAP + 1:
                owner[a:b] = r["id"]
    last_owner = owner
    path = None
    if rule in ("best", "last"):
        owner, path, _, _ = best_take_owner(runs, word_j, word_type, ms, script, t_words, speech,
                                            LATER_BONUS if rule == "best" else LAST_WINS)

    keep = [False] * n
    reason = [""] * n
    for i in range(n):
        if word_type[i] == "match":
            j = word_j[i]
            o = owner[j] if owner[j] >= 0 else (path[j] if path is not None else last_owner[j])
            if o == word_run[i]:
                keep[i] = True
            elif o > word_run[i]:
                reason[i] = f"retake: redone later (take {o})"
            else:
                reason[i] = f"retake: earlier take is better (take {o})"
        elif word_type[i] == "preroll":
            reason[i] = "off-script: before first scripted line"
    restore_lost_lines(t_words, script, ms, runs, word_type, word_j, word_run, keep, reason)

    # insertions survive only inside a kept stretch of the same run
    for i in range(n):
        if word_type[i] != "insert":
            continue
        r = word_run[i]
        prev_k = next((k for k in range(i - 1, -1, -1) if word_type[k] == "match"), None)
        next_k = next((k for k in range(i + 1, n) if word_type[k] == "match"), None)
        ok = (prev_k is not None and next_k is not None and keep[prev_k] and keep[next_k]
              and word_run[prev_k] == r and word_run[next_k] == r)
        # an ad-lib is spoken in one go; a long silence inside the stretch means the take was
        # interrupted (call to prayer, crew, phone) and the words are background or phantom text
        pauses = ok and max(t_words[k + 1]["s"] - t_words[k]["e"] for k in range(prev_k, next_k)) > INTERRUPT_GAP
        keep[i] = ok and not pauses
        if pauses:
            reason[i] = "off-script: interruption inside a take (long silence around off-script words)"
        elif not ok:
            reason[i] = "off-script: false start / chatter between takes"

    # the spoken closing after the last script line (channel outro) stays when the episode says so
    outro = set()
    if keep_outro:
        kept_m = [i for i in range(n) if keep[i] and word_type[i] == "match"]
        # a lone, weak match after the last line ("أيوة" read as "يوم") is not the script going on
        def isolated(i):
            before = t_words[i]["s"] - t_words[i - 1]["e"] if i > 0 else 99
            after = t_words[i + 1]["s"] - t_words[i]["e"] if i + 1 < n else 99
            return before > STRAY_GAP or after > STRAY_GAP
        start = None
        while len(kept_m) > 1 and ms[kept_m[-1], word_j[kept_m[-1]]] < STRAY_SCORE and isolated(kept_m[-1]):
            keep[kept_m[-1]], reason[kept_m[-1]] = False, "off-script: stray word before the outro"
            start = start or kept_m[-1] + 1
            kept_m.pop()
        last = kept_m[-1] if kept_m else None
        if last is not None:
            outro = set(range(start or last + 1, n))
            for i in outro:
                keep[i], reason[i] = True, ""
            # one or two words after a pause at the very end ("سلام ... أيوة") are said off camera
            tail = n - 1
            while tail > 0 and t_words[tail]["s"] - t_words[tail - 1]["e"] <= STRAY_GAP:
                tail -= 1
            if tail in outro and n - tail <= 2:
                for i in range(tail, n):
                    keep[i], reason[i] = False, "off-script: after the sign-off"

    for sl in script.get("slots", []):    # the presenter's own words where the script leaves them a place
        keep_slot(t_words, keep, reason, word_type, word_j, script["sent_of_word"], sl["after"])
    if script.get("drink_auto") and not script.get("slots"):     # no placeholder: his «مشروب» lines found in what he said
        after = drink_after(t_words, keep, word_type, word_j, script["sent_of_word"])
        if after is not None:
            keep_slot(t_words, keep, reason, word_type, word_j, script["sent_of_word"], after)

    cut_self_repeats(t_words, keep, reason, word_type, word_j, frozenset(outro))

    decisions = [{"i": i, "keep": keep[i], "type": word_type[i], "run": word_run[i],
                  "j": word_j[i], "sent": script["sent_of_word"][word_j[i]] if word_j[i] >= 0 else None,
                  "score": float(ms[i, word_j[i]]) if word_j[i] >= 0 else None,
                  "reason": reason[i], "outro": i in outro} for i in range(n)]
    covered = set(word_j[i] for i in range(n) if keep[i] and word_j[i] >= 0)
    return {"decisions": decisions, "runs": runs, "covered_script_words": sorted(covered),
            "owner": [int(o) for o in owner], "rule": rule}

"""The code checks every draft passes before you see it (plan 4.3). Errors block approval; warnings go in the margin.

Per line:
  numbers     every digit number (with its scale word) matches a number of a card the line cites (statement, passage,
              quote); a line without cards may hold no number                                                  (error)
  commentary  a line without cards is commentary                                                     (set automatically)
  cards       every cited card exists and passed its own checks                                                 (error)
  copy        no run of 6+ words (normalised) matches any text read or any card passage; a quotation that is exactly a
              cited quote card's words is exempt                                                                (error)
  quotes      a quotation of 4+ words is a cited quote card's words, word for word; disputed attributions     (error / warning)
  legal       a legal card from a non-legal, non-official source is "secondary source only"                    (warning)
  types       a valid type; a news line cites a news or official card and has its newspaper headline; a numbers line
              cites a number or data card                                                                (error / warning)
  news        the newspaper headline's numbers are on the line's cards; the headline copies no source           (error)
  links       no web address in the spoken text                                                                 (error)
  characters  nothing outside Arabic and Latin letters, digits and punctuation (stray model tokens)            (error)
  repeats     a line mostly made of an earlier line's words (6-word runs)                       (error; an echoed phrase: warning)
  spelled     numbers written as words in a line without cards                                                (warning)
  relevance   a cited card that shares no content word with its line (it may not support it)                  (warning)
Whole script: length within ±10% of the target; material mix and runs (warnings); local-model lines (label).
"""
import re

from .common import MIX, S, TYPES
from .text import content_words, numbers, number_found, quoted_spans, runs, shared_run, spelled_numbers, word_count, contains, norm


def _source_runs(p, cs):
    pool = set()
    tdir = S(p, "research", "texts")
    if tdir.exists():
        for f in tdir.glob("*.txt"):
            pool |= runs(f.read_text(encoding="utf-8"))
    for c in cs.values():
        pool |= runs(c.get("passage", ""))
    return pool


def run(p, dr, cs, source_runs=None):
    src = source_runs if source_runs is not None else _source_runs(p, cs)
    lines = [x for x in dr["items"] if x["kind"] == "line"]
    res = {"lines": {}, "script": {}, "totals": {}}
    in_promo = False
    for x in dr["items"]:
        if x["kind"] == "promo_start":
            in_promo = True
        elif x["kind"] == "promo_end":
            in_promo = False
        elif x["kind"] == "line":
            x["promo"] = in_promo
    seen_runs = {}                         # 6-word runs of earlier lines: a line must not repeat another one
    for x in lines:
        probs = []

        def err(t):
            probs.append({"level": "error", "text": t})

        def warn(t):
            probs.append({"level": "warning", "text": t})
        text = x["text"]
        if x.get("promo"):
            x["type"] = "promo"
            res["lines"][x["id"]] = [{"level": "info", "text": "promo block: no source check"}]
            continue
        cited = [cs[c] for c in x.get("cards", []) if c in cs]
        for c in x.get("cards", []):
            if c not in cs:
                err(f"card {c} does not exist")
            elif cs[c]["status"] != "ok":
                err(f"card {c} was dropped by its own checks ({'; '.join(cs[c]['problems'])})")
        cited = [c for c in cited if c["status"] == "ok"]
        if not cited:
            x["commentary"] = True
        pool = []
        for c in cited:
            for f in ("statement", "passage", "quote_ar", "quote_original"):
                pool += numbers(c.get(f, ""))
        for n in numbers(text):
            if not cited:
                err(f"the number «{n['raw']}» is in a line with no card (commentary may hold no numbers)")
            elif not number_found(n, pool):
                err(f"the number «{n['raw']}» is not on any card this line cites")
        if not cited and spelled_numbers(text):
            warn(f"numbers written as words with no card: {'، '.join(spelled_numbers(text))} — check they are not facts")
        quotes = [c for c in cited if c["kind"] == "quote"]
        check_text = text
        for q in quoted_spans(text):
            exact = [c for c in quotes if norm(q) in (norm(c["quote_ar"]), norm(c["quote_original"]))]
            if exact:
                check_text = check_text.replace(q, " ")
                for c in exact:
                    if c.get("disputed"):
                        warn(f"the quote's attribution is disputed ({c['speaker']}): {c.get('note') or 'see the card'}")
            elif len(q.split()) >= 4:
                partial = [c for c in quotes if contains(c["quote_ar"], q) or contains(c["quote_original"], q)]
                if partial:
                    check_text = check_text.replace(q, " ")
                    warn("the quotation is part of a quote card, not the whole quote: check it keeps the meaning")
                else:
                    err(f"«{q[:60]}» is in quotation marks but is not a cited quote card's words")
        hit = shared_run(check_text, src)
        if hit:
            err(f"copies a source: «{hit}» (6+ words match a text that was read)")
        mine = runs(check_text)
        again = [r for r in mine if r in seen_runs]
        if again and len(again) >= 0.5 * len(mine):
            err(f"repeats line {seen_runs[again[0]]}: «{again[0]}»")
        elif again:                            # a phrase echoed on purpose (a callback) is allowed, but shown
            warn(f"echoes line {seen_runs[again[0]]}: «{again[0]}» (a deliberate callback?)")
        for r in runs(check_text):
            seen_runs.setdefault(r, x["id"])
        for c in cited:
            if not content_words(text) & content_words(c["statement"] + " " + c.get("quote_ar", "")):
                warn(f"card {c['id']} shares no words with this line: does it really support it?")
            if c["kind"] == "legal" and c["source_kind"] not in ("legal", "official"):
                warn(f"legal point {c['id']} rests on a secondary source only ({c['outlet']})")
            for fl in c.get("flags", []):          # a card's note shows on a line only when that line uses the number it is about
                m = re.search(r"«([^»]+)»", fl)
                if not m or any(number_found(n, numbers(m.group(1))) for n in numbers(text)):
                    warn(f"{c['id']}: {fl}")
        t = x.get("type")
        if t not in TYPES:
            err(f"unknown material type «{t}»")
        if t == "news":
            if not any(c["source_kind"] in ("news", "official") for c in cited):
                err("a documented-news line must cite a news or official card")
            nw = x.get("news") or {}
            if not nw.get("headline"):
                err("a documented-news line needs its newspaper headline (news.headline)")
            else:
                for n in numbers(nw["headline"] + " " + nw.get("context", "")):
                    if not number_found(n, pool):
                        err(f"the newspaper headline's number «{n['raw']}» is not on the line's cards")
                h = shared_run(nw["headline"] + " " + nw.get("context", ""), src)
                if h:
                    err(f"the newspaper headline copies a source: «{h}»")
        if t == "numbers" and not any(c["kind"] == "number" or c["source_kind"] == "data" for c in cited):
            warn("a numbers line without a number or data card: is a chart possible?")
        if re.search(r"https?://|www\.", text):
            err("a web address in the spoken text")
        odd = re.findall(r"[^\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF\u0020-\u024F\u2010-\u206F«»٪٫٬…⟦⟧]", text)
        if odd:                                # a model can emit stray tokens from another script (seen: «攀»)
            err(f"characters that are not Arabic or Latin: {''.join(sorted(set(odd)))}")
        if x.get("made_by", "").startswith("local:") or x.get("revised_by", "").startswith("local:"):
            probs.append({"level": "label", "text": "written by the FREE LOCAL MODEL (lower quality): read it closely"})
        res["lines"][x["id"]] = probs
    spoken = [x for x in lines if not x.get("promo")]
    total_words = sum(word_count(x["text"]) for x in spoken)
    n = max(len(spoken), 1)
    share = {k: round(sum(1 for x in spoken if x["type"] == k) / n, 3) for k in TYPES}
    sw = []
    if abs(total_words - dr["target_words"]) > 0.10 * dr["target_words"]:
        sw.append(f"length {total_words} words is outside ±10% of the target {dr['target_words']}")
    if share["archive"] < MIX["archive_min"]:
        sw.append(f"archive {share['archive']:.0%} of lines (target at least {MIX['archive_min']:.0%})")
    if share["news"] < MIX["news_min"]:
        sw.append(f"documented news {share['news']:.0%} of lines (target at least {MIX['news_min']:.0%})")
    if share["stock"] > MIX["stock_max"]:
        sw.append(f"stock {share['stock']:.0%} of lines (target at most {MIX['stock_max']:.0%})")
    run_t, run_n, worst = None, 0, (0, None, None)
    for x in spoken:
        run_n = run_n + 1 if x["type"] == run_t else 1
        run_t = x["type"]
        if run_n > worst[0]:
            worst = (run_n, run_t, x["id"])
    if worst[0] > MIX["run_max"]:
        sw.append(f"{worst[0]} {TYPES.get(worst[1], worst[1])} lines in a row (up to {worst[2]}; at most {MIX['run_max']})")
    local = sum(1 for x in spoken if x.get("made_by", "").startswith("local:"))
    res["script"] = {"words": total_words, "target_words": dr["target_words"], "lines": len(spoken), "mix": share,
                     "longest_run": {"n": worst[0], "type": worst[1], "until": worst[2]}, "warnings": sw,
                     "commentary_lines": sum(1 for x in spoken if x["commentary"]), "local_lines": local,
                     "cards_cited": len({c for x in spoken for c in x.get("cards", [])})}
    res["totals"] = {"errors": sum(1 for v in res["lines"].values() for pr in v if pr["level"] == "error"),
                     "warnings": sum(1 for v in res["lines"].values() for pr in v if pr["level"] == "warning") + len(sw),
                     "lines_with_errors": sum(1 for v in res["lines"].values() if any(pr["level"] == "error" for pr in v))}
    res["checked"] = {"numbers_checked": sum(len(numbers(x["text"])) for x in spoken),
                      "quotations_checked": sum(len(quoted_spans(x["text"])) for x in spoken), "source_word_runs": len(src)}
    return res


def report_md(res, dr):
    s = res["script"]
    L = [f"# Checks — draft v{dr['version']}", "",
         f"- Errors: **{res['totals']['errors']}** (in {res['totals']['lines_with_errors']} lines) · warnings: {res['totals']['warnings']}",
         f"- Words: {s['words']} (target {s['target_words']}) · lines: {s['lines']} · commentary lines: {s['commentary_lines']} · "
         f"cards cited: {s['cards_cited']} · lines by the local model: {s['local_lines']}",
         f"- Numbers checked: {res['checked']['numbers_checked']} · quotations checked: {res['checked']['quotations_checked']} · "
         f"6-word runs of source text compared: {res['checked']['source_word_runs']}",
         "- Mix: " + ", ".join(f"{TYPES[k]} {v:.0%}" for k, v in s["mix"].items()), ""]
    if s["warnings"]:
        L += ["## Whole script", ""] + [f"- ⚠ {w}" for w in s["warnings"]] + [""]
    L += ["## Lines", ""]
    for x in dr["items"]:
        if x["kind"] != "line":
            continue
        pr = [q for q in res["lines"].get(x["id"], []) if q["level"] != "info"]
        if pr:
            L.append(f"- **{x['id']}** ({TYPES.get(x['type'], x['type'])}): {x['text'][:90]}…")
            L += [f"  - {'❌' if q['level'] == 'error' else ('🤖' if q['level'] == 'label' else '⚠')} {q['text']}" for q in pr]
    return "\n".join(L) + "\n"

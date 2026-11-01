"""Steps queries* -> gather -> select* -> read -> facts* (* = the brain decides; everything else is code).

Every brain request here is self-contained (instructions + inline inputs + answer_schema), so Claude Code, a paid API
brain later, or the free local model can answer the same request unchanged.
"""
import json
import re
from pathlib import Path

from ..core import brain
from ..core.brain import NeedsDecision
from ..core.io import load_json, save_json, write_text
from . import extract, fetch, sources
from .common import S, channel_dir, now, topic
from .text import norm_date, has_year, contains, numbers, number_found, runs, shared_run, words


LOCAL_TEXT_WORDS = 1500          # a fact-card request on a text this long or shorter counts as small (report decision 1a)
LOCAL_MAX_CHARS = 16000          # and no request whose inputs are longer (about 5 000 tokens: the local model slows sharply)


def request(what, instructions, inputs, schema, max_tokens=4000, local_ok=False):
    """local_ok: a small request (by kind AND by size) that the free local model may take over when the paid brain
    fails (report decision 1a); everything else stops the run with a clear message"""
    small = local_ok and len(json.dumps(inputs, ensure_ascii=False)) <= LOCAL_MAX_CHARS
    return {"what": what, "instructions": instructions, "inputs": inputs, "answer_schema": schema,
            "local_max_tokens": max_tokens, "local_ok": small,
            "answer_note": "Write the decision as JSON matching answer_schema; store it with  bin/monteer brain answer <project> <step> <key> <file>"}


def ask_all(p, asks):
    """ask several decisions at once: one stop for a person in a Claude Code session (all requests written together),
    a few at a time for the background brain (project option "brain_parallel", default 3), one after another for the
    local model. asks: [(step, key, request)] -> {key: decision}"""
    out, waiting = {}, []
    if brain.brain_name(p) == "claude-bg" and len(asks) > 1:
        from concurrent.futures import ThreadPoolExecutor
        todo = [(s, k, r) for s, k, r in asks if brain.existing(p, s, k, r) is None]
        for s, k, r in asks:
            if (s, k, r) not in todo:
                out[k] = brain.existing(p, s, k, r)["decision"]
        with ThreadPoolExecutor(max_workers=int(p.opt("brain_parallel", 3))) as ex:
            futs = {ex.submit(brain.decide, p, s, k, r): k for s, k, r in todo}
            for f, k in futs.items():
                out[k] = f.result()
        return out
    for step, key, req in asks:
        try:
            out[key] = brain.decide(p, step, key, req)
        except NeedsDecision as e:
            waiting += e.items
    if waiting:
        raise NeedsDecision(waiting)
    return out


# ------------------------------------------------------------------------------------------------ queries*
QUERIES_SCHEMA = {
    "type": "object", "required": ["news_terms", "since_days", "wikipedia", "data", "legal"],
    "properties": {
        "news_terms": {"type": "object", "properties": {"ar": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
                                                         "en": {"type": "array", "items": {"type": "string"}, "maxItems": 6}},
                       "required": ["ar", "en"]},
        "since_days": {"type": "integer", "minimum": 1, "maximum": 90},
        "wikipedia": {"type": "array", "maxItems": 6, "items": {"type": "object", "required": ["lang", "title"],
                                                                  "properties": {"lang": {"type": "string", "enum": ["en", "ar"]},
                                                                                 "title": {"type": "string"}}}},
        "data": {"type": "array", "maxItems": 6, "items": {"type": "object", "required": ["source", "request", "why"],
                                                             "properties": {"source": {"type": "string", "enum": list(sources.DATA_ADAPTERS)},
                                                                            "request": {"type": "object"}, "why": {"type": "string"}}}},
        "legal": {"type": "array", "maxItems": 4, "items": {"type": "object", "required": ["term"],
                                                              "properties": {"term": {"type": "string"}, "since": {"type": "string"}}}}}}

DATA_HELP = {
    "worldbank": 'World Bank indicators: {"indicator": "NY.GDP.MKTP.KD.ZG", "country": "EG" (ISO2/ISO3 or WLD), "years": "2015:2025" (optional), '
                 '"source": 15 or 22 (optional)}. source 15 = Global Economic Monitor, MONTHLY: TOTRESV (total reserves, USD millions), '
                 'DPANUSLCU (official exchange rate); source 22 = Quarterly External Debt Statistics, the figures the central bank '
                 'reports: DT.DOD.DECT.CD.AR.EN.US (gross external debt position, end of period, USD), and the "Gross Ext. Debt Pmt" '
                 'series (payments due by horizon) for repayment schedules. Use these for Egypt\'s reserves, external debt and what '
                 'falls due (the central bank\'s own site refuses us; CEIC is off for good)',
    "treasury": 'US Treasury Fiscal Data: {"endpoint": "v2/accounting/od/debt_to_penny" | "v2/accounting/od/avg_interest_rates" | '
                '"v1/accounting/mts/mts_table_5" ..., "rows": 12, "fields": "record_date,tot_pub_debt_out_amt" (optional), "filter": "..." (optional)}',
    "ecb": 'ECB Data Portal: {"flow": "FM", "key": "B.U2.EUR.4F.KR.DFR.LEV" (deposit facility rate), "last": 12}; '
           'other examples: "EXR" / "D.USD.EUR.SP00.A" (dollar-euro), "ICP" / "M.U2.N.000000.4.ANR" (euro-area inflation)',
    "eurostat": 'Eurostat: {"dataset": "prc_hicp_manr", "filters": {"geo": "EA", "coicop": "CP00"}, "last": 12}',
    "bls": 'US BLS: {"series": "CUUR0000SA0"} (consumer prices); "LNS14000000" (unemployment rate)'}


def step_queries(p):
    t = topic(p)
    srcs = [s for s in sources.load(channel_dir(p)) if s.get("on") and picked(p, s)]
    inputs = {"topic": t["topic"], "angle": t.get("angle", ""), "today": t["today"],
              "outlets_on_the_list": sorted({f"{s['name']} ({s['lang']}, {s['kind']})" for s in srcs if s["kind"] in ("news", "official")}),
              "data_sources": {s["access"]: DATA_HELP[s["access"]] for s in srcs if s["access"] in DATA_HELP},
              "legal_search": "Federal Register (US rules, executive orders, tariffs)" if any(s["access"] == "federal_register" for s in srcs) else "none"}
    instructions = (
        "You plan the research for one episode of an Arabic YouTube channel about economics, money and geopolitics "
        "(Egyptian-Arabic narration, long-form explainers). Choose what to search for. Rules:\n"
        "- news_terms: short search phrases (1-3 words each) in Arabic and English that headlines about this topic would use. "
        "They are matched against outlet feeds and the GDELT news index (last since_days days).\n"
        "- wikipedia: pages whose REFERENCES may lead to citable sources for background and history (Wikipedia itself is never "
        "cited). Use exact page titles.\n"
        "- data: official data series that give the episode's key numbers. Use only the request shapes in inputs.data_sources; "
        "use codes you are sure exist.\n"
        "- legal: Federal Register search terms, only if a US rule, order or tariff matters to the topic.\n"
        "Answer with JSON only.")
    d = brain.decide(p, "script", "queries", request("search plan for the topic", instructions, inputs, QUERIES_SCHEMA, 1500, local_ok=True))
    save_json(S(p, "research", "queries.json"), d)


# ------------------------------------------------------------------------------------------------ gather
def _store_text(p, item, text):
    tdir = S(p, "research", "texts")
    write_text(tdir / f"{item['id']}.txt", text)
    save_json(tdir / f"{item['id']}.json", {k: item.get(k) for k in ("id", "kind", "source_id", "outlet", "title", "date", "url", "lang")}
              | {"fetched_at": now(), "brain_allowed": True, "words": len(text.split())})


def picked(p, s):
    """the sources the owner picked for this script in the panel (topic.json "sources"); no list = every source on"""
    t = S(p, "topic.json")
    ids = load_json(t).get("sources") if t.exists() else None
    return not ids or s["id"] in ids


def gather(p, plan, items, log=print, round_no=1):
    ch = channel_dir(p)
    srcs = sources.load(ch)
    on = [s for s in srcs if s.get("on") and picked(p, s)]
    seen = {i["url"] for i in items if i.get("url")}
    notes = []

    def add(it, prefix):
        """True when the item is new (an address already found is not added twice)"""
        if it.get("url") and it["url"] in seen:
            return False
        n = sum(1 for i in items if i["id"].startswith(prefix)) + 1
        it["id"] = f"{prefix}{n:03d}"
        it["round"] = round_no
        items.append(it)
        if it.get("url"):
            seen.add(it["url"])
        return True

    terms = plan.get("news_terms", {})
    all_terms = [x for v in terms.values() for x in v]
    for s in on:
        if s["access"] == "rss":
            got, note = sources.rss_items(s, all_terms)
            for it in got:
                add(it, "N" if it["kind"] == "news" else "O")
            notes.append(f"{s['id']}: {note}")
        elif s["access"] == "gdelt" and terms:
            got, note = sources.gdelt_items(s, terms, plan.get("since_days", 30), srcs)
            for it in got:
                add(it, "N" if it["kind"] == "news" else "O")
            notes.append(f"gdelt: {note}")
    wp = next((s for s in on if s["access"] == "wikipedia"), None)
    wd = next((s for s in on if s["access"] == "wikidata"), None)
    for lead in plan.get("wikipedia", []) if wp else []:
        got, qid, note = sources.wikipedia_leads(wp, lead, srcs)
        for it in got:
            add(it, "R")
        notes.append(f"wikipedia: {note}")
        if wd and qid:
            text, url, note = sources.wikidata_text(qid)
            notes.append(f"wikidata: {note}")
            if text:
                it = {"kind": "reference", "source_id": "wikidata", "outlet": wd["name"], "title": f"Wikidata {qid} ({lead['title']})",
                      "date": "", "url": url, "lang": "multi", "summary": "", "lead_only": False, "how": "Wikidata (CC0)", "has_text": True}
                if add(it, "W"):
                    _store_text(p, it, text)
    for dq in plan.get("data", []):
        s = next((x for x in on if x["access"] == dq["source"]), None)
        if not s:
            notes.append(f"data {dq['source']}: source off or unknown")
            continue
        try:
            text, url, note = sources.DATA_ADAPTERS[dq["source"]](dq["request"])
        except Exception as e:  # noqa: BLE001  (a wrong series code from the brain: logged, not fatal)
            text, url, note = None, "", f"{type(e).__name__}: {e}"
        notes.append(f"data {dq['source']} {json.dumps(dq['request'], ensure_ascii=False)}: {note}")
        if text:
            first, last = sources.data_period(text)
            it = {"kind": "data", "source_id": s["id"], "outlet": s["name"], "title": text.splitlines()[0], "date": last or "",
                  "period": (f"{first}–{last}" if first != last else last) if last else "", "fetched_at": now(),
                  "url": url, "lang": "en", "summary": "", "lead_only": False, "how": f"data API ({dq.get('why', '')})",
                  "has_text": True, "data_request": dq}
            if add(it, "D"):
                _store_text(p, it, text)
    fr = next((s for s in on if s["access"] == "federal_register"), None)
    for lq in plan.get("legal", []) if fr else []:
        got, note = sources.federal_register(fr, lq["term"], lq.get("since") or None)
        for it in got:
            add(it, "L")
        notes.append(f"federal_register: {note}")
    for n in notes:
        log(n)
    return notes


def step_gather(p):
    plan = load_json(S(p, "research", "queries.json"))
    items = []
    notes = gather(p, plan, items)
    save_json(S(p, "research", "items.json"), {"items": items, "notes": {"round 1": notes}, "gathered_at": now()})
    print(f"gathered {len(items)} items: " + ", ".join(f"{k} {sum(1 for i in items if i['id'][0] == k)}" for k in "NOLRDW"))


# ------------------------------------------------------------------------------------------------ select*
SELECT_SCHEMA = {"type": "object", "required": ["read", "notes"],
                 "properties": {"read": {"type": "array", "items": {"type": "string"}, "maxItems": 30},
                                "more": {"type": "object", "properties": {
                                    "news_terms": {"type": "object", "properties": {"ar": {"type": "array", "items": {"type": "string"}},
                                                                                   "en": {"type": "array", "items": {"type": "string"}}}},
                                    "wikipedia": QUERIES_SCHEMA["properties"]["wikipedia"]}},
                                "notes": {"type": "string"}}}


def _brief(i):
    b = {"id": i["id"], "kind": i["kind"], "outlet": i["outlet"], "date": i.get("date", ""), "title": i["title"][:300]}
    if i.get("summary"):
        b["summary"] = i["summary"][:300]
    if i.get("lead_only"):
        b["lead_only"] = True
    if i.get("off_list"):
        b["from_wikipedia_references"] = True
    return b


def step_select(p):
    t = topic(p)
    store = load_json(S(p, "research", "items.json"))
    items = store["items"]
    instructions = (
        "Choose which found items to READ for an episode on the topic. Prefer: primary sources (official statements, data, "
        "legal texts), recent reporting by different outlets, and references that support the history the episode needs. "
        "Choose 8-25 items. Items marked lead_only may NOT be chosen (their text may not be read): use their headline only "
        "as a hint, and add search terms in 'more' to find the same fact in an allowed outlet. Items with "
        "has_text are already stored (data, Wikidata) and are always used: do not list them. If important angles are missing, "
        "add 'more' (new news_terms and/or wikipedia pages); otherwise leave 'more' empty. Answer with JSON only.")
    chosen = []
    for rnd in (1, 2):
        inputs = {"topic": t["topic"], "angle": t.get("angle", ""), "today": t["today"],
                  "items": [_brief(i) for i in items if not i.get("has_text") and i["id"] not in chosen]}
        d = brain.decide(p, "script", f"select_{rnd}", request(f"which items to read (round {rnd})", instructions, inputs, SELECT_SCHEMA, 1500,
                                                                           local_ok=True))
        ids = {i["id"]: i for i in items}
        for x in d.get("read", []):
            if x in ids and not ids[x].get("lead_only") and x not in chosen:
                chosen.append(x)
        more = d.get("more") or {}
        if rnd == 2 or not (more.get("news_terms") or more.get("wikipedia")):
            break
        plan = {"news_terms": more.get("news_terms", {}), "wikipedia": more.get("wikipedia", []),
                "since_days": load_json(S(p, "research", "queries.json")).get("since_days", 30)}
        store["notes"]["round 2"] = gather(p, plan, items, round_no=2)
        save_json(S(p, "research", "items.json"), store)
    save_json(S(p, "research", "selected.json"), {"read": chosen, "at": now()})
    print(f"selected {len(chosen)} items to read")


# ------------------------------------------------------------------------------------------------ read
def same_text(tdir, x, it):
    """a stored text is reused only for the SAME page: item numbers are given afresh by every search round, so a text kept
    under R022 may belong to another page (found 16 Oct 2026: cards carried an earlier R022's text and outlet under a new
    R022's address)"""
    j = tdir / f"{x}.json"
    return (tdir / f"{x}.txt").exists() and j.exists() and load_json(j).get("url") == it.get("url") and not fetch.held(it.get("url", ""))


def step_read(p):
    store = load_json(S(p, "research", "items.json"))
    ids = {i["id"]: i for i in store["items"]}
    sel = load_json(S(p, "research", "selected.json"))["read"]
    report = []
    for x in sel:
        it = ids[x]
        tdir = S(p, "research", "texts")
        if same_text(tdir, x, it):
            report.append({"id": x, "result": "read (kept)"})
            continue
        if fetch.held(it.get("url", "")):            # a site the owner has ruled out (CEIC)
            report.append({"id": x, "result": "not read", "why": fetch.held(it["url"])})
            continue
        r = fetch.get(it["url"])
        if not r["fetch"] or not r["brain"]:
            report.append({"id": x, "result": "not read", "why": r["why"]})
            continue
        if not r["ok"]:
            report.append({"id": x, "result": "not read", "why": f"HTTP {r.get('code')} {r.get('error') or ''}"})
            continue
        if "pdf" in r.get("content_type", "").lower():
            report.append({"id": x, "result": "not read", "why": "a PDF (not read by this version)"})
            continue
        a = extract.article(r["body"], r.get("final_url", it["url"]))
        if not a["ok"]:
            report.append({"id": x, "result": "not read", "why": a["why"]})
            continue
        # what the page itself says (outlet for references, its own date and title) goes beside the text, never into
        # items.json: that is the select step's input, and changing it would make the brain choose again
        seen = dict(it, outlet=it["outlet"] if it.get("source_id") not in (None, "wikipedia_ref") else (a["outlet"] or it["outlet"]),
                    date=a["date"] or it.get("date", ""), title=a["title"] or it["title"])
        _store_text(p, seen, a["text"])
        report.append({"id": x, "result": "read", "words": a["words"], "date": seen["date"]})
    save_json(S(p, "research", "read.json"), report)
    ok = sum(1 for r in report if r["result"].startswith("read"))
    print(f"read {ok} of {len(sel)}; not read: " + "; ".join(f"{r['id']}: {r['why']}" for r in report if r["result"] == "not read"))


# ------------------------------------------------------------------------------------------------ facts*
FACTS_SCHEMA = {"type": "object", "required": ["cards"], "properties": {"cards": {"type": "array", "maxItems": 14, "items": {
    "type": "object", "required": ["kind", "statement", "passage"],
    "properties": {"kind": {"type": "string", "enum": ["fact", "number", "legal", "quote"]},
                   "statement": {"type": "string"}, "passage": {"type": "string"}, "event_date": {"type": "string"},
                   "speaker": {"type": "string"}, "quote_original": {"type": "string"}, "quote_ar": {"type": "string"},
                   "disputed": {"type": "boolean"}, "note": {"type": "string"}}}}}}

FACTS_INSTRUCTIONS = (
    "Turn the source text into FACT CARDS for an Arabic explainer episode on the topic. Only facts relevant to the topic; "
    "at most 14 cards; none if the text is not relevant. For each card:\n"
    "- statement: the fact in ARABIC, in YOUR OWN WORDS (Modern Standard Arabic, short). Never copy or translate a sentence "
    "word for word: no run of 6 words may match the source. Keep every number exactly as the source gives it (digits, "
    "with its unit and scale word: «1.25 تريليون دولار»), and say whose claim it is when it is a claim.\n"
    "- passage: an EXACT copy (character for character, in the source's language) of the 1-2 sentences in the text "
    "that prove the statement; every number in the statement must appear in the passage.\n"
    "- kind: number (the point is a number), legal (a law, rule, court or treaty point), quote (someone's exact words), "
    "fact (anything else).\n"
    "- event_date: when it happened (YYYY, YYYY-MM or YYYY-MM-DD) if the text says.\n"
    "- For quotes: speaker; quote_original = the exact quoted words (inside the passage); quote_ar = a faithful Arabic "
    "rendering (the same words if the source is Arabic); at most two sentences; disputed = true if the attribution is "
    "doubtful or contested, with a note.\n"
    "Never add anything the text does not say. Answer with JSON only.")


def step_facts(p):
    t = topic(p)
    store = load_json(S(p, "research", "items.json"))
    tdir = S(p, "research", "texts")
    texts = [(dict(i, **{k: v for k, v in load_json(tdir / f"{i['id']}.json").items() if k in ("outlet", "date", "title", "fetched_at") and v}),
              (tdir / f"{i['id']}.txt").read_text(encoding="utf-8")) for i in store["items"] if same_text(tdir, i["id"], i)]
    asks = []
    for it, text in texts:
        w = text.split()
        body = " ".join(w[:6000]) + (" [...]" if len(w) > 6000 else "")
        inputs = {"topic": t["topic"], "today": t["today"],
                  "source": {"outlet": it["outlet"], "kind": it["kind"], "title": it["title"][:300], "date": it.get("date", ""),
                             "language": it.get("lang", "")}, "text": body}
        asks.append(("script", f"facts_{it['id']}", request(f"fact cards from {it['id']} ({it['outlet']})", FACTS_INSTRUCTIONS,
                                                            inputs, FACTS_SCHEMA, 3000, local_ok=len(w) <= LOCAL_TEXT_WORDS)))
    answers = ask_all(p, asks)
    cards = []
    for it, text in texts:
        d = answers[f"facts_{it['id']}"]
        rec = brain.record(p, "script", f"facts_{it['id']}") or {}
        src_runs = runs(text)
        for c in d.get("cards", []):
            card = verify_card(c, it, text, src_runs)
            card["id"] = f"C{len(cards) + 1:03d}"
            card["made_by"] = rec.get("made_by", "")
            cards.append(card)
    save_json(S(p, "facts.json"), {"cards": cards, "made_at": now()})
    ok = [c for c in cards if c["status"] == "ok"]
    print(f"fact cards: {len(ok)} kept, {len(cards) - len(ok)} dropped by the checks")
    for c in cards:
        if c["status"] != "ok":
            print(f"   dropped {c['id']} ({c['item_id']}): {'; '.join(c['problems'])}")


def verify_card(c, it, text, src_runs):
    """the code checks every card must pass: its passage is in the stored text, its numbers are in the passage, its
    wording is our own (no 6-word run from the source), a quote is inside its passage"""
    card = {"item_id": it["id"], "source_id": it.get("source_id"), "source_kind": it["kind"], "outlet": it["outlet"],
            "title": it["title"], "url": it.get("url", ""), "pub_date": norm_date(it.get("date", "")), "fetched_at": it.get("fetched_at", ""),
            "kind": c["kind"], "statement": c["statement"].strip(), "passage": c["passage"].strip(),
            "event_date": c.get("event_date", ""), "speaker": c.get("speaker", ""), "quote_original": c.get("quote_original", ""),
            "quote_ar": c.get("quote_ar", ""), "disputed": bool(c.get("disputed")), "note": c.get("note", ""),
            "problems": [], "flags": []}
    if not contains(text, card["passage"]):
        card["problems"].append("the passage is not word-for-word in the source text")
    # must-do g: a card's date always carries a year. A number with no dated page is dated by its data's own period
    # (report decision 5a); a card with neither is dropped
    if card["source_kind"] != "data" and not has_year(card["pub_date"]):
        if card["kind"] == "number" and has_year(card["event_date"]):
            card["period"] = card["event_date"]
        else:
            card["problems"].append("no date with a year (the page gives none): a card's date must carry a year")
    pn = numbers(card["passage"])
    for n in numbers(card["statement"]):
        if not number_found(n, pn):
            card["problems"].append(f"the number «{n['raw']}» is not in the passage")
        elif not any(abs(n["value"] - m["value"]) < 1e-9 for m in pn):
            card["flags"].append(f"«{n['raw']}» matches the passage only after rounding or converting the scale: check")
    hit = shared_run(card["statement"], src_runs)
    if hit:
        card["problems"].append(f"the statement copies the source («{hit}»)")
    if card["kind"] == "quote":
        if not card["quote_original"] or not contains(card["passage"], card["quote_original"]):
            card["problems"].append("the quote's original words are not in the passage")
        if not card["quote_ar"]:
            card["problems"].append("no Arabic rendering of the quote")
        if len(re.findall(r"[.!?؟]", card["quote_original"].strip().rstrip(".!?؟"))) >= 2 or len(words(card["quote_original"])) > 60:
            card["problems"].append("the quote is longer than two sentences")
        if card["disputed"]:
            card["flags"].append("the attribution is disputed: " + (card["note"] or "see the source"))
    if it["kind"] == "data":                   # report decision 5a: a data card is dated by the period its numbers cover
        first, last = sources.data_period(text)
        series = (f"{first}–{last}" if first != last else last) if last else ""
        card["period"] = card["event_date"] or series
        card["series_period"] = series
    if it["kind"] == "reference" and it.get("source_id") == "wikipedia":
        card["problems"].append("Wikipedia is a lead only, never a cited source")
    card["status"] = "dropped" if card["problems"] else "ok"
    return card

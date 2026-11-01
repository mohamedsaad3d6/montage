"""Storyblocks stock videos through Storyblocks' official MCP connector (the owner's S3 of 20 Oct 2026; the company's
Business subscription, connected and signed in on this Mac's Claude account), for the channels that turn it on
("montage.sources.storyblocks": true in channel.json: الحدث الأخير and اقتصاد احمس). Storyblocks' terms allow a connected
AI agent through their own connector only, and forbid scripted mass downloads: so only the clips a plan picks are
downloaded, at most CAP_PER_EPISODE an episode.

  How the engine reaches it: a background Claude Code (`claude -p`) with NO built-in tool but ToolSearch (to load the
  one connector tool), every other request denied (--permission-prompts none) and only ONE Storyblocks tool allowed:
    search  (search_many)  only mcp__claude_ai_Storyblocks__search_videos: one call per query; the results are read by
            the engine from the tool's own replies in the run's transcript (stream-json), never retyped by Claude.
    download (fetch_many)  only mcp__claude_ai_Storyblocks__get_download_url, for the exact ids the plan picked (every
            call licenses the clip and records a download on the account); the transcript is checked: a call for any
            other id, or a second call for one, is said in the log (AUDIT).
  The file: the smallest HD MP4 (1080p, else 720p), never the 4K master; a format over MAX_MB is never asked for, and
  the download itself stops at MAX_MB. Licence record «Storyblocks Business licence» (the one licence gate lets it in);
  credits record: title, page. Use log DATA/usage/storyblocks.jsonl -> «التكاليف».
  Searches are cached 24 h; nothing personal is sent (Storyblocks gets its own connection's ids, never ours).
"""
import hashlib
import json
import os
import re
import subprocess
import threading
import time

from ...core.io import load_json, save_json
from ...core.paths import CACHE, DATA
from . import UA, download, set_aside, video_ok

SERVER = "mcp__claude_ai_Storyblocks__"
SEARCH_TOOL, DOWNLOAD_TOOL = SERVER + "search_videos", SERVER + "get_download_url"
CLAUDE = os.path.expanduser("~/.local/bin/claude")
USAGE = DATA / "usage" / "storyblocks.jsonl"
CACHE_DIR = CACHE / "stock_search"
DAY = 24 * 3600
MAX_MB = 150
CAP_PER_EPISODE = 90             # owner's answer 1c of 22 Oct 2026 (was 60): all the episode's versions together
PER_CALL = 12                 # queries asked in one background run
RUNS_AT_ONCE = 3              # background search runs at the same time
TIMEOUT = 15 * 60
LICENCE = "Storyblocks Business licence (the company's subscription, via the official Storyblocks MCP)"
_lock = threading.Lock()


def on(p):
    """the channel turned Storyblocks on (the connector itself is checked by its first search)"""
    from . import mode
    if mode(p) == "free":              # «المصادر» of this episode: free only
        return False
    if not getattr(p, "profile", None):
        return False
    try:
        return bool((p.profile_montage().get("sources") or {}).get("storyblocks"))
    except Exception:  # noqa: BLE001
        return False


def note(what, **kw):
    USAGE.parent.mkdir(parents=True, exist_ok=True)
    with _lock, open(USAGE, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(at=time.strftime("%Y-%m-%d %H:%M:%S"), what=what, **kw), ensure_ascii=False) + "\n")


def usage():
    out = []
    if USAGE.exists():
        for ln in USAGE.read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(ln))
            except ValueError:
                continue
    return out


# ---------------------------------------------------------------------------------------------------- the background run
NO_CALL_TRIES = 3             # a run that made no real call of its tool is run again at once (nothing was asked of the service)


def run_claude(prompt, tool, cwd, log=print, timeout=None):
    """a background Claude Code run allowed exactly one connector tool -> [(input, result text)] for that tool's calls, read
    from the run's own transcript; plus the run's status. A run that made NO real call of the tool (it wrote its calls out
    as text, 21 Oct 2026) asked nothing of the service: it is run again at once, up to NO_CALL_TRIES runs in all."""
    for k in range(NO_CALL_TRIES):
        calls, st = _run_once(prompt, tool, cwd, log, timeout or TIMEOUT)
        st["runs"] = k + 1
        if calls:
            return calls, st
        if k < NO_CALL_TRIES - 1:
            log(f"storyblocks: a background run made no real call of {tool.rsplit('__', 1)[-1]}"
                + (f" (it wrote {st['calls_as_text']} out as text)" if st["calls_as_text"] else "") + "; run again at once")
    return calls, st


def _run_once(prompt, tool, cwd, log, timeout):
    # the request goes in on stdin, as the main brain's: given as an argument with no stdin (as the panel starts an episode),
    # the run wrote its tool calls out as text instead of making them (3 of 3 runs, measured 21 Oct 2026)
    cmd = [CLAUDE, "-p", "--restricted", "--tools", "ToolSearch", "--permission-prompts", "none", "--allowedTools", tool,
           "--model", "sonnet", "--output-format", "stream-json", "--verbose"]
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)           # the device owner's subscription, never a stray paid key
    os.makedirs(cwd, exist_ok=True)
    t0 = time.time()
    try:
        r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=timeout, cwd=str(cwd), env=env)
        out = r.stdout
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        log(f"storyblocks: the background run took over {timeout / 60:g} min; what it answered is used")
    calls, results, status, other, as_text = {}, {}, "?", [], 0
    for ln in out.splitlines():
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if d.get("type") == "assistant":
            for c in d["message"].get("content", []):
                if c.get("type") == "text":
                    as_text += (c.get("text") or "").count("<invoke")
                if c.get("type") == "tool_use":
                    if c["name"] == tool:
                        calls[c["id"]] = c.get("input") or {}
                    elif c["name"] != "ToolSearch":
                        other.append(c["name"])
        elif d.get("type") == "user":
            for c in d["message"].get("content", []) if isinstance(d["message"].get("content"), list) else []:
                if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in calls:
                    cont = c.get("content")
                    txt = cont if isinstance(cont, str) else "".join(x.get("text", "") for x in cont or [] if isinstance(x, dict))
                    results[c["tool_use_id"]] = (txt, bool(c.get("is_error")))
        elif d.get("type") == "result":
            status = d.get("subtype", "?")
    if other:
        log(f"storyblocks AUDIT: the background run tried other tools (denied): {sorted(set(other))}")
    return [(calls[k], *results.get(k, ("", True))) for k in calls], {"status": status, "seconds": round(time.time() - t0, 1),
                                                                         "other_tools": sorted(set(other)), "calls": len(calls),
                                                                         "calls_as_text": as_text}


# ---------------------------------------------------------------------------------------------------- search
def _cache_file(q):
    return CACHE_DIR / f"storyblocks_{hashlib.sha256(q.lower().encode()).hexdigest()[:20]}.json"


def cached(q):
    """this query's clips from a search of the last 24 h, or None"""
    f = _cache_file(q)
    if f.exists():
        d = load_json(f)
        if time.time() - d["at"] < DAY:
            return d["hits"]
    return None


def best_format(fmts):
    """the smallest HD MP4 (1080p, else 720p), never 4K -> (key, info) or None"""
    mp4 = (fmts or {}).get("MP4") or {}
    for k in ("_1080p", "_720p"):
        f = mp4.get(k)
        if f and f.get("file_size_bytes"):
            return k, f
    return None


def hit_of(x):
    """one search result -> our candidate record, or None when it has no HD MP4 at most MAX_MB, is not horizontal footage"""
    if x.get("type") not in (None, "footage") or x.get("orientation") not in (None, "horizontal"):
        return None
    bf = best_format(x.get("download_formats"))
    if not bf or bf[1]["file_size_bytes"] > MAX_MB * 1e6:
        return None
    kw = x.get("keywords") or []
    return {"id": f"sb{x['id']}", "title": x.get("title", ""), "tags": ", ".join([x.get("title", "")] + kw), "seconds": x.get("duration") or 0,
            "page": x.get("details_url", ""), "thumb": x.get("thumbnail_url", ""), "format": bf[0].strip("_"),
            "mb": round(bf[1]["file_size_bytes"] / 1e6, 1), "codec": bf[1].get("video_codec", "")}


def search_many(queries, cwd, project="", log=print):
    """search Storyblocks for every query not searched in the last 24 h (one background run per PER_CALL queries) ->
    {query: [hits]} for all of them"""
    want = [q for q in dict.fromkeys(q.strip() for q in queries if q and q.strip()) if cached(q) is None]
    parts = [want[i:i + PER_CALL] for i in range(0, len(want), PER_CALL)]
    if parts:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(RUNS_AT_ONCE) as ex:
            list(ex.map(lambda part: _search_part(part, cwd, project, log), parts))
    return {q: cached(q) or [] for q in queries}


def _search_part(part, cwd, project, log):
    """one background run for up to PER_CALL queries; each answered query is cached"""
    prompt = (f"Load the tool {SEARCH_TOOL} with ToolSearch (query \"select:{SEARCH_TOOL}\"). Then call it exactly once for each "
              "of these searches (several at once is fine), each with orientation \"horizontal\", results_per_page 10 and "
              "extended \"download_formats,keywords\", keywords exactly as given:\n"
              + "\n".join(f"- {q}" for q in part) + "\nCall no other tool. When done, reply with the single word done.")
    calls, st = run_claude(prompt, SEARCH_TOOL, cwd, log)
    got = 0
    for inp, txt, err in calls:
        q = (inp.get("keywords") or "").strip()
        match = next((x for x in part if x.lower() == q.lower()), None)
        if not match or err:
            continue
        try:
            res = json.loads(txt).get("results") or []
        except ValueError:
            continue
        hits = [h for h in (hit_of(x) for x in res) if h]
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        save_json(_cache_file(match), {"at": time.time(), "query": match, "hits": hits, "total": json.loads(txt).get("total_results")})
        got += 1
    note("search", queries=len(part), answered=got, seconds=st["seconds"], status=st["status"], project=project)
    log(f"storyblocks: {got} of {len(part)} search(es) answered in {st['seconds']:.0f} s ({st['status']})")


# ---------------------------------------------------------------------------------------------------- download
def links_of(txt):
    """every https link in a get_download_url reply, with the JSON keys that lead to it -> [(path, url)]"""
    out = []

    def walk(x, path):
        if isinstance(x, dict):
            for k, v in x.items():
                walk(v, path + [str(k)])
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, path + [str(i)])
        elif isinstance(x, str) and x.startswith("https://"):
            out.append(("/".join(path), x))
    try:
        walk(json.loads(txt), [])
    except ValueError:
        out += [("", u) for u in re.findall(r"https://\S+", txt)]
    return out


def pick_link(links, fmt):
    """the link for the chosen HD MP4 (fmt "1080p"/"720p"), never a 4K one"""
    def score(path):
        p = path.lower()
        if "2160" in p or "4k" in p or "mov" in p.replace("movie", ""):
            return -1
        return (2 if fmt.lower() in p else 0) + (1 if "mp4" in p else 0)
    ok = sorted(((score(pth), pth, u) for pth, u in links if score(pth) > 0), reverse=True)
    return (ok[0][1], ok[0][2]) if ok else (None, None)


BATCH = 10                    # download links asked in one background run (35 in one run came back with none, 21 Oct 2026)
TRIES = 2                     # the missing ones are asked once more
DOWNLOAD_TIMEOUT = 240        # s: 10 links take 15-25 s; a run that loops (9 min on 21 Oct 2026) is stopped


def ask_links(p, ids, log=print):
    """the download links of exactly these ids, BATCH at a time, the missing ones asked once more -> {id: reply text}.
    Only the tool's real calls count: a run that writes its calls as text, or ends "success" with no call, gives none
    (owner's decision of 21 Oct 2026, after a run of 35 ids did exactly that for 9 minutes and nothing was downloaded)"""
    by_id, runs = {}, p.work / "montage" / "storyblocks_runs"
    for k in range(TRIES):
        want = [i for i in ids if i not in by_id]
        if not want:
            break
        if k:
            log(f"storyblocks: {len(want)} of {len(ids)} download link(s) did not come back; asking once more, {BATCH} at a time")
        for j in range(0, len(want), BATCH):
            part = want[j:j + BATCH]
            prompt = (f"Load the tool {DOWNLOAD_TOOL} with ToolSearch (query \"select:{DOWNLOAD_TOOL}\"). The owner's video project "
                      f"has chosen these Storyblocks videos and asks to download them: call {DOWNLOAD_TOOL} exactly once for each "
                      f"of these stock item ids, with contentClass \"videos\", and for no other id: {part}. Do not call it twice "
                      "for an id. Call no other tool. When done, reply with the single word done.")
            calls, st = run_claude(prompt, DOWNLOAD_TOOL, runs, log, timeout=DOWNLOAD_TIMEOUT)
            asked = [int(inp.get("stockItemId", -1)) for inp, _, _ in calls]
            extra = [i for i in asked if i not in part] + [i for i in set(asked) if asked.count(i) > 1]
            if extra:
                log(f"storyblocks AUDIT: download links asked beyond the list (each licenses a clip): {extra}")
            got = {}
            for inp, txt, err in calls:
                n = int(inp.get("stockItemId", -1))
                if not err and n in part and txt:
                    got[n] = txt
            by_id.update(got)
            ok = "ok" if len(got) == len(part) else f"{len(part) - len(got)} missing"
            note("download-run", ids=part, asked=asked, extra=extra, seconds=st["seconds"], claude_status=st["status"],
                 calls=st["calls"], calls_as_text=st["calls_as_text"], status=ok, attempt=k + 1, project=p.folder.name)
            if not calls:
                log(f"storyblocks: the background run made NO real download call for {len(part)} clip(s) in {st['seconds']:.0f} s"
                    + (f" (it wrote {st['calls_as_text']} call(s) out as text instead)" if st["calls_as_text"] else "")
                    + f"; Claude said «{st['status']}», counted as a failure")
            else:
                log(f"storyblocks: {len(got)} of {len(part)} download link(s) in {st['seconds']:.0f} s")
    save_json(runs / f"links_{time.strftime('%Y%m%d_%H%M%S')}.json",       # signed links, ~30 min
              {"ids": ids, "replies": {str(k): v for k, v in by_id.items()}})
    return by_id


def fetch_many(p, items, ledger, log=print):
    """the picked Storyblocks clips -> work/assets/stock/sb<id>.mp4 with their credits records (each link asked licenses
    the clip on the company's account) -> [what could not be fetched]: the sources step fails on any (never «done» without
    the files); a clip left out by a rule (its size, the cap) is not a failure"""
    out_of = lambda it: p.asset_dir("stock") / f"{it['id']}.mp4"          # noqa: E731
    have = {k for k, r in ledger.rec.items() if r.get("source") == "Storyblocks"}
    todo, already = [], 0
    for it in {x["id"]: x for x in items}.values():
        f = out_of(it)
        if f.exists() and f.stat().st_size > 50000 and video_ok(f):
            already += 1
            continue
        if (it.get("mb") or 0) > MAX_MB:
            note("refused-size", id=it["id"], mb=it.get("mb"), project=p.folder.name)
            log(f"storyblocks {it['id']}: left out, its HD file is {it['mb']} MB, over {MAX_MB} MB")
            continue
        if len(have) + len(todo) >= CAP_PER_EPISODE:
            log(f"storyblocks {it['id']}: left out, {CAP_PER_EPISODE} Storyblocks clips in this episode already (the cap)")
            continue
        todo.append(it)
    if not todo:
        return []
    by_id = ask_links(p, [int(it["id"][2:]) for it in todo], log)
    failed = []
    for it in todo:
        num = int(it["id"][2:])
        txt = by_id.get(num)
        if txt is None:
            note("download", id=it["id"], ok=False, why="no link", project=p.folder.name)
            failed.append(f"{it['id']} (no download link after {TRIES} tries)")
            continue
        path, url = pick_link(links_of(txt), it.get("format") or "1080p")
        if not url:
            note("download", id=it["id"], ok=False, why="no HD MP4 link", project=p.folder.name)
            failed.append(f"{it['id']} (no HD MP4 link in the reply)")
            continue
        f = out_of(it)
        if f.exists():
            set_aside(p, f, "not a playable video (saved by an earlier run)", ledger, f"V:{it['id']}")
        ok, why = download(p, url, f, video_ok, ua=UA, max_bytes=MAX_MB * 1e6)
        note("download", id=it["id"], ok=ok, why=why, link=path, mb=it.get("mb"), project=p.folder.name)
        if not ok:
            failed.append(f"{it['id']} (the download failed: {why})")
            continue
        ledger.add(f"V:{it['id']}", kind="stock video", source="Storyblocks", page=it.get("page", ""), title=it.get("title", ""),
                   licence=LICENCE, file=str(f), format=it.get("format", ""), how="Storyblocks MCP (official connector), HD MP4")
        log(f"storyblocks {it['id']}: {it.get('format', '')} MP4, {f.stat().st_size / 1e6:.1f} MB")
    n = already + len(todo)
    log(f"storyblocks: {n - len(failed)} of {n} picked clip(s) here" + (f"; NOT FETCHED: {', '.join(failed)}" if failed else ""))
    return failed

"""The one way the script tool reaches the network (plan section 2.1; decision 3a).

- robots.txt (RFC 9309: longest match wins, Allow wins a tie, * and $ wildcards) is read for every site and checked for
  every URL, for three agents:
      "*" and our own agent ("monteer-research")  -> may we fetch it at all?
      "Claude-User"                               -> may its text go to the brain? (Claude reads it)
  robots.txt missing (4xx) = everything allowed; unreachable (5xx, no connection) = nothing allowed (RFC 9309 2.3.1).
- One request at a time per site, spaced by max(the site's Crawl-delay, the source's own rule, 5 s).
- 429 / 503: wait (Retry-After, else 10 s then 30 s) and try twice more; after that the site is left alone for the rest
  of the process ("refused").
- Cache: monteer_data/cache/script_sources/<sha of URL>.{body,json}, with the time fetched. A cached copy younger than
  the caller's max_age is used instead of the network (feeds 1 h, searches 24 h, article texts kept: they are our
  research record).
- Honest, neutral User-Agent ("monteer-research/1.0"): never a browser's, never the user's name or email. A site that
  refuses us is skipped; nothing is done to get around a refusal, a login or a paywall.
"""
import hashlib
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from ..core.io import atomic, load_json, save_json
from ..core.paths import CACHE

UA = "monteer-research/1.0"
AGENT = "monteer-research"
BRAIN_AGENT = "Claude-User"
DEFAULT_GAP = 5.0
MAX_BYTES = 8 << 20
DIR = CACHE / "script_sources"
HOSTS = DIR / "hosts.json"          # per site: last request time, robots.txt and its fetch time
_refused = set()
_ctx = None
# sites the owner has ruled out (never fetched, never cited, wherever the link comes from)
HELD = {"ceicdata.com": "CEIC: off for good (owner's decision 3a, 16 Oct 2026): its terms forbid commercial use and use with AI tools; "
                        "the same figures come from the World Bank (Global Economic Monitor, QEDS)"}


def held(url):
    """the reason a URL's site is held off, or "" """
    h = host_of(url) or ""
    return next((why for d, why in HELD.items() if h == d or h.endswith("." + d)), "")


def ssl_ctx():
    global _ctx
    if _ctx is None:
        try:
            import certifi
            _ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            _ctx = ssl.create_default_context()
    return _ctx


def iri(url):
    """an address with Arabic (or other non-ASCII) letters, percent-encoded so it can be requested"""
    sp = urllib.parse.urlsplit(url.strip())
    host = sp.hostname.encode("idna").decode() if sp.hostname else ""
    netloc = host + (f":{sp.port}" if sp.port else "")
    q = lambda x, safe: urllib.parse.quote(x, safe=safe)  # noqa: E731  (keeps existing %XX escapes)
    return urllib.parse.urlunsplit((sp.scheme, netloc, q(sp.path, "/%:@!$&'()*+,;=~"), q(sp.query, "/%:@!$&'()*+,;=?~"), ""))


def host_of(url):
    return urllib.parse.urlsplit(url).netloc.lower()


# ------------------------------------------------------------------------------------------------ robots.txt (RFC 9309)
def parse_robots(text):
    """[{agents: [...], rules: [(allow, path)], delay}]"""
    groups, cur, last_was_agent = [], None, False
    for line in (text or "").splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = [x.strip() for x in line.split(":", 1)]
        k = k.lower()
        if k == "user-agent":
            if cur is None or not last_was_agent:
                cur = {"agents": [], "rules": [], "delay": None}
                groups.append(cur)
            cur["agents"].append(v.lower())
            last_was_agent = True
            continue
        last_was_agent = False
        if cur is None:
            continue
        if k in ("allow", "disallow"):
            if v or k == "allow":
                cur["rules"].append((k == "allow", v))
        elif k == "crawl-delay":
            try:
                cur["delay"] = float(v)
            except ValueError:
                pass
    return groups


def _group_for(groups, agent):
    agent = agent.lower()
    mine = [g for g in groups if any(a != "*" and agent.startswith(a) for a in g["agents"])]
    if mine:   # all groups naming this agent are merged (RFC 9309 2.2.1)
        return {"rules": sum((g["rules"] for g in mine), []), "delay": next((g["delay"] for g in mine if g["delay"]), None)}
    star = [g for g in groups if "*" in g["agents"]]
    return {"rules": sum((g["rules"] for g in star), []), "delay": next((g["delay"] for g in star if g["delay"]), None)}


def _pat(p):
    rx = "".join(".*" if c == "*" else ("$" if c == "$" and i == len(p) - 1 else re.escape(c)) for i, c in enumerate(p))
    return re.compile(rx)


def allowed_by(groups, agent, path):
    best = None
    for allow, p in _group_for(groups, agent)["rules"]:
        if p == "":
            continue
        if _pat(p).match(path):
            key = (len(p), allow)
            if best is None or key > best[0]:
                best = (key, allow)
    return True if best is None else best[1]


def _hosts():
    return load_json(HOSTS) if HOSTS.exists() else {}


def _save_hosts(h):
    save_json(HOSTS, h)


def robots(url):
    """(status, groups): status 'ok' | 'none' (4xx: all allowed) | 'unreachable' (nothing allowed)"""
    sp = urllib.parse.urlsplit(url)
    host = sp.netloc.lower()
    h = _hosts()
    e = h.get(host, {})
    if e.get("robots_at") and time.time() - e["robots_at"] < 24 * 3600:
        return e["robots_status"], parse_robots(e.get("robots", ""))
    code, body, _ = _raw_get(f"{sp.scheme}://{sp.netloc}/robots.txt", host, gap=DEFAULT_GAP)
    if code == 200:
        status, text = "ok", body.decode("utf-8", "replace")
    elif code and 400 <= code < 500 and code != 429:
        status, text = "none", ""
    else:
        status, text = "unreachable", ""
    h = _hosts()
    h.setdefault(host, {}).update(robots_at=time.time(), robots_status=status, robots=text, robots_code=code)
    _save_hosts(h)
    return status, parse_robots(text)


def permissions(url):
    """{fetch: bool, brain: bool, why: str, crawl_delay}"""
    sp = urllib.parse.urlsplit(iri(url))
    path = (sp.path or "/") + (("?" + sp.query) if sp.query else "")
    status, groups = robots(url)
    if status == "unreachable":
        return {"fetch": False, "brain": False, "why": "robots.txt unreachable: nothing is fetched (RFC 9309)", "crawl_delay": None}
    star, own, cu = allowed_by(groups, "*", path), allowed_by(groups, AGENT, path), allowed_by(groups, BRAIN_AGENT, path)
    delay = _group_for(groups, AGENT)["delay"]
    why = []
    if not star:
        why.append("robots.txt disallows it for every agent (*)")
    if not own:
        why.append(f"robots.txt disallows it for {AGENT}")
    if not cu:
        why.append(f"robots.txt disallows it for {BRAIN_AGENT}: its text never goes to the brain")
    return {"fetch": star and own, "brain": star and own and cu, "why": "; ".join(why), "crawl_delay": delay}


# ------------------------------------------------------------------------------------------------ requests
def _wait_turn(host, gap):
    h = _hosts()
    last = h.get(host, {}).get("last", 0)
    wait = last + gap - time.time()
    if wait > 0:
        time.sleep(wait)
    h = _hosts()
    h.setdefault(host, {})["last"] = time.time()
    _save_hosts(h)


def _raw_get(url, host, gap, headers=None):
    """(code or None, body bytes, info) with spacing and back-off; never raises for HTTP errors"""
    if host in _refused:
        return None, b"", {"error": "site refused us earlier in this run"}
    for attempt in range(3):
        _wait_turn(host, gap)
        req = urllib.request.Request(iri(url), headers=dict({"User-Agent": UA, "Accept-Language": "ar,en;q=0.8"}, **(headers or {})))
        try:
            with urllib.request.urlopen(req, timeout=40, context=ssl_ctx()) as r:
                body = r.read(MAX_BYTES + 1)
                return r.status, body[:MAX_BYTES], {"final_url": r.geturl(), "content_type": r.headers.get("Content-Type", ""),
                                                    "truncated": len(body) > MAX_BYTES}
        except urllib.error.HTTPError as e:
            if e.code in (429, 503) and attempt < 2:
                ra = e.headers.get("Retry-After", "")
                time.sleep(min(120, float(ra)) if ra.isdigit() else (10, 30)[attempt])
                continue
            if e.code in (429, 503):
                _refused.add(host)
            try:
                body = e.read()[:20000]
            except OSError:
                body = b""
            return e.code, body, {"error": f"HTTP {e.code}"}
        except (urllib.error.URLError, OSError, ValueError) as e:
            if attempt < 1:
                time.sleep(5)
                continue
            return None, b"", {"error": f"no connection: {getattr(e, 'reason', e)}"}
    return None, b"", {"error": "gave up"}


def _cache_paths(url):
    k = hashlib.sha256(url.encode()).hexdigest()[:24]
    return DIR / f"{k}.body", DIR / f"{k}.json"


def cached(url):
    b, m = _cache_paths(url)
    if b.exists() and m.exists():
        return load_json(m), b.read_bytes()
    return None, None


def get(url, max_age=None, gap=None, headers=None, check_robots=True):
    """{ok, code, body, url, final_url, fetched_at, from_cache, fetch, brain, why, content_type}
    max_age: seconds a cached copy stays good (None = forever, 0 = always fetch again)."""
    host = host_of(url)
    if held(url):
        return {"url": url, "fetch": False, "brain": False, "why": held(url), "ok": False, "code": None, "body": b"", "from_cache": False}
    perm = permissions(url) if check_robots else {"fetch": True, "brain": True, "why": "", "crawl_delay": None}
    res = {"url": url, "fetch": perm["fetch"], "brain": perm["brain"], "why": perm["why"]}
    if not perm["fetch"]:
        return dict(res, ok=False, code=None, body=b"", from_cache=False)
    meta, body = cached(url)
    if meta and (max_age is None or time.time() - meta["fetched_ts"] < max_age):
        return dict(res, ok=meta["code"] == 200, code=meta["code"], body=body, final_url=meta.get("final_url", url),
                    fetched_at=meta["fetched_at"], content_type=meta.get("content_type", ""), from_cache=True)
    g = max(DEFAULT_GAP, gap or 0, perm["crawl_delay"] or 0)
    code, body, info = _raw_get(url, host, g, headers)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    if code == 200:
        b, m = _cache_paths(url)
        DIR.mkdir(parents=True, exist_ok=True)
        with atomic(b) as tmp:
            Path(tmp).write_bytes(body)
        save_json(m, {"url": url, "code": code, "final_url": info.get("final_url", url), "content_type": info.get("content_type", ""),
                      "fetched_at": now, "fetched_ts": time.time(), "truncated": info.get("truncated", False)})
    return dict(res, ok=code == 200, code=code, body=body, final_url=info.get("final_url", url), fetched_at=now,
                content_type=info.get("content_type", ""), from_cache=False, error=info.get("error"))


def get_json(url, **kw):
    r = get(url, **kw)
    if r["ok"]:
        try:
            r["json"] = json.loads(r["body"], strict=False)     # GDELT's titles can hold raw control characters
        except ValueError:
            r["ok"], r["error"] = False, "not JSON"
    return r

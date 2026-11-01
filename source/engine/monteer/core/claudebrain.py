"""The background brain: Claude Code run by the engine itself (`claude -p`), on the device owner's own Claude subscription
(owner's decision, 15 Oct 2026: option A of Works/output/brain_audit_report.md). No person needs a Claude Code session open.

How a request is answered:
  - Claude Code runs headless in RESTRICTED mode: no shell, no code-running tools, no user settings, plugins or
    connectors (--restricted --strict-mcp-config). It may only read files (Read, Glob, Grep) inside the folders the
    request needs: the project, the engine (rules and the code that defines each answer's format) and the channel.
    A request may add a tool it needs (e.g. "tools": ["WebSearch"]), never Bash/Write/Edit.
  - Never --bare: that mode ignores subscription logins (measured 15 Oct 2026).
  - The model is named (project option "claude_model", default "opus"): restricted mode ignores the user's model choice.
  - A request with an "answer_schema" gets it as --json-schema, so the answer always has the right shape. A schema
    whose root is a list is wrapped as {"answer": [...]} and unwrapped.
  - The prompt goes in on stdin (fact-card requests carry whole articles).
Failures:
  - Usage limit reached (the subscription's 5-hour / weekly limits): the brain WAITS and tries again (every 10 min, or
    at the reset time Claude Code gives), up to project option "usage_wait_hours" (default 8), logging when it will
    retry. It does not hand the request to the local model: waiting gives the owner Claude's quality (decision taken
    alone, see the overnight report).
  - Any other failure (not installed, not logged in, timeout, an answer that is not JSON): 2 more tries, then
    BrainUnavailable. With report decision 1a, small requests may then go to the free local model; large ones stop.
  - Claude Code gives up on the answer's shape (error_max_structured_output_retries; 20 Oct 2026, the drawn-image pick of
    a channel episode, three times): the next try runs without --json-schema and the JSON is read from the answer's text
    (the request's answer format is still in the prompt; a channel episode's engine checks the shape, montage/steps.py).
  - A request marked "one_try" (a cheap look whose failure the engine accepts): one try, no waiting out a usage limit.
Every decision it makes is stored with made_by "claude-code-bg:<model>" plus its time and usage.
"""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from .paths import ENGINE

TIMEOUT = 45 * 60            # one request
READ_TOOLS = ["Read", "Glob", "Grep"]
NEVER = {"Bash", "Write", "Edit", "NotebookEdit", "PowerShell"}


class UsageLimit(Exception):
    def __init__(self, msg, reset_ts=None):
        super().__init__(msg)
        self.reset_ts = reset_ts


def claude_bin():
    p = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude")
    return p if Path(p).exists() else None


def status():
    """(ok, text): Claude Code installed and logged in (no secret is printed)"""
    b = claude_bin()
    if not b:
        return False, "Claude Code is not installed (https://claude.com/claude-code), or `claude` is not on PATH"
    try:
        r = subprocess.run([b, "auth", "status"], capture_output=True, text=True, timeout=60)
        d = json.loads(r.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        return False, f"could not read Claude Code's login status ({e})"
    if not d.get("loggedIn"):
        return False, "Claude Code is not logged in: run  claude auth login  once, as the device's owner"
    how = d.get("authMethod", "?")
    plan = d.get("subscriptionType") or ("API key" if how != "claude.ai" else "?")
    return True, f"Claude Code logged in ({how}, plan: {plan})"


def _prompt(request, project_folder):
    """the text Claude Code gets on stdin"""
    if "instructions" in request:                    # self-contained (the script tool's requests)
        from .localbrain import prompt_parts
        system, user = prompt_parts(request)
        return system + "\n\n" + user + "\n\nReturn ONLY the answer (no file changes; you cannot write files)."
    # a montage request: what is needed, the files to read, the rules and the answer's format
    root = Path(project_folder)
    files = [str((root / f) if not Path(f).is_absolute() else Path(f)) for f in request.get("read", [])]
    engine_docs = [str(ENGINE / f) for f in request.get("format_docs", [])]
    rules = [str(ENGINE.parent / f) if f.startswith("engine/") else str(ENGINE / f) for f in request.get("rules", [])]
    parts = [
        "You are the judgement step of «مونتير» (Monteer), an engine that edits Arabic YouTube videos. You answer ONE "
        "decision of the montage. Read the files listed below with your Read tool (images too: look at them), follow the "
        "editing rules, and return only the decision.",
        f"DECISION NEEDED: {request.get('what', '')}",
    ]
    if request.get("instructions_extra"):
        parts.append(request["instructions_extra"])
    if files:
        parts.append("FILES TO READ (project files):\n" + "\n".join(f"- {f}" for f in files))
    if engine_docs:
        parts.append("THE ANSWER'S FORMAT is defined in these engine files (read their top docstrings):\n" + "\n".join(f"- {f}" for f in engine_docs))
    if rules:
        parts.append("EDITING RULES:\n" + "\n".join(f"- {f}" for f in rules))
    if request.get("channel"):
        parts.append(f"CHANNEL PROFILE FOLDER: {(root / request['channel']) if not Path(request['channel']).is_absolute() else request['channel']}")
    parts.append("ANSWER FORMAT EXAMPLE (shape only, not content):\n" + json.dumps(request.get("answer_format"), ensure_ascii=False))
    for k in ("previous_problem", "context"):
        if request.get(k):
            parts.append(f"{k.upper().replace('_', ' ')}:\n" + (request[k] if isinstance(request[k], str) else json.dumps(request[k], ensure_ascii=False)))
    parts.append("Return ONLY the decision as JSON. You cannot and must not change any file.")
    return "\n\n".join(parts)


def _dirs(request, project_folder):
    d = {str(Path(project_folder)), str(ENGINE)}
    ch = request.get("channel")
    if ch:
        d.add(str((Path(project_folder) / ch).resolve()) if not Path(ch).is_absolute() else ch)
    for f in request.get("read", []):
        p = Path(f) if Path(f).is_absolute() else Path(project_folder) / f
        d.add(str(p.parent.resolve()))
    for extra in request.get("read_dirs", []):
        d.add(str(extra))
    return sorted(d)


def _parse_json(text):
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    for opener in ("{", "["):
        i = text.find(opener)
        if i >= 0:
            try:
                return json.JSONDecoder().raw_decode(text[i:])[0]
            except ValueError:
                continue
    raise ValueError("no JSON in the answer")


def _limit(out_text):
    """(is a usage/rate limit, reset epoch or None)"""
    t = out_text or ""
    if re.search(r"usage limit|rate limit|limit reached|too many requests|\b429\b|overloaded|5-hour limit|weekly limit", t, re.I):
        m = re.search(r"limit reached\|(\d{9,})", t) or re.search(r"reset[s]? (?:at )?(\d{9,})", t)
        return True, (int(m.group(1)) if m else None)
    return False, None


SHAPE_GAVE_UP = "error_max_structured_output_retries"


def run_once(request, project_folder, model, log=print, use_schema=True):
    """one call; returns (decision, info) or raises UsageLimit / RuntimeError"""
    b = claude_bin()
    if not b:
        raise RuntimeError("Claude Code is not installed")
    schema = request.get("answer_schema") if use_schema else None
    wrapped = isinstance(schema, dict) and schema.get("type") == "array"
    if wrapped:
        schema = {"type": "object", "required": ["answer"], "properties": {"answer": schema}}
    tools = READ_TOOLS + [t for t in request.get("tools", []) if t not in NEVER]
    cmd = [b, "-p", "--restricted", "--strict-mcp-config", "--tools", ",".join(tools), "--model", model,
           "--output-format", "json", "--no-session-persistence"]
    for d in _dirs(request, project_folder):
        cmd += ["--add-dir", d]
    if schema:
        cmd += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
    t0 = time.time()
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)            # always the device owner's subscription, never a stray paid key
    r = subprocess.run(cmd, input=_prompt(request, project_folder), capture_output=True, text=True, timeout=TIMEOUT,
                       cwd=str(project_folder), env=env)
    secs = round(time.time() - t0, 1)
    try:
        out = json.loads(r.stdout)
    except ValueError:
        lim, ts = _limit(r.stdout + r.stderr)
        if lim:
            raise UsageLimit((r.stdout + r.stderr).strip()[:300], ts)
        raise RuntimeError(f"claude -p gave no JSON (exit {r.returncode}): {(r.stderr or r.stdout).strip()[:300]}")
    if out.get("is_error") or out.get("subtype") != "success":
        msg = str(out.get("result") or out.get("subtype"))
        lim, ts = _limit(msg + " " + str(out.get("api_error_status") or ""))
        if lim:
            raise UsageLimit(msg[:300], ts)
        raise RuntimeError(f"claude -p failed: {msg[:300]}")
    if schema and out.get("structured_output") is not None:
        decision = out["structured_output"]
    else:
        decision = _parse_json(out.get("result"))
    if wrapped and isinstance(decision, dict) and "answer" in decision:
        decision = decision["answer"]
    usage = out.get("usage", {})
    info = {"model": ",".join(out.get("modelUsage", {}).keys()) or model, "seconds": secs, "turns": out.get("num_turns"),
            "api_equivalent_usd": round(out.get("total_cost_usd") or 0, 3), "output_tokens": usage.get("output_tokens"),
            "context_tokens": (usage.get("cache_read_input_tokens") or 0) + (usage.get("cache_creation_input_tokens") or 0)
            + (usage.get("input_tokens") or 0)}
    return decision, info


def wait_file(project_folder):
    """run/brain_wait.json: written while the brain waits out the subscription's limit, removed after (the panel's paused
    card and sidebar read it; web panel plan 2.4). A step running alongside the main ones (phase D) has its own,
    run/brain_wait_alongside.json, so the one that ends first never removes the other's."""
    d = Path(project_folder) / "run"
    return d / ("brain_wait_alongside.json" if os.environ.get("MONTEER_ALONGSIDE") else "brain_wait.json") if d.is_dir() else None


def answer(request, project_folder, model="opus", wait_hours=8, log=print, tries=3):
    """the decision, waiting through usage limits; RuntimeError after `tries` failed tries"""
    deadline = time.time() + wait_hours * 3600
    errors, use_schema = 0, True
    wf, since = wait_file(project_folder), None
    try:
        while True:
            try:
                return run_once(request, project_folder, model, log, use_schema=use_schema)
            except UsageLimit as e:
                now = time.time()
                if now > deadline:
                    raise RuntimeError(f"the subscription's usage limit did not reset within {wait_hours} h: {e}")
                nxt = max(now + 60, min(e.reset_ts + 60, deadline)) if e.reset_ts else now + 600
                log(f"[brain] usage limit reached ({str(e)[:120]}); waiting until {time.strftime('%H:%M', time.localtime(nxt))} and trying again")
                since = since or now
                if wf:
                    wf.write_text(json.dumps({"since": round(since), "until": round(nxt), "until_hm": time.strftime("%H:%M", time.localtime(nxt)),
                                              "reset_known": bool(e.reset_ts), "reason": str(e)[:200]}, ensure_ascii=False))
                time.sleep(max(0, nxt - now))
            except (RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
                errors += 1
                if errors >= tries:
                    raise RuntimeError(str(e))
                if SHAPE_GAVE_UP in str(e) and use_schema:
                    use_schema = False         # the shape is still asked in the prompt; the JSON is read from the text
                    log("[brain] Claude Code gave up on the answer's shape; the next try asks for the JSON in the text")
                log(f"[brain] background Claude Code failed ({str(e)[:160]}); trying again ({errors}/{tries - 1})")
                time.sleep(20 * errors)
    finally:
        if wf:
            wf.unlink(missing_ok=True)

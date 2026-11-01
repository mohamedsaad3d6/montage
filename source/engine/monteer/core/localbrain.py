"""The free local model: llama.cpp's llama-server on the CPU with Qwen3-8B (Q4_K_M, Apache-2.0), set up by
`bin/monteer setup` (parts llama + models). A FALLBACK ONLY (report decision 1a of 15 Oct 2026, replacing 7b: small requests when the paid brain fails; everything only with --brain local): it is weaker than Claude, above all in
Egyptian Arabic, and every decision it makes is labelled "local:…" (core/brain.py).

It answers only self-contained requests: {"instructions": text, "inputs": {...inline...}, "answer_schema": JSON schema}.
The answer is forced into the schema by llama.cpp's grammar, so it is always valid JSON of the right shape (its content
still goes through every check the request's step makes).

One server per process, started on first use (model load about 10-20 s) and stopped when the process ends. Thinking
mode is off (Qwen3 "enable_thinking": false): on this CPU the hidden reasoning would double the time.
"""
import atexit
import json
import os
import socket
import subprocess
import time
import urllib.request

from .paths import CACHE, LLAMA_SERVER, LOCAL_LLM

MODEL_NAME = "qwen3-8b-q4km"
CTX = 32768
THREADS = 8                      # the i9-9980HK's 8 physical cores
_server = {}


def can_answer(request):
    return isinstance(request, dict) and "instructions" in request and "answer_schema" in request


def available():
    """(True, '') or (False, why)"""
    if not LLAMA_SERVER.exists():
        return False, f"llama-server missing ({LLAMA_SERVER}): run  bin/monteer setup --only llama"
    if not LOCAL_LLM.exists():
        return False, f"model missing ({LOCAL_LLM}): run  bin/monteer setup --only models"
    return True, ""


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start():
    if _server.get("proc") and _server["proc"].poll() is None:
        return _server["url"]
    ok, why = available()
    if not ok:
        from .brain import BrainUnavailable
        raise BrainUnavailable(why)
    port = _free_port()
    log = open(CACHE / "llama-server.log", "a")
    cmd = [str(LLAMA_SERVER), "-m", str(LOCAL_LLM), "--host", "127.0.0.1", "--port", str(port), "-c", str(CTX),
           "-t", str(THREADS), "--jinja", "--no-webui", "-np", "1", "--cache-reuse", "256"]
    env = dict(os.environ, DYLD_LIBRARY_PATH=str(LLAMA_SERVER.parent))
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env)
    url = f"http://127.0.0.1:{port}"
    t0 = time.time()
    while time.time() - t0 < 300:
        if proc.poll() is not None:
            from .brain import BrainUnavailable
            raise BrainUnavailable(f"llama-server stopped while starting (see {CACHE / 'llama-server.log'})")
        try:
            with urllib.request.urlopen(url + "/health", timeout=5) as r:
                if r.status == 200:
                    break
        except OSError:
            pass
        time.sleep(1)
    else:
        proc.terminate()
        from .brain import BrainUnavailable
        raise BrainUnavailable("llama-server did not become ready in 300 s")
    _server.update(proc=proc, url=url, load_seconds=round(time.time() - t0, 1))
    atexit.register(proc.terminate)
    print(f"[local model] {MODEL_NAME} loaded in {_server['load_seconds']} s (CPU, {THREADS} threads, context {CTX})", flush=True)
    return url


def prompt_parts(request):
    system = request["instructions"]
    user = ("INPUTS (JSON):\n" + json.dumps(request.get("inputs", {}), ensure_ascii=False, indent=0, separators=(",", ":"))
            + "\n\nAnswer with ONE JSON object that matches this JSON schema exactly:\n"
            + json.dumps(request["answer_schema"], ensure_ascii=False))
    return system, user


def answer(request):
    """(decision, info) — info: model, seconds, tokens in/out, tokens per second"""
    url = _start()
    system, user = prompt_parts(request)
    body = {"messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "answer", "schema": request["answer_schema"]}},
            "chat_template_kwargs": {"enable_thinking": False},
            "temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0, "presence_penalty": 1.0,
            "max_tokens": int(request.get("local_max_tokens", 6000)), "cache_prompt": True}
    t0 = time.time()
    req = urllib.request.Request(url + "/v1/chat/completions", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=4 * 3600) as r:
        out = json.loads(r.read())
    secs = round(time.time() - t0, 1)
    text = out["choices"][0]["message"]["content"]
    usage = out.get("usage", {})
    timings = out.get("timings", {})
    info = {"model": MODEL_NAME, "seconds": secs, "prompt_tokens": usage.get("prompt_tokens"),
            "answer_tokens": usage.get("completion_tokens"),
            "prompt_tokens_per_s": round(timings.get("prompt_per_second", 0), 1),
            "answer_tokens_per_s": round(timings.get("predicted_per_second", 0), 1),
            "finish": out["choices"][0].get("finish_reason")}
    try:
        decision = json.loads(text)
    except ValueError:
        from .brain import BrainUnavailable
        raise BrainUnavailable(f"the local model's answer is not complete JSON (finish: {info['finish']}, "
                               f"{info['answer_tokens']} tokens)")
    return decision, info

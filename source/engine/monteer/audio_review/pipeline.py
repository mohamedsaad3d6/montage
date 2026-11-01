# coding: utf-8
"""Free-project-only reviewer; no autonomous deletion or publication.

prepare is offline. review is explicitly gated by an external unbilled-project
record, never infers billing from a key, and stops on any transport error.
"""
import argparse
import base64
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import wave

MODEL = 'gemini-3.8-flash'
ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/interactions'
PROMPT = Path(__file__).with_name('prompt.txt')


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def save(path, data):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.part')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Invalid numeric timing')
    return value


def windows(duration, core=200, context=5):
    if not 0 < finite(duration) <= 3600:
        raise ValueError('Duration must be within 1 hour')
    return [dict(core_start=s, core_end=min(duration, s + core),
                 start=max(0, s-context), end=min(duration, s+core+context))
            for s in range(0, math.ceil(duration), core)]


def prepare(source, output, ffmpeg, seconds=600, stage='before'):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('New output directory required; use review to resume')
    if stage not in ('before', 'after', 'targeted'):
        raise ValueError('Unknown stage')
    with wave.open(str(source), 'rb') as w:
        duration = min(finite(seconds), w.getnframes()/w.getframerate())
    chunks = windows(duration)
    # All new writable files stay in this new run folder. Never next to source.
    output.mkdir(parents=True)
    prompt = PROMPT.read_text(encoding='utf-8')
    (output/'prompt.txt').write_text(prompt, encoding='utf-8')
    state = dict(version=1, stage=stage, model=MODEL, source=str(source),
                 source_sha256=digest(source), prompt_sha256=digest(output/'prompt.txt'),
                 status='preparing', network_calls=0, max_calls=len(chunks), chunks=[])
    save(output/'run.json', state)
    for i, c in enumerate(chunks):
        path = output / ('sample-%02d.wav' % (i+1))
        subprocess.run([str(ffmpeg), '-v', 'error', '-nostdin', '-n', '-ss', str(c['start']),
                        '-i', str(source), '-t', str(c['end']-c['start']),
                        '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', str(path)], check=True)
        c.update(file=path.name, sha256=digest(path), status='pending')
        state['chunks'].append(c)
        save(output/'run.json', state)
    if digest(source) != state['source_sha256']:
        raise ValueError('Source changed during preparation')
    state['status'] = 'prepared'
    save(output/'run.json', state)
    return state


def validate(result, duration):
    if not isinstance(result, dict) or not isinstance(result.get('transcript'), str):
        raise ValueError('Missing literal transcript')
    issues = result.get('issues')
    if not isinstance(issues, list) or len(issues) > 100:
        raise ValueError('Invalid issues list')
    for issue in issues:
        if not isinstance(issue, dict):
            raise ValueError('Invalid issue')
        start, end = finite(issue.get('start')), finite(issue.get('end'))
        if not 0 <= start < end <= duration:
            raise ValueError('Candidate timing out of clip range')
        if issue.get('kind') not in ('retake', 'truncated_word', 'pause', 'breath', 'uncertain'):
            raise ValueError('Invalid candidate kind')
        if issue.get('action') not in ('keep', 'investigate'):
            raise ValueError('Reviewer cannot approve deletion')
        for key in ('quote', 'reason'):
            if not isinstance(issue.get(key), str) or not issue[key].strip():
                raise ValueError('Missing candidate evidence')
    return result


def request(audio, prompt, key, *, timeout=180, max_output_tokens=10000):
    body = dict(model=MODEL, input=[dict(type='text', text=prompt),
                dict(type='audio', data=base64.b64encode(audio).decode('ascii'), mime_type='audio/wav')],
                generation_config=dict(max_output_tokens=max_output_tokens), store=False)
    encoded = json.dumps(body).encode()
    if len(encoded) >= 19_000_000:
        raise ValueError('Request exceeds local inline size limit')
    req = urllib.request.Request(ENDPOINT, data=encoded,
            headers={'Content-Type': 'application/json', 'x-goog-api-key': key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as e:
        # Never emit response bodies, headers, URLs, or the credential.
        raise RuntimeError('Gemini HTTP %s; stopped with no retry or fallback' % e.code) from None
    except (urllib.error.URLError, TimeoutError):
        raise RuntimeError('Gemini network failure; request may have been processed; no automatic retry') from None
    if payload.get('status') != 'completed':
        raise RuntimeError('Gemini response incomplete; stopped')
    text = payload.get('output_text')
    if not text:
        text = ''.join(s.get('text', '') for s in payload.get('outputs', []) if s.get('type') == 'text')
    if not text:
        text = ''.join(c.get('text', '') for step in payload.get('steps', [])
                       if step.get('type') == 'model_output'
                       for c in step.get('content', []) if c.get('type') == 'text')
    text = (text or '').strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0]
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        raise RuntimeError('Gemini did not return valid JSON; no edits applied') from None


def credentials(config):
    p = Path(config).expanduser().resolve()
    if Path(__file__).resolve().parents[3] in p.parents:
        raise ValueError('Credentials must live outside engine')
    if p.stat().st_mode & 0o077:
        raise ValueError('Connection record must be owner-only (0600)')
    cfg = read(p)
    # A record is an operator attestation backed by project UI evidence, NOT
    # automated billing verification. Fail closed until a real record exists.
    if cfg.get('billing_enabled') is not False or cfg.get('tier') != 'free':
        raise ValueError('Verified unbilled project required')
    if cfg.get('model') != MODEL or not cfg.get('project_id'):
        raise ValueError('Missing pinned model / project')
    if abs(time.time()-finite(cfg.get('verified_at_epoch'))) > 7*86400:
        raise ValueError('Free-project verification expired')
    evidence = Path(cfg.get('evidence_file', '')).expanduser()
    if not evidence.is_file() or digest(evidence) != cfg.get('evidence_sha256'):
        raise ValueError('Missing verification evidence')
    key = os.environ.get('MONTEER_GEMINI_API_KEY', '').strip()
    if not key and cfg.get('key_file'):
        key_path = Path(cfg['key_file']).expanduser().resolve()
        if key_path.parent != p.parent or key_path.stat().st_mode & 0o077:
            raise ValueError('Key file must be private and beside external connection record')
        key = key_path.read_text(encoding='utf-8').strip()
    if not key:
        raise ValueError('MONTEER_GEMINI_API_KEY is missing; never paste it in chat')
    if hashlib.sha256(key.encode()).hexdigest() != cfg.get('key_sha256'):
        raise ValueError('Key does not match the verified connection')
    return key


@contextlib.contextmanager
def lock(folder):
    path = Path(folder)/'.review.lock'
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        path.unlink()


def review(output, config, transport=request):
    output = Path(output).resolve()
    with lock(output):
        state = read(output/'run.json')
        if state['model'] != MODEL or digest(state['source']) != state['source_sha256']:
            raise ValueError('Model/source fingerprint changed')
        if digest(output/'prompt.txt') != state['prompt_sha256']:
            raise ValueError('Prompt changed')
        for c in state['chunks']:
            if digest(output/c['file']) != c['sha256']:
                raise ValueError('Chunk changed')
            if c['status'] == 'in_flight':
                raise ValueError('Uncertain previous request; reconcile before another call')
            if c['status'] == 'completed':
                if digest(output/c['result']) != c['result_sha256']:
                    raise ValueError('Saved result changed')
        pending = [c for c in state['chunks'] if c['status'] != 'completed']
        if pending:
            key = credentials(config)
        for c in pending:
            if state['network_calls'] >= state['max_calls']:
                raise ValueError('Run request budget exhausted')
            # Durable checkpoint before network: a crash never silently resends.
            c['status'] = 'in_flight'
            state['network_calls'] += 1
            save(output/'run.json', state)
            try:
                result = validate(transport((output/c['file']).read_bytes(),
                                  (output/'prompt.txt').read_text(encoding='utf-8'), key), c['end']-c['start'])
            except Exception:
                state['status'] = 'stopped_needs_reconciliation'
                save(output/'run.json', state)
                raise
            path = output/(c['file']+'.review.json')
            save(path, result)
            c.update(status='completed', result=path.name, result_sha256=digest(path))
            save(output/'run.json', state)
        candidates = []
        for c in state['chunks']:
            for i in read(output/c['result'])['issues']:
                item = dict(i, global_start=c['start']+i['start'], global_end=c['start']+i['end'],
                            chunk=c['file'], state='needs_word_alignment', automatically_approved=False)
                # Overlap context retained as evidence, owned by only one core.
                mid = (item['global_start']+item['global_end'])/2
                if c['core_start'] <= mid < c['core_end']:
                    candidates.append(item)
        save(output/'candidates.json', candidates)
        state.update(status='reviewed_requires_alignment', source_unchanged=digest(state['source']) == state['source_sha256'])
        save(output/'run.json', state)
        return state


def main(argv=None):
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == 'gate':
        from .gate import main as gate_main
        return gate_main(args[1:])
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--audio', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--ffmpeg', required=True)
    p.add_argument('--seconds', type=float, default=600)
    p.add_argument('--stage', choices=['before', 'after', 'targeted'], default='before')
    p = sub.add_parser('review')
    p.add_argument('--out', required=True)
    p.add_argument('--connection', required=True)
    p = sub.add_parser('status')
    p.add_argument('--out', required=True)
    a = ap.parse_args(argv)
    try:
        if a.command == 'prepare':
            result = prepare(a.audio, a.out, a.ffmpeg, a.seconds, a.stage)
        elif a.command == 'review':
            result = review(a.out, a.connection)
        else:
            result = read(Path(a.out)/'run.json')
        print(json.dumps(dict(status=result['status'], chunks=len(result['chunks']),
                              network_calls=result['network_calls']), ensure_ascii=False))
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as e:
        raise SystemExit(str(e)) from None

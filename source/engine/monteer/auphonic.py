"""Optional Auphonic bridge. No paid requests, automatic cuts, or video replacement.

Run with python3 -m monteer.auphonic --help from engine/.
Credentials stay in ~/.config/montage/auphonic.json, outside the repository.
"""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import shutil
import struct
import tempfile
import urllib.parse
import uuid
import wave

HOST = 'auphonic.com'
RESULT_STORAGE_HOST = 'ab7e85693fce51fdca76bafbd20afa6a.eu.r2.cloudflarestorage.com'
CONFIG = Path.home() / '.config/montage/auphonic.json'


def wav_duration(path):
    """Read PCM RIFF/WAVE, including 24-bit extensible output on Python 3.9."""
    with Path(path).open('rb') as handle:
        header = handle.read(12)
        if len(header) != 12 or header[:4] != b'RIFF' or header[8:] != b'WAVE':
            raise ValueError('Expected a PCM RIFF WAV file.')
        rate = alignment = data_size = None
        total = Path(path).stat().st_size
        while handle.tell() + 8 <= total:
            tag, size = struct.unpack('<4sI', handle.read(8))
            start = handle.tell()
            if start + size > total:
                raise ValueError('Truncated WAV chunk.')
            if tag == b'fmt ':
                fmt = handle.read(min(size, 40))
                if len(fmt) < 16:
                    raise ValueError('Invalid WAV format.')
                encoding, channels, rate, _, alignment, bits = struct.unpack('<HHIIHH', fmt[:16])
                if encoding == 65534:
                    if len(fmt) < 40 or fmt[24:40] != bytes.fromhex('0100000000001000800000aa00389b71'):
                        raise ValueError('Only PCM extensible WAV is supported.')
                elif encoding != 1:
                    raise ValueError('Only PCM WAV is supported.')
                if not channels or not rate or alignment != channels * ((bits + 7) // 8):
                    raise ValueError('Invalid WAV frame size.')
            elif tag == b'data':
                data_size = size
            handle.seek(start + size + (size % 2))
        if rate is None or data_size is None or not alignment:
            raise ValueError('WAV metadata is incomplete.')
        return data_size / alignment / rate


def save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    os.replace(temporary, path)


def config():
    if CONFIG.stat().st_mode & 0o077:
        raise ValueError('Credentials must be private (permissions 0600).')
    return json.loads(CONFIG.read_text())


def request(method, path, body=None, headers=None):
    """Never redirects or prints credentials/server error bodies."""
    connection = http.client.HTTPSConnection(HOST, timeout=180)
    auth = {'Authorization': 'bearer ' + config()['api_key']}
    auth.update(headers or {})
    try:
        connection.request(method, path, body=body, headers=auth)
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('Auphonic request failed: HTTP ' + str(response.status))
        result = json.load(response)
        if result.get('status_code') != 200:
            raise ValueError('Auphonic did not confirm success.')
        return result['data']
    finally:
        connection.close()


def validate_preset(preset):
    algorithms = preset.get('algorithms', {})
    if algorithms.get('cutter') is not False or any(algorithms.get(name) for name in
            ('silence_cutter', 'filler_cutter', 'cough_cutter', 'music_cutter')):
        raise ValueError('Automatic cutting must remain disabled in Auphonic.')
    if preset.get('outgoing_services'):
        raise ValueError('Automatic publishing is not allowed by this bridge.')
    return algorithms


def check():
    settings = config()
    user = request('GET', '/api/user.json')
    presets = request('GET', '/api/presets.json')
    preset = next(p for p in presets if p['uuid'] == settings['preset_uuid'])
    validate_preset(preset)
    # Stop if paid credit pools exist: the service otherwise consumes them first.
    if user.get('is_paying_user') or float(user.get('onetime_credits', 0)) > 0:
        raise ValueError('Free-only safeguard: paid account/credits require separate approval.')
    return {'connected': True, 'preset': preset['preset_name'],
            'remaining_hours': user['credits'], 'algorithms': preset['algorithms']}


def submit(source, job):
    source, job = Path(source).resolve(), Path(job).resolve()
    if job.exists():
        raise ValueError('Job already exists; fetch it instead of uploading again.')
    duration = wav_duration(source)
    connection_info = check()
    if float(connection_info['remaining_hours']) * 3600 < max(180, duration):
        raise ValueError('Insufficient free credits; no purchase will be attempted.')
    digest = hashlib.sha256()
    with source.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    state = {'state': 'upload_pending', 'source': str(source),
             'sha256': digest.hexdigest(), 'source_duration_s': duration,
             'preset_uuid': config()['preset_uuid'],
             'algorithms': connection_info['algorithms']}
    # Persist before POST. An interrupted POST is never blindly retried.
    job.parent.mkdir(parents=True, exist_ok=True)
    with job.open('x') as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    boundary = 'montage-' + uuid.uuid4().hex
    with tempfile.TemporaryFile() as body:
        fields = {'preset': state['preset_uuid'], 'title': source.stem,
                  'action': 'start'}
        for name, value in fields.items():
            body.write(('--' + boundary + '\r\nContent-Disposition: form-data; name="' +
                        name + '"\r\n\r\n' + value + '\r\n').encode())
        body.write(('--' + boundary + '\r\nContent-Disposition: form-data; '
                    'name="input_file"; filename="presenter.wav"\r\n'
                    'Content-Type: audio/wav\r\n\r\n').encode())
        with source.open('rb') as handle:
            shutil.copyfileobj(handle, body)
        body.write( ('\r\n--' + boundary + '--\r\n').encode())
        size = body.tell()
        body.seek(0)
        try:
            production = request('POST', '/api/simple/productions.json', body,
                                 {'Content-Type': 'multipart/form-data; boundary=' + boundary,
                                  'Content-Length': str(size)})
        except Exception:
            state['state'] = 'submission_uncertain_check_account_before_retry'
            save(job, state)
            raise
    state.update(state='submitted', production_uuid=production['uuid'])
    save(job, state)
    return {'state': state['state'], 'job': str(job)}


def fetch(job, output):
    job, output = Path(job), Path(output)
    state = json.loads(job.read_text())
    identifier = state.get('production_uuid')
    if not identifier or not identifier.isalnum():
        raise ValueError('No confirmed production; inspect the account before retrying.')
    production = request('GET', '/api/production/' + identifier + '.json')
    state['remote_status'] = production.get('status_string')
    save(job, state)
    if production.get('error_status'):
        raise ValueError('Auphonic processing failed; check the production page.')
    if production.get('status') != 3:
        return {'state': 'not_ready', 'status': state['remote_status']}
    validate_preset(production)
    result = next(f for f in production['output_files'] if f['format'] == 'wav-24bit')
    url = urllib.parse.urlsplit(result['download_url'])
    if url.scheme != 'https' or url.netloc != HOST or not url.path.startswith('/api/download/'):
        raise ValueError('Unexpected result destination; credentials will not be sent.')
    if output.exists():
        raise ValueError('Output already exists; it will not be overwritten.')
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_suffix(output.suffix + '.partial')
    connection = http.client.HTTPSConnection(HOST, timeout=180)
    try:
        connection.request('GET', url.path + ('?' + url.query if url.query else ''),
                           headers={'Authorization': 'bearer ' + config()['api_key']})
        response = connection.getresponse()
        for _ in range(3):
            if response.status not in (301, 302, 303, 307, 308):
                break
            redirect = urllib.parse.urlsplit(response.getheader('Location', ''))
            if (redirect.scheme != 'https' or redirect.username or redirect.password
                    or redirect.port not in (None, 443)
                    or not (redirect.hostname in (HOST, RESULT_STORAGE_HOST) or
                            (redirect.hostname or '').endswith('.' + HOST))):
                raise ValueError('Unsafe download redirect was refused.')
            connection.close()
            connection = http.client.HTTPSConnection(redirect.hostname, timeout=180)
            # Signed CDN links must never receive the account API key.
            connection.request('GET', redirect.path + ('?' + redirect.query if redirect.query else ''))
            response = connection.getresponse()
        if response.status != 200:
            raise ValueError('Result download failed: HTTP ' + str(response.status))
        with partial.open('xb') as handle:
            shutil.copyfileobj(response, handle)
        if partial.stat().st_size != result['size']:
            raise ValueError('Incomplete result download.')
        checksum = hashlib.md5()
        with partial.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                checksum.update(chunk)
        if checksum.hexdigest() != result['checksum']:
            raise ValueError('Result checksum mismatch.')
        duration = wav_duration(partial)
        partial.rename(output)
    finally:
        connection.close()
        if partial.exists():
            partial.unlink()
    delta = duration - state['source_duration_s']
    state.update(state='downloaded', output=str(output.resolve()),
                 result_duration_s=duration, duration_delta_s=delta,
                 automatic_video_replace_allowed=False,
                 review_required='Check free jingle position and audiovisual alignment; preserve branding.')
    save(job, state)
    return {k: state[k] for k in ('state', 'output', 'duration_delta_s',
                                  'automatic_video_replace_allowed', 'review_required')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    actions.add_parser('check')
    send = actions.add_parser('submit')
    send.add_argument('source', type=Path)
    send.add_argument('job', type=Path)
    get = actions.add_parser('fetch')
    get.add_argument('job', type=Path)
    get.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        if args.action == 'check':
            result = check()
            result.pop('algorithms', None)
        elif args.action == 'submit':
            result = submit(args.source, args.job)
        else:
            result = fetch(args.job, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, StopIteration, KeyError, http.client.HTTPException) as error:
        # Do not dump responses, headers, credentials or authentication tracebacks.
        parser.exit(1, 'Auphonic bridge stopped: ' + (str(error) if isinstance(error, ValueError)
                                                   else type(error).__name__) + '\n')


if __name__ == '__main__':
    main()

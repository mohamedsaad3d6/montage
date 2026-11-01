"""Fail-closed, artifact-bound audio review gate. Never grants publication approval."""
import json
import wave
from pathlib import Path
from .pipeline import digest, read, validate


def check(media, review_folder, technical_checks):
    media, folder, checks_path = Path(media).resolve(), Path(review_folder).resolve(), Path(technical_checks).resolve()
    reasons = []
    try:
        media_hash = digest(media)
        checks = read(checks_path)
        if checks.get('technical_pass') is not True:
            reasons.append('technical_checks_not_passed')
        if checks.get('output_sha256') != media_hash:
            reasons.append('technical_checks_for_different_media')
        if checks.get('use_as_baseline') is False or str(checks.get('editorial_status', '')).startswith('rejected'):
            reasons.append('user_rejected_media')
        from .word_audit import check_receipt
        try:
            word_result = check_receipt(folder/'word-audit-binding.json', media_hash)
            if not word_result['passed']:
                reasons.extend(word_result['reasons'])
        except (OSError, ValueError, KeyError, TypeError):
            reasons.append('missing_or_invalid_word_deletion_audit')
        binding = read(folder/'final-media-binding.json')
        if binding.get('media_sha256') != media_hash:
            reasons.append('review_for_different_media')
        state = read(folder/'run.json')
        if state.get('status') != 'reviewed_requires_alignment':
            reasons.append('review_not_completed')
        source = Path(state['source'])
        if digest(source) != state.get('source_sha256') or binding.get('audio_sha256') != state.get('source_sha256'):
            reasons.append('review_audio_changed')
        with wave.open(str(source), 'rb') as w:
            duration = w.getnframes()/w.getframerate()
        if abs(duration-float(binding['media_duration_seconds'])) > .1:
            reasons.append('partial_audio_not_whole_media')
        chunks = state.get('chunks', [])
        if not chunks:
            reasons.append('no_review_chunks')
        cursor = 0.0
        for i, c in enumerate(chunks):
            if abs(float(c['core_start'])-cursor) > .001 or c['core_end'] <= c['core_start']:
                reasons.append('review_coverage_gap')
            cursor = float(c['core_end'])
            if c.get('status') != 'completed':
                reasons.append('incomplete_review_chunk_%d' % i)
                continue
            audio_path = (folder/c['file']).resolve()
            if folder not in audio_path.parents or digest(audio_path) != c.get('sha256'):
                reasons.append('review_chunk_audio_changed_%d' % i)
            if state.get('review_method') == 'aistudio_ui':
                evidence_path = (folder/c.get('evidence_file','')).resolve()
                if folder not in evidence_path.parents or not evidence_path.is_file() or digest(evidence_path) != c.get('evidence_sha256'):
                    reasons.append('review_chunk_ui_evidence_changed_%d' % i)
            result_path = (folder/c['result']).resolve()
            if folder not in result_path.parents or digest(result_path) != c.get('result_sha256'):
                reasons.append('review_result_changed_%d' % i)
                continue
            result = validate(read(result_path), c['end']-c['start'])
            if not result['transcript'].strip():
                reasons.append('empty_transcript_%d' % i)
            from .resolutions import confirmed_keeps
            kept = confirmed_keeps(folder, media_hash, state, c, result)
            if any(z['action'] == 'investigate' and j not in kept for j,z in enumerate(result['issues'])):
                reasons.append('unresolved_editorial_issues_%d' % i)
        if abs(cursor-duration) > .1:
            reasons.append('review_does_not_cover_whole_media')
        if state.get('review_method') == 'aistudio_ui':
            evidence = folder/state['evidence_file']
            if digest(evidence) != state.get('evidence_sha256'):
                reasons.append('missing_ui_review_evidence')
        elif not state.get('network_calls', 0):
            reasons.append('independent_review_not_proven')
    except (OSError, ValueError, KeyError, TypeError, wave.Error) as e:
        reasons.append('missing_or_invalid_evidence:' + type(e).__name__)
    return dict(status='blocked' if reasons else 'passed_for_review', reasons=list(dict.fromkeys(reasons)),
                media=str(media), publication_approved=False,
                note='This gate verifies completed review evidence, not a guarantee of perfect editorial quality.')


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--video', required=True)
    ap.add_argument('--review', required=True)
    ap.add_argument('--checks', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args(argv)
    result = check(a.video, a.review, a.checks)
    Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
    if result['status'] != 'passed_for_review':
        raise SystemExit(2)

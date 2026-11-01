"""Account for source words removed by an edit; waveform confidence is not permission."""
from .pipeline import digest, read
from pathlib import Path


def inspect(plan, words, decisions):
    fps = plan['fps']
    spans = sorted((k['start_frame']/fps, k['end_frame']/fps) for k in plan['keeps'])
    if not spans:
        return dict(passed=False, missing_word_ids=[], reasons=['no_kept_spans'])
    scope = plan.get('audit_raw_range', [spans[0][0], spans[-1][1]])
    removed = [i for i,w in enumerate(words) if scope[0] <= (w['s']+w['e'])/2 < scope[1]
               and not any(s <= (w['s']+w['e'])/2 < e for s,e in spans)]
    approved = set()
    for d in decisions:
        if d.get('kind') in ('retake','abandoned_attempt','filler','explicit_content_removal') and d.get('reason','').strip() and d.get('evidence_file') and d.get('evidence_sha256'):
            q=Path(d['evidence_file'])
            if d.get('manual_boundaries'):
                try:
                    attestation=Path(d['boundary_attestation_file'])
                    valid=attestation.is_file() and digest(attestation)==d['boundary_attestation_sha256']
                    receipt=read(attestation) if valid else {}
                    if receipt.get('listened_all_joins') is not True or receipt.get('kept_meaning_complete') is not True:continue
                except (OSError,KeyError,ValueError,TypeError):continue
            if q.is_file() and digest(q)==d['evidence_sha256']:
                approved.update(d.get('word_ids',[]))
    missing = sorted(set(removed)-approved)
    return dict(passed=not missing, removed_word_ids=removed, missing_word_ids=missing,
                reasons=['unexplained_word_deletions'] if missing else [])


def check_receipt(path, media_hash):
    r=read(path)
    if r['media_sha256']!=media_hash:
        raise ValueError('word audit belongs to different media')
    if r.get('audit_method')=='full_source_byte_identity':
        matched=(digest(r['source_file'])==r['source_sha256']==media_hash and digest(r['reviewed_media_file'])==media_hash)
        return dict(passed=matched,removed_word_ids=[],missing_word_ids=[],audit_method='full_source_byte_identity',reasons=[] if matched else ['uncut_source_identity_failed'])
    plan,words=Path(r['plan_file']),Path(r['source_words_file'])
    if digest(plan)!=r['plan_sha256'] or digest(words)!=r['source_words_sha256']:
        raise ValueError('word audit inputs changed')
    pp=read(plan);pause=pp.get('confirmed_pause_plan')
    if pause and digest(pause['file'])!=pause['sha256']:raise ValueError('Pause review evidence changed')
    ww=read(words);ww=ww['words'] if isinstance(ww,dict) else ww
    return inspect(pp,ww,r['decisions'])

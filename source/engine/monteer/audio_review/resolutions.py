"""Evidence-bound KEEP adjudications. Never grants permission to delete audio.

A flagged passage may be retained only after a blind short review and an
explicit keep judgment on a PCM-verified excerpt of the exact final audio.
Original full-review findings remain unchanged.
"""
import wave
from pathlib import Path
from .pipeline import read,digest,validate


def confirmed_keeps(folder, media_hash, state, chunk, result):
    folder=Path(folder).resolve(); path=folder/'editorial-resolutions.json'
    if not path.is_file():return set()
    approved=set()
    try:resolutions=read(path)
    except (OSError,ValueError):return set()
    if not isinstance(resolutions,list):return set()
    root=folder.parent
    for r in resolutions:
        try:
            if r.get('decision')!='keep' or r.get('media_sha256')!=media_hash or r.get('source_audio_sha256')!=state['source_sha256']:continue
            if r.get('chunk_result_sha256')!=chunk['result_sha256']:continue
            idx=r['issue_index']
            if type(idx) is not int or not 0<=idx<len(result['issues']):continue
            issue=result['issues'][idx]
            if r.get('issue_quote')!=issue['quote'] or not r.get('reason','').strip():continue
            evidence={}
            for name in ('clip','blind_result','blind_screenshot','adjudication_result','adjudication_screenshot','blind_prompt','adjudication_prompt'):
                q=Path(r[name]['file']).resolve()
                if root not in q.parents or digest(q)!=r[name]['sha256']:raise ValueError('Evidence changed or escaped artifact')
                evidence[name]=q
            lo,hi=float(r['clip_start']),float(r['clip_end'])
            if not 0<=lo<hi or lo>chunk['start']+issue['start'] or hi<chunk['start']+issue['end']:continue
            with wave.open(str(state['source']),'rb') as src,wave.open(str(evidence['clip']),'rb') as clip:
                if (src.getnchannels(),src.getsampwidth(),src.getframerate())!=(1,2,16000):continue
                if (clip.getnchannels(),clip.getsampwidth(),clip.getframerate())!=(1,2,16000):continue
                frames=round((hi-lo)*16000)
                if clip.getnframes()!=frames or lo*16000+frames>src.getnframes():continue
                src.setpos(round(lo*16000));parent=src.readframes(frames);excerpt=clip.readframes(frames)
                # Independent decoding may alter only the resampler's 64 edge samples.
                if frames<256 or parent[128:-128]!=excerpt[128:-128]:continue
            blind=validate(read(evidence['blind_result']),hi-lo);judgment=validate(read(evidence['adjudication_result']),hi-lo)
            if not blind['transcript'].strip() or any(z['action']=='investigate' for z in blind['issues']):continue
            if not judgment['transcript'].strip() or not judgment['issues'] or any(z['action']!='keep' for z in judgment['issues']):continue
            if any(evidence[n].stat().st_size<10000 for n in ('blind_screenshot','adjudication_screenshot')):continue
            approved.add(idx)
        except (OSError,ValueError,KeyError,TypeError,wave.Error):continue
    return approved

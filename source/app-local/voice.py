"""Exact source intervals for one or many approved/candidate voice pieces."""
from pathlib import Path
from media import run,Cancelled

def prepare(store,clips,fps,start,end,folder,cancel):
 clips=sorted(clips,key=lambda c:c['start_frame']);cursor=start;parts=[]
 for c in clips:
  lo=max(start,c['start_frame']);hi=min(end,c['end_frame'])
  if hi<=lo:continue
  if lo!=cursor:raise ValueError('فجوة أو تداخل في مسار التعليق الصوتي')
  parts.append((c,lo,hi));cursor=hi
 if cursor!=end or not parts:raise ValueError('التعليق الصوتي لا يغطي مدة الإخراج كاملة')
 if len(parts)==1:
  c=parts[0][0];return c,store.asset(c['asset_id']),False
 folder=Path(folder)/'voice-pieces';folder.mkdir(exist_ok=True);files=[]
 for i,(c,lo,hi) in enumerate(parts):
  if cancel():raise Cancelled()
  asset=store.asset(c['asset_id']);duration=(hi-lo)/fps;source=(c['source_in_frame']+lo-c['start_frame'])/fps;path=folder/f'{i:05d}.wav';volume=c.get('properties',{}).get('volume',1)
  # Tiny fades suppress join clicks without deleting/overlapping any samples or changing duration.
  fade=min(.004,duration/8);filters=f'atrim=duration={duration},asetpts=PTS-STARTPTS,volume={volume},afade=t=in:st=0:d={fade},afade=t=out:st={duration-fade}:d={fade}'
  run(['-ss',source,'-i',asset['path'],'-t',duration,'-af',filters,'-ar','48000','-ac','2','-c:a','pcm_s16le',path],folder,cancel)
  files.append(path)
 manifest=folder/'concat.txt';manifest.write_text(''.join("file '"+str(p).replace("'","'\\''")+"'\n" for p in files));out=folder/'joined.wav';run(['-f','concat','-safe','0','-i',manifest,'-c:a','copy',out],folder,cancel)
 # Source-position zero is relative to this export window; no second trim at global start.
 c={'start_frame':start,'end_frame':end,'source_in_frame':0,'source_out_frame':end-start,'properties':{'volume':1}}
 return c,{'path':str(out),'kind':'audio'},True

"""Timed local music/effects bus; narration is never cut or moved by this adapter."""
from core import Invalid

def active(tracks,start,end):
 return [(kind,c)for kind in ('music','effects')for c in tracks.get(kind,{}).get('clips',[])if min(end,c['end_frame'])>max(start,c['start_frame'])]

def add(store,args,filters,voice,items,start,end,fps,first_input):
 if len(items)>128:raise Invalid('عدد طبقات الصوت أكبر من الحد المدعوم')
 duration=(end-start)/fps;groups={'music':[],'effects':[]};placements=[]
 for n,(kind,c) in enumerate(items):
  asset=store.asset(c['asset_id'])
  if asset['kind'] not in ('audio','video'):raise Invalid('طبقة الموسيقى أو المؤثر تحتاج ملفًا صوتيًا')
  lo=max(start,c['start_frame']);hi=min(end,c['end_frame']);seconds=(hi-lo)/fps;source=c.get('source_in_frame',0)+lo-c['start_frame'];volume=c.get('properties',{}).get('volume',.12 if kind=='music' else .4)
  delay=round((lo-start)*1000/fps);index=first_input+n;label='bed'+str(n);fade=min(.25 if kind=='music' else .015,seconds/4)
  args+=['-ss',source/fps,'-t',seconds,'-i',asset['path']]
  chain=f'[{index}:a]atrim=duration={seconds},asetpts=PTS-STARTPTS,volume={volume}'
  if lo==c['start_frame']:chain+=f',afade=t=in:st=0:d={fade}'
  if hi==c['end_frame']:chain+=f',afade=t=out:st={seconds-fade}:d={fade}'
  filters.append(chain+f',adelay={delay}:all=1,apad,atrim=duration={duration}[{label}]');groups[kind].append(label)
  placements.append({'track':kind,'asset_id':asset['id'],'start_frame':lo,'end_frame':hi,'source_in_frame':source,'volume':volume})
 def bus(kind):
  labels=groups[kind]
  if not labels:return None
  label=kind+'bus';filters.append(''.join('['+x+']'for x in labels)+f'amix=inputs={len(labels)}:duration=longest:normalize=0[{label}]');return label
 music=bus('music');effects=bus('effects');labels=[voice]
 if music:
  filters.append(f'[{voice}]asplit=2[spokenbus][sidebus]');filters.append(f'[{music}][sidebus]sidechaincompress=threshold=0.035:ratio=8:attack=20:release=650[duckbus]');labels=['spokenbus','duckbus']
 if effects:labels.append(effects)
 if len(labels)==1:return '['+voice+']',placements
 filters.append(''.join('['+x+']'for x in labels)+f'amix=inputs={len(labels)}:duration=first:normalize=0,alimiter=limit=0.95:level=0:latency=1,atrim=duration={duration}[mixedbus]')
 return '[mixedbus]',placements

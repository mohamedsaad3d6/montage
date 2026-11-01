"""Waveform data from verified local analysis PCM; not invented timeline decorations."""
import json,wave,array,sys
from pathlib import Path
from core import Invalid
from media import file_hash

def peaks(store,job_id,bins=800):
 with store.connect() as c:j=store.one(c,'SELECT * FROM jobs WHERE id=?',(job_id,))
 if j['kind'] not in ['transcribe','editorial_plan'] or j['status']!='completed':raise Invalid('التحليل الصوتي غير مكتمل')
 result=json.loads(j['result']);path=Path(result['wave_file']).resolve()
 if store.root not in path.parents or file_hash(path)!=result.get('wave_sha256'):raise Invalid('الصوت الذي بُنيت عليه الموجة تغير')
 with wave.open(str(path),'rb') as f:
  if f.getsampwidth()!=2 or f.getnchannels()!=1 or not 0<f.getnframes()<=f.getframerate()*3600:raise Invalid('صيغة موجة غير مدعومة')
  n=f.getnframes();bucket=max(1,(n+bins-1)//bins);values=[]
  for _ in range(bins):
   block=f.readframes(bucket)
   if not block:break
   samples=array.array('h');samples.frombytes(block)
   if sys.byteorder!='little':samples.byteswap()
   values.append(round(max(abs(min(samples)),abs(max(samples)))/32768,5))
  return {'job':job_id,'revision':j['revision'],'audio_sha256':result['wave_sha256'],'duration':n/f.getframerate(),'peaks':values,'editorial_quality_proven':False}

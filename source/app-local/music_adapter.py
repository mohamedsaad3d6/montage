"""Offline original synthesized score, bounded independent cues; no external service fallback."""
import os,json,math,subprocess,time,signal
from pathlib import Path
from media import ROOT,tool,run,probe,file_hash,Cancelled
from core import Invalid

def generate(store,rev,folder,options,cancel):
 seconds=options.get('seconds',rev['timeline']['duration_frames']/rev['timeline']['fps']or 24)
 seed=options.get('seed',7)
 if type(seconds)not in (int,float)or not math.isfinite(seconds)or not 6<=seconds<=3600 or type(seed)is not int or not 0<=seed<2**31:raise Invalid('مدة الموسيقى بين ٦ ثوانٍ وساعة وبذرة صالحة')
 python=Path(os.environ.get('MONTAJ_ML_PYTHON',str(ROOT.parent/'AI agent/monteer_data/envs/ml/bin/python')))
 if not python.is_file():raise Invalid('بيئة الموسيقى المحلية غير متاحة؛ لا بديل خارجي تلقائي')
 folder=Path(folder);n=math.ceil(seconds/60);length=seconds/n;files=[];cues=[]
 env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','PYTHONPYCACHEPREFIX':str(folder/'cache/pyc'),'XDG_CACHE_HOME':str(folder/'cache'),'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','OMP_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'2'}
 for i in range(n):
  path=folder/f'cue-{i:03d}.wav'
  with (folder/f'cue-{i:03d}.log').open('wb')as log:
   p=subprocess.Popen([str(python),str(ROOT/'engine/monteer/music/code_bed.py'),'--seconds',str(length),'--seed',str(seed+i*997),'--out',str(path)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,env=env,cwd=folder)
   from process_guard import wait
   wait(p,cancel,timeout_seconds=300)
   if p.returncode:raise Invalid('تعذر توليد الموسيقى المحلية؛ لم نستدعِ خدمة خارجية')
  files.append(path);cues.append({'seed':seed+i*997,'duration_seconds':length,'file_sha256':file_hash(path)})
 manifest=folder/'music-concat.txt';manifest.write_text(''.join("file '"+str(x).replace("'","'\\''")+"'\n"for x in files));out=folder/'original-music.m4a'
 run(['-f','concat','-safe','0','-i',manifest,'-af','loudnorm=I=-24:TP=-3:LRA=7','-ar','48000','-ac','2','-c:a','aac','-b:a','192k','-t',seconds,out],folder,cancel)
 info=probe(out);actual=float(info['format']['duration'])
 if abs(actual-seconds)>.05 or not any(x['codec_type']=='audio'for x in info['streams']):raise Invalid('مدة الموسيقى لا تطابق المطلوب')
 asset=store.add_asset(rev['project'],str(out),actual,'audio');metadata={'own_original':True,'procedural':True,'audio_role':'music','synthesis_manifest':cues,'generator':'local_code_bed','uses_samples':False,'contains_synthesized_speech':False,'editorial_listening_approved':False}
 with store.connect()as c:c.execute("UPDATE assets SET name=?,source_type='generated',metadata=? WHERE id=?",('موسيقى أصلية للحلقة.m4a',json.dumps(metadata,ensure_ascii=False),asset))
 return {'asset_id':asset,'kind':'original_procedural_music','seconds':actual,'cue_count':n,'file_sha256':file_hash(out),'generator':'local_code_bed','external_calls':0,'timeline_changed':False,'requires_listening_review':True}

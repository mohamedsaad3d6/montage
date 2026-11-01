"""Refine uncertain ASR timing near acoustic silence; preserve labels and all rejected estimates."""
import copy,json,os,subprocess,time,wave
from pathlib import Path
from editorial import norm,silence_proposals
from media import ROOT,file_hash,Cancelled

def refine(wav,words,folder,cancel):
 folder=Path(folder);folder.mkdir(exist_ok=True);wav=Path(wav)
 with wave.open(str(wav),'rb') as f:duration=f.getnframes()/f.getframerate()
 gaps=silence_proposals(wav,[]);windows=[]
 for gap in gaps:
  if gap['source_end']-gap['source_start']>10:continue
  start=max(0,gap['source_start']-4);end=min(duration,gap['source_end']+4)
  selected=[(i,w) for i,w in enumerate(words) if start<=(w['s']+w['e'])/2<end]
  if not selected:continue
  start=max(0,min(start,selected[0][1]['s']-.4));end=min(duration,max(end,selected[-1][1]['e']+.4))
  if end-start>30:continue
  if windows and start<=windows[-1]['end'] and max(end,windows[-1]['end'])-windows[-1]['start']<=30:
   start=windows.pop()['start'];selected=[(i,w) for i,w in enumerate(words) if start<=(w['s']+w['e'])/2<end]
  windows.append({'start':start,'end':end,'words':[{'index':i,'normalized':norm(w['w'])} for i,w in selected]})
 if not windows:return words,{'status':'no_bounded_silence_windows','refined_words':0}
 python=os.environ.get('MONTAJ_ML_PYTHON',str(ROOT.parent/'AI agent/monteer_data/envs/ml/bin/python'))
 model=os.environ.get('MONTAJ_CTC_MODEL',str(ROOT.parent/'AI agent/monteer_data/models/wav2vec2-egyptian'))
 output=folder/'forced-words.json';config=folder/'forced-input.json';config.write_text(json.dumps({'wav':str(wav),'model':model,'windows':windows,'output':str(output)},ensure_ascii=False))
 env={**os.environ,'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HUB_DISABLE_IMPLICIT_TOKEN':'1','HF_HUB_DISABLE_TELEMETRY':'1','HF_HOME':str(folder/'cache/hf'),'XDG_CACHE_HOME':str(folder/'cache'),'PYTHONDONTWRITEBYTECODE':'1'}
 with (folder/'forced.log').open('wb') as log:
  proc=subprocess.Popen([python,str(ROOT/'app-local/forced_runner.py'),str(config)],stdout=log,stderr=log,env=env,cwd=folder)
  while proc.poll() is None:
   if cancel():proc.terminate();proc.wait();raise Cancelled()
   time.sleep(.1)
  if proc.returncode:raise ValueError('تعذرت محاذاة حدود الكلمات؛ لا قص عند التعارض')
 data=json.loads(output.read_text());by_index={}
 for item in data['words']:
  if item['alignment_mean_posterior']<.7 or item['alignment_min_char_posterior']<.05:continue
  by_index.setdefault(item['index'],[]).append(item)
 result=copy.deepcopy(words);count=0
 for index,items in by_index.items():
  if any(abs(a['s']-b['s'])>.15 or abs(a['e']-b['e'])>.15 for a in items for b in items):continue
  best=max(items,key=lambda x:x['alignment_mean_posterior']);word=result[index]
  if best['e']<=best['s'] or best['s']<0 or best['e']>duration:continue
  word['original_asr_interval']=[word['s'],word['e']];word.update(s=best['s'],e=best['e'],timing_method=best['method'],alignment_mean_posterior=best['alignment_mean_posterior']);count+=1
 return result,{'status':'bounded_acoustic_alignment','refined_words':count,'file':str(output),'sha256':file_hash(output),'window_limit_seconds':30,'posterior_is_not_editorial_accuracy':True,'original_word_labels_preserved':True}

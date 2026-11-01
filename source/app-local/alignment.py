"""Second local Egyptian CTC pass. Read-only model; isolated caches per job."""
import json,os,subprocess,time
from pathlib import Path
from media import ROOT,Cancelled

def literal_words(wav,folder,cancel):
 folder=Path(folder);runtime=folder/'ctc-runtime';models=runtime/'models';models.mkdir(parents=True,exist_ok=True)
 source=Path(os.environ.get('MONTAJ_CTC_MODEL',str(ROOT.parent/'AI agent/monteer_data/models/wav2vec2-egyptian'))).resolve()
 python=Path(os.environ.get('MONTAJ_ML_PYTHON',str(ROOT.parent/'AI agent/monteer_data/envs/ml/bin/python')))
 if not source.is_dir() or not python.is_file():raise ValueError('محاذاة الكلمات الثانية غير متاحة؛ لا قص تلقائي')
 out=folder/'literal-words.json';env={**os.environ,'MONTEER_DATA':str(runtime),'MONTAJ_CTC_MODEL':str(source),'MONTEER_KEYS':str(folder/'no-credentials.json'),'MONTEER_CHANNELS':str(folder/'no-channels'),'HF_HOME':str(runtime/'cache/hf'),'XDG_CACHE_HOME':str(runtime/'cache'),'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1','HF_HUB_DISABLE_IMPLICIT_TOKEN':'1','PYTHONDONTWRITEBYTECODE':'1','PYTHONPATH':str(ROOT/'engine')}
 with (folder/'ctc.log').open('wb') as log:
  p=subprocess.Popen([str(python),'-m','monteer.cut.ctc_words',str(wav),str(out)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=env,cwd=folder)
  while p.poll() is None:
   if cancel():
    p.terminate()
    try:p.wait(timeout=5)
    except subprocess.TimeoutExpired:p.kill();p.wait()
    raise Cancelled()
   time.sleep(.1)
  if p.returncode:raise ValueError('تعذرت محاذاة الكلمات الثانية؛ لم تُطبق قصّات')
 data=json.loads(out.read_text())
 if not data.get('words'):raise ValueError('المحاذاة الثانية لم تثبت وجود كلمات؛ لا قص تلقائي')
 return data['words']


def breath_candidates(wav,folder,cancel):
 folder=Path(folder);python=os.environ.get('MONTAJ_ML_PYTHON',str(ROOT.parent/'AI agent/monteer_data/envs/ml/bin/python'));out=folder/'breath-candidates.json';env={**os.environ,'PYTHONPATH':str(ROOT/'engine'),'PYTHONDONTWRITEBYTECODE':'1','XDG_CACHE_HOME':str(folder/'cache'),'HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1'}
 with (folder/'breath.log').open('wb') as log:
  p=subprocess.Popen([python,str(ROOT/'app-local/alignment_runner.py'),str(wav),str(folder/'literal-words.json'),str(out)],stdout=log,stderr=log,cwd=folder,env=env)
  while p.poll() is None:
   if cancel():p.terminate();p.wait();raise Cancelled()
   time.sleep(.1)
  if p.returncode:raise ValueError('تعذر فحص النفس؛ لا يُفترض أنه سكتة')
 return json.loads(out.read_text())

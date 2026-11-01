"""Local readiness without credentials, requests, installation, or billing changes."""
import os,shutil
from pathlib import Path
from media import ROOT,tool

def report(data_root):
 checks=[]
 for name,label in [('ffmpeg','إخراج الفيديو'),('ffprobe','فحص الفيديو'),('whisper-cli','تفريغ العربي')]:
  try:ready=Path(tool(name)).is_file()
  except ValueError:ready=False
  checks.append({'id':name,'label':label,'ready':ready})
 model=Path(os.environ.get('MONTAJ_WHISPER_MODEL',str(ROOT.parent/'AI agent/monteer_data/models/whisper/ggml-large-v3-turbo.bin')))
 checks.append({'id':'asr_model','label':'نموذج التفريغ المحلي','ready':model.is_file()})
 checks.append({'id':'egyptian_model','label':'تحليل الكلمات المصري','ready':Path(os.environ.get('MONTAJ_CTC_MODEL',str(ROOT.parent/'AI agent/monteer_data/models/wav2vec2-egyptian'))).is_dir()})
 checks.append({'id':'node','label':'محرك الحركة المحلي','ready':bool(os.environ.get('MONTAJ_NODE') or shutil.which('node'))})
 checks.append({'id':'graphics_deps','label':'اعتماديات الموشن والعناوين','ready':(ROOT/'app-local/node_modules/@remotion/renderer').is_dir()})
 checks.append({'id':'browser','label':'محرك رسم العربي','ready':Path(os.environ.get('MONTAJ_CHROME','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')).is_file()})
 free=shutil.disk_usage(data_root).free
 checks.append({'id':'disk','label':'مساحة العمل تكفي للبدء','ready':free>=5*1024**3})
 return {'local_ready':all(x['ready'] for x in checks),'checks':checks,'free_gib':round(free/1024**3,1),
         'api_generation_verified':False,'studio_review_bridge_supported':True,'autonomous_browser_review':False,'automatic_episode':False,
         'company_deployment_verified':False,'credentials_included':False}

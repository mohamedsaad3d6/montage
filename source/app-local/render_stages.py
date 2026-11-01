"""Observed render stages, never guessed completion percentages or editorial approval."""
import json,os,time
from pathlib import Path
from core import Invalid
NAMES={'plan':'خطة الإخراج','materials':'تجهيز الخامات','graphics':'الجرافيك والعناوين','transitions':'الانتقالات','mix':'إعداد مزج الصوت','encode':'الدمج والترميز','technical':'الفحص الفني'}
def begin(folder,revision):
 data={'revision':revision,'stages':[{'id':key,'title':title,'status':'waiting'} for key,title in NAMES.items()],'publication_approved':False}
 save(folder,data)
def save(folder,data):
 path=Path(folder)/'render-stages.json';temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False));os.replace(temp,path)
def mark(folder,key,status):
 path=Path(folder)/'render-stages.json';data=json.loads(path.read_text());item=next(x for x in data['stages'] if x['id']==key);item['status']=status
 if status=='running':item['started']=time.time()
 if status in ['completed','not_required']:item['finished']=time.time()
 save(folder,data)
def describe(store,job_id):
 with store.connect() as c:j=store.one(c,'SELECT * FROM jobs WHERE id=?',(job_id,))
 if j['kind']!='render':raise Invalid('اختَر مهمة إخراج')
 path=store.root/'jobs'/j['id']/'render-stages.json'
 data=json.loads(path.read_text()) if path.is_file() else {'revision':j['revision'],'stages':[],'publication_approved':False}
 if data['revision']!=j['revision']:raise Invalid('سجل المراحل من نسخة أخرى')
 # A killed or failed worker cannot leave its last stage looking active.
 if j['status'] in ['failed','cancelled']:
  for item in data['stages']:
   if item['status']=='running':item.update(status=j['status'],terminal_state_source='job_status')
 return {**data,'job':job_id,'status':j['status'],'error':j['error'],'checkpoint':j['checkpoint'],'total':j['total'],'measured_stages':bool(data['stages']),'technical_completion_is_not_audio_review':True}

"""Audition and record human take choices. No timestamp becomes a speech deletion."""
import hashlib,json,math,time,wave
from pathlib import Path
from core import Invalid,Conflict,dump
from media import file_hash

def init(store):
 with store.connect() as c:c.execute('CREATE TABLE IF NOT EXISTS control_take_decisions(job TEXT,candidate TEXT,version INTEGER,revision TEXT,plan_sha256 TEXT,audio_sha256 TEXT,choice TEXT,selected_attempt INTEGER,reason TEXT,listened_all INTEGER,created REAL,PRIMARY KEY(job,candidate,version))')

def bound(store,job_id):
 with store.connect() as c:j=store.one(c,'SELECT * FROM jobs WHERE id=?',(job_id,))
 if j['kind']!='editorial_plan' or j['status']!='completed':raise Invalid('اختر تحليل تقطيع محليًا مكتملًا')
 r=json.loads(j.get('result') or '{}');source=store.asset(r.get('source_asset_id'));
 if source['project']!=j['project'] or source['hash']!=r.get('source_asset_sha256') or file_hash(store.resolve(source['path']))!=source['hash']:raise Invalid('الخام الذي بُني عليه التحليل تغير')
 folder=store.root/'jobs'/job_id
 paths={}
 for key,hash_key in [('plan_file','plan_sha256'),('wave_file','wave_sha256')]:
  path=Path(r.get(key,'')).resolve()
  if folder not in path.parents or not path.is_file() or file_hash(path)!=r.get(hash_key):raise Invalid('خطة المحاولات أو الصوت تغير؛ أعد التحليل قبل المراجعة')
  paths[key]=path
 with wave.open(str(paths['wave_file']),'rb') as wav:
  if wav.getnchannels()!=1 or wav.getsampwidth()!=2 or wav.getframerate()<=0:raise Invalid('صيغة صوت المقارنة غير مدعومة')
  duration=wav.getnframes()/wav.getframerate()
 if not 0<duration<=3600:raise Invalid('مدة صوت المقارنة غير صالحة')
 timeline=store.revision(j['revision'])['timeline']
 if abs(duration-timeline['duration_frames']/timeline['fps'])>max(.1,1/timeline['fps']):raise Invalid('ساعة صوت المقارنة لا تطابق نسخة الحلقة')
 plan=json.loads(paths['plan_file'].read_text());items=plan.get('retakes',[])
 if not isinstance(items,list) or len(items)>5000:raise Invalid('قائمة المحاولات غير صالحة')
 candidates=[];keys=set()
 for item in items:
  attempts=item.get('attempts',[])
  if not isinstance(attempts,list) or not 2<=len(attempts)<=12:raise Invalid('المقارنة تحتاج محاولتين على الأقل')
  out=[]
  for a in attempts:
   start,end=a.get('start'),a.get('end');text=a.get('text')
   if type(start) not in [int,float] or type(end) not in [int,float] or not math.isfinite(start) or not math.isfinite(end) or not 0<=start<end<=duration+.05 or not isinstance(text,str) or not 1<=len(text)<=6000:raise Invalid('حدود أو نص محاولة غير صالح')
   out.append({'start':start,'end':min(end,duration),'text':text})
  key='take-'+hashlib.sha256(json.dumps({'id':item.get('id'),'stream':item.get('word_stream','whisper'),'attempts':out},ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:24]
  if key in keys:raise Invalid('هوية مقارنة متكررة في الخطة')
  keys.add(key);candidates.append({'key':key,'analysis_id':item.get('id'),'word_stream':item.get('word_stream','whisper'),'approximate_word_matches':item.get('approximate_word_matches',0),'attempts':out,'requires_listening':True,'automatic_delete_allowed':False})
 return j,r,paths['wave_file'],duration,candidates

def describe(store,job_id):
 j,r,path,duration,candidates=bound(store,job_id);init(store);current=store.project(j['project'])['active']==j['revision']
 with store.connect() as c:rows=[dict(x) for x in c.execute('SELECT * FROM control_take_decisions WHERE job=? ORDER BY version DESC,created DESC',(job_id,))]
 for item in candidates:
  entries=[x for x in rows if x['candidate']==item['key']];item['decision']=entries[0] if entries else None;item['history_count']=len(entries)
 return {'job':job_id,'project':j['project'],'revision':j['revision'],'current_revision':current,'plan_sha256':r['plan_sha256'],'audio_sha256':r['wave_sha256'],'duration':duration,'candidates':candidates,'cuts_applied':False,'independent_review_granted':False,'reviewer_identity_verified':False}

def audio(store,job_id):return bound(store,job_id)[2]

def save(store,data):
 j,r,path,duration,candidates=bound(store,data['job']);init(store)
 if j['project']!=data.get('project'):raise Invalid('التحليل لا ينتمي لهذه الحلقة')
 item=next((x for x in candidates if x['key']==data.get('candidate')),None)
 if not item:raise Invalid('اختر مقارنة من نفس بصمة الخطة')
 if data.get('plan_sha256')!=r['plan_sha256'] or data.get('audio_sha256')!=r['wave_sha256']:raise Conflict('بصمة المقارنة تغيرت؛ حدّث الصفحة')
 choice=data.get('choice');selected=data.get('selected_attempt');reason=data.get('reason');listened=data.get('listened_all')
 if choice not in ['keep_attempt','intentional_repeat','needs_review']:raise Invalid('اختر قرارًا واضحًا للمحاولات')
 if not isinstance(reason,str) or not 6<=len(reason.strip())<=2000:raise Invalid('اكتب سبب القرار أو ما يحتاج مراجعة')
 if type(listened)!=bool:raise Invalid('حالة تأكيد السماع غير صالحة')
 if choice!='needs_review' and listened is not True:raise Invalid('اسمع كل المحاولات وأكد المقارنة قبل تسجيل اختيار')
 if choice=='keep_attempt':
  if type(selected)!=int or not 0<=selected<len(item['attempts']):raise Invalid('اختر المحاولة الأكمل والأوضح، دون أفضلية تلقائية للأخيرة')
 elif selected is not None:raise Invalid('هذا القرار لا يختار محاولة للحذف أو الإبقاء')
 with store.connect() as c:
  c.execute('BEGIN IMMEDIATE');p=store.one(c,'SELECT active FROM projects WHERE id=?',(j['project'],))
  if p['active']!=j['revision'] or data.get('expected_revision')!=p['active']:raise Conflict('نسخة الحلقة تغيرت؛ لا تسجل قرارًا على تحليل قديم')
  version=c.execute('SELECT COALESCE(MAX(version),0) FROM control_take_decisions WHERE job=? AND candidate=?',(j['id'],item['key'])).fetchone()[0]
  if type(data.get('expected_version'))!=int or version!=data['expected_version']:raise Conflict('قرار المحاولة تغير؛ حدّث الصفحة')
  c.execute('INSERT INTO control_take_decisions VALUES(?,?,?,?,?,?,?,?,?,?,?)',(j['id'],item['key'],version+1,j['revision'],r['plan_sha256'],r['wave_sha256'],choice,selected,reason.strip(),int(listened),time.time()))
 return {'version':version+1,'cuts_applied':False,'timeline_changed':False,'independent_review_granted':False}

def pending_count(store,job):
 """Navigation hint only. A saved human choice never opens a release gate."""
 r=json.loads(job.get('result') or '{}');count=r.get('retake_candidates',0)
 if type(count)!=int or count<=0:return 0
 init(store)
 with store.connect() as c:rows=[dict(x) for x in c.execute('SELECT candidate,choice,version FROM control_take_decisions WHERE job=? AND plan_sha256=? AND audio_sha256=? ORDER BY version DESC',(job['id'],r.get('plan_sha256'),r.get('wave_sha256')))]
 latest={}
 for row in rows:latest.setdefault(row['candidate'],row['choice'])
 return max(0,count-sum(choice in ['keep_attempt','intentional_repeat'] for choice in latest.values()))


def boundary_count(store,job):
 """Navigation hint only; repair endpoints recheck the exact audio and decisions."""
 r=json.loads(job.get('result') or '{}');init(store)
 with store.connect()as c:rows=c.execute('SELECT candidate,choice FROM control_take_decisions WHERE job=? AND plan_sha256=? AND audio_sha256=? ORDER BY version DESC',(job['id'],r.get('plan_sha256'),r.get('wave_sha256'))).fetchall()
 latest={}
 for row in rows:latest.setdefault(row['candidate'],row['choice'])
 return sum(choice=='keep_attempt' for choice in latest.values())

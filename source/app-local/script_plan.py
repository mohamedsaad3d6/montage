"""Evidence-based local script planning. Manual verification is never AI fact-checking."""
import datetime,hashlib,json,re,time,urllib.parse
from core import Invalid,Conflict,dump
DEFAULT={'topic':'','sources':[],'facts':[],'outline':[]}
MATERIALS={'presenter','card','map','archive','verified_news'}
def init(store):
 with store.connect() as c:c.execute('CREATE TABLE IF NOT EXISTS control_script_plans(project TEXT,version INTEGER,data TEXT,content_hash TEXT,approved_at REAL,PRIMARY KEY(project,version))')
def content_hash(data):return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def get(store,project):
 store.project(project);init(store)
 with store.connect() as c:r=c.execute('SELECT * FROM control_script_plans WHERE project=? ORDER BY version DESC LIMIT 1',(project,)).fetchone()
 if r:return {**dict(r),'data':json.loads(r['data']),'outline_approved':r['approved_at'] is not None,'automatic_research':False,'authenticated_approval':False}
 return {'project':project,'version':0,'data':json.loads(dump(DEFAULT)),'content_hash':content_hash(DEFAULT),'approved_at':None,'outline_approved':False,'automatic_research':False,'authenticated_approval':False}
def text(value,limit,required=False):
 if not isinstance(value,str) or len(value)>limit or (required and not value.strip()):raise Invalid('النص مطلوب وبطول مناسب')
 return value.strip()
def date(value,required=False):
 value=text(value,10,required)
 if value:
  try:datetime.date.fromisoformat(value)
  except ValueError:raise Invalid('التاريخ بصيغة سنة-شهر-يوم')
 return value

def normalize(data):
 if not isinstance(data,dict) or set(data)!=set(DEFAULT):raise Invalid('خطة السكريبت غير صالحة')
 out={'topic':text(data['topic'],300),'sources':[],'facts':[],'outline':[]}
 for key,limit in [('sources',100),('facts',200),('outline',50)]:
  if not isinstance(data[key],list) or len(data[key])>limit:raise Invalid('قائمة كبيرة أو غير صالحة')
 sources=set();facts=set();sections=set()
 for s in data['sources']:
  if not isinstance(s,dict):raise Invalid('مصدر غير صالح')
  id=text(s.get('id'),80,True)
  if id in sources:raise Invalid('هوية مصدر مكررة')
  sources.add(id);url=text(s.get('url'),2000,True);u=urllib.parse.urlsplit(url)
  if u.scheme not in ['https','http'] or not u.hostname or u.username or u.password:raise Invalid('رابط المصدر يجب أن يكون عامًا بصيغة HTTP أو HTTPS دون بيانات دخول')
  if s.get('kind') not in ['news','economy','legal','other'] or s.get('language') not in ['ar','en','other']:raise Invalid('نوع أو لغة المصدر غير صالحة')
  out['sources'].append({'id':id,'title':text(s.get('title'),300,True),'url':url,'date':date(s.get('date','')),'kind':s['kind'],'language':s['language']})
 for f in data['facts']:
  if not isinstance(f,dict):raise Invalid('حقيقة غير صالحة')
  id=text(f.get('id'),80,True)
  if id in facts:raise Invalid('هوية معلومة مكررة')
  facts.add(id);source=f.get('source_id');verified=f.get('verified',False);quote=text(f.get('quote',''),3000)
  if source not in sources:raise Invalid('كل معلومة تحتاج مصدرًا مسجلًا')
  if type(verified)!=bool:raise Invalid('حالة التأكيد غير صالحة')
  if verified and (not quote or not next(s for s in out['sources'] if s['id']==source)['date']):raise Invalid('التأكيد اليدوي يحتاج اقتباسًا داعمًا وتاريخ المصدر')
  out['facts'].append({'id':id,'claim':text(f.get('claim'),2000,True),'source_id':source,'quote':quote,'verified':verified})
 last=0
 for part in data['outline']:
  if not isinstance(part,dict):raise Invalid('جزء هيكل غير صالح')
  id=text(part.get('id'),80,True);start=part.get('start');end=part.get('end');refs=part.get('fact_ids',[])
  if id in sections:raise Invalid('جزء هيكل مكرر')
  sections.add(id)
  if type(start)!=int or type(end)!=int or not last<=start<end<=14400:raise Invalid('ترتيب وتوقيت أجزاء الهيكل غير صالحين')
  last=end
  if part.get('material') not in MATERIALS:raise Invalid('نوع المادة غير صالح')
  if not isinstance(refs,list) or any(x not in facts for x in refs) or len(refs)!=len(set(refs)):raise Invalid('مرجع معلومة الهيكل غير صالح')
  out['outline'].append({'id':id,'title':text(part.get('title'),300,True),'summary':text(part.get('summary',''),3000),'material':part['material'],'start':start,'end':end,'fact_ids':refs})
 return out

def save(store,payload):
 project=payload['project'];current=get(store,project);data=normalize(payload.get('data'))
 previous_facts={f['id']:f for f in current['data']['facts']};previous_sources={s['id']:s for s in current['data']['sources']};sources={s['id']:s for s in data['sources']}
 for f in data['facts']:
  old=previous_facts.get(f['id'])
  if old and f['verified'] and (any(f[k]!=old[k] for k in ['claim','quote','source_id']) or previous_sources.get(f['source_id'])!=sources.get(f['source_id'])):f['verified']=False
 h=content_hash(data)
 with store.connect() as c:
  c.execute('BEGIN IMMEDIATE');r=c.execute('SELECT * FROM control_script_plans WHERE project=? ORDER BY version DESC LIMIT 1',(project,)).fetchone();version=r['version'] if r else 0
  if type(payload.get('expected_version'))!=int or version!=payload['expected_version']:raise Conflict('الخطة تغيرت؛ حدّث الصفحة')
  approved=r['approved_at'] if r and r['content_hash']==h else None
  c.execute('INSERT INTO control_script_plans VALUES(?,?,?,?,?)',(project,version+1,dump(data),h,approved))
 return get(store,project)

def approve(store,payload):
 project=payload['project'];current=get(store,project);data=current['data']
 if type(payload.get('expected_version'))!=int or current['version']!=payload['expected_version'] or current['content_hash']!=payload.get('content_hash'):raise Conflict('اعتمد نفس نسخة الخطة المعروضة بعد حفظها')
 if not data['topic'] or not data['sources'] or not data['facts'] or not data['outline']:raise Invalid('أكمل الموضوع والمصادر والمعلومات والهيكل قبل الاعتماد')
 if not all(f['verified'] for f in data['facts']):raise Invalid('هناك معلومات لم تتأكد يدويًا؛ لا تعتمد الهيكل بعد')
 if payload.get('confirm_manual_review') is not True:raise Invalid('راجع بنفسك المصادر والهيكل أولًا')
 with store.connect() as c:
  c.execute('BEGIN IMMEDIATE');latest=c.execute('SELECT MAX(version) FROM control_script_plans WHERE project=?',(project,)).fetchone()[0]
  if latest!=current['version']:raise Conflict('الخطة تغيرت أثناء الاعتماد')
  c.execute('UPDATE control_script_plans SET approved_at=? WHERE project=? AND version=?',(time.time(),project,current['version']))
 return get(store,project)

def scaffold(store,project):
 plan=get(store,project)
 if not plan['outline_approved']:raise Invalid('الهيكل الحالي لم يعتمد بعد')
 data=plan['data'];facts={f['id']:f for f in data['facts']}
 return {'text':'\n\n'.join(part['title']+'\n'+part['summary']+('' if not part['fact_ids'] else '\n'+'\n'.join(facts[id]['claim'] for id in part['fact_ids']))for part in data['outline']),'source':'outline_scaffold','plan_hash':plan['content_hash'],'generated_by_model':False}

"""Local revision registry. No legacy engine imports or external services."""
import contextlib, hashlib, json, math, os, sqlite3, time, uuid
from pathlib import Path
class Invalid(ValueError): pass
class Conflict(Invalid): pass
def uid(): return uuid.uuid4().hex
def dump(x): return json.dumps(x,ensure_ascii=False)
def fingerprint(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
class Store:
 def __init__(self,root,allowed):
  self.root=Path(root).resolve();self.root.mkdir(parents=True,exist_ok=True);self.db=self.root/'montaj.sqlite3';self.allowed=[Path(x).resolve() for x in allowed];os.chmod(self.root,0o700)
  with self.connect() as c:c.executescript('''
   PRAGMA journal_mode=WAL;
   CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,name TEXT NOT NULL,active TEXT,created REAL);
   CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,project TEXT NOT NULL,path TEXT,kind TEXT,name TEXT,duration REAL,hash TEXT,FOREIGN KEY(project) REFERENCES projects(id));
   CREATE TABLE IF NOT EXISTS revisions(id TEXT PRIMARY KEY,project TEXT,parent TEXT,number INTEGER,timeline TEXT,status TEXT,summary TEXT,created REAL,FOREIGN KEY(project) REFERENCES projects(id));
   CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,project TEXT,revision TEXT,kind TEXT,status TEXT,checkpoint INTEGER DEFAULT 0,total INTEGER DEFAULT 0,error TEXT,result TEXT,worker_pid INTEGER,created REAL);
   CREATE TABLE IF NOT EXISTS feedback(id TEXT PRIMARY KEY,project TEXT,revision TEXT,time_ms INTEGER,category TEXT,note TEXT,status TEXT,created REAL);
  ''')
  self.migrate()
 def migrate(self):
  with self.connect() as c:
   names={r[1] for r in c.execute('PRAGMA table_info(jobs)')}
   if 'options' not in names:c.execute("ALTER TABLE jobs ADD COLUMN options TEXT NOT NULL DEFAULT '{}'")
   asset_cols={r[1] for r in c.execute('PRAGMA table_info(assets)')}
   if 'source_type' not in asset_cols:c.execute("ALTER TABLE assets ADD COLUMN source_type TEXT NOT NULL DEFAULT 'uploaded'")
   if 'metadata' not in asset_cols:c.execute("ALTER TABLE assets ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
   feedback_cols={r[1] for r in c.execute('PRAGMA table_info(feedback)')}
   if 'output_job' not in feedback_cols:c.execute('ALTER TABLE feedback ADD COLUMN output_job TEXT')
   c.execute('CREATE TABLE IF NOT EXISTS control_job_activity(job TEXT,sequence INTEGER,phase TEXT,started REAL,finished REAL,PRIMARY KEY(job,sequence))')
   c.execute('CREATE TABLE IF NOT EXISTS control_trash(entity TEXT,id TEXT,project TEXT,name TEXT,version INTEGER,deleted_at REAL,reason TEXT,updated REAL,PRIMARY KEY(entity,id))')
   c.execute('CREATE TABLE IF NOT EXISTS control_trash_events(id TEXT PRIMARY KEY,entity TEXT,target TEXT,version INTEGER,event TEXT,created REAL,details TEXT)')
   c.execute('CREATE TABLE IF NOT EXISTS rules(id TEXT PRIMARY KEY,project TEXT,feedback TEXT,key TEXT,value REAL,status TEXT,created REAL)')
 @contextlib.contextmanager
 def connect(self):
  c=sqlite3.connect(self.db,timeout=20);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
  try:
   yield c
   c.commit()
  except Exception:
   c.rollback();raise
  finally:c.close()
 def one(self,c,q,args=()):
  r=c.execute(q,args).fetchone()
  if r is None:raise Invalid('العنصر غير موجود')
  return dict(r)
 def projects(self):
  with self.connect() as c:return [dict(r) for r in c.execute("SELECT * FROM projects p WHERE NOT EXISTS(SELECT 1 FROM control_trash t WHERE t.entity='project' AND t.id=p.id AND t.deleted_at IS NOT NULL) ORDER BY created DESC")]
 def create(self,name):
  name=str(name).strip()
  if not name or len(name)>150:raise Invalid('اسم المشروع مطلوب ولا يتجاوز ١٥٠ حرفًا')
  p=uid();r=uid();tl={'fps':24,'duration_frames':0,'tracks':[{'id':k,'kind':k,'clips':[]} for k in ['video','text','voice','graphics','music','effects']]}
  with self.connect() as c:
   c.execute('INSERT INTO projects VALUES(?,?,?,?)',(p,name,r,time.time()));c.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?,?,?)',(r,p,None,1,dump(tl),'draft','إنشاء المشروع',time.time()))
  from profiles import apply_default
  apply_default(self,p)
  return self.project(p)
 def revision(self,r):
  with self.connect() as c:v=self.one(c,'SELECT * FROM revisions WHERE id=?',(r,))
  v['timeline']=json.loads(v['timeline']);return v
 def project(self,p):
  with self.connect() as c:
   v=self.one(c,'SELECT * FROM projects WHERE id=?',(p,));v['assets']=[dict(r) for r in c.execute('SELECT id,project,kind,name,duration,hash,source_type,metadata FROM assets a WHERE project=? AND NOT EXISTS(SELECT 1 FROM control_trash t WHERE t.entity="asset" AND t.id=a.id AND t.deleted_at IS NOT NULL)',(p,))];v['revisions']=[dict(r) for r in c.execute('SELECT id,parent,number,status,summary FROM revisions WHERE project=? ORDER BY number DESC',(p,))];v['jobs']=[dict(r) for r in c.execute('SELECT * FROM jobs WHERE project=? ORDER BY created DESC',(p,))];v['feedback']=[dict(r) for r in c.execute('SELECT * FROM feedback WHERE project=? ORDER BY created DESC',(p,))]
  with self.connect() as c:
   versions={r['id']:r['version'] for r in c.execute("SELECT id,version FROM control_trash WHERE entity='asset' AND project=?",(p,))}
  from job_activity import attach
  attach(self,p,v['jobs'])
  for a in v['assets']:a['lifecycle_version']=versions.get(a['id'],0)
  v['revision']=self.revision(v['active'])
  from lifecycle import missing
  v['unavailable_assets']=missing(self,p)
  with self.connect() as c:
   state=c.execute("SELECT version,deleted_at FROM control_trash WHERE entity='project' AND id=?",(p,)).fetchone()
  v['lifecycle']={'version':state['version'] if state else 0,'deleted':bool(state and state['deleted_at'] is not None)}
  with self.connect() as c:v['rules']=[dict(r) for r in c.execute('SELECT * FROM rules WHERE project=? ORDER BY created DESC',(p,))]
  from profiles import assigned
  v['style_profile']=assigned(self,p)
  return v
 def resolve(self,path):
  p=Path(path).expanduser().resolve()
  if not p.is_file() or not any(p==a or a in p.parents for a in self.allowed):raise Invalid('اختَر ملفًا داخل مجلد المواد المسموح به')
  if p.suffix.lower() not in ['.mp4','.mov','.webm','.mkv','.ogv','.wav','.mp3','.m4a','.opus','.ogg','.flac','.png','.jpg','.jpeg','.webp','.txt','.srt','.docx','.md']:raise Invalid('نوع الملف غير مدعوم')
  return p
 def add_asset(self,project,path,duration,kind):
  from lifecycle import open_project
  open_project(self,project);self.project(project);p=self.resolve(path)
  if kind not in ['video','audio','image','script']:raise Invalid('نوع الأصل غير صحيح')
  if not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<0:raise Invalid('مدة غير صالحة')
  h=fingerprint(p);a=uid()
  with self.connect() as c:
   c.execute('BEGIN IMMEDIATE');open_project(self,project,c);c.execute('INSERT INTO assets(id,project,path,kind,name,duration,hash) VALUES(?,?,?,?,?,?,?)',(a,project,str(p),kind,p.name,duration,h))
  return a
 def asset(self,a):
  with self.connect() as c:return self.one(c,'SELECT * FROM assets WHERE id=?',(a,))
 def validate(self,p,t):
  from lifecycle import open_project,open_asset
  open_project(self,p)
  if not isinstance(t,dict) or type(t.get('fps'))!=int or not 1<=t['fps']<=120:raise Invalid('معدل الإطارات غير صالح')
  if type(t.get('duration_frames'))!=int or not 0<=t['duration_frames']<=120*60*60*24:raise Invalid('مدة التايملاين غير صالحة')
  if not isinstance(t.get('tracks'),list) or len(t['tracks'])>32:raise Invalid('المسارات غير صالحة')
  if t.get('primary_video_asset_id'):
   open_asset(self,t['primary_video_asset_id']);a=self.asset(t['primary_video_asset_id'])
   if a['project']!=p or a['kind']!='video':raise Invalid('الفيديو الخام الأساسي غير صالح')
  ids=set();clipids=set();visual_spans=[]
  primary=t.get('primary_video_asset_id') or next((c.get('asset_id') for tr in t['tracks'] if tr.get('kind')=='voice' for c in tr.get('clips',[]) if c.get('asset_id')),None)
  primary_hash=self.asset(primary)['hash'] if primary else None
  for tr in t['tracks']:
   if tr.get('kind') not in ['video','text','voice','graphics','music','effects'] or not tr.get('id') or tr['id'] in ids:raise Invalid('مسار مكرر أو غير صالح')
   if 'locked' in tr and type(tr['locked'])!=bool:raise Invalid('حالة قفل المسار غير صالحة')
   ids.add(tr['id'])
   if not isinstance(tr.get('clips'),list) or len(tr['clips'])>20000:raise Invalid('لقطات غير صالحة')
   spans=[];source_spans=[]
   for x in tr['clips']:
    if not x.get('id') or x['id'] in clipids:raise Invalid('هوية لقطة مكررة')
    clipids.add(x['id']);s=x.get('start_frame');e=x.get('end_frame')
    if type(s)!=int or type(e)!=int or not 0<=s<e<=t['duration_frames']:raise Invalid('حدود لقطة غير صالحة')
    props=x.get('properties',{})
    if not isinstance(props,dict):raise Invalid('خصائص غير صالحة')
    if 'color' in props:
     if tr['kind']!='video':raise Invalid('ضبط اللون الحالي لمسار الصورة فقط')
     from color_grade import normalized
     normalized(props['color'])
    vol=props.get('volume',1)
    if type(vol) not in [int,float] or not math.isfinite(vol) or not 0<=vol<=2:raise Invalid('مستوى الصوت خارج النطاق')
    if len(str(props.get('text','')))>1000:raise Invalid('عنوان طويل')
    if x.get('asset_id'):
     open_asset(self,x['asset_id']);a=self.asset(x['asset_id'])
     if a['project']!=p:raise Invalid('الأصل من مشروع آخر')
     si=x.get('source_in_frame',0);so=x.get('source_out_frame')
     if type(si)!=int or type(so)!=int or not 0<=si<so or (a['kind'] in ['video','audio'] and so>a['duration']*t['fps']+1):raise Invalid('حدود المصدر غير صالحة')
     if a['kind'] in ['video','audio'] and so-si!=e-s:raise Invalid('تغيير سرعة التشغيل غير مدعوم بعد')
     if tr['kind'] in ['video','graphics'] and a['hash']!=primary_hash:
      if any(a['hash']==h and (a['kind']=='image' or si<end_ and so>begin) for h,begin,end_ in visual_spans):raise Invalid('نفس الصورة أو نفس مجال الفيديو مستخدم بالفعل؛ اختَر خامة مستقلة')
      visual_spans.append((a['hash'],si,so))
    elif tr['kind'] not in ['text','graphics']:raise Invalid('لقطة بلا أصل')
    if tr['kind'] in ['video','voice'] and any(s<y and e>z for z,y in spans):raise Invalid('تداخل غير مصرح في المسار؛ الانتقالات تحتاج نموذج مقابض مستقل')
    if tr['kind']=='voice' and x.get('asset_id'):
     key=self.asset(x['asset_id'])['hash'];a=x.get('source_in_frame',0);b=x['source_out_frame']
     if any(key==k and a<y and b>z for k,z,y in source_spans):raise Invalid('تكرار نفس مجال الصوت في التايملاين ممنوع لتجنب إعادة الكلام')
     source_spans.append((key,a,b))
    spans.append((s,e))
 def save(self,p,expected,t,summary='تعديل التايملاين',trusted_cut_proof=False,commit_guard=None):
  t=json.loads(dump(t));old=self.project(p)['revision']['timeline']
  if not trusted_cut_proof:
   def voice_signature(x):return [[c.get('asset_id'),c['start_frame'],c['end_frame'],c.get('source_in_frame'),c.get('source_out_frame')] for tr in x['tracks'] if tr['kind']=='voice' for c in tr['clips']]
   if old.get('cutting_proof') and voice_signature(old)==voice_signature(t):t['cutting_proof']=old['cutting_proof']
   else:t.pop('cutting_proof',None)
  byid={tr['id']:tr for tr in t['tracks']}
  for tr in old['tracks']:
   if tr.get('locked') and (tr['id'] not in byid or tr['clips']!=byid[tr['id']]['clips']):raise Invalid('المسار مقفول؛ افتحه قبل تغيير عناصره')
  self.validate(p,t);r=uid()
  with self.connect() as c:
   c.execute('BEGIN IMMEDIATE');from lifecycle import open_project
   open_project(self,p,c)
   from lifecycle import open_asset
   used={clip.get('asset_id') for tr in t['tracks'] for clip in tr['clips']}|{t.get('primary_video_asset_id')}
   for asset in used:
    if asset:open_asset(self,asset,c)
   if commit_guard:commit_guard(c)
   pr=self.one(c,'SELECT * FROM projects WHERE id=?',(p,))
   if pr['active']!=expected:raise Conflict('النسخة اتغيرت؛ حدّث الصفحة قبل الحفظ')
   n=c.execute('SELECT COALESCE(MAX(number),0)+1 FROM revisions WHERE project=?',(p,)).fetchone()[0];c.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?,?,?)',(r,p,expected,n,dump(t),'draft',summary,time.time()));c.execute('UPDATE projects SET active=? WHERE id=?',(r,p))
  return self.project(p)
 def activate(self,p,r):
  v=self.revision(r)
  if v['project']!=p:raise Invalid('نسخة من مشروع آخر')
  from lifecycle import usable
  with self.connect() as c:
   c.execute('BEGIN IMMEDIATE');usable(self,p,r,c);c.execute('UPDATE projects SET active=? WHERE id=?',(r,p))
  return self.project(p)
 def enqueue(self,p,kind='asset_integrity',options=None,revision=None):
  if kind not in ['codex_plan','take_assess','reference_refine','input_prepare','asset_integrity','render','transcribe','audio_review','generate_graphic','generate_music','editorial_plan','shot_plan','inspect_asset','archive_search','archive_collect','storyblocks_search','storyblocks_collect','storyblocks_autoselect','preview_transition']:raise Invalid('نوع مهمة غير صالح')
  v=self.project(p);j=uid()
  if revision is not None:
   frozen=self.revision(revision)
   if frozen['project']!=p:raise Invalid('النسخة من مشروع آخر')
   v={**v,'active':revision}
  if kind=='storyblocks_search':
   from storyblocks_connector import options_for
   options=options_for(options)
  if kind=='storyblocks_collect':
   from storyblocks_connector import selected
   selected(self,p,v['active'],options)
  if kind=='audio_review':
   if (options or {}).get('consent_google_audio') is not True:raise Invalid('المراجعة الخارجية تحتاج موافقة تخص هذا الملف')
   with self.connect() as c:
    target=self.one(c,'SELECT * FROM jobs WHERE id=?',((options or {}).get('output_job'),))
    if target['project']!=p or target['revision']!=v['active'] or target['kind']!='render' or target['status']!='completed':raise Invalid('ناتج المراجعة غير صالح')
    target_result=json.loads(target['result']);identity=target_result.get('audio_hash') or target_result.get('file_sha256')
    if not identity:raise Invalid('ناتج بلا بصمة صوت أو ملف؛ لا إرسال خارجي')
    for previous in c.execute("SELECT * FROM jobs WHERE project=? AND kind='audio_review'",(p,)).fetchall():
     prior_options=json.loads(previous['options'] or '{}');prior_output=c.execute('SELECT result FROM jobs WHERE id=?',(prior_options.get('output_job'),)).fetchone()
     if not prior_output:continue
     prior_result=json.loads(prior_output[0] or '{}')
     if (prior_result.get('audio_hash') or prior_result.get('file_sha256'))!=identity:continue
     run=self.root/'jobs'/previous['id']/'independent-review/run.json'
     if run.exists():
      state=json.loads(run.read_text())
      if state.get('status')=='stopped_needs_reconciliation' or any(x.get('status')=='in_flight' for x in state.get('chunks',[])):raise Conflict('يوجد طلب سابق غير محسوم لنفس الصوت؛ لا إعادة إرسال قبل تسوية حالته')
  from lifecycle import usable,open_asset
  with self.connect() as c:
   c.execute('BEGIN IMMEDIATE');usable(self,p,v['active'],c)
   for key in ['asset_id','from_asset_id','to_asset_id']:
    if (options or {}).get(key):open_asset(self,options[key],c)
   if c.execute("SELECT 1 FROM jobs WHERE project=? AND revision=? AND kind=? AND status IN ('queued','running')",(p,v['active'],kind)).fetchone():raise Conflict('نفس المهمة تعمل بالفعل على هذه النسخة')
   c.execute('INSERT INTO jobs(id,project,revision,kind,status,total,created,options) VALUES(?,?,?,?,?,?,?,?)',(j,p,v['active'],kind,'queued',len(v['assets']),time.time(),dump(options or {})))
  return j
 def feedback(self,p,revision,at,category,note,output_job=None):
  r=self.revision(revision)
  if r['project']!=p or type(at)!=int or not 0<=at<=round(r['timeline']['duration_frames']/r['timeline']['fps']*1000):raise Invalid('توقيت الملاحظة خارج النسخة')
  if category not in ['audio','cuts','cards','shots','maps','transitions','other'] or not str(note).strip() or len(str(note))>4000:raise Invalid('ملاحظة غير صالحة')
  if output_job:
   with self.connect() as c:j=self.one(c,'SELECT * FROM jobs WHERE id=?',(output_job,))
   if j['project']!=p or j['revision']!=revision or j['kind']!='render' or j['status']!='completed':raise Invalid('الملاحظة غير مرتبطة بملف إخراج مكتمل من نفس النسخة')
  with self.connect() as c:c.execute('INSERT INTO feedback(id,project,revision,time_ms,category,note,status,created,output_job) VALUES(?,?,?,?,?,?,?,?,?)',(uid(),p,revision,at,category,note,'recorded_not_learned',time.time(),output_job))

 def propose_rule(self,p,feedback,key,value):
  if key not in ['card_min_seconds','transition_seconds'] or type(value) not in [int,float] or not math.isfinite(value):raise Invalid('قاعدة غير صالحة')
  if key=='card_min_seconds' and not 2.5<=value<=12:raise Invalid('مدة قراءة غير صالحة')
  if key=='transition_seconds' and not .1<=value<=1.5:raise Invalid('مدة انتقال غير صالحة')
  with self.connect() as c:
   f=self.one(c,'SELECT * FROM feedback WHERE id=?',(feedback,))
   if f['project']!=p:raise Invalid('الملاحظة من مشروع آخر')
   r=uid();c.execute('INSERT INTO rules VALUES(?,?,?,?,?,?,?)',(r,p,feedback,key,value,'proposed',time.time()))
  return self.project(p)
 def rule_status(self,p,r,status):
  if status not in ['approved','revoked']:raise Invalid('حالة القاعدة غير صالحة')
  with self.connect() as c:
   row=self.one(c,'SELECT * FROM rules WHERE id=?',(r,))
   if row['project']!=p:raise Invalid('القاعدة من مشروع آخر')
   if status=='approved':c.execute("UPDATE rules SET status='superseded' WHERE project=? AND key=? AND status='approved'",(p,row['key']))
   c.execute('UPDATE rules SET status=? WHERE id=?',(status,r))
  return self.project(p)

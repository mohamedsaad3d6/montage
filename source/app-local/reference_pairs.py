"""Before/after evidence register. Saving a reference never trains a model."""
import json,re,time,urllib.parse
from core import uid,dump,Invalid
from media import file_hash

def init(store):
 with store.connect() as c:c.execute('CREATE TABLE IF NOT EXISTS control_reference_pairs(id TEXT PRIMARY KEY,project TEXT,before_asset TEXT,after_asset TEXT,after_url TEXT,notes TEXT,before_hash TEXT,after_hash TEXT,created REAL)')
def list_pairs(store,project):
 store.project(project);init(store)
 with store.connect() as c:items=[dict(r) for r in c.execute('SELECT * FROM control_reference_pairs WHERE project=? ORDER BY created DESC',(project,))]
 for x in items:
  x['status']='registered_not_trained';x['model_trained']=False;x['remote_video_verified']=False
 return items

def save(store,data):
 project=data['project'];store.project(project);init(store);before=store.asset(data.get('before_asset'));after_id=data.get('after_asset') or None;url=data.get('after_url') or '';notes=data.get('notes','')
 if before['project']!=project or before['kind']!='video' or before['source_type']=='review_evidence':raise Invalid('اختَر فيديو قبل من نفس الحلقة')
 if bool(after_id)==bool(url):raise Invalid('اختَر ملف بعد أو رابط يوتيوب واحدًا')
 if not isinstance(notes,str) or not 1<=len(notes.strip())<=5000:raise Invalid('اكتب ما تريد ملاحظته في الفرق بين النسختين')
 after=None
 if after_id:
  after=store.asset(after_id)
  if after['project']!=project or after['kind']!='video' or after['source_type']=='review_evidence' or after['hash']==before['hash']:raise Invalid('فيديو بعد يحتاج ملفًا مختلفًا من نفس الحلقة')
 else:
  if not isinstance(url,str) or len(url)>1000:raise Invalid('رابط كبير أو غير صالح')
  u=urllib.parse.urlsplit(url);host=(u.hostname or '').lower();video=urllib.parse.parse_qs(u.query).get('v',[''])[0] if host in ['youtube.com','www.youtube.com'] and u.path=='/watch' else u.path.strip('/') if host=='youtu.be' else ''
  if u.scheme!='https' or u.username or u.password or not re.fullmatch('[A-Za-z0-9_-]{11}',video):raise Invalid('استخدم رابط مشاهدة يوتيوب HTTPS صالحًا')
  url='https://www.youtube.com/watch?v='+video
 for a in [before,after]:
  if a and file_hash(store.resolve(a['path']))!=a['hash']:raise Invalid('ملف الدليل تغير')
 id=uid()
 with store.connect() as c:c.execute('INSERT INTO control_reference_pairs VALUES(?,?,?,?,?,?,?,?,?)',(id,project,before['id'],after_id,url,notes.strip(),before['hash'],after['hash'] if after else None,time.time()))
 return {'id':id,'model_trained':False,'timeline_changed':False,'remote_video_verified':False}

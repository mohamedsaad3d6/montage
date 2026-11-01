"""Versioned channel settings. Metadata cannot silently alter an existing timeline."""
import json,time
from core import uid,dump,Invalid,Conflict

def init(store):
 with store.connect() as c:
  c.execute('CREATE TABLE IF NOT EXISTS control_channels(id TEXT PRIMARY KEY,name TEXT,reviewer TEXT,description TEXT,profile TEXT,version INTEGER,created REAL)')
  c.execute('CREATE TABLE IF NOT EXISTS control_project_channels(project TEXT PRIMARY KEY,channel TEXT)')

def channels(store):
 init(store)
 with store.connect() as c:return [dict(r) for r in c.execute('SELECT * FROM control_channels ORDER BY created')]

def save_channel(store,data):
 init(store);name=str(data.get('name','')).strip();reviewer=str(data.get('reviewer','')).strip();desc=str(data.get('description','')).strip();profile=data.get('profile') or None
 if not 1<=len(name)<=120 or len(reviewer)>150 or len(desc)>2000:raise Invalid('اكتب اسم قناة صالحًا ووصفًا مختصرًا')
 if profile:
  from profiles import list_profiles
  if profile not in [p['id'] for p in list_profiles(store)]:raise Invalid('الأسلوب المختار غير موجود')
 id=data.get('id') or uid()
 with store.connect() as c:
  if data.get('id'):
   old=store.one(c,'SELECT * FROM control_channels WHERE id=?',(id,))
   if old['version']!=data.get('expected_version'):raise Conflict('القناة تغيرت؛ حدّث الصفحة قبل الحفظ')
   c.execute('UPDATE control_channels SET name=?,reviewer=?,description=?,profile=?,version=version+1 WHERE id=?',(name,reviewer,desc,profile,id))
  else:c.execute('INSERT INTO control_channels VALUES(?,?,?,?,?,?,?)',(id,name,reviewer,desc,profile,1,time.time()))
 return next(x for x in channels(store) if x['id']==id)

def assign(store,project,channel,apply_style=False):
 init(store);store.project(project)
 with store.connect() as c:
  item=store.one(c,'SELECT * FROM control_channels WHERE id=?',(channel,))
  if apply_style and not item['profile']:raise Invalid('القناة ليس لها أسلوب معتمد بعد')
  c.execute('INSERT OR REPLACE INTO control_project_channels VALUES(?,?)',(project,channel))
 if apply_style:
  if not item['profile']:raise Invalid('القناة ليس لها أسلوب معتمد بعد')
  from profiles import apply_profile
  apply_profile(store,project,item['profile'])
 return {'project':project,'channel':channel,'style_applied':bool(apply_style),'existing_media_changed':False}

def assignments(store):
 init(store)
 with store.connect() as c:return {r['project']:r['channel'] for r in c.execute('SELECT * FROM control_project_channels')}

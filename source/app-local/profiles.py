"""Explicit reusable style snapshots from approved feedback rules, not model training."""
import json,time
from core import Invalid,uid

def init(store):
 with store.connect() as c:
  c.execute('CREATE TABLE IF NOT EXISTS style_profiles(id TEXT PRIMARY KEY,name TEXT,source_project TEXT,source_revision TEXT,rules TEXT,created REAL)')
  c.execute('CREATE TABLE IF NOT EXISTS style_assignments(project TEXT PRIMARY KEY,profile TEXT)')
  c.execute('CREATE TABLE IF NOT EXISTS app_settings(key TEXT PRIMARY KEY,value TEXT)')

def list_profiles(store):
 init(store)
 with store.connect() as c:
  rows=[dict(r) for r in c.execute('SELECT * FROM style_profiles ORDER BY created DESC')]
 for row in rows:row['rules']=json.loads(row['rules'])
 return rows

def assigned(store,project):
 init(store)
 with store.connect() as c:
  row=c.execute('SELECT p.* FROM style_assignments a JOIN style_profiles p ON p.id=a.profile WHERE a.project=?',(project,)).fetchone()
 if not row:return None
 row=dict(row);row['rules']=json.loads(row['rules']);return row

def save_profile(store,project,name):
 init(store);v=store.project(project);name=str(name).strip()
 if not name or len(name)>120:raise Invalid('اكتب اسم الأسلوب')
 rules={r['key']:{'value':r['value'],'feedback':r['feedback'],'source_rule':r['id']} for r in reversed(v['rules']) if r['status']=='approved'}
 if not rules:raise Invalid('اعتمد قاعدة من ملاحظات الحلقة الأول؛ لا تعلّم بلا ملاحظة معتمدة')
 id=uid()
 with store.connect() as c:c.execute('INSERT INTO style_profiles VALUES(?,?,?,?,?,?)',(id,name,project,v['active'],json.dumps(rules,ensure_ascii=False),time.time()))
 return {'id':id,'name':name,'rules':rules,'affects_existing_media':False}

def apply_profile(store,project,profile):
 init(store);store.project(project)
 with store.connect() as c:
  store.one(c,'SELECT id FROM style_profiles WHERE id=?',(profile,))
  c.execute('INSERT OR REPLACE INTO style_assignments VALUES(?,?)',(project,profile))
 return store.project(project)

def set_default(store,profile):
 init(store)
 with store.connect() as c:
  store.one(c,'SELECT id FROM style_profiles WHERE id=?',(profile,))
  c.execute("INSERT OR REPLACE INTO app_settings VALUES('default_style',?)",(profile,))
 return {'future_projects_only':True,'profile':profile}

def apply_default(store,project):
 init(store)
 with store.connect() as c:
  row=c.execute("SELECT value FROM app_settings WHERE key='default_style'").fetchone()
  if row:c.execute('INSERT OR REPLACE INTO style_assignments VALUES(?,?)',(project,row[0]))

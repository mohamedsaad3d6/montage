"""Human editorial instructions, distinct from executable renderer rules."""
import time
from core import Invalid,Conflict,uid
CATEGORIES={'cuts','visual','graphics','transitions','audio'}
def init(store):
 with store.connect() as c:c.execute('CREATE TABLE IF NOT EXISTS control_editorial_directives(id TEXT PRIMARY KEY,project TEXT,category TEXT,text TEXT,reason TEXT,status TEXT,version INTEGER,created REAL)')
def list_directives(store,project):
 store.project(project);init(store)
 with store.connect() as c:rows=[dict(r) for r in c.execute('SELECT * FROM control_editorial_directives WHERE project=? ORDER BY created DESC',(project,))]
 for r in rows:r['automatic_enforcement']=False
 return rows

def save(store,data):
 project=data['project'];store.project(project);init(store);category=data.get('category');text=data.get('text','');reason=data.get('reason','')
 if category not in CATEGORIES or not isinstance(text,str) or not 1<=len(text.strip())<=1500 or not isinstance(reason,str) or len(reason)>2000:raise Invalid('اكتب توجيهًا واضحًا وقسمًا صالحًا')
 id=uid()
 with store.connect() as c:c.execute('INSERT INTO control_editorial_directives VALUES(?,?,?,?,?,?,?,?)',(id,project,category,text.strip(),reason.strip(),'proposed',1,time.time()))
 return list_directives(store,project)
def set_status(store,data):
 init(store);project=data['project'];status=data.get('status')
 if status not in ['approved','revoked']:raise Invalid('حالة توجيه غير صالحة')
 with store.connect() as c:
  c.execute('BEGIN IMMEDIATE');r=store.one(c,'SELECT * FROM control_editorial_directives WHERE id=? AND project=?',(data['id'],project))
  if type(data.get('expected_version'))!=int or r['version']!=data['expected_version']:raise Conflict('التوجيه تغير؛ حدّث الصفحة')
  c.execute('UPDATE control_editorial_directives SET status=?,version=version+1 WHERE id=?',(status,r['id']))
 return list_directives(store,project)

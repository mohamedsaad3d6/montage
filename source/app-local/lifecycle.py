"""Recoverable project/material removal. Raw files and immutable revisions are never deleted."""
import json,time
from core import Invalid,Conflict,uid,dump

def open_project(store,project,c=None):
 if c is None:
  with store.connect() as conn:return open_project(store,project,conn)
 store.one(c,'SELECT id FROM projects WHERE id=?',(project,))
 if c.execute("SELECT 1 FROM control_trash WHERE entity='project' AND id=? AND deleted_at IS NOT NULL",(project,)).fetchone():raise Invalid('الحلقة في سلة المحذوفات؛ استرجعها قبل استكمال الشغل')

def open_asset(store,asset,c=None):
 if c is None:
  with store.connect() as conn:return open_asset(store,asset,conn)
 a=store.one(c,'SELECT project FROM assets WHERE id=?',(asset,));open_project(store,a['project'],c)
 if c.execute("SELECT 1 FROM control_trash WHERE entity='asset' AND id=? AND deleted_at IS NOT NULL",(asset,)).fetchone():raise Invalid('الخامة في سلة المحذوفات؛ استرجعها قبل استخدامها')

def missing(store,project,revision=None,c=None):
 if c is None:
  with store.connect() as conn:return missing(store,project,revision,conn)
 pr=store.one(c,'SELECT active FROM projects WHERE id=?',(project,));rev=store.one(c,'SELECT timeline FROM revisions WHERE id=? AND project=?',(revision or pr['active'],project));t=json.loads(rev['timeline']);ids={x.get('asset_id') for tr in t.get('tracks',[]) for x in tr.get('clips',[]) if x.get('asset_id')}
 if t.get('primary_video_asset_id'):ids.add(t['primary_video_asset_id'])
 return [dict(r) for r in c.execute("SELECT a.id,a.name,t.version FROM assets a JOIN control_trash t ON t.entity='asset' AND t.id=a.id WHERE a.project=? AND t.deleted_at IS NOT NULL",(project,)) if r['id'] in ids]

def usable(store,project,revision=None,c=None):
 if c is None:
  with store.connect() as conn:return usable(store,project,revision,conn)
 open_project(store,project,c)
 if missing(store,project,revision,c):raise Invalid('النسخة تعتمد على فيديو أو خامة في السلة؛ استرجعها أو أنشئ حلقة جديدة')

def describe(store):
 with store.connect() as c:
  rows=[dict(r) for r in c.execute('SELECT * FROM control_trash WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC')]
  for r in rows:
   p=store.one(c,'SELECT name,active FROM projects WHERE id=?',(r['project'],));r.update(project_name=p['name'],project_deleted=bool(c.execute("SELECT 1 FROM control_trash WHERE entity='project' AND id=? AND deleted_at IS NOT NULL",(r['project'],)).fetchone()))
 return {'items':rows,'raw_files_deleted':False,'permanent_deletion_available':False}

def change(store,data,restore=False):
 entity=data.get('entity');id=data.get('id');expected=data.get('expected_version');reason=data.get('reason','')
 if entity not in ['project','asset'] or not isinstance(id,str) or type(expected)!=int or not isinstance(reason,str) or len(reason)>1000:raise Invalid('اختَر حلقة أو خامة وحالة صالحة')
 with store.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  if entity=='project':record=store.one(c,'SELECT id,name,active FROM projects WHERE id=?',(id,));project=id
  else:
   record=store.one(c,'SELECT id,name,project,source_type FROM assets WHERE id=?',(id,));project=record['project']
   if record['source_type']=='review_evidence':raise Invalid('دليل المراجعة مستقل ومحفوظ؛ ليس خامة تُحذف من المكتبة')
   if data.get('project')!=project:raise Invalid('الخامة لا تنتمي للحلقة المختارة')
   open_project(store,project,c)
  prior=c.execute('SELECT * FROM control_trash WHERE entity=? AND id=?',(entity,id)).fetchone();version=prior['version'] if prior else 0
  if version!=expected:raise Conflict('حالة العنصر تغيرت؛ حدّث الصفحة')
  if restore and (not prior or prior['deleted_at'] is None):raise Invalid('العنصر ليس في السلة')
  if not restore and prior and prior['deleted_at'] is not None:raise Invalid('العنصر موجود في السلة بالفعل')
  cancelled=[]
  if not restore:
   jobs=[dict(r) for r in c.execute("SELECT * FROM jobs WHERE project=? AND status IN ('queued','running')",(project,))]
   for j in jobs:
    relevant=entity=='project'
    if not relevant:
     options=json.loads(j['options'] or '{}');rev=json.loads(store.one(c,'SELECT timeline FROM revisions WHERE id=?',(j['revision'],))['timeline']);assets={x.get('asset_id') for tr in rev.get('tracks',[]) for x in tr.get('clips',[])};assets.update(options.get(k) for k in ['asset_id','from_asset_id','to_asset_id'])
     relevant=id in assets or rev.get('primary_video_asset_id')==id
    if relevant:c.execute("UPDATE jobs SET status='cancelled' WHERE id=? AND status IN ('queued','running')",(j['id'],));cancelled.append(j['id'])
  if entity=='asset' and not restore and c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='control_intake'").fetchone():
   intake=c.execute('SELECT version,data FROM control_intake WHERE project=?',(project,)).fetchone()
   if intake:
    selection=json.loads(intake['data']);changed=False
    for key in ['video','voice','script']:
     if selection.get(key)==id:selection[key]=None;changed=True
    if changed:c.execute('UPDATE control_intake SET version=version+1,data=? WHERE project=?',(dump(selection),project))
  now=time.time();c.execute('INSERT OR REPLACE INTO control_trash VALUES(?,?,?,?,?,?,?,?)',(entity,id,project,record['name'],version+1,None if restore else now,reason.strip(),now));c.execute('INSERT INTO control_trash_events VALUES(?,?,?,?,?,?,?)',(uid(),entity,id,version+1,'restored' if restore else 'trashed',now,dump({'project':project,'cancelled_jobs':cancelled,'raw_files_deleted':False})))
 return {'entity':entity,'id':id,'project':project,'version':version+1,'restored':restore,'cancelled_jobs':cancelled,'raw_files_deleted':False,'active_revision_changed':False}

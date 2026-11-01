"""Shared local catalogue; reuse is explicit and never transfers rights approval silently."""
import json
from core import Invalid
from media import file_hash

def catalogue(store,query='',kind='',offset=0):
 if type(offset)!=int or offset<0:raise Invalid('صفحة خامات غير صالحة')
 query=str(query).strip()
 if len(query)>180 or kind not in ['', 'video','audio','image']:raise Invalid('فلتر خامات غير صالح')
 with store.connect() as c:
  rows=[dict(r) for r in c.execute("SELECT a.id,a.project,a.kind,a.name,a.duration,a.hash,a.source_type,p.name AS project_name FROM assets a JOIN projects p ON p.id=a.project WHERE a.kind IN ('video','image','audio') AND a.source_type!='review_evidence' AND NOT EXISTS(SELECT 1 FROM control_trash t WHERE t.deleted_at IS NOT NULL AND ((t.entity='asset' AND t.id=a.id) OR (t.entity='project' AND t.id=p.id))) ORDER BY a.rowid DESC")]
 rows=[r for r in rows if (not kind or r['kind']==kind) and (not query or query.casefold() in (r['name']+' '+r['project_name']).casefold())]
 return {'total':len(rows),'offset':offset,'items':rows[offset:offset+50],'next_offset':offset+50 if offset+50<len(rows) else None}

def reuse(store,project,source_id):
 from lifecycle import open_project,open_asset
 open_project(store,project);open_asset(store,source_id);store.project(project);source=store.asset(source_id)
 if source['kind'] not in ['video','image','audio'] or source['source_type']=='review_evidence':raise Invalid('دليل المراجعة ليس خامة مونتاج')
 if file_hash(source['path'])!=source['hash']:raise Invalid('الخامة المشتركة تغيرت؛ أعد فحص أصلها')
 with store.connect() as c:
  existing=c.execute("SELECT id FROM assets a WHERE project=? AND hash=? AND kind=? AND NOT EXISTS(SELECT 1 FROM control_trash t WHERE t.entity='asset' AND t.id=a.id AND t.deleted_at IS NOT NULL)",(project,source['hash'],source['kind'])).fetchone()
  if existing:return {'asset_id':existing['id'],'already_present':True,'timeline_changed':False}
 asset=store.add_asset(project,source['path'],source['duration'],source['kind']);metadata=json.loads(source['metadata'] or '{}')
 metadata.update(reused_from_asset=source_id,rights_verified=False,requires_rights_review_for_this_project=True)
 with store.connect() as c:c.execute('UPDATE assets SET name=?,source_type=?,metadata=? WHERE id=?',(source['name'],source['source_type'],json.dumps(metadata,ensure_ascii=False),asset))
 return {'asset_id':asset,'already_present':False,'timeline_changed':False,'source_unchanged':True,'rights_approval_transferred':False}

def exclude(store,project,asset_id,excluded):
 if type(excluded)!=bool:raise Invalid('حالة استبعاد غير صالحة')
 a=store.asset(asset_id)
 if a['project']!=project or a['source_type']=='review_evidence':raise Invalid('اختَر خامة من نفس الحلقة')
 if file_hash(store.resolve(a['path']))!=a['hash']:raise Invalid('ملف الخامة تغير')
 with store.connect() as c:
  c.execute('BEGIN IMMEDIATE');row=store.one(c,'SELECT metadata FROM assets WHERE id=?',(asset_id,));metadata=json.loads(row['metadata'] or '{}');metadata['excluded_from_suggestions']=excluded;c.execute('UPDATE assets SET metadata=? WHERE id=?',(json.dumps(metadata,ensure_ascii=False),asset_id))
 return {'asset_id':asset_id,'excluded_from_suggestions':excluded,'timeline_changed':False}

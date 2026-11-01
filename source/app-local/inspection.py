"""Bind material descriptions to inspected frames and the actual source fingerprint."""
import json
from pathlib import Path
from media import probe,run,file_hash

def inspect(store,asset_id,folder,cancel):
 a=store.asset(asset_id)
 if a['kind'] not in ['video','image']:raise ValueError('اختَر مادة بصرية للفحص')
 if file_hash(a['path'])!=a['hash']:raise ValueError('الملف تغير قبل الفحص')
 folder=Path(folder);frames=[]
 for i,p in enumerate([.15,.5,.8] if a['kind']=='video' else [0]):
  out=folder/f'frame-{i}.jpg';args=(['-ss',a['duration']*p] if a['kind']=='video' else [])+['-i',a['path'],'-vf','scale=640:360:force_original_aspect_ratio=decrease,pad=640:360:(ow-iw)/2:(oh-ih)/2','-frames:v',1,'-q:v','2',out];run(args,folder,cancel);frames.append({'file':str(out),'sha256':file_hash(out),'at_seconds':a['duration']*p})
 return {'status':'frames_extracted_not_semantically_verified','asset_id':a['id'],'asset_sha256':a['hash'],'frames':frames,'visual_verified':False}
def describe(store,project,inspection_job,metadata):
 with store.connect() as c:j=store.one(c,'SELECT * FROM jobs WHERE id=?',(inspection_job,))
 if j['project']!=project or j['kind']!='inspect_asset' or j['status']!='completed':raise ValueError('يلزم فحص صور مكتمل من نفس المشروع')
 r=json.loads(j['result']);asset=store.asset(r['asset_id'])
 if file_hash(asset['path'])!=r['asset_sha256']:raise ValueError('المادة تغيرت بعد الفحص')
 for f in r['frames']:
  if file_hash(f['file'])!=f['sha256']:raise ValueError('صور التحقق تغيرت')
 if metadata.get('visual_verified') is not True or metadata.get('rights_verified') is not True:raise ValueError('يلزم تأكيد محتوى الصور وصلاحية استخدام المادة قبل اختيارها تلقائيًا')
 visual_type=metadata.get('visual_type')
 if visual_type not in ['person','event_footage','event_photo','map','illustration','equipment','place']:raise ValueError('نوع بصري غير صالح')
 from selection import ALIASES
 subjects=metadata.get('subjects',[])
 if not isinstance(subjects,list) or not subjects or len(subjects)>15 or any(x not in ALIASES for x in subjects):raise ValueError('موضوعات المادة غير صالحة')
 previous=json.loads(asset['metadata'] or '{}')
 out={'excluded_from_suggestions':previous.get('excluded_from_suggestions',False),'subjects':subjects,'visual_type':visual_type,'rights_verified':True,'visual_verified':True,'verification_frames':[f['sha256'] for f in r['frames']],'inspection_job':inspection_job,'asset_sha256':asset['hash'],'focus_person':metadata.get('focus_person'),'illustrative':metadata.get('illustrative') is True,'event_verified':metadata.get('event_verified') is True,'credit_required':metadata.get('credit_required') is True,'credit_text':str(metadata.get('credit_text',''))[:500]}
 if out['credit_required'] and not out['credit_text']:raise ValueError('المادة تحتاج نسبة للمصدر؛ اكتبها ولا تخفها')
 for k in ['year_start','year_end']:
  if k in metadata:
   if type(metadata[k])!=int or not 1800<=metadata[k]<=2100:raise ValueError('حقبة غير صالحة')
   out[k]=metadata[k]
 if out.get('year_start',1800)>out.get('year_end',2100):raise ValueError('بداية حقبة الخامة بعد نهايتها')
 with store.connect() as c:c.execute('UPDATE assets SET metadata=? WHERE id=?',(json.dumps(out,ensure_ascii=False),asset['id']))
 return store.project(project)

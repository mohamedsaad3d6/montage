"""Apply only reviewed, uniquely matched shot proposals to a new visual revision."""
import copy,json,math
from pathlib import Path
from core import Invalid,Conflict,uid
from media import file_hash

def apply_plan(store,project,job_id,expected):
 v=store.project(project)
 if v['active']!=expected:raise Conflict('النسخة اتغيرت؛ أعد خطة الخامات')
 from production import status
 if not status(v,store)['ready_for_montage']:raise Invalid('أكمل المراجعة السمعية المستقلة لهذه النسخة قبل المونتاج')
 with store.connect() as c:j=store.one(c,'SELECT * FROM jobs WHERE id=?',(job_id,))
 if j['project']!=project or j['revision']!=expected or j['kind']!='shot_plan' or j['status']!='completed':raise Invalid('خطة المواد لا تخص النسخة الحالية')
 result=json.loads(j['result']);p=Path(result['plan_file']).resolve()
 if store.root not in p.parents or file_hash(p)!=result['plan_sha256']:raise Invalid('خطة المواد تغيرت')
 plan=json.loads(p.read_text())
 if plan.get('source_revision')!=expected:raise Invalid('خطة مرتبطة بنسخة أخرى')
 t=copy.deepcopy(v['revision']['timeline']);fps=t['fps']
 if t.get('phase')=='montage_candidate':raise Invalid('هذه نسخة مونتاج بالفعل؛ راجعها قبل إعادة التخطيط')
 track=next(x for x in t['tracks'] if x['kind']=='video');used=set();applied=[];last_end=0
 for proposal in plan['proposals']:
  asset_id=proposal.get('suggested_asset_id')
  if not asset_id:continue
  # Only clear complete sentence endings are eligible for automatic visual placement.
  if not proposal['narration'].strip().endswith(('.', '؟','!','…')):continue
  a=store.asset(asset_id);evidence=plan.get('asset_evidence',{}).get(asset_id)
  if not evidence or a['hash']!=evidence['sha256'] or file_hash(a['path'])!=a['hash']:raise Invalid('خامة الخطة تغيرت')
  import hashlib
  if hashlib.sha256(a['metadata'].encode()).hexdigest()!=evidence['metadata_sha256']:raise Invalid('وصف الخامة تغير بعد اختيارها')
  start=math.ceil(proposal['start_ms']/1000*fps);end=min(t['duration_frames'],math.floor(proposal['end_ms']/1000*fps))
  if end<=start or start<last_end or a['hash'] in used:continue
  if a['kind']=='video' and end-start>math.floor(a['duration']*fps):raise Invalid('المادة أقصر من الجملة؛ لا تكرار آلي')
  clips=[]
  for c in track['clips']:
   if c['end_frame']<=start or c['start_frame']>=end:clips.append(c);continue
   if c['start_frame']<start:
    left=copy.deepcopy(c);left.update(id=uid(),end_frame=start,source_out_frame=c.get('source_in_frame',0)+start-c['start_frame']);clips.append(left)
   if c['end_frame']>end:
    right=copy.deepcopy(c);right.update(id=uid(),start_frame=end,source_in_frame=c.get('source_in_frame',0)+end-c['start_frame']);right.get('properties',{}).pop('transition',None);clips.append(right)
  clips.append({'id':uid(),'asset_id':asset_id,'start_frame':start,'end_frame':end,'source_in_frame':0,'source_out_frame':end-start,'properties':{}})
  track['clips']=sorted(clips,key=lambda c:c['start_frame']);used.add(a['hash']);last_end=end;applied.append({'asset_id':asset_id,'start_frame':start,'end_frame':end})
 if not applied:raise Invalid('لا توجد خامات موثقة لجمل كاملة قابلة للتطبيق؛ المذيع محفوظ دون بديل عشوائي')
 from transition_policy import assign
 transitions=assign(store,track['clips'],fps)
 t.update(phase='montage_candidate',montage_plan=job_id,montage_placements=applied,transition_decisions=transitions,requires_new_independent_audio_review=True)
 return store.save(project,expected,t,'تطبيق خامات موثقة لجمل كاملة — نسخة بصرية جديدة للمراجعة')

"""Explicitly auditioned, manually bounded retake repairs. Never an automatic ASR deletion."""
import json,math,time,wave,array,copy
from pathlib import Path
from core import Invalid,Conflict,uid,dump
from media import file_hash
from take_review import describe,bound
from lifecycle import usable
from editorial import norm

def _state(store,job,expected):
 data=describe(store,job);j,r,wav,duration,candidates=bound(store,job);p=store.project(j['project']);usable(store,p['id'])
 if p['active']!=j['revision'] or expected!=p['active']:raise Conflict('نسخة الحلقة تغيرت؛ أعد التحليل على النسخة الحالية')
 t=p['revision']['timeline']
 if t.get('phase')!='raw' or any(tr['clips'] for tr in t['tracks'] if tr['kind'] not in ['video','voice']):raise Invalid('إصلاح المحاولات للخام قبل إضافة المونتاج فقط')
 if any(tr.get('locked') for tr in t['tracks'] if tr['kind'] in ['voice','video']):raise Invalid('افتح قفل الصوت والصورة قبل تجهيز إصلاح متزامن')
 if not data['candidates']:raise Invalid('لا توجد محاولات للمقارنة')
 for item in data['candidates']:
  d=item['decision']
  if d and (d['plan_sha256']!=data['plan_sha256'] or d['audio_sha256']!=data['audio_sha256']):raise Conflict('قرار المقارنة لا يخص صوت التحليل الحالي')
  if not d or d['choice']=='needs_review' or not d['listened_all']:raise Invalid('احسم كل المقارنات بالسماع أولًا؛ لا اختيار تلقائي للمحاولات')
 return data,j,r,wav,duration,p

def _quiet(samples,rate,seconds,edge):
 if seconds<=0 or seconds>=edge:return True
 center=round(seconds*rate);part=samples[max(0,center-round(.008*rate)):center+round(.008*rate)]
 if not part:return False
 return math.sqrt(sum(x*x for x in part)/len(part))/32768<=10**(-32/20)

def _preserves_text(candidate,index):
 decision=candidate['decision'];attempt=candidate['attempts'][index];chosen=candidate['attempts'][decision['selected_attempt']]
 rejected=[norm(w) for w in attempt['text'].split() if norm(w)];kept=iter(norm(w) for w in chosen['text'].split() if norm(w))
 if not rejected or any(not any(token==other for other in kept) for token in rejected):raise Invalid('المحاولة المستبعدة فيها كلمات مختلفة أو إضافية في التفريغ؛ صحّح المقارنة والمحاذاة أولًا. تأكيد السماع وحده لا يحذف إضافة قد تكون مهمة')

def _words(store,j,r,cuts,fps):
 path=Path(r['source_words_file']).resolve()
 if store.root/'jobs'/j['id'] not in path.parents or file_hash(path)!=r['source_words_sha256']:raise Invalid('دليل الكلمات تغير')
 words=json.loads(path.read_text())['words']
 if not words:raise Invalid('لا يوجد دليل كلمات')
 for cut in cuts:
  for word in words:
   if cut['kind']=='quiet_gap_only' and word['s']-.12<cut['end_frame']/fps and word['e']+.12>cut['start_frame']/fps:raise Invalid('الفجوة تمس كلامًا أو هامش حمايته؛ لا تُحذف كسكتة')
   if any(word['s']<frame/fps<word['e'] for frame in [cut['start_frame'],cut['end_frame']]):raise Invalid('حد الوصلة يقطع مجال كلمة في المحاذاة؛ أعد ضبطه أو أصلح المحاذاة قبل التطبيق')
 return path,words

def preview(store,data):
 state,j,r,wav,duration,p=_state(store,data['job'],data['expected_revision'])
 if p['id']!=data.get('project'):raise Invalid('التحليل من حلقة أخرى')
 supplied=data.get('cuts');fps=p['revision']['timeline']['fps'];total=p['revision']['timeline']['duration_frames']
 if not isinstance(supplied,list) or not 1<=len(supplied)<=100:raise Invalid('حدّد حدود كل محاولة مستبعدة؛ بحد أقصى مائة وصلة في الخطة')
 bykey={c['key']:c for c in state['candidates']};expected={(c['key'],i) for c in state['candidates'] if c['decision']['choice']=='keep_attempt' for i in range(len(c['attempts'])) if i!=c['decision']['selected_attempt']};seen=set();cuts=[]
 with wave.open(str(wav),'rb')as f:rate=f.getframerate();samples=array.array('h',f.readframes(f.getnframes()))
 for cut in supplied:
  candidate=bykey.get(cut.get('candidate'));index=cut.get('rejected_attempt');a=cut.get('start_frame');b=cut.get('end_frame');reason=cut.get('reason')
  if not candidate or type(index)!=int or (candidate['key'],index) not in expected or (candidate['key'],index) in seen:raise Invalid('اختَر كل محاولة مستبعدة مرة واحدة فقط')
  decision=candidate['decision']
  if cut.get('decision_version')!=decision['version']:raise Conflict('اختيار المحاولة تغير؛ جهّز وصلة جديدة')
  if type(a)!=int or type(b)!=int or not 0<=a<b<=total or not isinstance(reason,str) or not 8<=len(reason.strip())<=2000:raise Invalid('الحدود تحتاج إطارات صحيحة وسببًا واضحًا')
  attempt=candidate['attempts'][index];chosen=candidate['attempts'][decision['selected_attempt']]
  _preserves_text(candidate,index)
  if a/fps<max(0,attempt['start']-.5) or b/fps>min(duration,attempt['end']+.5) or a/fps>attempt['start']+.1 or b/fps<attempt['end']-.1:raise Invalid('الحدود لا تطابق المحاولة المستبعدة؛ أعد المحاذاة بدل تخمين قصّ كلمات')
  if a/fps<chosen['end']+.04 and b/fps>max(0,chosen['start']-.04):raise Invalid('القص يمس المحاولة التي اخترت الاحتفاظ بها')
  if not _quiet(samples,rate,a/fps,duration) or not _quiet(samples,rate,b/fps,duration):raise Invalid('الوصلة داخل صوت واضح؛ حرّك الحد إلى فراغ منخفض الصوت واسمعه. انخفاض الصوت وحده لا يثبت اكتمال الجملة')
  cuts.append({**cut,'reason':reason.strip(),'kept_attempt':decision['selected_attempt'],'kind':'reviewed_retake','decision':decision});seen.add((candidate['key'],index))
 if seen!=expected:raise Invalid('باقي محاولات مستبعدة بلا حدود؛ لن نطبق خطة جزئية ونترك تكرارًا غير محسوم')
 pause_receipt=None;skipped_pauses=[]
 if type(data.get('include_confirmed_pauses',False))!=bool:raise Invalid('اختيار ضم السكتات غير صالح')
 if data.get('include_confirmed_pauses'):
  from pause_review import confirmed_plan
  pause_plan,path,sha=confirmed_plan(store,p,json.loads(Path(r['plan_file']).read_text()),store.root/'jobs'/j['id'])
  pause_receipt={'file':str(path),'sha256':sha}
  manual=list(cuts)
  for cut in pause_plan['cuts']:
   if any(cut['start_frame']<c['end_frame'] and cut['end_frame']>c['start_frame'] for c in manual):skipped_pauses.append({'start_frame':cut['start_frame'],'end_frame':cut['end_frame'],'reason':'overlaps_retake_kept_separate_no_double_deletion'})
   else:cuts.append(cut)
 if len(cuts)>1000:raise Invalid('الخطة تتجاوز ألف وصلة؛ تحتاج تقسيم المراجعة قبل التطبيق')
 cuts.sort(key=lambda x:x['start_frame'])
 if any(a['end_frame']>b['start_frame'] for a,b in zip(cuts,cuts[1:])):raise Invalid('المقارنات متداخلة؛ لا تُحذف المنطقة مرتين')
 _words(store,j,r,cuts,fps)
 key=uid();folder=store.root/'jobs'/j['id']/'manual-repairs'/key;folder.mkdir(parents=True)
 from cutplan import splice
 from repair_preview import build
 mapping=splice(p['revision']['timeline'],cuts)['raw_to_output'];previews=build(samples,rate,fps,mapping,cuts,folder)
 receipt={'schema_version':2,'audition_scope':'all_proposed_cuts','id':key,'project':p['id'],'job':j['id'],'revision':p['active'],'fps':fps,'audio_sha256':state['audio_sha256'],'plan_sha256':state['plan_sha256'],'cuts':cuts,'confirmed_pause_plan':pause_receipt,'skipped_overlapping_pauses':skipped_pauses,'retake_cut_count':len(supplied),'quiet_cut_count':sum(c['kind']=='quiet_gap_only' for c in cuts),'previews':previews,'created':time.time(),'status':'internal_boundary_audition_not_approved','independent_audio_review_granted':False}
 (folder/'proposal.json').write_text(dump(receipt));return public(receipt)

def public(receipt):
 return {k:v for k,v in receipt.items() if k!='cuts'}|{'cuts':[{k:v for k,v in c.items() if k!='decision'}for c in receipt['cuts']]}

def load(store,job,id):
 if not isinstance(id,str) or len(id)!=32 or any(x not in '0123456789abcdef' for x in id):raise Invalid('معرّف وصلة غير صالح')
 with store.connect()as c:j=store.one(c,'SELECT project FROM jobs WHERE id=?',(job,))
 usable(store,j['project']);folder=store.root/'jobs'/job/'manual-repairs'/id;path=folder/'proposal.json';receipt=json.loads(path.read_text())
 if receipt['job']!=job or receipt['id']!=id or receipt['project']!=j['project']:raise Invalid('وصلة لا تنتمي للتحليل')
 return folder,receipt

def audio(store,job,id,index):
 folder,receipt=load(store,job,id)
 if type(index)!=int or not 0<=index<len(receipt['previews']):raise Invalid('وصلة غير موجودة')
 item=receipt['previews'][index];path=(folder/item['file']).resolve()
 if folder.resolve() not in path.parents or file_hash(path)!=item['sha256']:raise Invalid('صوت الوصلة تغير')
 return path

def apply(store,data):
 folder,receipt=load(store,data['job'],data['proposal']);state,j,r,wav,duration,p=_state(store,data['job'],data['expected_revision'])
 if receipt.get('audition_scope')!='all_proposed_cuts':raise Invalid('هذه المعاينة قديمة؛ جهّز الوصلات من الخطة الكاملة قبل التطبيق')
 if receipt['project']!=data.get('project') or receipt['revision']!=p['active'] or receipt['audio_sha256']!=state['audio_sha256'] or receipt['plan_sha256']!=state['plan_sha256']:raise Conflict('خطة الوصلات تغيرت أو تخص نسخة أخرى')
 if data.get('listened_all_joins') is not True or data.get('kept_meaning_complete') is not True:raise Invalid('اسمع كل الوصلات وتأكد من اكتمال الكلام والإضافات قبل التطبيق')
 current={c['key']:c for c in state['candidates']}
 for cut in receipt['cuts']:
  if cut['kind']!='reviewed_retake':continue
  _preserves_text(current[cut['candidate']],cut['rejected_attempt'])
  if current.get(cut['candidate'],{}).get('decision')!=cut['decision']:raise Conflict('قرار المحاولة تغير بعد تجهيز الوصلة')
 for i in range(len(receipt['previews'])):audio(store,j['id'],receipt['id'],i)
 fps=receipt['fps'];cuts=receipt['cuts'];words_file,words=_words(store,j,r,cuts,fps)
 pause_receipt=receipt.get('confirmed_pause_plan')
 if pause_receipt:
  path=Path(pause_receipt['file']).resolve()
  if store.root/'jobs'/j['id'] not in path.parents or file_hash(path)!=pause_receipt['sha256']:raise Invalid('دليل السكتات المؤكدة تغير')
  from pause_review import confirmed_plan
  fresh,_,_=confirmed_plan(store,p,json.loads(Path(r['plan_file']).read_text()),store.root/'jobs'/j['id'])
  approved={dump(c) for c in fresh['cuts']}
  if any(dump(c) not in approved for c in cuts if c['kind']=='quiet_gap_only'):raise Invalid('مراجعة السكتات لم تعد تطابق الخطة؛ جهّز الوصلات من جديد')
 # Archive the human boundary assertions, explicitly distinct from independent review.
 attestation=folder/'boundary-attestation.json'
 if attestation.exists():raise Conflict('تم تقديم هذه الخطة بالفعل؛ حدّث الصفحة')
 attestation.write_text(dump({'proposal_sha256':file_hash(folder/'proposal.json'),'listened_all_joins':True,'kept_meaning_complete':True,'created':time.time(),'reviewer_identity_verified':False,'independent_review':False}))
 from cutplan import splice
 t=splice(p['revision']['timeline'],cuts);decisions=[]
 for cut in cuts:
  if cut['kind']!='reviewed_retake':continue
  ids=[i for i,w in enumerate(words) if cut['start_frame']/fps<=(w['s']+w['e'])/2<cut['end_frame']/fps]
  decisions.append({'kind':'retake','manual_boundaries':True,'word_ids':ids,'reason':cut['reason'],'evidence_file':str(folder/'proposal.json'),'evidence_sha256':file_hash(folder/'proposal.json'),'boundary_attestation_file':str(attestation),'boundary_attestation_sha256':file_hash(attestation)})
 plan={**receipt,'keeps':[{'start_frame':k['input_start_frame'],'end_frame':k['input_end_frame']} for k in t['raw_to_output']],'audit_raw_range':[0,duration],'decisions':decisions,'status':'manual_candidate_requires_independent_final_review'};pp=folder/'applied-word-plan.json';pp.write_text(dump(plan))
 t['cutting_proof']={'plan_file':str(pp),'plan_sha256':file_hash(pp),'source_words_file':str(words_file),'source_words_sha256':r['source_words_sha256'],'source_asset_id':r['source_asset_id'],'source_asset_sha256':r['source_asset_sha256'],'decisions':decisions};t['cleaning_job']=j['id'];t['requires_new_independent_audio_review']=True
 def guard(c):
  for cut in cuts:
   if cut['kind']!='reviewed_retake':continue
   latest=store.one(c,'SELECT version FROM control_take_decisions WHERE job=? AND candidate=? ORDER BY version DESC LIMIT 1',(j['id'],cut['candidate']))
   if latest['version']!=cut['decision_version']:raise Conflict('قرار المحاولة تغير أثناء التطبيق؛ لم تُحفظ نسخة')
 return store.save(p['id'],p['active'],t,'تطبيق اختيار المحاولات وحدود الوصلات يدويًا — نسخة مرشحة تحتاج مراجعة مستقلة',trusted_cut_proof=True,commit_guard=guard)

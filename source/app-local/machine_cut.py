"""Compile machine listening proposals into a reversible internal candidate, never a release."""
import array,json,math,wave
from pathlib import Path
from core import Invalid,Conflict
from media import file_hash
from take_review import bound
from editorial import norm
from cutplan import splice

def boundaries(item,choice,words,samples,rate,fps,total):
 kept=item['attempts'][choice];kept_tokens=[norm(w)for w in kept['text'].split()if norm(w)];cuts=[]
 for index,attempt in enumerate(item['attempts']):
  if index==choice:continue
  tokens=[norm(w)for w in attempt['text'].split()if norm(w)];sequence=iter(kept_tokens)
  if not tokens or any(not any(token==other for other in sequence)for token in tokens):raise Invalid('اختلاف كلمات قد يحذف إضافة ذات معنى؛ يلزم دليل أوضح')
  def eligible(frame):
   second=frame/fps
   if not 0<=frame<=total or kept['start']-.08<second<kept['end']+.08:return False
   if any(w['s']<second<w['e']for w in words):return False
   n=round(second*rate);part=samples[max(0,n-round(.012*rate)):min(len(samples),n+round(.012*rate))]
   return bool(part)and math.sqrt(sum(v*v for v in part)/len(part))/32768<=10**(-35/20)
  starts=[f for f in range(max(0,math.ceil((attempt['start']-.4)*fps)),min(total,math.floor(attempt['start']*fps))+1)if eligible(f)]
  ends=[f for f in range(max(0,math.ceil(attempt['end']*fps)),min(total,math.floor((attempt['end']+.4)*fps))+1)if eligible(f)]
  if not starts or not ends:raise Invalid('لم تثبت حدود هادئة خارج الكلمات لهذه المحاولة')
  a=max(starts);b=min(ends)
  if a>=b or a/fps<kept['end']+.08 and b/fps>kept['start']-.08:raise Invalid('حدود المحاولة تمس الكلام المختار')
  if any(w.get('unreliable_asr')and w['s']<b/fps and w['e']>a/fps for w in words):raise Invalid('القص يمر بجزء غير موثوق التفريغ')
  cuts.append({'start_frame':a,'end_frame':b,'kind':'machine_reviewed_retake','candidate':item['key'],'kept_attempt':choice,'rejected_attempt':index})
 return cuts

def apply(store,project,assessment_job,expected):
 with store.connect()as c:j=store.one(c,'SELECT * FROM jobs WHERE id=?',(assessment_job,))
 if j['kind']!='take_assess'or j['status']!='completed'or j['project']!=project or j['revision']!=expected:raise Invalid('مراجعة المحاولات ليست مكتملة على هذه النسخة')
 result=json.loads(j['result']);folder=store.root/'jobs'/j['id'];report_path=Path(result['report_file']).resolve()
 if folder not in report_path.parents or file_hash(report_path)!=result['report_sha256']:raise Invalid('تغير تقرير المقارنة الآلية')
 report=json.loads(report_path.read_text());source,r,audio,duration,items=bound(store,report['analysis_job']);p=store.project(project)
 if p['active']!=expected or p['revision']['timeline'].get('phase')!='raw':raise Conflict('النسخة تغيرت؛ لا قص على تحليل قديم')
 if source['project']!=project or source['revision']!=expected or report['audio_sha256']!=r['wave_sha256']or report['plan_sha256']!=r['plan_sha256']:raise Conflict('دليل المراجعة لا يطابق الصوت وخطة المحاولات')
 from take_assessment import validate,_save
 choices=validate({'comparisons':report['comparisons']},items)
 if any(x['classification']=='uncertain'for x in choices):raise Invalid('بعض المقارنات السمعية غير محسومة؛ لا تطبيق جزئي يخفيها')
 for evidence in report['evidence']:
  path=Path(evidence['file']).resolve()
  if store.root/'take-assessment-ledger' not in path.parents or file_hash(path)!=evidence['sha256']:raise Invalid('دليل الاستماع الآلي تغير')
 wp=Path(r['source_words_file']).resolve()
 if store.root/'jobs'/source['id'] not in wp.parents or file_hash(wp)!=r['source_words_sha256']:raise Invalid('دليل الكلمات تغير')
 words=json.loads(wp.read_text())['words'];byid={x['key']:x for x in items};fps=p['revision']['timeline']['fps'];total=p['revision']['timeline']['duration_frames']
 if not words or any(tr.get('locked')for tr in p['revision']['timeline']['tracks']if tr['kind']in ('video','voice')):raise Invalid('الكلمات غير متاحة أو مسارات المصدر مقفلة')
 with wave.open(str(audio),'rb')as wav:rate=wav.getframerate();samples=array.array('h',wav.readframes(wav.getnframes()))
 cuts=[];protected=[];issues=[]
 for choice in choices:
  item=byid[choice['candidate']]
  if choice['classification']=='intentional_repeat':protected.extend(item['attempts']);continue
  protected.append(item['attempts'][choice['selected_attempt']])
  try:cuts.extend(boundaries(item,choice['selected_attempt'],words,samples,rate,fps,total))
  except Invalid as error:issues.append({'candidate':item['key'],'reason':str(error)})
 if issues:
  _save(folder/'boundary-issues.json',{'status':'blocked_no_source_changes','issues':issues});raise Invalid('تعذر إثبات حدود '+str(len(issues))+' مقارنة؛ التفاصيل محفوظة دون تغيير الحلقة')
 unique={(x['start_frame'],x['end_frame']):x for x in cuts};cuts=sorted(unique.values(),key=lambda x:x['start_frame'])
 if any(a['end_frame']>b['start_frame']for a,b in zip(cuts,cuts[1:])):raise Invalid('مقارنات متداخلة؛ لا تُحذف المنطقة مرتين')
 if any(c['start_frame']/fps<k['end']+.08 and c['end_frame']/fps>k['start']-.08 for c in cuts for k in protected):raise Invalid('قص مرشح يمس محاولة محفوظة في مقارنة أخرى')
 original=json.loads(Path(r['plan_file']).read_text())
 for pause in original.get('cuts',[]):
  a,b=pause['start_frame'],pause['end_frame']
  if pause.get('kind')!='quiet_gap_only' or any(w['s']-.12<b/fps and w['e']+.12>a/fps for w in words):continue
  if any(a<c['end_frame']and b>c['start_frame']for c in cuts):continue
  cuts.append(pause)
 cuts.sort(key=lambda x:x['start_frame']);t=splice(p['revision']['timeline'],cuts)
 evidence_file=folder/'machine-boundary-validation.json';_save(evidence_file,{'status':'machine_candidate_only','human_listening_attested':False,'audio_sha256':r['wave_sha256'],'report_sha256':result['report_sha256'],'cuts':cuts,'independent_final_audio_review_required':True})
 decisions=[]
 for cut in cuts:
  if cut['kind']=='quiet_gap_only':continue
  ids=[i for i,w in enumerate(words)if cut['start_frame']/fps<=(w['s']+w['e'])/2<cut['end_frame']/fps]
  decisions.append({'kind':'retake','word_ids':ids,'reason':'مقارنة سمعية آلية مع حفظ الكلمات المتكررة في المحاولة المختارة وحدود خارج الكلمات؛ تحتاج مراجعة مستقلة للناتج','evidence_file':str(report_path),'evidence_sha256':result['report_sha256'],'boundary_attestation_file':str(evidence_file),'boundary_attestation_sha256':file_hash(evidence_file),'human_listening_attested':False})
 pp=folder/'machine-cut-plan.json';plan={'fps':fps,'keeps':[{'start_frame':k['input_start_frame'],'end_frame':k['input_end_frame']}for k in t['raw_to_output']],'audit_raw_range':[0,duration],'cuts':cuts,'decisions':decisions,'status':'machine_candidate_requires_independent_final_review'};_save(pp,plan)
 t['cutting_proof']={'plan_file':str(pp),'plan_sha256':file_hash(pp),'source_words_file':str(wp),'source_words_sha256':r['source_words_sha256'],'source_asset_id':r['source_asset_id'],'source_asset_sha256':r['source_asset_sha256'],'decisions':decisions};t['requires_new_independent_audio_review']=True;t['machine_assessment_job']=j['id']
 def guard(c):
  if file_hash(report_path)!=result['report_sha256']or file_hash(audio)!=r['wave_sha256']or file_hash(wp)!=r['source_words_sha256']:raise Conflict('تغير دليل المقارنة أثناء حفظ الخطة')
  for item in report['evidence']:
   if file_hash(item['file'])!=item['sha256']:raise Conflict('تغير دليل الاستماع أثناء حفظ الخطة')
 return store.save(project,expected,t,'نسخة تقطيع آلية مرشحة — مراجعة صوت نهائية مستقلة لازمة',trusted_cut_proof=True,commit_guard=guard)

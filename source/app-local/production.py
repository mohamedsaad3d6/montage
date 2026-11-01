"""Evidence-bound progress, not an automatic editorial approval."""
import json

def decoded(job):
 try:return json.loads(job.get('result') or '{}')
 except (ValueError,TypeError):return {}

def status(project,store=None):
 t=project['revision']['timeline'];jobs=[j for j in project['jobs'] if j['revision']==project['active']]
 completed=[j for j in jobs if j['status']=='completed']
 analyses=[j for j in completed if j['kind'] in ['transcribe','editorial_plan']]
 renders=[j for j in completed if j['kind']=='render']
 reviews=[j for j in completed if j['kind']=='audio_review']
 newest={};filtered=[]
 for j in reviews:
  r=decoded(j);key=r.get('output_job')
  if key and r.get('review_complete') is True and key not in newest:newest[key]=j;filtered.append(j)
 reviews=filtered
 full=[j for j in renders if decoded(j).get('start_frame')==0 and decoded(j).get('frames')==t['duration_frames']]
 approved=[];completed_raw_reviews=[]
 if store:
  from pause_review import evidence
  byid={j['id']:j for j in full}
  for review in reviews:
   r=decoded(review);out=byid.get(r.get('output_job'))
   if out:
    details=decoded(out)
    if details.get('audio_unchanged') and evidence(store,review,details):completed_raw_reviews.append(review['id'])
 for out in full:
  result=decoded(out)
  if not result.get('file_sha256') or result.get('technical_decode') is not True:continue
  for review in reviews:
   r=decoded(review)
   if (r.get('output_job')==out['id'] and r.get('output_sha256')==result['file_sha256']
       and r.get('review_complete') is True and r.get('gate',{}).get('status')=='passed_for_review'):
    from media import file_hash
    if store:
     from release import reviewed
     if not reviewed(store,review,result):continue
    try:
     if file_hash(result['file'])==result['file_sha256']:approved.append(out['id'])
    except (OSError,KeyError):pass
 remaining_takes=0;boundary_choices=0
 if store and analyses and analyses[0]['kind']=='editorial_plan':
  from take_review import pending_count
  remaining_takes=pending_count(store,analyses[0])
  from take_review import boundary_count
  boundary_choices=boundary_count(store,analyses[0])
 remaining_takes=max(remaining_takes,int(t.get('unresolved_take_comparisons')or 0))
 has_source=t.get('duration_frames',0)>0
 stages=[{'id':'materials','title':'المواد','status':'complete' if has_source else 'waiting'},
         {'id':'analysis','title':'تحليل الكلام','status':'complete' if analyses else 'waiting'},
         {'id':'audio_review','title':'مراجعة الصوت الكامل','status':'complete' if approved else 'blocked' if full else 'waiting'},
         {'id':'montage','title':'المونتاج','status':'available' if approved else 'blocked'}]
 if project.get('unavailable_assets'):action={'kind':'restore','label':'استرجع الفيديو أو الخامة من السلة قبل استكمال الحلقة'}
 elif project.get('lifecycle',{}).get('deleted'):action={'kind':'restore','label':'استرجع الحلقة من سلة المحذوفات'}
 elif not has_source:action={'kind':'upload','label':'أضف الخام والسكريبت'}
 elif t.get('local_cut_analysis_job') and not full:action={'kind':'render','label':'جهّز مسودة التنظيف المحلي للفحص المستقل'}
 elif not analyses and not t.get('local_cut_analysis_job'):action={'kind':'editorial_plan' if t.get('phase')=='raw' else 'transcribe','label':'حلّل الكلام على النسخة الحالية'}
 elif remaining_takes and not full:action={'kind':'takes','label':'المحاولات تحتاج مقارنة صوتية آلية قبل تحديد حدود القص'}
 elif boundary_choices and t.get('phase')=='raw':action={'kind':'boundaries','label':'اضبط حدود المحاولات المستبعدة واسمع الوصلات قبل التطبيق'}
 elif not full:action={'kind':'render','label':'جهّز نسخة كاملة للفحص'}
 elif not approved and completed_raw_reviews:action={'kind':'repair','label':'راجع مواضع الإصلاح التي اكتشفتها المراجعة'}
 elif not approved:action={'kind':'review','label':'أكمل المراجعة السمعية المستقلة لنفس ملف الإخراج'}
 else:action={'kind':'montage','label':'مراجعة اختيار المواد قبل المونتاج'}
 return {'revision':project['active'],'phase':t.get('phase','reference'),'stages':stages,
         'next_action':action,'full_outputs':[j['id'] for j in full],
         'audio_review_passed_outputs':approved,'ready_for_montage':bool(approved) and not project.get('unavailable_assets') and not project.get('lifecycle',{}).get('deleted',False),
         'take_comparisons_remaining':remaining_takes,'take_boundary_choices':boundary_choices,'publication_approved':False,'automatic_episode':False,'raw_review_complete':bool(completed_raw_reviews),
         'running_jobs':len([j for j in jobs if j['status'] in ['queued','running']])}

"""Durable bounded orchestration. Stop/continue never bypass speech or output review gates."""
import contextlib,json,time
from core import Invalid,Conflict
PIPELINE={'codex_plan','take_assess','generate_graphic','generate_music','preview_transition','archive_search','archive_collect','storyblocks_search','storyblocks_collect','storyblocks_autoselect','inspect_asset','shot_plan','reference_refine','input_prepare','asset_integrity','editorial_plan','transcribe','render','audio_review'}
def init(store):
 with store.connect()as c:c.execute('CREATE TABLE IF NOT EXISTS control_workflow(project TEXT PRIMARY KEY,state TEXT,revision TEXT,job TEXT,reason TEXT,version INTEGER,updated REAL)')
@contextlib.contextmanager
def lock(store):
 import platform_lock as fcntl
 with (store.root/'workflow.lock').open('a')as f:
  fcntl.flock(f,fcntl.LOCK_EX)
  try:yield
  finally:fcntl.flock(f,fcntl.LOCK_UN)
def get(store,project):
 init(store)
 with store.connect()as c:
  p=store.one(c,'SELECT active FROM projects WHERE id=?',(project,));r=c.execute('SELECT * FROM control_workflow WHERE project=?',(project,)).fetchone()
 return dict(r)if r else {'project':project,'state':'idle','revision':p['active'],'job':None,'reason':'جاهز للبدء من المرحلة التالية','version':0,'updated':None}
def _put(store,project,state,revision,job,reason):
 old=get(store,project)
 with store.connect()as c:c.execute('INSERT OR REPLACE INTO control_workflow VALUES(?,?,?,?,?,?,?)',(project,state,revision,job,reason,old['version']+1,time.time()))
 return get(store,project)
def describe(store,project):
 from job_activity import snapshot
 state=get(store,project);snap=snapshot(store,project);preparation=None
 with store.connect()as c:j=c.execute("SELECT * FROM jobs WHERE project=? AND revision=? AND kind='input_prepare' ORDER BY created DESC LIMIT 1",(project,state['revision'])).fetchone()
 if j:
  preparation={'job':j['id'],'status':j['status'],'chunks':[]}
  for name in ('camera','master'):
   path=store.root/'jobs'/j['id']/name/'progress.json'
   try:
    d=json.loads(path.read_text());preparation['chunks'].append({'source':name,**{k:d[k]for k in ('completed_chunks','total_chunks','completed_seconds')}})
   except (OSError,ValueError,KeyError):pass
  coarse=store.root/'jobs'/j['id']/'coarse-acoustic-map.json'
  try:
   samples=json.loads(coarse.read_text()).get('samples',[]);preparation['acoustic_samples_checked']=len(samples);preparation['acoustic_samples_passed']=sum(bool(x.get('passed'))for x in samples)
  except (OSError,ValueError):pass
  if j['status']=='completed':
   d=json.loads(j['result']or'{}');preparation['summary']={k:d.get(k)for k in ('sync_status','matched_word_fraction','ambiguous_phrases','reference_words','source_words')};preparation['summary']['anchors']=len(d.get('anchors',[]));preparation['summary']['acoustic_samples']=len(d.get('acoustic_samples',[]));preparation['summary']['acoustic_samples_passed']=sum(bool(x.get('passed'))for x in d.get('acoustic_samples',[]))
 return {**state,'snapshot':snap,'input_preparation':preparation,'automatic_publication':False,'resume_from_saved_stage_not_instruction_pointer':True}

def pause(store,project):
 init(store)
 with lock(store):
  p=store.project(project);cancelled=[];old=get(store,project)
  with store.connect()as c:
   for j in p['jobs']:
    if j['revision']==p['active'] and j['kind']in PIPELINE and j['status']in ['queued','running']:
     c.execute("UPDATE jobs SET status='cancelled' WHERE id=? AND status IN ('queued','running')",(j['id'],));cancelled.append(j['id'])
  from codex_agent import state as director_state, put as director_put
  director=director_state(store,project)
  if director['state']=='running':director_put(store,project,'paused',director['job'],director['turn'],director['goal'],'متوقف بطلب المستخدم')
  _put(store,project,'paused',p['active'],cancelled[0]if cancelled else old['job'],'متوقف بطلبك. كمّل يعيد المرحلة غير المكتملة من بدايتها مع الاحتفاظ بالمراحل المكتملة.')
 return {**describe(store,project),'cancelled_jobs':cancelled}
def advance(store,project,automatic=False,consent=None):
 init(store);new_job=None
 with lock(store):
  old=get(store,project)
  if automatic and old['state']!='running':return {'new_job':None,'workflow':old}
  from lifecycle import usable
  usable(store,project);p=store.project(project)
  if automatic and p['active']!=old['revision']:
   return {'new_job':None,'workflow':_put(store,project,'needs_input',p['active'],None,'النسخة تغيرت؛ اضغط كمّل لاعتماد العمل على النسخة الحالية.')}
  from codex_agent import state as director_state
  director=director_state(store,project)
  if director['state']=='running':return {'new_job':None,'workflow':old}
  if old['state']=='paused' and director['state']=='paused':
   from codex_agent import start_locked
   result=start_locked(store,p,director['goal'])
   return {**result,'workflow':get(store,project)}
  busy=next((j for j in p['jobs']if j['revision']==p['active']and j['kind']in PIPELINE and j['status']in ['queued','running']),None)
  if busy:return {'new_job':None,'workflow':_put(store,project,'running',p['active'],busy['id'],'الشغل مستمر على المرحلة الحالية')}
  prior=next((j for j in p['jobs']if j['id']==old['job']and j['revision']==p['active']),None)
  if prior and prior['kind']=='input_prepare' and prior['status']=='completed':
   from intake import start
   proof=json.loads(prior['result']or'{}')
   if proof.get('sync_status')in ('post_cut_reference_candidates','post_cut_acoustic_candidates'):
    job=store.enqueue(project,'reference_refine',{'source_job':prior['id']},revision=p['active'])
    return {'new_job':job,'workflow':_put(store,project,'running',p['active'],job,'اكتمل فحص المراسي؛ يجري التحقق الصوتي الكامل لمطابقة مقاطع الصورة')}

   try:
    p=start(store,{'project':project,'expected':p['active'],'input_version':proof.get('input_version'),'sync_job':prior['id']})
   except (Invalid,Conflict)as error:return {'new_job':None,'workflow':_put(store,project,'needs_input',p['active'],None,str(error))}
   _put(store,project,'running',p['active'],None,'اكتمل فحص المدخلات والتزامن؛ بدأ تحليل الكلام')
  if prior and prior['kind']=='reference_refine'and prior['status']=='completed':
   report=json.loads(prior['result']or'{}')
   if report.get('mapping_ready')is True:
    from reference_picture import apply as apply_picture
    try:p=apply_picture(store,project,prior['id'],p['active'])
    except (Invalid,Conflict)as error:return {'new_job':None,'workflow':_put(store,project,'needs_input',p['active'],prior['id'],str(error))}
    _put(store,project,'running',p['active'],None,'اكتملت خطة الصورة متعددة المقاطع؛ الصوت المرجعي محفوظ كاملًا؛ بدأ تحليل النسخة للفحص')
    prior=None
   else:
    reason='توقفت مطابقة الصورة بأمان: '+str(len(report.get('issues',report.get('unverified_intervals',[]))))+' موضعًا غير محسوم. لم يُغيَّر الصوت أو الفيديو؛ تفاصيل المطابقة محفوظة للفحص.'
    return {'new_job':None,'workflow':_put(store,project,'blocked_alignment',p['active'],prior['id'],reason)}
  if prior and prior['kind']=='take_assess'and prior['status']=='completed':
   from machine_cut import apply as apply_machine_cut
   try:p=apply_machine_cut(store,project,prior['id'],p['active'])
   except (Invalid,Conflict)as error:return {'new_job':None,'workflow':_put(store,project,'needs_input',p['active'],prior['id'],str(error))}
   _put(store,project,'running',p['active'],None,'طبقت خطة آلية مرشحة بعد تدقيق الحدود؛ يجري تجهيز الناتج للمراجعة المستقلة دون اعتماد نشر.')
   prior=None
  if old['state']=='blocked_materials'and prior and prior['kind']=='shot_plan':prior=None
  if prior and prior['kind']=='shot_plan'and prior['status']=='completed':
   from montage import apply_plan
   try:p=apply_plan(store,project,prior['id'],p['active'])
   except Invalid as error:return {'new_job':None,'workflow':_put(store,project,'blocked_materials',p['active'],prior['id'],str(error))}
   _put(store,project,'running',p['active'],None,'تم تركيب الخامات الموثقة والانتقالات على جمل مكتملة؛ جاري تجهيز فحص النسخة الجديدة')
   prior=None
  # Local drafting is independent of cloud availability. Never retry an
  # unresolved listening request merely to continue quiet-only processing.
  if p['revision']['timeline'].get('phase')=='raw':
   analysis=next((j for j in p['jobs']if j['revision']==p['active']and j['kind']=='editorial_plan'and j['status']=='completed'),None)
   if analysis and json.loads(analysis.get('result')or'{}').get('plan_file') and (not prior or prior['kind']in ('editorial_plan','take_assess')):
    from local_cut import apply as apply_local_cut
    try:p=apply_local_cut(store,project,analysis['id'],p['active'])
    except (Invalid,Conflict,ValueError)as error:return {'new_job':None,'workflow':_put(store,project,'needs_input',p['active'],analysis['id'],str(error))}
    options={'resolution':'source','purpose':'review','start_frame':0,'end_frame':p['revision']['timeline']['duration_frames']}
    job=store.enqueue(project,'render',options,revision=p['active'])
    return {'new_job':job,'workflow':_put(store,project,'running',p['active'],job,'يجري إخراج مسودة التنظيف المحلي؛ الكلام الملتبس محفوظ والمراجعة المستقلة لازمة.')}
  if prior and prior['status']in ['failed','cancelled']:
   if automatic:return {'new_job':None,'workflow':_put(store,project,'failed',p['active'],prior['id'],prior.get('error')or'توقفت المرحلة؛ لن نعيدها تلقائيًا')}
   if prior['kind']=='audio_review' and json.loads(prior['options']or'{}').get('provider')=='api':
    return {'new_job':None,'workflow':_put(store,project,'needs_input',p['active'],prior['id'],'المسودة محفوظة. مراجعة Google لم تنجح: '+str(prior.get('error')or'نتيجة غير محسومة')+' — لن يعاد إرسال الصوت بالضغط على كمّل؛ يلزم تسوية الطلب أولًا.')}
   # Explicit Continue retries the same unfinished stage, not the entire episode.
   kind=prior['kind'];options=json.loads(prior['options']or'{}')
  else:
   from production import status
   production=status(p,store);action=production['next_action'];kind=action['kind'];options={}
   if kind=='takes':
    analysis=next((j for j in p['jobs']if j['revision']==p['active']and j['kind']=='editorial_plan'and j['status']=='completed'),None)
    r=json.loads(analysis['result']or'{}')if analysis else {}
    target={'analysis_job':analysis['id'],'audio_sha256':r.get('wave_sha256'),'plan_sha256':r.get('plan_sha256')}if analysis else None
    if not target or not consent or consent.get('google_audio')is not True or any(consent.get(k)!=v for k,v in target.items()):
     return {'new_job':None,'workflow':_put(store,project,'needs_input',p['active'],None,'اسمح بمقارنة صوت المحاولات لهذا التحليل في Google المجاني؛ لا إرسال دون الموافقة ولا قص من التفريغ وحده.')}
    from reviewer import check_free_connection
    check_free_connection();kind='take_assess';options={**target,'consent_google_audio':True}
   if kind in ['boundaries','repair','upload','restore']:

    return {'new_job':None,'workflow':_put(store,project,'needs_input',p['active'],None,action['label'])}
   if kind=='montage':
    if p['revision']['timeline'].get('phase')=='montage_candidate':return {'new_job':None,'workflow':_put(store,project,'ready_for_montage',p['active'],None,'اكتمل إخراج نسخة المونتاج ومراجعتها السمعية؛ متاحة للمراجعة البصرية والتعديل، دون نشر تلقائي.')}
    narration=next((j for j in p['jobs']if j['revision']==p['active']and j['kind']in ('transcribe','editorial_plan')and j['status']=='completed'),None)
    if narration is None:
     job=store.enqueue(project,'transcribe',{},revision=p['active'])
     return {'new_job':job,'workflow':_put(store,project,'running',p['active'],job,'تجهيز توقيت الكلام على النسخة المقطعة لاختيار الخامات؛ الصوت والقص محفوظان')}
    from storyblocks_auto import ensure as storyblocks_ensure
    research=storyblocks_ensure(store,project)
    if research:return {'new_job':research,'workflow':_put(store,project,'running',p['active'],research,'اختيار لقطات Storyblocks حسب كلام الحلقة')}
    # The director inspects available material and can collect/generate more
    # before asking the existing montage engine to assemble verified assets.
    from codex_agent import start_locked
    result=start_locked(store,p,'جهز مونتاج الحلقة بعد اكتمال مراجعة صوتها. اقرأ جمل الحلقة والخامات المتاحة أولًا. استخدم مصادر الأرشيف المتنوعة وتوليد الموشن والموسيقى ومعاينة الانتقالات عند الحاجة، ثم اطلب shot_plan عندما توجد خامات موثقة تطابق الجمل. لا تفترض أن خامة مولدة أو منزلة معتمدة بصريًا، ولا تتجاوز فحص الحقوق والمطابقة. اذكر النواقص الدقيقة إن لم يمكن التحقق منها.')
    return {**result,'workflow':get(store,project)}
   if kind=='render':options={'resolution':'source','purpose':'review','start_frame':0,'end_frame':p['revision']['timeline']['duration_frames']}
   elif kind=='review':
    output=production['full_outputs'][0]if production['full_outputs']else None
    session=next((j for j in p['jobs']if j['revision']==p['active']and j['kind']=='audio_review'and j['status']=='completed'and json.loads(j['result']or'{}').get('output_job')==output and (json.loads(j['result']or'{}').get('provider')!='google_ai_studio_ui' or json.loads(j['result']or'{}').get('review_complete')is True)),None)
    if session:return {'new_job':None,'workflow':_put(store,project,'needs_input',p['active'],None,'مراجعة الصوت المستقلة لم تكتمل؛ يلزم استكمال نتيجتها قبل المونتاج.')}
    bound=next((j for j in p['jobs']if j['id']==output),None);digest=json.loads(bound['result']or'{}').get('file_sha256')if bound else None
    if not consent or consent.get('output_job')!=output or consent.get('output_sha256')!=digest or consent.get('google_audio')is not True:
     return {'new_job':None,'workflow':_put(store,project,'needs_input',p['active'],None,'ملف الفحص جاهز. يلزم السماح بمراجعة صوت هذا الملف في Google؛ لا إرسال تلقائي دون الموافقة.')}
    failed_api=next((j for j in p['jobs']if j['revision']==p['active']and j['kind']=='audio_review'and j['status']=='failed'and json.loads(j['options']or'{}').get('provider')=='api'and json.loads(j['options']or'{}').get('output_job')==output),None)
    if failed_api:return {'new_job':None,'workflow':_put(store,project,'needs_input',p['active'],failed_api['id'],'طلب مراجعة Google لهذا الملف تعطل؛ المسودة محفوظة ولا إعادة إرسال قبل تسوية النتيجة.')}
    provider=consent.get('provider','studio')
    if provider not in ('studio','api'):raise Invalid('نوع مراجعة غير صالح')
    if provider=='api':
     from reviewer import check_free_connection
     try:check_free_connection()
     except (ValueError,OSError)as error:return {'new_job':None,'workflow':_put(store,project,'needs_input',p['active'],None,'ربط مراجعة Google المجانية غير جاهز؛ لم يُرسل الصوت: '+str(error))}
    kind='audio_review';options={'provider':provider,'output_job':output,'consent_google_audio':True}
   elif kind not in ['take_assess','shot_plan','editorial_plan','transcribe']:return {'new_job':None,'workflow':_put(store,project,'needs_input',p['active'],None,'المرحلة تحتاج مراجعة قبل المتابعة')}
  try:new_job=store.enqueue(project,kind,options,revision=p['active'])
  except (Invalid,Conflict)as error:return {'new_job':None,'workflow':_put(store,project,'needs_input',p['active'],old['job'],str(error))}
  result=_put(store,project,'running',p['active'],new_job,'بدأ تنفيذ المرحلة التالية')
 return {'new_job':new_job,'workflow':result}
def tick(store,dispatch):
 init(store)
 with store.connect()as c:projects=[r[0]for r in c.execute("SELECT project FROM control_workflow WHERE state='running'")]
 for project in projects:
  try:
   state=get(store,project)
   with store.connect()as c:j=c.execute('SELECT status FROM jobs WHERE id=?',(state['job'],)).fetchone()
   if j and j['status']in ['queued','running']:continue
   step=advance(store,project,automatic=True)
   if step['new_job']:dispatch(step['new_job'])
  except Exception as error:
   state=get(store,project);_put(store,project,'failed',state['revision'],state['job'],str(error)[:400])

def begin(store,data):
 from intake import get as intake_get,checked_asset
 p=store.project(data['project']);selection=intake_get(store,p['id'])
 if p['active']!=data.get('expected') or selection['version']!=data.get('input_version'):raise Conflict('المدخلات تغيرت؛ أعد فتح الصفحة')
 if p['revision']['timeline']['duration_frames']:return advance(store,p['id'])
 checked_asset(store,p['id'],selection['selection'].get('video'),'video')
 if selection['selection']['voice_mode']in ['external','external_cut']:checked_asset(store,p['id'],selection['selection'].get('voice'),'audio')
 with lock(store):
  busy=next((j for j in store.project(p['id'])['jobs']if j['revision']==p['active']and j['kind']in PIPELINE and j['status']in ['running','queued']),None)
  if busy:return {'new_job':None,'workflow':_put(store,p['id'],'running',p['active'],busy['id'],'الشغل بدأ بالفعل')}
  job=store.enqueue(p['id'],'input_prepare',{'input_version':selection['version']},revision=p['active']);state=_put(store,p['id'],'running',p['active'],job,'فحص المدخلات والتزامن تلقائيًا')
 return {'new_job':job,'workflow':state}

"""Persisted jobs with frozen revisions and explicit candidate/review separation."""
import argparse,json,os,time,subprocess,shutil,signal,hashlib
from pathlib import Path
from core import Store,fingerprint
from media import render,Cancelled,tool,ROOT,run,probe,file_hash

def transcribe(store,rev,folder,cancel,progress,stage=None):
 stage=stage or (lambda _:None)
 stage('voice_prepare')
 t=rev['timeline'];voices=[c for tr in t['tracks'] if tr['kind']=='voice' for c in tr['clips']]
 if not voices:raise ValueError('لا يوجد تعليق صوتي لتحليله')
 from voice import prepare as prepare_voice
 fps=t['fps'];c,a,joined=prepare_voice(store,voices,fps,0,t['duration_frames'],folder,cancel)
 stage('audio_extract')
 wav=folder/'speech.wav'
 run(['-ss',c.get('source_in_frame',0)/fps,'-i',a['path'],'-t',t['duration_frames']/fps,'-ar','16000','-ac','1','-c:a','pcm_s16le',wav],folder,cancel,progress)
 source_bindings=[{'asset_id':x['asset_id'],'asset_sha256':store.asset(x['asset_id'])['hash'],
                   'source_in_frame':x.get('source_in_frame',0),'source_out_frame':x['source_out_frame'],
                   'start_frame':x['start_frame'],'end_frame':x['end_frame']} for x in voices]
 wave_sha=file_hash(wav)
 with store.connect() as conn:
  previous=[dict(x) for x in conn.execute("SELECT * FROM jobs WHERE project=? AND kind='transcribe' AND status='completed' ORDER BY created DESC",(rev['project'],))]
 for job in previous:
  prior=json.loads(job['result'])
  if prior.get('wave_sha256')!=wave_sha:continue
  if prior.get('asr_strategy')!='independent_120s_no_context_v2':continue
  if not all(prior.get(p) and file_hash(prior[p])==prior.get(h) for p,h in [('asr_file','asr_sha256'),('analysis_file','analysis_sha256')]):continue
  stage('reuse')
  return {**prior,'wave_file':str(wav),'wave_sha256':wave_sha,'analysis_audio_sha256':wave_sha,
          'source_voice_pieces':source_bindings,'source_asset_id':a.get('id'),'source_asset_sha256':a.get('hash'),
          'voice_joined':joined,'reused_from_job':job['id'],'status':'transcribed_reused_exact_pcm_not_independently_reviewed'}
 model=os.environ.get('MONTAJ_WHISPER_MODEL') or str(ROOT.parent/'AI agent/monteer_data/models/whisper/ggml-large-v3-turbo.bin')
 if not Path(model).is_file():raise ValueError('نموذج التفريغ العربي المحلي غير متاح؛ لم تُحذف أي كلمة')
 stem=folder/'transcript'
 stage('asr')
 from chunked_asr import transcribe as transcribe_parts
 data=transcribe_parts(wav,folder,model,store.root/'asr-cache',cancel,progress)
 stem.with_suffix('.json').write_text(json.dumps(data,ensure_ascii=False))
 segments=data.get('transcription',[])
 if not segments:raise ValueError('لم يستخرج المحلل كلامًا؛ لا توجد خطة قص آلية')
 stage('word_candidates')
 from editorial import analyze
 analysis=analyze(data,wav);analysis_file=folder/'editorial-analysis.json';analysis_file.write_text(json.dumps(analysis,ensure_ascii=False,indent=2))
 return {'asr_strategy':'independent_120s_no_context_v2','asr_file':str(stem.with_suffix('.json')),'asr_sha256':file_hash(stem.with_suffix('.json')),'analysis_file':str(analysis_file),'analysis_sha256':file_hash(analysis_file),'wave_file':str(wav),'wave_sha256':file_hash(wav),'source_asset_id':a.get('id'),'source_asset_sha256':a.get('hash'),'source_voice_pieces':source_bindings,'analysis_audio_sha256':file_hash(wav),'voice_joined':joined,'timeline_clock':True,'transcript':[{'start_ms':s.get('offsets',{}).get('from'),'end_ms':s.get('offsets',{}).get('to'),'text':'[تفريغ غير موثوق — الصوت محفوظ]'if s.get('unreliable_asr')else s.get('text',''),'unreliable_asr':s.get('unreliable_asr',False)} for s in segments],'status':'transcribed_not_independently_reviewed','automatic_cuts_applied':False,'note':'التفريغ يساعد المراجعة ولا يثبت صلاحية حذف كلمات أو نفس.'}

def editorial_plan(store,rev,folder,cancel,progress,stage=None):
 stage=stage or (lambda _:None)
 from editorial import analyze,retakes,norm
 from alignment import literal_words,breath_candidates
 from cutplan import plan
 import shutil
 voices=[c for tr in rev['timeline']['tracks'] if tr['kind']=='voice' for c in tr['clips']]
 if len(voices)!=1 or voices[0]['start_frame']!=0 or voices[0]['end_frame']!=rev['timeline']['duration_frames']:raise ValueError('ابدأ بالخـام ذي المسار الصوتي المتصل؛ لا إعادة تقطيع لنسخة معتمدة')
 asset=store.asset(voices[0]['asset_id']);prior=None
 with store.connect() as c:jobs=[dict(x) for x in c.execute("SELECT * FROM jobs WHERE project=? AND revision=? AND kind='transcribe' AND status='completed' ORDER BY created DESC",(rev['project'],rev['id']))]
 for j in jobs:
  r=json.loads(j['result'])
  if r.get('source_asset_sha256')==asset['hash'] and r.get('asr_file') and file_hash(r['asr_file'])==r.get('asr_sha256') and file_hash(r['wave_file'])==r.get('wave_sha256'):
   prior=r;break
 if prior is None:prior=transcribe(store,rev,folder,cancel,progress,stage)
 wav=folder/'analysis-source.wav';shutil.copyfile(prior['wave_file'],wav)
 data=json.loads(Path(prior['asr_file']).read_text());analysis=analyze(data,wav);stage('ctc');ctc=None;ctc_reused=None
 with store.connect()as conn:
  past=[dict(row)for row in conn.execute("SELECT * FROM jobs WHERE project=? AND kind='editorial_plan' AND status='completed' ORDER BY created DESC",(rev['project'],))]
 for previous in past:
  evidence=json.loads(previous['result']or'{}');wordpath=Path(evidence.get('source_words_file',''))
  if evidence.get('wave_sha256')!=prior['wave_sha256'] or not wordpath.is_file() or file_hash(wordpath)!=evidence.get('source_words_sha256'):continue
  candidate=json.loads(wordpath.read_text()).get('ctc')
  if not isinstance(candidate,list) or not candidate or any(not isinstance(w,dict)or not isinstance(w.get('w'),str)or not 0<=w.get('s',-1)<w.get('e',-1)<=rev['timeline']['duration_frames']/rev['timeline']['fps']+.05 for w in candidate):continue
  ctc=candidate;ctc_reused=previous['id'];(folder/'literal-words.json').write_text(json.dumps({'words':ctc,'reused_from_job':ctc_reused,'scope':'exact_audio_analysis_only_not_cut_approval'},ensure_ascii=False));break
 if ctc is None:ctc=literal_words(wav,folder,cancel)
 from forced import refine
 stage('forced')
 original_words=analysis['words'];analysis['words'],forced_evidence=refine(wav,original_words,folder,cancel)
 stage('breath')
 breaths=breath_candidates(wav,folder,cancel);stage('cut_plan');cp=plan(analysis,ctc,wav,rev['timeline']['fps']);cp['forced_alignment']=forced_evidence
 ctc_repeats=retakes([{**w,'id':i,'n':norm(w['w'])} for i,w in enumerate(ctc)],allow_ctc_variants=True)
 for item in cp['retakes']:item['word_stream']='whisper'
 for item in ctc_repeats:
  item['word_stream']='egyptian_ctc'
  if not any(abs(item['attempts'][0]['start']-x['attempts'][0]['start'])<.35 and abs(item['attempts'][1]['start']-x['attempts'][1]['start'])<.35 for x in cp['retakes']):cp['retakes'].append(item)
 cp['source_revision']=rev['id'];cp['source_asset_id']=asset['id'];cp['source_asset_sha256']=asset['hash'];cp['analysis_start_frame']=voices[0]['start_frame'];cp['analysis_source_in_frame']=voices[0]['source_in_frame'];cp['breath_observations']=breaths;cp['audit_raw_range']=[0,rev['timeline']['duration_frames']/rev['timeline']['fps']];cp['keeps']=[];cursor=0
 for cut in cp['cuts']:
  if cursor<cut['start_frame']:cp['keeps'].append({'start_frame':cursor,'end_frame':cut['start_frame']})
  cursor=cut['end_frame']
 if cursor<rev['timeline']['duration_frames']:cp['keeps'].append({'start_frame':cursor,'end_frame':rev['timeline']['duration_frames']})
 target=folder/'cut-plan.json';target.write_text(json.dumps(cp,ensure_ascii=False,indent=2));words_file=folder/'source-words.json';words_file.write_text(json.dumps({'words':[{**w,'stream':'whisper'} for w in analysis['words']]+[{**w,'stream':'egyptian_ctc'} for w in ctc],'asr':analysis['words'],'original_asr_estimates':original_words,'forced_alignment':forced_evidence,'ctc':ctc},ensure_ascii=False,indent=2))
 return {'ctc_reused_from_job':ctc_reused,'status':'cut_plan_proposed_not_applied','transcript':prior['transcript'],'plan_file':str(target),'plan_sha256':file_hash(target),'source_words_file':str(words_file),'source_words_sha256':file_hash(words_file),'wave_file':str(wav),'wave_sha256':file_hash(wav),'retake_candidates':len(cp['retakes']),'quiet_gap_candidates':len(cp['cuts']),'breath_candidates':len(breaths['breaths']),'breath_detector_status':breaths['status'],'forced_alignment':forced_evidence,'retake_deletions':0,'automatic_speech_deletion':False,'source_asset_id':asset['id'],'source_asset_sha256':asset['hash']}

def shot_plan(store,rev,folder):
 from selection import shortlist
 with store.connect() as c:jobs=[dict(x) for x in c.execute("SELECT * FROM jobs WHERE project=? AND revision=? AND kind IN ('transcribe','editorial_plan') AND status='completed' ORDER BY created DESC",(rev['project'],rev['id']))]
 if not jobs:raise ValueError('حلل الكلام قبل اختيار المواد؛ لا تخمين من اسم الفيديو')
 r=json.loads(jobs[0]['result']);assets=store.project(rev['project'])['assets'];proposals=[];used=set();byid={a['id']:a for a in assets}
 for segment in r['transcript']:
  proposal={'start_ms':segment['start_ms'],'end_ms':segment['end_ms'],**shortlist(segment['text'],assets,max(.1,(segment['end_ms']-segment['start_ms'])/1000))}
  unique=[]
  for candidate in proposal['candidates']:
   if byid[candidate['asset_id']]['hash'] in used:proposal['rejected'].append({'asset_id':candidate['asset_id'],'reason':'same_visual_already_allocated_in_this_plan'})
   else:unique.append(candidate)
  proposal['candidates']=unique
  if unique:
   proposal['suggested_asset_id']=unique[0]['asset_id'];used.add(byid[unique[0]['asset_id']]['hash'])
  else:proposal['status']='retain_presenter_no_verified_unique_match'
  proposals.append(proposal)
 out=folder/'shot-plan.json';out.write_text(json.dumps({'source_revision':rev['id'],'proposals':proposals,'asset_evidence':{a['id']:{'sha256':a['hash'],'metadata_sha256':hashlib.sha256(a['metadata'].encode()).hexdigest()} for a in assets},'automatic_apply':False,'audio_review_required_before_montage':True},ensure_ascii=False,indent=2))
 return {'status':'shot_proposals_not_applied','plan_file':str(out),'plan_sha256':file_hash(out),'segments':len(proposals),'verified_matches':sum(bool(s['candidates']) for s in proposals),'presenter_retained':sum(not s['candidates'] for s in proposals),'automatic_apply':False}

def _execute(store,jobid,delay=0):
 with store.connect() as c:
  c.execute('BEGIN IMMEDIATE');j=store.one(c,'SELECT * FROM jobs WHERE id=?',(jobid,))
  if j['status']!='queued':return
  c.execute('UPDATE jobs SET status=?,worker_pid=? WHERE id=?',('running',os.getpid(),jobid))
 folder=store.root/'jobs'/jobid;folder.mkdir(parents=True,exist_ok=True)
 def cancel():
  with store.connect() as c:return store.one(c,'SELECT status FROM jobs WHERE id=?',(jobid,))['status']=='cancelled'
 def progress(seconds):
  with store.connect() as c:c.execute("UPDATE jobs SET checkpoint=? WHERE id=? AND status='running'",(round(seconds*rev['timeline']['fps']),jobid))
 from job_activity import record as activity_record,finish as activity_finish
 def stage(phase):
  if cancel():raise Cancelled()
  activity_record(store,jobid,phase)
 started=time.monotonic();metric=None
 try:
  from telemetry import start as metric_start
  metric=metric_start(store,jobid)
  stage('source_check')
  rev=store.revision(j['revision']);ids=sorted({x['asset_id'] for t in rev['timeline']['tracks'] for x in t['clips'] if x.get('asset_id')})
  options=json.loads(j.get('options') or '{}');total=len(ids) if j['kind']=='asset_integrity' else max(1,int(options.get('end_frame',rev['timeline']['duration_frames']))-int(options.get('start_frame',0)))
  with store.connect() as c:c.execute('UPDATE jobs SET total=?,checkpoint=0 WHERE id=?',(total,jobid))
  for i,a in enumerate(ids):
   if cancel():raise Cancelled()
   asset=store.asset(a)
   if fingerprint(asset['path'])!=asset['hash']:raise ValueError('ملف مصدر اتغير بعد الفهرسة؛ مطلوب إعادة تحقق')
   if delay:
    until=time.monotonic()+delay
    while time.monotonic()<until:
     if cancel():raise Cancelled()
     time.sleep(min(.1,max(0,until-time.monotonic())))
   if j['kind']=='asset_integrity':
    with store.connect() as c:c.execute("UPDATE jobs SET checkpoint=? WHERE id=? AND status='running'",(i+1,jobid))
  if j['kind'] in ['take_assess','render','generate_graphic','generate_music','preview_transition','archive_search','archive_collect','storyblocks_search','storyblocks_collect','storyblocks_autoselect','inspect_asset','shot_plan','audio_review']:stage(j['kind'])
  if j['kind']=='codex_plan':
   from codex_agent import plan as codex_plan
   stage('codex_thinking');result=codex_plan(store,rev,folder,options,cancel)
  elif j['kind']=='reference_refine':
   from reference_acoustic import inspect
   stage('reference_acoustic_full');result=inspect(store,options['source_job'],folder,cancel,rev['project'],rev['id'])
  elif j['kind']=='input_prepare':
   from input_prepare import prepare
   result=prepare(store,rev,folder,options,cancel,stage)
  elif j['kind']=='render':
   if options.get('reference_only') is True:
    from reference import prepare
    result=prepare(store,rev,folder,options,cancel,progress)
   else:result=render(store,rev,folder,options,cancel,progress)
  elif j['kind']=='take_assess':
   from take_assessment import assess
   result=assess(store,rev,folder,options,cancel)
  elif j['kind']=='generate_music':
   from music_adapter import generate
   result=generate(store,rev,folder,options,cancel)
  elif j['kind']=='generate_graphic':
   options=json.loads(j.get('options') or '{}');template=options.get('template');items=json.loads((ROOT/'app-local/graphics/catalog.json').read_text())
   if template not in [x['id'] for x in items]:raise ValueError('قالب غير معروف')
   with (folder/'graphics.log').open('wb') as log:
    proc=subprocess.Popen([shutil.which('node'),str(ROOT/'app-local/graphics/render.mjs'),str(folder),template],stdout=log,stderr=log,start_new_session=True)
    from process_guard import wait as wait_bounded
    if wait_bounded(proc,cancel,timeout_seconds=300):raise ValueError('تعذر توليد الموشن المحلي؛ راجع سجل الرندر')
   info=probe(folder/'graphic.mp4');stream=next(x for x in info['streams'] if x['codec_type']=='video')
   if int(stream['nb_frames'])!=144:raise ValueError('عدد إطارات الموشن غير مطابق')
   asset_id=store.add_asset(rev['project'],str(folder/'graphic.mp4'),6,'video')
   with store.connect() as c:c.execute("UPDATE assets SET name=?,source_type='generated',metadata=? WHERE id=?",(next(x['title'] for x in items if x['id']==template)+'.mp4',json.dumps({'own_original':True,'procedural':True,'represents_real_event':False}),asset_id))
   result={'asset_id':asset_id,'kind':'original_procedural_motion','template':template,'represents_real_event':False,'width':1920,'height':1080}
  elif j['kind']=='preview_transition':
   from transitions import build
   opts=json.loads(j.get('options') or '{}');left=store.asset(opts.get('from_asset_id'));right=store.asset(opts.get('to_asset_id'))
   if any(a['project']!=rev['project'] or a['kind'] not in ['video','image'] for a in [left,right]):raise ValueError('اختَر خامتين بصريتين من نفس الحلقة')
   for a in [left,right]:
    if file_hash(a['path'])!=a['hash']:raise ValueError('خامة المعاينة تغيرت')
   fps=rev['timeline']['fps'];boundary=round(fps*.5)
   previous={'asset_id':left['id'],'source_in_frame':0,'start_frame':0,'end_frame':boundary}
   current={'asset_id':right['id'],'source_in_frame':0,'start_frame':boundary,'end_frame':boundary+48}
   path,frames,recipe=build(store,previous,current,boundary,fps,640,360,folder,{'recipe_id':opts.get('recipe_id')},cancel)
   for a in [left,right]:
    if file_hash(a['path'])!=a['hash']:raise ValueError('خامة المعاينة تغيرت أثناء الرندر')
   result={'file':str(path),'file_sha256':file_hash(path),'frames':frames,'duration':frames/fps,'recipe':recipe,'silent_visual_diagnostic':True,'not_final_media':True}
  elif j['kind']=='storyblocks_autoselect':
   from storyblocks_auto import run as run_automatic
   result=run_automatic(store,rev,folder,options,cancel,stage)
  elif j['kind']=='storyblocks_search':
   from storyblocks_connector import search
   result=search(folder,options,cancel)
  elif j['kind']=='storyblocks_collect':
   from storyblocks_connector import collect
   result=collect(store,rev,folder,options,cancel)
  elif j['kind']=='archive_search':
   from archive import search
   options=json.loads(j.get('options') or '{}');result=search(options.get('query',''),options.get('sources',['commons','internet_archive']),options.get('media_type','visual'))
   (folder/'archive-search.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
  elif j['kind']=='archive_collect':
   from archive_import import collect
   result=collect(store,rev,folder,options,cancel)
  elif j['kind']=='inspect_asset':
   from inspection import inspect
   target=store.asset(json.loads(j.get('options') or '{}').get('asset_id'))
   if target['project']!=rev['project']:raise ValueError('المادة من مشروع آخر')
   result=inspect(store,target['id'],folder,cancel)
  elif j['kind']=='editorial_plan':result=editorial_plan(store,rev,folder,cancel,progress,stage)
  elif j['kind']=='shot_plan':result=shot_plan(store,rev,folder)
  elif j['kind']=='audio_review':
   options=json.loads(j.get('options') or '{}')
   if options.get('provider')=='studio':
    from studio import prepare
    result=prepare(store,rev,folder,options,cancel)
   else:
    from reviewer import review_output
    result=review_output(store,rev,folder,options,cancel)
  elif j['kind']=='transcribe':result=transcribe(store,rev,folder,cancel,progress,stage)
  else:result={'verified_assets':len(ids),'scope':'source_integrity_only_not_audio_or_editorial_review'}
  stage('final_verify')
  # Files may be replaced while a job runs; never certify the earlier snapshot alone.
  for a in ids:
   asset=store.asset(a)
   if fingerprint(asset['path'])!=asset['hash']:raise ValueError('المصدر اتغير أثناء العمل؛ الناتج غير معتمد')
  with store.connect() as c:c.execute("UPDATE jobs SET status='completed',result=?,checkpoint=total WHERE id=? AND status='running'",(json.dumps(result,ensure_ascii=False),jobid))
 except Cancelled:
  with store.connect() as c:c.execute("UPDATE jobs SET status='cancelled' WHERE id=?",(jobid,))
 except Exception as e:
  with store.connect() as c:c.execute("UPDATE jobs SET status='failed',error=? WHERE id=? AND status='running'",(str(e),jobid))
 finally:
  activity_finish(store,jobid)
  if metric:
   from telemetry import finish
   with store.connect() as c:final_status=store.one(c,'SELECT status FROM jobs WHERE id=?',(jobid,))['status']
   finish(store,metric,time.monotonic()-started,final_status)
def execute(store,jobid,delay=0):
 import platform_lock as fcntl
 # One heavy job per local data store. Crashes release the OS lock automatically.
 with (store.root/'execution.lock').open('a') as lock:
  while True:
   try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
   except BlockingIOError:
    with store.connect() as c:
     if store.one(c,'SELECT status FROM jobs WHERE id=?',(jobid,))['status']!='queued':return
    time.sleep(.2)
  try:return _execute(store,jobid,delay)
  finally:fcntl.flock(lock,fcntl.LOCK_UN)

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--data',required=True);p.add_argument('--job',required=True);a=p.parse_args();execute(Store(a.data,[a.data]),a.job)

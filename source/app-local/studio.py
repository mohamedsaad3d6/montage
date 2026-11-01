"""Google AI Studio UI review bridge; no API request, credentials, or fabricated approval."""
import json,sys,wave,shutil
import platform_lock as fcntl
from pathlib import Path
from media import ROOT,run,tool,file_hash,probe
from audit import uncut_receipt,validate_proof,reference_receipt

def pipeline():
 sys.path.insert(0,str(ROOT/'engine'))
 from monteer.audio_review import pipeline as p
 return p

def output(store,rev,options):
 if options.get('consent_google_audio') is not True:raise ValueError('يلزم السماح بمراجعة صوت هذا الملف في Google Studio')
 with store.connect() as c:j=store.one(c,'SELECT * FROM jobs WHERE id=?',(options.get('output_job'),))
 if j['project']!=rev['project'] or j['revision']!=rev['id'] or j['kind']!='render' or j['status']!='completed':raise ValueError('ناتج غير صالح للمراجعة')
 result=json.loads(j['result'])
 if file_hash(result['file'])!=result['file_sha256']:raise ValueError('الناتج تغير قبل المراجعة')
 return j,result

def prepare(store,rev,folder,options,cancel):
 job,result=output(store,rev,options);folder=Path(folder);p=pipeline()
 proof=result.get('cutting_proof') or reference_receipt(store,rev,result) or uncut_receipt(store,rev,folder);validate_proof(store,proof)
 wav=folder/'exact-final-audio.wav';run(['-i',result['file'],'-map','0:a:0','-ar','16000','-ac','1','-c:a','pcm_s16le',wav],folder,cancel)
 with wave.open(str(wav),'rb') as w:duration=w.getnframes()/w.getframerate()
 reviews=folder/'independent-review';state=p.prepare(wav,reviews,tool('ffmpeg'),seconds=duration,stage='after')
 state.update(review_method='aistudio_ui',status='prepared_for_ui',network_calls=0)
 for chunk in state['chunks']:
  original=reviews/chunk['file'];mp3=original.with_suffix('.mp3')
  run(['-i',original,'-c:a','libmp3lame','-b:a','64k',mp3],folder,cancel)
  chunk.update(source_wav_file=original.name,source_wav_sha256=chunk['sha256'],
               file=mp3.name,sha256=file_hash(mp3),review_encoding='MP3 64kbps derived from exact final PCM without editorial changes')
 p.save(reviews/'run.json',state)
 p.save(reviews/'final-media-binding.json',{'media_sha256':result['file_sha256'],'audio_sha256':file_hash(wav),'media_duration_seconds':duration})
 p.save(reviews/'word-audit-binding.json',{'media_sha256':result['file_sha256'],**proof,'decisions':proof.get('decisions',[])})
 p.save(folder/'technical-checks.json',{'technical_pass':result['technical_decode'],'output_sha256':result['file_sha256']})
 return {'provider':'google_ai_studio_ui','status':'awaiting_studio_results','review_complete':False,
         'output_job':job['id'],'output_sha256':result['file_sha256'],'chunks':len(state['chunks']),
         'review_folder':str(reviews),'publication_approved':False,'api_success':False,
         'gate':{'status':'blocked','reasons':['studio_review_not_completed']}}

def state_for(store,job_id):
 with store.connect() as c:job=store.one(c,'SELECT * FROM jobs WHERE id=?',(job_id,))
 result=json.loads(job.get('result') or '{}')
 if job['kind']!='audio_review' or job['status']!='completed' or result.get('provider')!='google_ai_studio_ui':raise ValueError('جلسة Studio غير جاهزة')
 folder=store.root/'jobs'/job_id;reviews=folder/'independent-review';state=json.loads((reviews/'run.json').read_text())
 if Path(state['source']).resolve()!=(folder/'exact-final-audio.wav').resolve():raise ValueError('مسار صوت المراجعة غير صالح')
 if file_hash(state['source'])!=state['source_sha256']:raise ValueError('صوت المراجعة تغير')
 return job,result,folder,reviews,state

def describe(store,job_id):
 job,result,folder,reviews,state=state_for(store,job_id);chunks=[]
 for chunk in state['chunks']:
  item={k:v for k,v in chunk.items() if k not in ['source_wav_file']}
  if chunk['status']=='completed':
   path=(reviews/chunk['result']).resolve();evidence=(reviews/chunk['evidence_file']).resolve()
   if reviews.resolve() not in path.parents or reviews.resolve() not in evidence.parents:raise ValueError('مسار دليل غير صالح')
   if file_hash(path)!=chunk['result_sha256'] or file_hash(evidence)!=chunk['evidence_sha256']:raise ValueError('نتيجة المراجعة أو دليلها تغير')
   item['review']=json.loads(path.read_text())
  chunks.append(item)
 return {'job':job_id,'status':state['status'],'provider':'google_ai_studio_ui',
         'output_sha256':result['output_sha256'],'prompt':(reviews/'prompt.txt').read_text(),
         'chunks':chunks,'review_complete':result['review_complete'],'gate':result['gate'],'api_success':False}

def audio_file(store,job_id,index):
 job,result,folder,reviews,state=state_for(store,job_id)
 if not 0<=index<len(state['chunks']):raise ValueError('جزء غير موجود')
 chunk=state['chunks'][index];path=(reviews/chunk['file']).resolve()
 if reviews.resolve() not in path.parents:raise ValueError('مسار جزء غير صالح')
 if file_hash(path)!=chunk['sha256']:raise ValueError('ملف الجزء تغير')
 return path

def record(store,job_id,index,result,evidence_asset,attested):
 if attested is not True:raise ValueError('يلزم تأكيد أن النتيجة من مراجعة هذا الجزء في Google Studio')
 job,summary,folder,reviews,state=state_for(store,job_id);p=pipeline()
 with (folder/'ui-record.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  state=json.loads((reviews/'run.json').read_text())
  if type(index)!=int or not 0<=index<len(state['chunks']):raise ValueError('جزء غير صالح')
  chunk=state['chunks'][index]
  if chunk['status']=='completed':raise ValueError('نتيجة الجزء محفوظة بالفعل؛ لا تستبدل دليلًا مسجلًا')
  if file_hash(reviews/chunk['file'])!=chunk['sha256']:raise ValueError('الصوت الذي روجع تغير')
  if isinstance(result,str):
   text=result.strip()
   if text.startswith('```'):text=text.split('\n',1)[1].rsplit('```',1)[0]
   result=json.loads(text)
  result=p.validate(result,chunk['end']-chunk['start'])
  if not result['transcript'].strip():raise ValueError('التفريغ فارغ؛ لا مراجعة مكتملة')
  asset=store.asset(evidence_asset)
  if asset['project']!=job['project'] or asset['kind']!='image':raise ValueError('أرفق صورة إثبات من نفس المشروع')
  source=Path(asset['path'])
  if source.stat().st_size>10*1024*1024 or file_hash(source)!=asset['hash']:raise ValueError('دليل غير صالح أو متغير')
  with source.open('rb') as f:magic=f.read(12)
  if not (magic.startswith(b'\x89PNG\r\n\x1a\n') or magic.startswith(b'\xff\xd8\xff')):raise ValueError('دليل المراجعة يجب أن يكون صورة PNG أو JPEG')
  image=next((x for x in probe(source).get('streams',[]) if x.get('codec_type')=='video'),{})
  if image.get('width',0)<200 or image.get('height',0)<100:raise ValueError('صورة الإثبات غير قابلة للقراءة')
  result_file=reviews/f'result-{index+1:02d}.json';evidence=reviews/f'evidence-{index+1:02d}{source.suffix.lower()}'
  shutil.copyfile(source,evidence);p.save(result_file,result)
  with store.connect() as c:c.execute("UPDATE assets SET source_type='review_evidence',metadata=? WHERE id=?",(json.dumps({'review_job':job_id,'chunk':index,'not_broll':True}),evidence_asset))
  chunk.update(status='completed',result=result_file.name,result_sha256=file_hash(result_file),
               evidence_file=evidence.name,evidence_sha256=file_hash(evidence))
  state['status']='reviewed_requires_alignment' if all(c['status']=='completed' for c in state['chunks']) else 'prepared_for_ui'
  receipt=reviews/'ui-evidence.json'
  evidence_entries=[]
  for c in state['chunks']:
   if c['status']!='completed':continue
   if file_hash(reviews/c['evidence_file'])!=c['evidence_sha256']:raise ValueError('دليل سابق تغير')
   evidence_entries.append({'file':c['evidence_file'],'sha256':c['evidence_sha256']})
  p.save(receipt,{'review_method':'aistudio_ui','chunk_evidence':evidence_entries,'api_success':False})
  state.update(evidence_file=receipt.name,evidence_sha256=file_hash(receipt));p.save(reviews/'run.json',state)
  with store.connect() as c:out=store.one(c,'SELECT result FROM jobs WHERE id=?',(summary['output_job'],))
  media=json.loads(out['result'])['file']
  if file_hash(media)!=summary['output_sha256']:raise ValueError('النسخة النهائية تغيرت أثناء المراجعة')
  from monteer.audio_review.gate import check
  gate=check(media,reviews,folder/'technical-checks.json');p.save(folder/'gate.json',gate)
  summary.update(review_complete=state['status']=='reviewed_requires_alignment',
                 status='reviewed' if state['status']=='reviewed_requires_alignment' else 'awaiting_studio_results',gate=gate)
  with store.connect() as c:c.execute('UPDATE jobs SET result=? WHERE id=?',(json.dumps(summary,ensure_ascii=False),job_id))
 return describe(store,job_id)

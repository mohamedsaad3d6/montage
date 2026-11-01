"""Post-cut audio reference analysis. ASR anchors are candidates, never executable cuts."""
import json,os,re,subprocess,time,hashlib
from pathlib import Path
from collections import defaultdict
from core import Invalid,Conflict,fingerprint
from media import tool,run,ROOT,Cancelled

def normalize(text):
 text=re.sub('[\u0610-\u061a\u064b-\u065f\u0670\u0640]','',text).translate(str.maketrans('أإآىة','ااايه'))
 return re.sub(r'[^\w\s]',' ',text).strip().split()

def words(data,offset=0):
 rows=[]
 for seg in data.get('transcription',[]):
  current=None
  for tok in seg.get('tokens',[]):
   text=tok.get('text','');clock=tok.get('offsets',{});a=clock.get('from',0)/1000+offset;b=clock.get('to',0)/1000+offset
   if not text.strip() or text.startswith('[_'):continue
   if text.startswith(' ') or current is None:
    current={'text':text.strip(),'start':a,'end':b};rows.append(current)
   else:current['text']+=text;current['end']=max(current['end'],b)
 out=[]
 for row in rows:
  n=normalize(row['text'])
  if len(n)==1 and row['end']>row['start']:out.append({**row,'n':n[0]})
 return out

def anchors(source,reference,width=6):
 """Exact contextual anchors; ambiguous repeated takes remain unresolved."""
 lookup=defaultdict(list)
 for i in range(len(source)-width+1):lookup[tuple(x['n']for x in source[i:i+width])].append(i)
 found=[];ambiguous=0;matched=set();last_source=-1
 for i in range(0,max(0,len(reference)-width+1),max(1,width//2)):
  key=tuple(x['n']for x in reference[i:i+width]);hits=lookup.get(key,[])
  if len(hits)>1:ambiguous+=1;continue
  if not hits:continue
  j=hits[0]
  # A backwards jump could be a retake/order change: do not resolve from ASR alone.
  reverse=j<last_source;last_source=j
  found.append({'reference_start':reference[i]['start'],'reference_end':reference[i+width-1]['end'],'source_start':source[j]['start'],'source_end':source[j+width-1]['end'],'text':' '.join(x['text']for x in reference[i:i+width]),'source_word_index':j,'reference_word_index':i,'backward_jump':reverse,'executable':False})
  if not reverse:matched.update(range(i,i+width))
 return {'anchors':found,'ambiguous_phrases':ambiguous,'reference_words':len(reference),'matched_word_fraction':len(matched)/len(reference)if reference else 0,'automatic_cuts_applied':False,'requires_acoustic_boundary_verification':True,'independent_audio_review_passed':False}

def transcribe(path,duration,folder,cancel,stage,label,cache_root=None):
 """Bounded local chunks, cache bound to exact extracted PCM. No cloud."""
 folder=Path(folder);folder.mkdir(exist_ok=True);all_words=[]
 model=Path(os.environ.get('MONTAJ_WHISPER_MODEL')or str(ROOT.parent/'AI agent/monteer_data/models/whisper/ggml-large-v3-turbo.bin'))
 if not model.is_file():raise Invalid('نموذج التفريغ العربي المحلي غير متاح')
 from asr_cache import restore as cache_restore,save as cache_save
 cli=tool('whisper-cli')
 engine={'schema':1,'model_sha256':fingerprint(model),'binary_sha256':fingerprint(cli),'language':'ar','full_json':True,'threads':4}
 for i,start in enumerate(range(0,int(duration)+1,300)):
  length=min(300,duration-start)
  if length<=0:break
  if cancel():raise Cancelled()
  stage(label);stem=folder/f'{i:04d}';wav=stem.with_suffix('.wav');receipt=stem.with_suffix('.receipt.json');out=stem.with_suffix('.json')
  if not wav.exists():run(['-ss',start,'-i',path,'-t',length,'-ar',16000,'-ac',1,'-c:a','pcm_s16le',wav],folder,cancel)
  digest=fingerprint(wav);valid=False;identity={**engine,'pcm_sha256':digest}
  if receipt.exists()and out.exists():
   try:
    old=json.loads(receipt.read_text());valid=old.get('identity')==identity and old.get('asr_sha256')==fingerprint(out)
   except (OSError,ValueError):valid=False
  if not valid and cache_root is not None:valid=cache_restore(cache_root,identity,out)
  if not valid:
   with stem.with_suffix('.log').open('wb')as log:
    p=subprocess.Popen([cli,'-m',str(model),'-f',str(wav),'-l','ar','-ojf','-of',str(stem),'-t','4'],stdin=subprocess.DEVNULL,stdout=log,stderr=log,env={**os.environ,'XDG_CACHE_HOME':str(folder/'cache')})
    while p.poll()is None:
     if cancel():p.terminate();p.wait();raise Cancelled()
     time.sleep(.2)
    if p.returncode:raise Invalid('تعذر تفريغ جزء المطابقة؛ لا قص آلي')
  # Bind model/settings as well as PCM; old receipts lacking this identity are not trusted.
  receipt.write_text(json.dumps({'identity':identity,'pcm_sha256':digest,'asr_sha256':fingerprint(out),'start_seconds':start,'duration_seconds':length}))
  if cache_root is not None:cache_save(cache_root,identity,out)
  all_words.extend(words(json.loads(out.read_text()),start))
  (folder/'progress.json').write_text(json.dumps({'completed_chunks':i+1,'total_chunks':int((duration+299.999)//300),'source':label,'completed_seconds':start+length}))
 return all_words

def coarse_acoustic_map(video,voice,folder,cancel,stage):
 from input_prepare import pcm,match
 import numpy as np
 stage('reference_coarse_match');source=pcm(video['path'],0,video['duration'],folder,cancel);points=[]
 if voice['duration']<10:return []
 positions=sorted(set([min(35,max(0,voice['duration']-9))]+[round(float(x),2)for x in np.linspace(max(0,voice['duration']*.08),max(0,voice['duration']-10),8)]))
 for pos in positions:
  if cancel():raise Cancelled()
  try:
   ref=pcm(voice['path'],pos,8,folder,cancel);lag,score,margin=match(ref,source);points.append({'reference_seconds':pos,'source_seconds':lag,'correlation':score,'peak_margin':margin,'passed':score>=.65 and margin>=.025,'executable_cut_boundary':False})
  except Invalid:points.append({'reference_seconds':pos,'passed':False,'executable_cut_boundary':False})
 return points

def check_acoustic_samples(video,voice,rows,folder,cancel,stage,limit=12):
 from input_prepare import pcm,match
 import numpy as np
 if not rows:return []
 samples=[]
 for index in sorted(set(int(x)for x in np.linspace(0,len(rows)-1,min(limit,len(rows))))):
  stage('reference_acoustic_match');row=rows[index];length=min(3,row['reference_end']-row['reference_start'])
  if length<1:continue
  ref_start=row['reference_start'];src_start=max(0,row['source_start']-2)
  try:
   reference=pcm(voice['path'],ref_start,length,folder,cancel);source=pcm(video['path'],src_start,min(length+4,video['duration']-src_start),folder,cancel);lag,score,margin=match(reference,source)
   samples.append({'anchor_index':index,'reference_start':ref_start,'source_start_measured':src_start+lag,'correlation':score,'peak_margin':margin,'passed':score>=.65 and margin>=.025,'executable_cut_boundary':False})
  except Invalid:samples.append({'anchor_index':index,'passed':False,'reason':'insufficient_acoustic_evidence','executable_cut_boundary':False})
 return samples

def prepare_text_diagnostic(store,rev,folder,options,cancel,stage,video,voice,state):
 coarse=coarse_acoustic_map(video,voice,folder,cancel,stage)
 (Path(folder)/'coarse-acoustic-map.json').write_text(json.dumps({'samples':coarse,'scope':'distributed_acoustic_anchor_samples_not_complete_cut_plan'},ensure_ascii=False,indent=2))
 stage('reference_camera_asr');source=transcribe(video['path'],video['duration'],Path(folder)/'camera',cancel,stage,'reference_camera_asr',store.root/'cache'/'asr-v1')
 stage('reference_master_asr');reference=transcribe(voice['path'],voice['duration'],Path(folder)/'master',cancel,stage,'reference_master_asr',store.root/'cache'/'asr-v1')
 stage('reference_word_match');report=anchors(source,reference)
 report['coarse_acoustic_samples']=coarse
 report['acoustic_samples']=check_acoustic_samples(video,voice,report['anchors'],folder,cancel,stage)
 report['acoustic_scope']='at_most_12_distributed_phrase_samples_not_all_joins'
 for a in (video,voice):
  if fingerprint(store.resolve(a['path']))!=a['hash']:raise Invalid('المصدر تغير أثناء مطابقة مرجع الصوت')
 from intake import get
 if get(store,rev['project'])['version']!=state['version']:raise Conflict('اختيارات الملفات تغيرت أثناء المطابقة؛ الخطة القديمة غير صالحة للتطبيق')
 report.update({'sync_status':'post_cut_reference_candidates','source_revision':rev['id'],'input_version':state['version'],'video_id':video['id'],'voice_id':voice['id'],'video_sha256':video['hash'],'voice_sha256':voice['hash'],'video_duration_seconds':video['duration'],'reference_duration_seconds':voice['duration'],'audio_unchanged':True,'source_words':len(source),'scope':'candidate_word_correspondence_only_not_frame_cut_plan'})
 out=Path(folder)/'reference-alignment.json';out.write_text(json.dumps(report,ensure_ascii=False,indent=2));report['report_file']=str(out);report['report_sha256']=fingerprint(out)
 return report


def prepare(store,rev,folder,options,cancel,stage,video,voice,state):
 """Acoustic first: edited reference already chooses the words; raw ASR is not a prerequisite."""
 from intake import get
 folder=Path(folder);stage('reference_coarse_match');samples=coarse_acoustic_map(video,voice,folder,cancel,stage)
 for asset in (video,voice):
  if fingerprint(store.resolve(asset['path']))!=asset['hash']:raise Invalid('المصدر تغير أثناء قياس المراسي الصوتية')
 if get(store,rev['project'])['version']!=state['version']:raise Conflict('المدخلات تغيرت أثناء المطابقة')
 report={'sync_status':'post_cut_acoustic_candidates','analysis_mode':'acoustic_first','source_revision':rev['id'],'input_version':state['version'],'video_id':video['id'],'voice_id':voice['id'],'video_sha256':video['hash'],'voice_sha256':voice['hash'],'video_duration_seconds':video['duration'],'reference_duration_seconds':voice['duration'],'coarse_acoustic_samples':samples,'anchors':[],'automatic_cuts_applied':False,'asr_deferred_until_reference_timeline':True,'independent_audio_review_passed':False,'scope':'acoustic_proposals_not_executable_picture_plan'}
 file=folder/'reference-alignment.json';file.write_text(json.dumps(report,ensure_ascii=False,indent=2));report.update(report_file=str(file),report_sha256=fingerprint(file));return report

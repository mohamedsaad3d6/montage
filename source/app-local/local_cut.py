"""Local quiet-only candidate; speech comparisons stay unresolved, never approved."""
import array,json,math,wave
from pathlib import Path
from core import Invalid,Conflict
from media import file_hash
from take_review import bound
from cutplan import apply as apply_quiet

def apply(store,project,analysis_job,expected):
 source,r,audio,duration,items=bound(store,analysis_job);p=store.project(project)
 if source['project']!=project or source['revision']!=expected or p['active']!=expected:raise Conflict('تحليل محلي من نسخة مختلفة')
 t=p['revision']['timeline'];fps=t['fps']
 if t.get('phase')!='raw' or any(tr.get('locked') for tr in t['tracks'] if tr['kind'] in ('video','voice')):raise Invalid('التنظيف المحلي يحتاج خامًا ومسارات غير مقفلة')

 if not r.get('source_words_file') or not r.get('source_words_sha256'):raise Invalid('دليل الكلمات المحلي غير مكتمل؛ لا قص تخميني')
 wp=Path(r['source_words_file']).resolve();folder=store.root/'jobs'/source['id']
 if folder not in wp.parents or file_hash(wp)!=r['source_words_sha256']:raise Invalid('دليل الكلمات المحلي تغير')
 words=json.loads(wp.read_text())['words']
 if not words:raise Invalid('الكلمات المحلية غير متاحة')
 original=json.loads(Path(r['plan_file']).read_text());cuts=[];held=[]
 protected=[*words,*[a for i in items for a in i['attempts']]]
 with wave.open(str(audio),'rb') as wav:
  rate=wav.getframerate()
  for cut in original.get('cuts',[]):
   a,b=cut.get('start_frame'),cut.get('end_frame')
   if cut.get('kind')!='quiet_gap_only' or cut.get('removed_word_ids') or type(a)!=int or type(b)!=int or not 0<=a<b<=t['duration_frames']:raise Invalid('خطة سكتات محلية غير صالحة')
   start,end=a/fps,b/fps
   if any(w.get('s',w.get('start',0))-.12<end and w.get('e',w.get('end',0))+.12>start for w in protected):held.append(cut);continue
   wav.setpos(round(start*rate));pcm=array.array('h',wav.readframes(round((end-start)*rate)))
   if not pcm or math.sqrt(sum(v*v for v in pcm)/len(pcm))/32768>10**(-50/20):held.append(cut);continue
   cuts.append(cut)
 out=apply_quiet(t,{'cuts':cuts});receipt=folder/'local-quiet-candidate.json'
 evidence={'analysis_job':source['id'],'audio_sha256':r['wave_sha256'],'original_plan_sha256':r['plan_sha256'],'fps':fps,'cuts':cuts,'decisions':[],
 'keeps':[{'start_frame':k['input_start_frame'],'end_frame':k['input_end_frame']} for k in out['raw_to_output']], 'audit_raw_range':[0,duration],
 'unresolved_comparisons':items,'held_quiet_cuts':held,'speech_deletions':0,'breath_deletions':0,'status':'internal_local_candidate_pending_independent_review'}
 receipt.write_text(json.dumps(evidence,ensure_ascii=False,indent=2))
 out['cutting_proof']={'plan_file':str(receipt),'plan_sha256':file_hash(receipt),'source_words_file':str(wp),'source_words_sha256':r['source_words_sha256'],'source_asset_id':r['source_asset_id'],'source_asset_sha256':r['source_asset_sha256'],'decisions':[]}
 out['local_cut_analysis_job']=source['id'];out['unresolved_take_comparisons']=len(items);out['requires_new_independent_audio_review']=True
 out['local_cut_summary']={'quiet_cuts':len(cuts),'held_quiet_cuts':len(held),'removed_seconds':sum(c['end_frame']-c['start_frame'] for c in cuts)/fps,'speech_deletions':0,'breath_deletions':0}
 def guard(c):
  if file_hash(audio)!=r['wave_sha256'] or file_hash(r['plan_file'])!=r['plan_sha256'] or file_hash(wp)!=r['source_words_sha256']:raise Conflict('دليل التنظيف المحلي تغير قبل الحفظ')
 return store.save(project,expected,out,'تقطيع محلي للسكتات المثبتة فقط؛ المحاولات محفوظة والمراجعة المستقلة معلقة',trusted_cut_proof=True,commit_guard=guard)

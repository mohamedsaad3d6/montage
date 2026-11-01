"""Real word evidence for continuous uncut narration; never fabricate an empty audit."""
import json
from pathlib import Path
from media import file_hash

def uncut_receipt(store,rev,folder):
 t=rev['timeline'];clips=[c for tr in t['tracks'] if tr['kind']=='voice' for c in tr['clips']]
 if len(clips)!=1 or clips[0]['start_frame']!=0 or clips[0]['end_frame']!=t['duration_frames']:
  raise ValueError('يلزم دليل الكلمات وخطة القص قبل إرسال الصوت للمراجعة')
 clip=clips[0];asset=store.asset(clip['asset_id'])
 if file_hash(asset['path'])!=asset['hash']:raise ValueError('مصدر الصوت تغير')
 with store.connect() as c:
  jobs=[dict(x) for x in c.execute("SELECT * FROM jobs WHERE project=? AND revision=? AND kind IN ('transcribe','editorial_plan') AND status='completed' ORDER BY created DESC",(rev['project'],rev['id']))]
 words=None
 for job in jobs:
  r=json.loads(job['result'])
  if r.get('source_asset_id')!=asset['id'] or r.get('source_asset_sha256')!=asset['hash']:continue
  if r.get('source_words_file'):
   if file_hash(r['source_words_file'])!=r['source_words_sha256']:raise ValueError('دليل الكلمات تغير')
   words=json.loads(Path(r['source_words_file']).read_text())['words']
  elif r.get('analysis_file'):
   if file_hash(r['analysis_file'])!=r['analysis_sha256']:raise ValueError('تحليل الكلمات تغير')
   pieces=r.get('source_voice_pieces')
   if pieces and (len(pieces)!=1 or pieces[0]['source_in_frame']!=clip.get('source_in_frame',0)
                  or pieces[0]['source_out_frame']!=clip['source_out_frame']):continue
   words=json.loads(Path(r['analysis_file']).read_text())['words']
  if words:break
 if not words:raise ValueError('حلّل كلمات هذه النسخة قبل المراجعة؛ لا دليل كلمات فارغ')
 folder=Path(folder);wp=folder/'uncut-source-words.json';pp=folder/'uncut-word-plan.json'
 wp.write_text(json.dumps({'words':words},ensure_ascii=False,indent=2))
 pp.write_text(json.dumps({'fps':t['fps'],'keeps':[{'start_frame':0,'end_frame':t['duration_frames']}],
                          'audit_raw_range':[0,t['duration_frames']/t['fps']],
                          'word_deletions':0,'continuous_voice_unchanged_source_intervals':True},indent=2))
 return {'plan_file':str(pp),'plan_sha256':file_hash(pp),'source_words_file':str(wp),
         'source_words_sha256':file_hash(wp),'source_asset_id':asset['id'],'source_asset_sha256':asset['hash']}

def validate_proof(store,proof):
 if proof.get('audit_method')=='full_source_byte_identity':
  source=store.asset(proof['source_asset_id'])
  if Path(source['path']).resolve()!=Path(proof['source_file']).resolve() or source['hash']!=proof['source_sha256']:raise ValueError('مرجع هوية صوت غير صالح')
  if file_hash(source['path'])!=source['hash'] or file_hash(proof['reviewed_media_file'])!=source['hash']:raise ValueError('المرجع لم يعد مطابقًا بايتًا')
  return
 for path,sha in [('plan_file','plan_sha256'),('source_words_file','source_words_sha256')]:
  if file_hash(proof[path])!=proof[sha]:raise ValueError('دليل الكلمات تغير؛ المراجعة ممنوعة')
 words=json.loads(Path(proof['source_words_file']).read_text())
 if not (words.get('words') if isinstance(words,dict) else words):raise ValueError('دليل الكلمات فارغ')
 plan=json.loads(Path(proof['plan_file']).read_text())
 pause=plan.get('confirmed_pause_plan')
 if pause and file_hash(pause['file'])!=pause['sha256']:raise ValueError('دليل مراجعة السكتات تغير')
 if proof.get('decisions',[])!=plan.get('decisions',[]):raise ValueError('قرارات حذف الكلام لا تطابق خطة القص')
 for decision in proof.get('decisions',[]):
  for key in ['evidence','boundary_attestation']:
   if not decision.get(key+'_file') or file_hash(decision[key+'_file'])!=decision.get(key+'_sha256'):raise ValueError('دليل قرار الوصلة تغير')
 source=store.asset(proof['source_asset_id'])
 if file_hash(source['path'])!=proof['source_asset_sha256']:raise ValueError('الخام تغير بعد تدقيق الكلمات')

def reference_receipt(store,rev,result):
 """Whole-file byte equality proves no word was removed; this is not an empty word list."""
 if result.get('byte_identical_reference') is not True:return None
 clips=[c for tr in rev['timeline']['tracks'] if tr['kind']=='voice' for c in tr['clips']]
 if len(clips)!=1:raise ValueError('مرجع صوتي غير متصل')
 source=store.asset(clips[0]['asset_id'])
 if result['file_sha256']!=source['hash'] or file_hash(source['path'])!=source['hash'] or file_hash(result['file'])!=source['hash']:
  raise ValueError('لا تطابق بايت للمرجع الكامل؛ يلزم تدقيق الكلمات المعتاد')
 return {'audit_method':'full_source_byte_identity','source_asset_id':source['id'],
         'source_file':source['path'],'source_sha256':source['hash'],
         'reviewed_media_file':result['file'],'reviewed_media_sha256':result['file_sha256'],
         'word_deletion_possible':False}

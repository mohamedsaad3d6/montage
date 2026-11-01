"""Optional free-only reviewer adapter. Default off; exact per-output consent is required."""
import json,os,sys,wave
from pathlib import Path
from media import ROOT,run,tool,file_hash,Cancelled

def check_free_connection():
 sys.path.insert(0,str(ROOT/'engine'))
 from monteer.audio_review.pipeline import credentials
 config=os.environ.get('MONTAJ_GOOGLE_CONNECTION',str(Path.home()/'.config/monteer/gemini/connection.json'))
 credentials(config)
 return config

def review_output(store,rev,folder,options,cancel):
 if options.get('consent_google_audio') is not True:raise ValueError('إرسال الصوت إلى Google يحتاج اختيارًا صريحًا لهذا الناتج')
 with store.connect() as c:j=store.one(c,'SELECT * FROM jobs WHERE id=?',(options.get('output_job'),))
 if j['kind']!='render' or j['status']!='completed' or j['project']!=rev['project'] or j['revision']!=rev['id']:raise ValueError('اختَر ناتجًا مكتملًا من نفس النسخة')
 result=json.loads(j['result']);media=Path(result['file']).resolve()
 if file_hash(media)!=result.get('file_sha256'):raise ValueError('ملف الناتج اتغير؛ المراجعة ممنوعة')
 from audit import uncut_receipt,validate_proof,reference_receipt
 proof=result.get('cutting_proof') or reference_receipt(store,rev,result) or uncut_receipt(store,rev,folder)
 validate_proof(store,proof)
 sys.path.insert(0,str(ROOT/'engine'))
 from monteer.audio_review.pipeline import prepare,review,credentials,request
 from monteer.audio_review.gate import check
 config=check_free_connection() # free-only, billing-disabled; no network probe or key output
 wav=folder/'exact-final-audio.wav';reviews=folder/'independent-review'
 if not wav.exists():run(['-i',media,'-map','0:a:0','-ar','16000','-ac','1','-c:a','pcm_s16le',wav],folder,cancel)
 with wave.open(str(wav),'rb') as w:duration=w.getnframes()/w.getframerate()
 if not reviews.exists():prepare(wav,reviews,tool('ffmpeg'),seconds=duration,stage='after')
 def transport(audio,prompt,key):
  if cancel():raise Cancelled()
  return request(audio,prompt,key,timeout=180)
 state=review(reviews,config,transport=transport)
 (reviews/'final-media-binding.json').write_text(json.dumps({'media_sha256':result['file_sha256'],'audio_sha256':file_hash(wav),'media_duration_seconds':duration},indent=2))
 checks=folder/'technical-checks.json';checks.write_text(json.dumps({'technical_pass':result['technical_decode'],'output_sha256':result['file_sha256']}))
 validate_proof(store,proof)
 binding={'media_sha256':result['file_sha256'],**proof,'decisions':proof.get('decisions',[])}
 (reviews/'word-audit-binding.json').write_text(json.dumps(binding,ensure_ascii=False,indent=2))
 # Missing/partial evidence remains blocked; no empty synthetic word list.
 gate=check(media,reviews,checks);(folder/'gate.json').write_text(json.dumps(gate,ensure_ascii=False,indent=2))
 return {'scope':'independent_audio_review_only','review_complete':state['status']=='reviewed_requires_alignment','gate':gate,'output_job':j['id'],'output_sha256':result['file_sha256'],'publication_approved':False}

"""Machine listening proposals, separate from human take choices and release approval."""
import hashlib,json,os,time,wave
from pathlib import Path
from core import Invalid,Conflict
from media import Cancelled,file_hash
from take_review import bound

PROMPT='''Listen to the original Arabic recording, including restarts, pronunciation, emphasis and context. Compare the numbered audio intervals below. Do not choose the last take by default. Preserve meaningful additions. Return only JSON {"comparisons":[{"candidate":"exact key","classification":"restart|intentional_repeat|uncertain","selected_attempt":integer or null,"kept_complete":boolean,"pronunciation_clear":boolean,"reason":"Arabic explanation grounded in heard audio","quote":"short actually heard phrase"}]}. For a restart choose a take only if it is complete and clearly pronounced; otherwise use uncertain. Timestamps are rough context labels, never authorized cut boundaries. This is analysis only, no publication approval.\n'''

def groups(candidates,duration):
 result=[]
 for item in sorted(candidates,key=lambda x:x['attempts'][0]['start']):
  start=max(0,min(x['start']for x in item['attempts'])-5);end=min(duration,max(x['end']for x in item['attempts'])+8)
  if end-start>120:raise Invalid('مقارنة أطول من نافذة الاستماع؛ تحتاج تقسيمًا موثقًا')
  if result and start<=result[-1]['end'] and max(end,result[-1]['end'])-result[-1]['start']<=120:
   result[-1]['end']=max(result[-1]['end'],end);result[-1]['items'].append(item)
  else:result.append({'start':start,'end':end,'items':[item]})
 return result

def validate(value,items):
 rows=value.get('comparisons') if isinstance(value,dict)else None
 expected={i['key']:i for i in items}
 if not isinstance(rows,list)or len(rows)!=len(expected):raise Invalid('مراجعة المحاولات لم تغطِّ المقارنات المطلوبة')
 seen=set()
 for row in rows:
  key=row.get('candidate');item=expected.get(key)
  if not item or key in seen:raise Invalid('هوية مقارنة غير صالحة في الرد')
  seen.add(key);kind=row.get('classification');selected=row.get('selected_attempt')
  if kind not in ('restart','intentional_repeat','uncertain'):raise Invalid('تصنيف مقارنة غير صالح')
  if any(type(row.get(k))is not bool for k in ('kept_complete','pronunciation_clear')):raise Invalid('رد المقارنة ناقص دليل الاكتمال والنطق')
  if any(not isinstance(row.get(k),str)or len(row[k].strip())<3 for k in ('reason','quote')):raise Invalid('رد المقارنة بلا سبب أو عبارة مسموعة')
  if kind=='restart':
   if type(selected)is not int or not 0<=selected<len(item['attempts']):raise Invalid('رقم محاولة غير صالح')
   if not(row['kept_complete']and row['pronunciation_clear']):raise Invalid('المحاولة المختارة لم تجتز اكتمال الكلام والنطق')
  elif selected is not None:raise Invalid('لا اختيار محاولة مع تكرار مقصود أو مقارنة غير محسومة')
 return rows

def safe_failure(exc):
 # Persist only fixed codes, never raw exception text, URLs or credentials.
 message=str(exc)
 if isinstance(exc,TimeoutError):return {'kind':'timeout'}
 if isinstance(exc,RuntimeError):
  import re
  match=re.fullmatch(r'Gemini HTTP ([45][0-9]{2}); stopped with no retry or fallback',message)
  if match:return {'kind':'http','http_status':int(match[1])}
  if message=='Gemini network failure; request may have been processed; no automatic retry':return {'kind':'network_unknown'}
  if message=='Gemini response incomplete; stopped':return {'kind':'response_incomplete'}
  if message=='Gemini did not return valid JSON; no edits applied':return {'kind':'invalid_json'}
 if isinstance(exc,Invalid):return {'kind':'comparison_validation'}
 return {'kind':'unknown'}

def assess(store,rev,folder,options,cancel,transport=None):
 if options.get('consent_google_audio')is not True:raise Invalid('مقارنة الصوت في Google تحتاج موافقة لهذا التحليل')
 j,r,audio,duration,candidates=bound(store,options.get('analysis_job'))
 if j['project']!=rev['project']or j['revision']!=rev['id']:raise Conflict('تحليل المحاولات من حلقة أو نسخة مختلفة')
 if options.get('audio_sha256')!=r['wave_sha256']or options.get('plan_sha256')!=r['plan_sha256']:raise Conflict('تغيرت بصمة الصوت أو المقارنات قبل الإرسال')
 from reviewer import check_free_connection
 config=check_free_connection()
 from monteer.audio_review.pipeline import credentials,request,MODEL
 key=credentials(config)
 if transport is None:transport=lambda data,prompt,secret:request(data,prompt,secret,timeout=90,max_output_tokens=5000)
 folder=Path(folder);ledger=store.root/'take-assessment-ledger';ledger.mkdir(exist_ok=True);windows=groups(candidates,duration);all_rows=[];receipts=[]
 with wave.open(str(audio),'rb')as source:
  rate=source.getframerate()
  for index,window in enumerate(windows):
   if cancel():raise Cancelled()
   clip=folder/f'original-context-{index:03d}.wav';source.setpos(round(window['start']*rate))
   with wave.open(str(clip),'wb')as dest:dest.setparams(source.getparams());dest.writeframes(source.readframes(round((window['end']-window['start'])*rate)))
   labels=[{'candidate':i['key'],'intervals':[{'attempt':n,'start':round(a['start']-window['start'],3),'end':round(a['end']-window['start'],3)}for n,a in enumerate(i['attempts'])]}for i in window['items']]
   prompt=PROMPT+json.dumps(labels,ensure_ascii=False);digest=file_hash(clip);identity={'audio_sha256':digest,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'model':MODEL};fingerprint=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest();receipt=ledger/(fingerprint+'.json')
   state=json.loads(receipt.read_text())if receipt.exists()else None
   if state and any(state.get(k)!=v for k,v in identity.items()):raise Invalid('هوية دليل المقارنة المحفوظ تغيرت')
   if state and state['status']=='in_flight':raise Invalid('طلب مراجعة محاولات سابق غير محسوم؛ لا إعادة إرسال تلقائية')
   if state and state['status']=='completed':
    payload=state['response'];rows=validate(payload,window['items'])
    if hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()!=state['response_sha256']:raise Invalid('دليل مراجعة المحاولات تغير')
   else:
    state={**identity,'status':'in_flight','project':rev['project'],'revision':rev['id'],'analysis_job':j['id'],'source_start':window['start'],'source_end':window['end'],'sent_at':time.time()};_save(receipt,state)
    try:payload=transport(clip.read_bytes(),prompt,key);rows=validate(payload,window['items'])
    except Exception as exc:
     state['failure']=safe_failure(exc);state['failed_at']=time.time();state['stopped_needs_reconciliation']=True;_save(receipt,state);raise Invalid('لم تكتمل مراجعة المحاولات عبر Google؛ النتيجة غير محسومة ومحفوظة، لن يعاد إرسالها تلقائيًا')from None
    state.update(status='completed',response=payload,response_sha256=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest());_save(receipt,state)
   all_rows.extend(rows);receipts.append({'file':str(receipt),'sha256':file_hash(receipt)})
   _save(folder/'take-assessment-progress.json',{'completed_groups':index+1,'total_groups':len(windows),'updated':time.time(),'scope':'machine_listening_not_cut_or_release_approval'})
 _,fresh,_,_,_=bound(store,j['id'])
 if fresh['plan_sha256']!=r['plan_sha256']:raise Conflict('خطة المقارنات تغيرت أثناء الاستماع')
 if file_hash(audio)!=r['wave_sha256']:raise Conflict('الصوت تغير أثناء المراجعة؛ لا قرار قابل للتطبيق')
 report={'status':'machine_proposals_require_boundary_verification','analysis_job':j['id'],'revision':rev['id'],'audio_sha256':r['wave_sha256'],'plan_sha256':r['plan_sha256'],'comparisons':all_rows,'evidence':receipts,'human_listening_attested':False,'cuts_applied':False,'independent_final_audio_review_passed':False}
 out=folder/'machine-take-proposals.json';_save(out,report)
 return {'status':report['status'],'analysis_job':j['id'],'audio_sha256':r['wave_sha256'],'plan_sha256':r['plan_sha256'],'report_file':str(out),'report_sha256':file_hash(out),'comparisons':len(all_rows),'uncertain':sum(x['classification']=='uncertain'for x in all_rows),'cuts_applied':False,'human_listening_attested':False,'independent_audio_review_granted':False}

def _save(path,data):
 path=Path(path);tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2));os.replace(tmp,path)

"""Independent bounded ASR chunks with exact PCM receipts and no carried text context."""
import copy,json,os,subprocess,wave,time
from pathlib import Path
from core import fingerprint,Invalid
from media import tool,Cancelled
from asr_cache import restore,save
from transcription_quality import inspect

def transcribe(wav,folder,model,cache_root,cancel,progress=lambda _:None):
 folder=Path(folder);parts=folder/'asr-parts';parts.mkdir(exist_ok=True);cli=tool('whisper-cli')
 identity={'schema':2,'model_sha256':fingerprint(model),'binary_sha256':fingerprint(cli),'language':'ar','threads':4,'max_context':0,'full_json':True}
 merged=[];quality=[]
 with wave.open(str(wav),'rb')as source:
  rate=source.getframerate();total=source.getnframes();size=120*rate;count=(total+size-1)//size
  for index,first in enumerate(range(0,total,size)):
   if cancel():raise Cancelled()
   stem=parts/f'{index:04d}';audio=stem.with_suffix('.wav');output=stem.with_suffix('.json');length=min(size,total-first)
   source.setpos(first)
   with wave.open(str(audio),'wb')as dest:dest.setparams(source.getparams());dest.writeframes(source.readframes(length))
   binding={**identity,'pcm_sha256':fingerprint(audio)};cached=restore(cache_root,binding,output)
   if not cached:
    with stem.with_suffix('.log').open('wb')as log:
     proc=subprocess.Popen([cli,'-m',str(model),'-f',str(audio),'-l','ar','-ojf','-of',str(stem),'-t','4','-mc','0'],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,env={**os.environ,'XDG_CACHE_HOME':str(parts/'cache')})
     from process_guard import wait
     try:code=wait(proc,cancel,timeout_seconds=600)
     except TimeoutError:raise Invalid('تجاوز جزء التفريغ مهلة التشغيل؛ الأجزاء المكتملة محفوظة دون اعتماد قص')from None
     if code:raise Invalid('تعذر تفريغ جزء من الصوت؛ لم تتغير الحلقة')
    save(cache_root,binding,output)
   data=json.loads(output.read_text());check=inspect(data);quality.append({'part':index,'start_seconds':first/rate,**check})
   shift=round(first/rate*1000)
   for segment in data.get('transcription',[]):
    segment=copy.deepcopy(segment)
    for item in [segment,*segment.get('tokens',[])]:
     offsets=item.get('offsets')
     if offsets:
      for key in ('from','to'):
       if isinstance(offsets.get(key),(int,float)):offsets[key]+=shift
    segment['unreliable_asr']=check['requires_second_pass'];segment['asr_part']=index;segment['independent_chunk_context']=True;merged.append(segment)
   receipt={'identity':binding,'response_sha256':fingerprint(output),'start_seconds':first/rate,'duration_seconds':length/rate,'quality':check}
   stem.with_suffix('.receipt.json').write_text(json.dumps(receipt,ensure_ascii=False))
   done=(first+length)/rate;progress(done)
   (folder/'asr-progress.json').write_text(json.dumps({'completed_chunks':index+1,'total_chunks':count,'completed_seconds':done,'total_seconds':total/rate,'updated':time.time(),'scope':'asr_not_episode_completion'}))
 result={'transcription':merged,'independent_chunks':count,'max_context':0,'offsets_clock':'full_analysis_audio','not_cut_approval':True}
 (folder/'transcription-quality.json').write_text(json.dumps({'status':'contains_unreliable_parts_kept_in_source'if any(x['requires_second_pass']for x in quality)else'narrow_decoder_check_passed_not_editorial_review','parts':quality},ensure_ascii=False,indent=2))
 return result

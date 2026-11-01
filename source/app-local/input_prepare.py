"""Automatic local audio sync measurement. No user attestation or time stretching."""
import json,math,subprocess,time
from pathlib import Path
from core import Invalid,Conflict,fingerprint
from media import tool,probe,Cancelled

def pcm(path,start,seconds,folder,cancel):
 out=Path(folder)/'sync-sample.f32'
 with out.open('wb')as f:
  p=subprocess.Popen([tool('ffmpeg'),'-v','error','-ss',str(start),'-t',str(seconds),'-i',str(path),'-vn','-af','highpass=f=100,lowpass=f=1800','-ar','4000','-ac','1','-f','f32le','-'],stdout=f,stderr=subprocess.DEVNULL)
  while p.poll()is None:
   if cancel():p.terminate();p.wait();raise Cancelled()
   time.sleep(.05)
  if p.returncode:raise Invalid('تعذر استخراج عينات فحص التزامن')
 import numpy as np
 x=np.fromfile(out,dtype='<f4');out.unlink(missing_ok=True)
 if len(x)<4000:raise Invalid('عينة الصوت أقصر من المطلوب لفحص التزامن')
 n=len(x)//40;x=x[:n*40].reshape(n,40);return np.log(np.sqrt(np.mean(x*x,axis=1))+.0001)

def match(reference,search):
 import numpy as np
 n=len(reference);m=len(search)
 if m<n or np.std(reference)<.08:raise Invalid('الصوت المرجعي صامت أو غير كافٍ لقياس التزامن')
 q=reference-reference.mean();size=1<<(n+m-1).bit_length()
 conv=np.fft.irfft(np.fft.rfft(search,size)*np.fft.rfft(q[::-1],size),size)[n-1:m]
 sums=np.r_[0,np.cumsum(search)];squares=np.r_[0,np.cumsum(search*search)];energy=np.maximum(squares[n:]-squares[:-n]-(sums[n:]-sums[:-n])**2/n,0)
 score=np.divide(conv,np.sqrt(energy*np.sum(q*q)),out=np.zeros_like(conv),where=energy>1e-8);best=int(np.argmax(score));masked=score.copy();masked[max(0,best-30):best+31]=-1
 return best/100,float(score[best]),float(score[best]-np.max(masked))

def prepare(store,rev,folder,options,cancel,stage):
 from intake import get,checked_asset
 state=get(store,rev['project']);p=store.project(rev['project'])
 if p['active']!=rev['id'] or state['version']!=options.get('input_version') or rev['timeline']['duration_frames']:raise Conflict('المدخلات أو نسخة الحلقة تغيرت؛ اضغط ابدأ على اختياراتك الحالية')
 sel=state['selection'];video=checked_asset(store,rev['project'],sel.get('video'),'video');info=probe(video['path']);has_camera=any(x['codec_type']=='audio'for x in info['streams']);n=int(video['duration']*24)
 result={'input_version':state['version'],'source_revision':rev['id'],'video_id':video['id'],'video_sha256':video['hash'],'independent_audio_review_passed':False}
 if sel['voice_mode']=='camera':
  if not has_camera:raise Invalid('الفيديو لا يحتوي على صوت؛ أضف ملف الصوت الخارجي')
  result.update({'sync_status':'camera_same_container','offset_frames':0});return result
 if not has_camera:raise Invalid('تعذر قياس التزامن تلقائيًا لأن الفيديو بلا صوت مرجعي؛ يلزم مرجع صوتي من الكاميرا')
 voice=checked_asset(store,rev['project'],sel.get('voice'),'audio')
 if sel['voice_mode']=='external_cut':
  from cut_reference import prepare as prepare_reference
  return prepare_reference(store,rev,folder,options,cancel,stage,video,voice,state)
 d=video['duration'];length=min(12,d/5)
 if length<3:raise Invalid('الملف أقصر من فحص التزامن التلقائي الموثوق')
 windows=[min(15,d*.1),max(0,d*.5-length/2),max(0,d-length-2)];observations=[];hint=sel.get('audio_offset_frames',0)/24
 for index,base in enumerate(windows):
  stage(['sync_beginning','sync_middle','sync_ending'][index]);found=None
  offsets_to_try=range(0,int(min(420,max(0,d*.2)))+1,30) if index==0 else (0,-15,15,-30,30) if index==1 else (0,-30,-60,-120)
  for delta in offsets_to_try:
   pos=base+delta
   if pos<0 or pos+length>d:continue
   left=max(0,pos+hint-30);right=min(voice['duration'],pos+hint+length+30)
   if right-left<length:continue
   try:
    a=pcm(video['path'],pos,length,folder,cancel);b=pcm(voice['path'],left,right-left,folder,cancel);lag,score,margin=match(a,b)
   except Invalid:continue
   if score>=.65 and margin>=.025:
    found={'video_seconds':pos,'offset_seconds':left+lag-pos,'correlation':score,'peak_margin':margin};break
  if found is None:raise Invalid('فحص التزامن غير حاسم في '+['بداية التسجيل','منتصف التسجيل','نهاية التسجيل'][index]+'؛ لم يُربط الصوت ولم يبدأ القص. تحقق من نوع الصوت المختار')
  observations.append(found)

 offsets=[x['offset_seconds']for x in observations]
 if max(offsets)-min(offsets)>.06:raise Invalid('اكتُشف اختلاف في التزامن بين البداية والنهاية؛ لا قص أو تمديد للصوت تلقائيًا')
 offset=round(sorted(offsets)[1]*24)
 if offset<0:raise Invalid('الصوت الخارجي يبدأ بعد الفيديو؛ لن نحذف بداية الصورة أو الكلام خفية')
 if offset+n>math.floor(voice['duration']*24):raise Invalid('الصوت الخارجي لا يغطي الفيديو كاملًا بعد قياس التزامن؛ لم يبدأ القص')
 for a in (video,voice):
  if fingerprint(store.resolve(a['path']))!=a['hash']:raise Invalid('مصدر تغير أثناء فحص التزامن')
 result.update({'sync_status':'measured_three_windows','voice_id':voice['id'],'voice_sha256':voice['hash'],'offset_frames':offset,'observations':observations,'maximum_offset_spread_seconds':max(offsets)-min(offsets),'time_stretch_applied':False})
 (Path(folder)/'input-sync.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));return result

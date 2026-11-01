"""Review an unchanged flat source without introducing another encoding generation."""
import shutil,os
from pathlib import Path
from media import probe,run,file_hash,audio_hash,Cancelled

def prepare(store,rev,folder,options,cancel,progress):
 t=rev['timeline'];tracks={x['kind']:x['clips'] for x in t['tracks']};video=tracks.get('video',[]);voice=tracks.get('voice',[])
 if len(video)!=1 or len(voice)!=1 or any(tracks.get(k) for k in ['text','graphics','music','effects']):raise ValueError('مراجعة المرجع كما هو تتطلب ملفًا مسطحًا دون طبقات تعديل')
 for c in video+voice:
  if c['start_frame']!=0 or c['end_frame']!=t['duration_frames'] or c.get('source_in_frame',0)!=0 or c['source_out_frame']!=t['duration_frames']:raise ValueError('حدود المرجع ليست الملف الكامل')
  if c.get('properties',{}).get('volume',1)!=1 or c.get('properties',{}).get('transition'):raise ValueError('يوجد تعديل في المرجع')
 if video[0]['asset_id']!=voice[0]['asset_id']:raise ValueError('الصوت والصورة ليسا من نفس المرجع المسطح')
 asset=store.asset(video[0]['asset_id']);info=probe(asset['path']);stream=next(x for x in info['streams'] if x['codec_type']=='video')
 if int(stream.get('nb_frames',-1))!=t['duration_frames'] or abs(float(stream['duration'])-t['duration_frames']/t['fps'])>.06:raise ValueError('مدة المرجع لا تطابق التايملاين')
 folder=Path(folder);temporary=folder/'reference.tmp.mp4';target=folder/'review.mp4'
 with open(asset['path'],'rb') as source,temporary.open('wb') as out:
  while True:
   if cancel():raise Cancelled()
   block=source.read(1024*1024)
   if not block:break
   out.write(block)
 if file_hash(temporary)!=asset['hash']:raise ValueError('المرجع تغير أثناء النسخ')
 run(['-i',temporary,'-f','null','-'],folder,cancel,progress);os.replace(temporary,target);audio=audio_hash(target)
 return {'file':str(target),'file_sha256':asset['hash'],'duration':t['duration_frames']/t['fps'],'frames':t['duration_frames'],
         'width':stream['width'],'height':stream['height'],'resolution':'unchanged_reference','upscaled':False,
         'audio_hash':audio,'source_audio_hash':audio,'audio_unchanged':True,'voice_joined':False,
         'technical_decode':True,'review_status':'needs_independent_audio_review','is_internal_candidate':True,
         'source_revision':rev['id'],'start_frame':0,'end_frame':t['duration_frames'],'cutting_proof':None,
         'byte_identical_reference':True,'not_a_new_montage':True}

"""Bounded silent visual batches for long edit lists; exact integer frame counts."""
from pathlib import Path
from media import run,probe
from color_grade import filters as color_filters
BATCH_SIZE=16

def batched(store,segments,fps,width,height,folder,cancel,progress):
 folder=Path(folder)/'visual-batches';folder.mkdir(exist_ok=True);parts=[];done=0
 for start in range(0,len(segments),BATCH_SIZE):
  group=segments[start:start+BATCH_SIZE];args=[];filters=[];frames=sum(hi-lo for c,lo,hi in group)
  for i,(c,lo,hi) in enumerate(group):
   asset=store.asset(c['asset_id']);offset=(c.get('source_in_frame',0)+lo-c['start_frame'])/fps
   args+=(['-loop','1'] if asset['kind']=='image' else ['-ss',offset])
   args+=['-t',(hi-lo+2)/fps,'-threads','1','-i',asset['path']]
   grade=color_filters(c.get('properties',{}));filters.append(f'[{i}:v]setpts=PTS-STARTPTS,fps={fps}:eof_action=pass,trim=end_frame={hi-lo},setpts=PTS-STARTPTS,'+(grade+',' if grade else '')+f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,settb=1/{fps},setpts=PTS-STARTPTS[v{i}]')
  labels=''.join(f'[v{i}]' for i in range(len(group)))
  filters.append(labels+f'concat=n={len(group)}:v=1:a=0[joined];[joined]settb=1/{fps},setpts=N[out]')
  out=folder/f'batch-{start//BATCH_SIZE:05d}.mp4'
  args+=['-filter_complex_threads','1','-filter_complex',';'.join(filters),'-map','[out]','-an','-frames:v',frames,
         '-c:v','libx264','-preset','fast','-crf','14','-threads','3',out]
  run(args,folder,cancel,lambda seconds:progress(done/fps+seconds))
  video=next(s for s in probe(out)['streams'] if s['codec_type']=='video')
  if int(video.get('nb_frames',-1))!=frames:raise ValueError('عدد إطارات دفعة الصورة لا يطابق الخطة')
  parts.append(out);done+=frames
 manifest=folder/'concat.txt';manifest.write_text(''.join("file '"+str(p).replace("'","'\\''")+"'\n" for p in parts))
 out=folder/'joined.mp4';run(['-f','concat','-safe','0','-i',manifest,'-c:v','copy','-an',out],folder,cancel)
 return out,{'batches':len(parts),'max_simultaneous_sources':BATCH_SIZE,'intermediate_crf':14,'extra_visual_encode':True}

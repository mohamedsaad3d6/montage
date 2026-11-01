"""Local tools and deterministic frame-based render adapter; no automatic speech deletion."""
import hashlib,json,os,shutil,subprocess,time,zipfile,xml.etree.ElementTree as ET
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
class Cancelled(Exception):pass
def tool(name):
 explicit=os.environ.get('MONTAJ_'+name.upper())
 if explicit:return explicit
 found=shutil.which(name)
 if found:return found
 local=ROOT.parent/'AI agent/monteer_data/tools/bin'/name
 if local.is_file():return str(local)
 raise ValueError('أداة الوسائط غير متاحة محليًا: '+name)
def probe(path):
 r=subprocess.run([tool('ffprobe'),'-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True,timeout=40,check=True);return json.loads(r.stdout)
def file_hash(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def duration(info,kind):
 if kind=='video':
  v=next((s for s in info.get('streams',[]) if s.get('codec_type')=='video'),None)
  if not v:raise ValueError('الملف لا يحتوي على صورة فيديو')
  if v.get('duration') is not None:return float(v['duration'])
 return float(info['format']['duration'])
def audio_hash(path):
 r=subprocess.run([tool('ffmpeg'),'-v','error','-i',str(path),'-map','0:a:0','-c:a','copy','-f','hash','-hash','sha256','-'],capture_output=True,text=True,check=True);return r.stdout.strip()
def run(args,folder,cancel=lambda:False,progress=lambda x:None):
 log=Path(folder)/'process.log';prog=Path(folder)/'progress.txt'
 with log.open('ab') as f:
  p=subprocess.Popen([tool('ffmpeg'),'-hide_banner','-y','-progress',str(prog),*map(str,args)],stdin=subprocess.DEVNULL,stdout=f,stderr=f)
  while p.poll() is None:
   if cancel():
    p.terminate()
    try:p.wait(timeout=4)
    except subprocess.TimeoutExpired:p.kill();p.wait()
    raise Cancelled()
   if prog.exists():
    for line in reversed(prog.read_text(errors='ignore').splitlines()):
     if line.startswith('out_time_us='):
      try:progress(int(line.split('=')[1])/1e6)
      except ValueError:pass
      break
   time.sleep(.1)
  if p.returncode:raise ValueError('تعذر إخراج الوسائط؛ التفاصيل محفوظة في سجل المهمة')
def eastern(s):return str(s).translate(str.maketrans('0123456789','٠١٢٣٤٥٦٧٨٩'))
def read_script(path):
 p=Path(path)
 if p.stat().st_size>20*1024*1024:raise ValueError('ملف السكريبت أكبر من الحد المدعوم')
 if p.suffix.lower()=='.docx':
  with zipfile.ZipFile(p) as z:
   info=z.getinfo('word/document.xml')
   if info.file_size>10*1024*1024:raise ValueError('السكريبت كبير جدًا')
   root=ET.fromstring(z.read(info));return '\n'.join(''.join(x.itertext()) for x in root.findall('.//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p'))
 return p.read_text(encoding='utf-8-sig')
def render(store,rev,folder,options,cancel,progress):
 from render_stages import begin,mark
 begin(folder,rev['id']);mark(folder,'plan','running')
 t=rev['timeline'];fps=t['fps'];store.validate(rev['project'],t)
 if not t['duration_frames']:raise ValueError('الفيديو غير موجود في التايملاين')
 start=int(options.get('start_frame',0));end=int(options.get('end_frame',t['duration_frames']))
 if not 0<=start<end<=t['duration_frames']:raise ValueError('مجال الإخراج غير صالح')
 tracks={x['kind']:x for x in t['tracks']};visual=sorted(tracks.get('video',{}).get('clips',[]),key=lambda x:x['start_frame']);out=Path(folder)/'candidate.tmp.mp4';final=Path(folder)/'review.mp4';segments=[]
 voices=tracks.get('voice',{}).get('clips',[])
 if not voices:raise ValueError('مسار التعليق الصوتي غير موجود')
 mark(folder,'plan','completed');mark(folder,'materials','running')
 from voice import prepare as prepare_voice
 voice,voice_asset,voice_joined=prepare_voice(store,voices,fps,start,end,folder,cancel)
 reference_voice_asset=store.asset(voices[0]['asset_id'])
 # Gap-free image sequence; exact approved frame windows, no inferred retake cuts.
 cursor=start
 for c in visual:
  lo=max(start,c['start_frame']);hi=min(end,c['end_frame'])
  if hi<=lo:continue
  if lo!=cursor:raise ValueError('فجوة في مسار الصورة؛ لم يُنتج ملف ناقص')
  segments.append((c,lo,hi));cursor=hi
 if cursor!=end:raise ValueError('مسار الصورة لا يغطي المدة كاملة')
 primary=t.get('primary_video_asset_id')
 if not primary and reference_voice_asset['kind']=='video':primary=voices[0]['asset_id']
 primary=primary or segments[0][0]['asset_id'];source_probe=probe(store.asset(primary)['path']);source_stream=next(x for x in source_probe['streams'] if x['codec_type']=='video');presets={'source':(source_stream['width'],source_stream['height']),'720':(1280,720),'1080':(1920,1080),'2160':(3840,2160)};resolution=options.get('resolution','720' if options.get('purpose')=='preview' else 'source')
 if resolution not in presets:raise ValueError('إعداد دقة غير مدعوم')
 width,height=presets[resolution];width=width//2*2;height=height//2*2
 if width>3840 or height>3840:raise ValueError('دقة المصدر أكبر من الحد المدعوم حاليًا')
 args=[];filters=[];labels=[]
 visual_batching=None;visual_inputs=len(segments)
 if len(segments)>24:
  from visual import batched
  base,visual_batching=batched(store,segments,fps,width,height,folder,cancel,progress)
  args=['-i',base];filters=['[0:v]setpts=PTS-STARTPTS[base]'];v='base';visual_inputs=1
 else:
  from color_grade import filters as color_filters
  for i,(c,lo,hi) in enumerate(segments):
   a=store.asset(c['asset_id']);si=(c['source_in_frame']+lo-c['start_frame'])/fps;duration=(hi-lo)/fps
   args+=(['-loop','1'] if a['kind']=='image' else ['-ss',si])+['-t',duration+2/fps,'-threads','1','-i',a['path']];grade=color_filters(c.get('properties',{}));filters.append(f'[{i}:v]setpts=PTS-STARTPTS,fps={fps}:eof_action=pass,trim=end_frame={hi-lo},setpts=PTS-STARTPTS,'+(grade+',' if grade else '')+f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,settb=1/{fps},setpts=PTS-STARTPTS[v{i}]');labels.append(f'[v{i}]')
  if len(labels)>1:filters.append(''.join(labels)+f'concat=n={len(labels)}:v=1:a=0[joined];[joined]settb=1/{fps},setpts=N[base]');v='base'
  else:v='v0'
 mark(folder,'materials','completed');mark(folder,'transitions','running')
 transition_count=0;used_transitions=[]
 for i,(clip,lo,hi) in enumerate(segments):
  tr=clip.get('properties',{}).get('transition')
  if not tr or i==0 or lo!=clip['start_frame']:continue
  from transitions import build
  transition_folder=Path(folder)/f'transition-{i}';transition_folder.mkdir(exist_ok=True)
  path,n,recipe=build(store,segments[i-1][0],clip,lo,fps,width,height,transition_folder,tr,cancel)
  index=visual_inputs+transition_count;args+=['-i',path];offset=(lo-start)/fps;filters.append(f'[{index}:v]setpts=PTS-STARTPTS+{offset}/TB[tr{i}]');next_label=f'transition{i}';filters.append(f'[{v}][tr{i}]overlay=eof_action=pass:repeatlast=0[{next_label}]');v=next_label;transition_count+=1;used_transitions.append(recipe)
 mark(folder,'transitions','completed' if transition_count else 'not_required');mark(folder,'graphics','running')
 font=ROOT/'experiments/saudi-semantic-repair-03/public/Cairo.ttf'
 if not font.is_file():raise ValueError('خط العناوين العربي غير متاح محليًا')
 from layers import add as add_layers
 v,graphic_inputs=add_layers(store,args,filters,v,tracks.get('graphics',{}).get('clips',[]),start,end,fps,width,height,visual_inputs+transition_count)
 from cards import add as add_cards
 v,card_inputs=add_cards(args,filters,v,tracks.get('text',{}).get('clips',[]),start,end,fps,width,height,folder,font,visual_inputs+transition_count+graphic_inputs,cancel)
 mark(folder,'graphics','completed' if graphic_inputs or card_inputs else 'not_required');mark(folder,'mix','running')
 va=voice_asset;vsi=voice['source_in_frame']+start-voice['start_frame'];duration=(end-start)/fps
 if vsi<0 or end>voice['end_frame']:raise ValueError('الصوت لا يغطي مجال الإخراج')
 ai=visual_inputs+transition_count+graphic_inputs+card_inputs;args+=['-ss',vsi/fps,'-t',duration,'-i',va['path']];vol=voice.get('properties',{}).get('volume',1)
 from audio_mix import active as active_audio,add as add_audio
 extras=active_audio(tracks,start,end);mixed_placements=[]
 copy_audio=(not voice_joined and start==0 and end==t['duration_frames'] and voice['source_in_frame']==0 and vol==1 and not extras)
 if copy_audio:amap=f'{ai}:a:0';audioargs=['-c:a','copy']
 else:
  filters.append(f'[{ai}:a]atrim=duration={duration},asetpts=PTS-STARTPTS,volume={vol}[voice]');amap='[voice]';audioargs=['-c:a','aac','-b:a','192k']
  if extras:amap,mixed_placements=add_audio(store,args,filters,'voice',extras,start,end,fps,ai+1)
 args+=['-filter_complex_threads','1','-filter_complex',';'.join(filters),'-map',f'[{v}]','-map',amap,'-frames:v',end-start,'-t',duration,'-c:v','libx264','-preset','fast','-crf','22' if options.get('purpose')=='preview' else '17','-threads','3',*audioargs,'-movflags','+faststart',out]
 mark(folder,'mix','completed');mark(folder,'encode','running')
 run(args,folder,cancel,progress);mark(folder,'encode','completed');mark(folder,'technical','running');meta=probe(out);vs=next(x for x in meta['streams'] if x['codec_type']=='video')
 if int(vs.get('nb_frames',-1))!=end-start:raise ValueError('عدد إطارات الإخراج لا يطابق الخطة')
 # Full decode required independently of encoder exit status.
 run(['-i',out,'-f','null','-'],folder,cancel,lambda _:None);os.replace(out,final);h=audio_hash(final);source_h=audio_hash(reference_voice_asset['path'])
 mark(folder,'technical','completed')
 return {'file':str(final),'file_sha256':file_hash(final),'transitions':used_transitions,'animated_cards':card_inputs,'graphic_layers':graphic_inputs,'audio_mix':{'placements':mixed_placements,'music_ducking':any(x['track']=='music' for x in mixed_placements),'narration_timing_unchanged':True},'duration':duration,'frames':end-start,'width':width,'height':height,'resolution':resolution,'upscaled':width>source_stream['width'] or height>source_stream['height'],'audio_hash':h,'audio_unchanged':h==source_h,'voice_joined':voice_joined,'visual_batching':visual_batching,'source_audio_hash':source_h,'technical_decode':True,'review_status':'needs_independent_audio_review','is_internal_candidate':True,'source_revision':rev['id'],'cutting_proof':t.get('cutting_proof'),'start_frame':start,'end_frame':end}

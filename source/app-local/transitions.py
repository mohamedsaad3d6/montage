"""Actual library renderer on moving source frames, not renamed FFmpeg approximations."""
import json,os,shutil,signal,subprocess,time
from pathlib import Path
from media import ROOT,run,Cancelled,probe

def catalog():return json.loads((ROOT/'library/our-transitions-01/catalog.json').read_text())
def recipe(transition,fps,width,height):
 cat=catalog();r=next((dict(x) for x in cat['recipes'] if x['id']==transition.get('recipe_id')),None)
 if not r:raise ValueError('الانتقال غير موجود في مكتبتنا')
 for k,lo,hi in [('duration_frames',4,48),('strength',.05,1.5)]:
  if k in transition:
   v=transition[k]
   if type(v) not in [int,float] or not lo<=v<=hi:raise ValueError('إعداد انتقال خارج النطاق')
   r[k]=v
 if type(r['duration_frames'])!=int:raise ValueError('مدة الانتقال تحتاج عدد إطارات صحيحًا')
 if transition.get('direction'):
  if transition['direction'] not in ['left','right','up','down']:raise ValueError('اتجاه انتقال غير صحيح')
  r['direction']=transition['direction']
 r.update(fps=fps,width=width,height=height);return r

def build(store,previous,current,boundary,fps,width,height,folder,transition,cancel):
 r=recipe(transition,fps,width,height);n=r['duration_frames'];folder=Path(folder);frames=folder/'frames'
 for name in ['a','b']:(frames/name).mkdir(parents=True,exist_ok=True)
 for name,clip,is_out in [('a',previous,True),('b',current,False)]:
  a=store.asset(clip['asset_id']);source=clip['source_in_frame']+(boundary-clip['start_frame'] if is_out else 0)
  if a['kind']=='video' and source+n>a['duration']*fps+1:raise ValueError('اللقطة لا تحتوي مقابض كافية لهذا الانتقال؛ اختَر مادة أطول أو انتقالًا أقصر')
  from color_grade import filters as color_filters
  grade=color_filters(clip.get('properties',{}))
  args=(['-loop','1'] if a['kind']=='image' else ['-ss',source/fps])+['-i',a['path'],'-vf',f'setpts=PTS-STARTPTS,fps={fps},'+(grade+',' if grade else '')+f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2','-frames:v',n,'-q:v','2',frames/name/'%04d.jpg']
  run(args,folder,cancel)
  if len(list((frames/name).glob('*.jpg')))!=n:raise ValueError('لم تستخرج كل إطارات الانتقال')
 (folder/'recipe.json').write_text(json.dumps(r));node=os.environ.get('MONTAJ_NODE') or shutil.which('node')
 if not node:raise ValueError('محرك الانتقالات المحلي غير متاح')
 with (folder/'render.log').open('wb') as log:
  p=subprocess.Popen([node,str(ROOT/'app-local/transition/render.mjs'),str(folder)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
  from process_guard import wait
  wait(p,cancel,timeout_seconds=300)
  if p.returncode:raise ValueError('تعذر إخراج الانتقال؛ لم يُستبدل بانتقال آخر خفيًا')
 out=folder/'transition.mp4';v=next(x for x in probe(out)['streams'] if x['codec_type']=='video')
 if int(v['nb_frames'])!=n:raise ValueError('عدد إطارات الانتقال غير مطابق')
 return out,n,r

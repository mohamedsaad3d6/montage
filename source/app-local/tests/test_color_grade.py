import sys,unittest,tempfile,subprocess,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from color_grade import filters,normalized
from core import Store
from media import render,tool,probe,audio_hash
class Color(unittest.TestCase):
 def test_limits_and_presets(self):
  self.assertIn('colorbalance=',filters({'color':{'preset':'warm'}}));self.assertEqual(normalized({'preset':'warm'})['temperature'],.1)
  for value in [{'brightness':float('nan')},{'gamma':0},{'shadows':{'r':2}},{'preset':'unknown'}]:
   with self.assertRaises(ValueError):normalized(value)
  self.assertEqual(filters({}),'')
 def test_color_reaches_render_and_batch_path_preserves_audio(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);source=root/'gray.mp4';subprocess.run([tool('ffmpeg'),'-v','error','-y','-f','lavfi','-i','color=c=gray:s=160x90:r=24:d=2','-f','lavfi','-i','sine=frequency=440:duration=2','-c:v','libx264','-threads','1','-c:a','aac','-shortest',str(source)],check=True)
   s=Store(root/'data',[root]);p=s.create('color');a=s.add_asset(p['id'],str(source),2,'video');t=copy.deepcopy(p['revision']['timeline']);t['duration_frames']=48;t['primary_video_asset_id']=a
   for key in ['video','voice']:
    next(tr for tr in t['tracks'] if tr['kind']==key)['clips']=[{'id':key,'asset_id':a,'start_frame':0,'end_frame':48,'source_in_frame':0,'source_out_frame':48,'properties':{}}]
   t['tracks'][0]['clips'][0]['properties']['color']={'saturation':0,'brightness':.15}
   p=s.save(p['id'],p['active'],t);folder=root/'single';folder.mkdir();single=render(s,p['revision'],folder,{'resolution':'source'},lambda:False,lambda _:None)
   def pixel(path):return subprocess.check_output([tool('ffmpeg'),'-v','error','-i',str(path),'-frames:v','1','-vf','scale=1:1','-pix_fmt','rgb24','-f','rawvideo','-'])
   self.assertGreater(sum(pixel(single['file'])),sum(pixel(source))+30);self.assertEqual(single['audio_hash'],audio_hash(source))
   t=copy.deepcopy(p['revision']['timeline']);template=t['tracks'][0]['clips'][0];clips=[];cursor=0
   for i in range(25):
    n=1 if i<24 else 24;c=copy.deepcopy(template);c.update(id='clip'+str(i),start_frame=cursor,end_frame=cursor+n,source_in_frame=cursor,source_out_frame=cursor+n);clips.append(c);cursor+=n
   t['tracks'][0]['clips']=clips;p=s.save(p['id'],p['active'],t);folder=root/'batch';folder.mkdir();batch=render(s,p['revision'],folder,{'resolution':'source'},lambda:False,lambda _:None)
   self.assertEqual(batch['frames'],48);self.assertEqual(batch['visual_batching']['batches'],2);self.assertEqual(batch['audio_hash'],audio_hash(source));self.assertGreater(sum(pixel(batch['file'])),sum(pixel(source))+30)

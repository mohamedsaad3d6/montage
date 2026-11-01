import sys,unittest,tempfile,subprocess,copy,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from audio_mix import active,add
from core import Store,Invalid
from media import render,tool,probe
class AudioMix(unittest.TestCase):
 def test_outside_window_does_not_force_music_or_reencode(self):
  self.assertEqual(active({'music':{'clips':[{'start_frame':50,'end_frame':100}]}},0,24),[])
 def test_music_and_effects_render_together_on_real_media(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);raw=root/'raw.mp4';bed=root/'bed.wav';fx=root/'fx.wav'
   subprocess.run([tool('ffmpeg'),'-v','error','-y','-f','lavfi','-i','color=c=navy:s=320x180:r=24','-f','lavfi','-i','sine=frequency=420:sample_rate=48000','-t','2','-c:v','libx264','-preset','ultrafast','-c:a','aac',raw],check=True)
   for path,tone in [(bed,110),(fx,1500)]:subprocess.run([tool('ffmpeg'),'-v','error','-y','-f','lavfi','-i',f'sine=frequency={tone}:sample_rate=48000','-t','2',path],check=True)
   s=Store(root/'data',[root]);p=s.create('mix integration');video=s.add_asset(p['id'],str(raw),2,'video');music=s.add_asset(p['id'],str(bed),2,'audio');effect=s.add_asset(p['id'],str(fx),2,'audio');t=p['revision']['timeline'];t['duration_frames']=48
   for tr in t['tracks']:
    if tr['kind']in ('video','voice'):tr['clips']=[{'id':tr['kind'],'asset_id':video,'start_frame':0,'end_frame':48,'source_in_frame':0,'source_out_frame':48}]
    if tr['kind']=='music':tr['clips']=[{'id':'m1','asset_id':music,'start_frame':0,'end_frame':24,'source_in_frame':0,'source_out_frame':24},{'id':'m2','asset_id':music,'start_frame':24,'end_frame':48,'source_in_frame':24,'source_out_frame':48}]
    if tr['kind']=='effects':tr['clips']=[{'id':'sfx','asset_id':effect,'start_frame':12,'end_frame':24,'source_in_frame':0,'source_out_frame':12}]
   p=s.save(p['id'],p['active'],t);folder=root/'render';folder.mkdir();r=render(s,p['revision'],folder,{},lambda:False,lambda _:None)
   self.assertTrue(r['technical_decode']);self.assertEqual(r['frames'],48);self.assertEqual(len(r['audio_mix']['placements']),3);self.assertTrue(r['audio_mix']['music_ducking']);self.assertFalse(r['audio_unchanged']);self.assertEqual(r['review_status'],'needs_independent_audio_review')
   data=subprocess.check_output([tool('ffmpeg'),'-v','error','-i',r['file'],'-vn','-ar','48000','-ac','1','-f','f32le','-'])
   import numpy as np
   samples=np.frombuffer(data,dtype='<f4')
   def strength(a,b,hz):
    x=samples[int(a*48000):int(b*48000)];freq=np.fft.rfftfreq(len(x),1/48000);fft=abs(np.fft.rfft(x*np.hanning(len(x))));return float(fft[abs(freq-hz)<8].max())
   self.assertGreater(strength(.60,.85,1500),strength(1.4,1.65,1500)*5)
   self.assertGreater(strength(1.4,1.65,110),.1)
   self.assertGreater(strength(1.4,1.65,420),strength(1.4,1.65,110))
if __name__=='__main__':unittest.main()

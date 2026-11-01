import sys,tempfile,unittest,wave,subprocess,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid
from input_prepare import match,prepare
from intake import save
from workflow import begin,tick,pause,get
from worker import execute
from media import tool
import numpy as np
class PrepareInputs(unittest.TestCase):
 def test_known_shift_and_silence(self):
  rng=np.random.default_rng(4);q=rng.normal(size=900);search=np.r_[rng.normal(size=134),q,rng.normal(size=300)];lag,score,margin=match(q,search);self.assertAlmostEqual(lag,1.34);self.assertGreater(score,.99);self.assertGreater(margin,.5)
  with self.assertRaises(Invalid):match(np.zeros(200),np.zeros(400))
 def test_real_worker_measures_three_windows_then_workflow_starts_analysis_without_checkbox(self):
  with tempfile.TemporaryDirectory()as temp:
   root=Path(temp);s=Store(root/'data',[root]);p=s.create('isolated automatic input sync');rate=4000;seconds=30;rng=np.random.default_rng(8)
   env=np.repeat(rng.uniform(.03,.8,seconds*100),40);noise=rng.normal(size=seconds*rate);signal=(noise*env*.18).clip(-.9,.9)
   def wav(path,signal):
    with wave.open(str(path),'wb')as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes((signal*32767).astype('<i2').tobytes())
   camera=root/'camera.wav';voice=root/'external.wav';video=root/'raw.mp4';wav(camera,signal);wav(voice,np.r_[np.zeros(4800),signal,np.zeros(4000)])
   subprocess.run([tool('ffmpeg'),'-v','error','-f','lavfi','-i','color=c=black:s=160x90:r=24:d=30','-i',str(camera),'-c:v','libx264','-preset','ultrafast','-c:a','aac','-shortest',str(video)],check=True)
   v=s.add_asset(p['id'],str(video),seconds,'video');a=s.add_asset(p['id'],str(voice),32.2,'audio');save(s,{'project':p['id'],'expected_version':0,'video':v,'voice':a,'voice_mode':'external'})
   first=begin(s,{'project':p['id'],'expected':p['active'],'input_version':1});self.assertIsNone(begin(s,{'project':p['id'],'expected':p['active'],'input_version':1})['new_job']);execute(s,first['new_job']);job=s.project(p['id'])['jobs'][0];self.assertEqual(job['status'],'completed',job['error']);proof=json.loads(job['result']);self.assertEqual(proof['offset_frames'],29);self.assertEqual(len(proof['observations']),3);self.assertFalse(proof['independent_audio_review_passed']);self.assertEqual(s.project(p['id'])['active'],p['active'])
   dispatched=[];tick(s,dispatched.append);updated=s.project(p['id']);self.assertNotEqual(updated['active'],p['active']);clip=next(t for t in updated['revision']['timeline']['tracks']if t['kind']=='voice')['clips'][0];self.assertEqual(clip['source_in_frame'],29);self.assertFalse(updated['revision']['timeline']['intake']['external_sync_user_confirmed']);self.assertEqual(len(dispatched),1);self.assertEqual(updated['jobs'][0]['kind'],'editorial_plan')
   from production import status
   self.assertFalse(status(updated,s)['ready_for_montage']);pause(s,p['id']);self.assertEqual(get(s,p['id'])['state'],'paused')

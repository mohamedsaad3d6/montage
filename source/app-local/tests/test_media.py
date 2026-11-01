import sys,unittest,tempfile,copy,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid,Conflict,fingerprint
from media import render,probe,Cancelled
from plans import propose,apply
FIXTURE=Path(__file__).resolve().parents[1]/'.fixtures/spoken.mp4'
class Render(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=Store(self.root/'data',[FIXTURE.parent]);self.p=self.s.create('اختبار إخراج داخلي');self.a=self.s.add_asset(self.p['id'],str(FIXTURE),6,'video');t=copy.deepcopy(self.p['revision']['timeline']);t['duration_frames']=144
  for k in ['video','voice']:next(x for x in t['tracks'] if x['kind']==k)['clips']=[{'id':k,'asset_id':self.a,'start_frame':0,'end_frame':144,'source_in_frame':0,'source_out_frame':144,'properties':{'volume':1}}]
  t['tracks'][1]['clips']=[{'id':'title','start_frame':0,'end_frame':96,'properties':{'text':'اقتصاد ٢٠٢٦'}}];self.p=self.s.save(self.p['id'],self.p['active'],t)
 def tearDown(self):self.tmp.cleanup()
 def test_render_real_audio_video_and_title(self):
  old=fingerprint(FIXTURE);folder=self.root/'render';folder.mkdir();result=render(self.s,self.p['revision'],folder,{},lambda:False,lambda _:None);self.assertEqual(result['frames'],144);self.assertTrue(result['technical_decode']);self.assertEqual(result['review_status'],'needs_independent_audio_review');self.assertTrue(Path(result['file']).is_file());self.assertEqual(fingerprint(FIXTURE),old)
 def test_plan_approval_stale_and_no_guess(self):
  p=propose(self.s,self.p['id'],'الصوت ٥٠٪');before=self.s.project(self.p['id'])['active'];self.assertEqual(before,p['base']);v=apply(self.s,p['id']);self.assertNotEqual(v['active'],before);voice=next(x for x in v['revision']['timeline']['tracks'] if x['kind']=='voice');self.assertEqual(voice['clips'][0]['properties']['volume'],.5)
  with self.assertRaises(Invalid):apply(self.s,p['id'])
  unknown=propose(self.s,v['id'],'شيل الكلام اللي غلط');self.assertEqual(unknown['status'],'needs_editorial_review');self.assertEqual(unknown['operations'],[])
  p=propose(self.s,v['id'],'الصوت ٧٠٪');self.s.save(v['id'],v['active'],v['revision']['timeline'])
  with self.assertRaises(Conflict):apply(self.s,p['id'])
 def test_rule_approval_and_revoke_preserve_snapshot(self):
  self.s.feedback(self.p['id'],self.p['active'],1000,'cards','الكارت سريع');v=self.s.project(self.p['id']);rule=self.s.propose_rule(v['id'],v['feedback'][0]['id'],'card_min_seconds',4)['rules'][0];self.assertEqual(rule['status'],'proposed');self.s.rule_status(v['id'],rule['id'],'approved');self.assertEqual(self.s.project(v['id'])['active'],v['active']);self.s.rule_status(v['id'],rule['id'],'revoked');self.assertEqual(self.s.project(v['id'])['rules'][0]['status'],'revoked')
 def test_no_render_on_unsupported_track(self):
  t=copy.deepcopy(self.p['revision']['timeline']);t['tracks'][3]['clips']=[{'id':'gfx','start_frame':0,'end_frame':24,'properties':{}}];v=self.s.save(self.p['id'],self.p['active'],t);folder=self.root/'render';folder.mkdir()
  with self.assertRaises(ValueError):render(self.s,v['revision'],folder,{},lambda:False,lambda _:None)

class NativeResolution(unittest.TestCase):
 def test_native_fullhd_and_4k_are_not_downgraded(self):
  import subprocess
  from media import tool
  for width,height in [(1920,1080),(3840,2160)]:
   with self.subTest(resolution=(width,height)),tempfile.TemporaryDirectory() as tmp:
    p=Path(tmp);source=p/'native.mp4';subprocess.run([tool('ffmpeg'),'-v','error','-y','-f','lavfi','-i',f'color=c=blue:s={width}x{height}:r=24','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','0.25','-frames:v','6','-c:v','libx264','-preset','ultrafast','-c:a','aac',str(source)],check=True)
    s=Store(p/'data',[p]);v=s.create('اختبار دقة');a=s.add_asset(v['id'],str(source),.25,'video');t=v['revision']['timeline'];t['duration_frames']=6
    for tr in t['tracks']:
     if tr['kind'] in ['video','voice']:tr['clips']=[{'id':tr['kind'],'asset_id':a,'start_frame':0,'end_frame':6,'source_in_frame':0,'source_out_frame':6,'properties':{}}]
    v=s.save(v['id'],v['active'],t);out=p/'render';out.mkdir();r=render(s,v['revision'],out,{},lambda:False,lambda _:None);self.assertEqual((r['width'],r['height']),(width,height));self.assertFalse(r['upscaled'])
 def test_reviewer_never_sends_without_per_output_consent(self):
  from reviewer import review_output
  with self.assertRaisesRegex(ValueError,'اختيارًا صريحًا'):review_output(None,None,None,{},lambda:False)

if __name__=='__main__':unittest.main(verbosity=2)

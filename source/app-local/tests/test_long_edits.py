import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store
from media import render
FIXTURE=Path(__file__).resolve().parents[1]/'.fixtures/spoken.mp4'
class LongEdits(unittest.TestCase):
 def test_many_picture_cuts_have_bounded_inputs_and_exact_frames(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);s=Store(p/'data',[FIXTURE.parent]);v=s.create('تشخيص قصات كثيرة');a=s.add_asset(v['id'],str(FIXTURE),6,'video');t=v['revision']['timeline'];t['duration_frames']=96
   next(tr for tr in t['tracks'] if tr['kind']=='video')['clips']=[{'id':str(i),'asset_id':a,'start_frame':i*3,'end_frame':i*3+3,'source_in_frame':i*3,'source_out_frame':i*3+3} for i in range(32)]
   next(tr for tr in t['tracks'] if tr['kind']=='voice')['clips']=[{'id':'v','asset_id':a,'start_frame':0,'end_frame':96,'source_in_frame':0,'source_out_frame':96}]
   next(tr for tr in t['tracks'] if tr['kind']=='text')['clips']=[{'id':'title','start_frame':0,'end_frame':96,'properties':{'text':'الاقتصاد ٢٠٢٦'}}]
   v=s.save(v['id'],v['active'],t);folder=p/'render';folder.mkdir();r=render(s,v['revision'],folder,{},lambda:False,lambda _:None)
   self.assertEqual(r['frames'],96);self.assertEqual(r['visual_batching']['batches'],2);self.assertEqual(r['animated_cards'],1);self.assertTrue(r['technical_decode'])
if __name__=='__main__':unittest.main()

import sys,unittest,tempfile,copy,wave,array,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cutplan import plan,apply
from core import Store,Invalid
from media import render
FIXTURE=Path(__file__).resolve().parents[1]/'.fixtures/spoken.mp4'
class CutPlan(unittest.TestCase):
 def test_conflicting_word_timings_never_cut_speech(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'quiet.wav'
   with wave.open(str(p),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(array.array('h',[0]*48000).tobytes())
   analysis={'words':[{'s':0,'e':3}],'retakes':[]}
   self.assertEqual(plan(analysis,[{'s':0,'e':.1}],p,24)['cuts'],[])
   with self.assertRaises(ValueError):plan(analysis,[],p,24)
 def test_apply_remaps_both_tracks_and_protects_approved_reference(self):
  t={'phase':'raw','duration_frames':144,'tracks':[{'id':k,'kind':k,'clips':[{'id':k,'asset_id':'a','start_frame':0,'end_frame':144,'source_in_frame':0,'source_out_frame':144}]} for k in ['video','voice']]}
  cp={'cuts':[{'start_frame':48,'end_frame':72,'kind':'quiet_gap_only','removed_word_ids':[]}]};out=apply(t,cp)
  self.assertEqual(out['duration_frames'],120);self.assertEqual(t['duration_frames'],144)
  for tr in out['tracks']:self.assertEqual([(c['start_frame'],c['end_frame'],c['source_in_frame'],c['source_out_frame']) for c in tr['clips']],[(0,48,0,48),(48,120,72,144)])
  t['phase']='approved'
  with self.assertRaises(ValueError):apply(t,cp)
 def test_real_two_piece_voice_picture_render_and_proof_invalidation(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);s=Store(p/'data',[FIXTURE.parent]);v=s.create('اختبار وصلات');a=s.add_asset(v['id'],str(FIXTURE),6,'video');t=v['revision']['timeline'];t.update(phase='raw',duration_frames=144)
   for tr in t['tracks']:
    if tr['kind'] in ['video','voice']:tr['clips']=[{'id':tr['kind'],'asset_id':a,'start_frame':0,'end_frame':144,'source_in_frame':0,'source_out_frame':144,'properties':{}}]
   out=apply(t,{'cuts':[{'start_frame':48,'end_frame':72,'kind':'quiet_gap_only','removed_word_ids':[]}]})
   # Deliberate diagnostic cut tests plumbing only, not editorial correctness.
   out['cutting_proof']={'test_only':True};v=s.save(v['id'],v['active'],out,trusted_cut_proof=True)
   folder=p/'render';folder.mkdir();r=render(s,v['revision'],folder,{},lambda:False,lambda _:None)
   self.assertEqual(r['frames'],120);self.assertTrue(r['voice_joined']);self.assertEqual(r['review_status'],'needs_independent_audio_review')
   changed=copy.deepcopy(v['revision']['timeline']);voice=next(x for x in changed['tracks'] if x['kind']=='voice');voice['clips'][1]['source_in_frame']=71;voice['clips'][1]['source_out_frame']=143
   v=s.save(v['id'],v['active'],changed);self.assertNotIn('cutting_proof',v['revision']['timeline'])
   changed=copy.deepcopy(v['revision']['timeline']);voice=next(x for x in changed['tracks'] if x['kind']=='voice');voice['clips'][1]['source_in_frame']=0;voice['clips'][1]['source_out_frame']=72
   with self.assertRaises(Invalid):s.save(v['id'],v['active'],changed)
if __name__=='__main__':unittest.main()

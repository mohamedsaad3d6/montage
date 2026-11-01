import sys,tempfile,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid,Conflict
from timeline_ops import apply
class Timeline(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=Store(self.root/'data',[self.root]);self.p=self.s.create('edit');file=self.root/'raw.mp4';file.write_bytes(b'original');self.a=self.s.add_asset(self.p['id'],str(file),10,'video');t=copy.deepcopy(self.p['revision']['timeline']);t['duration_frames']=144;t['primary_video_asset_id']=self.a
  for k in ['video','voice']:
   tr=next(tr for tr in t['tracks'] if tr['kind']==k);tr['clips']=[{'id':k,'asset_id':self.a,'start_frame':0,'end_frame':144,'source_in_frame':0,'source_out_frame':144,'properties':{}}]
  self.p=self.s.save(self.p['id'],self.p['active'],t);self.original=copy.deepcopy(self.p['revision']['timeline']);self.base=self.p['active']
 def tearDown(self):self.tmp.cleanup()
 def action(self,**operation):self.p=apply(self.s,self.p['id'],self.p['active'],operation);return self.p
 def split(self):return self.action(type='split',track='video',clip='video',frame=72)
 def video(self):return next(tr for tr in self.p['revision']['timeline']['tracks'] if tr['kind']=='video')['clips']
 def test_split_preserves_all_frames_and_voice(self):
  self.split();c=self.video();self.assertEqual([(x['source_in_frame'],x['source_out_frame']) for x in c],[(0,72),(72,144)]);self.assertEqual(self.original['tracks'][2],self.s.revision(self.base)['timeline']['tracks'][2]);self.assertEqual(next(t for t in self.original['tracks'] if t['kind']=='voice'),next(t for t in self.p['revision']['timeline']['tracks'] if t['kind']=='voice'))
 def test_no_voice_cut_and_stale_editor(self):
  with self.assertRaises(Invalid):self.action(type='split',track='voice',clip='voice',frame=72)
  self.split()
  with self.assertRaises(Conflict):apply(self.s,self.p['id'],self.base,{'type':'split','track':'video','clip':'video','frame':36})
 def test_slip_and_roll_bounds(self):
  self.split();self.action(type='slip',track='video',clip='video',source_in_frame=24);self.assertEqual(self.video()[0]['source_out_frame'],96);self.action(type='roll',track='video',clip='video',frame=84);self.assertEqual(self.video()[1]['source_in_frame'],84);self.assertEqual(self.video()[0]['end_frame'],84)
  with self.assertRaises(Invalid):self.action(type='slip',track='video',clip='video',source_in_frame=-1)
  with self.assertRaises(Invalid):self.action(type='slip',track='video',clip='video',source_in_frame=220)
 def test_reorder_keeps_duration_and_source_ranges(self):
  self.split();self.action(type='reorder',track='video',clip='video',index=1);self.assertEqual([c['source_in_frame'] for c in self.video()],[72,0]);self.assertEqual([(c['start_frame'],c['end_frame']) for c in self.video()],[(0,72),(72,144)])
 def test_lock_cannot_be_bypassed_by_generic_save(self):
  self.action(type='lock',track='video',locked=True)
  with self.assertRaises(Invalid):self.action(type='split',track='video',clip='video',frame=72)
  t=copy.deepcopy(self.p['revision']['timeline']);t['tracks'][0]['clips'][0]['properties']['volume']=.5
  with self.assertRaises(Invalid):self.s.save(self.p['id'],self.p['active'],t)
  self.action(type='lock',track='video',locked=False);self.split()
 def test_undo_redo_and_wrong_branch(self):
  self.split();child=self.p['active'];self.action(type='undo');self.assertEqual(self.p['active'],self.base);self.action(type='redo',revision=child);self.assertEqual(self.p['active'],child)
  with self.assertRaises(Invalid):self.action(type='redo',revision=self.base)
 def test_overlay_moves_without_touching_episode_clock(self):
  t=copy.deepcopy(self.p['revision']['timeline']);next(x for x in t['tracks'] if x['kind']=='text')['clips']=[{'id':'title','start_frame':0,'end_frame':60,'properties':{'text':'العنوان'}}];self.p=self.s.save(self.p['id'],self.p['active'],t);self.action(type='move_overlay',track='text',clip='title',frame=24);self.assertEqual(self.p['revision']['timeline']['duration_frames'],144)
  with self.assertRaises(Invalid):self.action(type='move_overlay',track='text',clip='title',frame=120)

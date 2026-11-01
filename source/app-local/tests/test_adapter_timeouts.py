"""A hung creative subprocess must exit, not leave an export waiting forever."""
import sys,tempfile,subprocess,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from process_guard import wait as real_wait
class AdapterTimeouts(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.children=[];self.spawn=subprocess.Popen
 def tearDown(self):
  for child in self.children:
   if child.poll()is None:child.kill();child.wait()
  self.tmp.cleanup()
 def hung(self,*args,**kwargs):
  child=self.spawn([sys.executable,'-c','import time; time.sleep(60)'],start_new_session=True);self.children.append(child);return child
 def bounded(self,proc,cancel,timeout_seconds):
  self.assertEqual(timeout_seconds,300);return real_wait(proc,cancel,.05)
 def check(self,call,module):
  with patch(module+'.subprocess.Popen',side_effect=self.hung),patch('process_guard.wait',side_effect=self.bounded):
   with self.assertRaises(TimeoutError):call()
  self.assertEqual(len(self.children),1);self.assertIsNotNone(self.children[0].poll())
 def test_cards_timeout_stops_real_child_and_propagates_failure(self):
  from cards import add
  clips=[{'start_frame':0,'end_frame':24,'properties':{'text':'عنوان'}}]
  self.check(lambda:add([],[],'base',clips,0,24,24,640,360,self.root,self.root/'font.ttf',1,lambda:False),'cards')
 def test_music_timeout_stops_real_child_and_propagates_failure(self):
  from music_adapter import generate
  with patch.dict('os.environ',{'MONTAJ_ML_PYTHON':sys.executable}):self.check(lambda:generate(None,{'timeline':{'duration_frames':144,'fps':24}},self.root,{'seconds':6},lambda:False),'music_adapter')
 def test_transition_timeout_stops_real_child_and_propagates_failure(self):
  from transitions import build
  class Store:
   def asset(self,id):return {'kind':'image','path':'unused'}
  def frames(args,folder,cancel):
   target=Path(args[-1]);target.parent.mkdir(parents=True,exist_ok=True)
   for i in range(4):(target.parent/(str(i)+'.jpg')).write_bytes(b'fixture')
  recipe={'duration_frames':4}
  with patch('transitions.recipe',return_value=recipe),patch('transitions.run',side_effect=frames),patch.dict('os.environ',{'MONTAJ_NODE':'fixture-node'}):
   self.check(lambda:build(Store(),{'asset_id':'a','source_in_frame':0,'start_frame':0},{'asset_id':'b','source_in_frame':0,'start_frame':24},24,24,640,360,self.root,{},lambda:False),'transitions')

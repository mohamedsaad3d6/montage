import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid,Conflict
from workspace import save_channel,assign
from channel_kit import get,save,DEFAULT
import copy
class ChannelKit(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'data',[self.tmp.name]);self.p=self.s.create('isolated');self.c=save_channel(self.s,{'name':'قناة اختبار'});self.data=copy.deepcopy(DEFAULT)
 def tearDown(self):self.tmp.cleanup()
 def put(self,version=0):return save(self.s,{'channel':self.c['id'],'expected_version':version,'data':self.data})
 def test_defaults_and_saved_planning_cannot_mutate_timeline(self):
  self.assertEqual(get(self.s,self.c['id'])['version'],0);active=self.p['active'];self.data['pace']=74
  saved=self.put();self.assertEqual(saved['data']['pace'],74);self.assertFalse(saved['automatic_application']);self.assertEqual(self.s.project(self.p['id'])['active'],active)
  with self.assertRaises(Conflict):self.put()
 def test_assets_require_assigned_channel_and_correct_kind(self):
  f=Path(self.tmp.name)/'logo.png';f.write_bytes(b'fixture');a=self.s.add_asset(self.p['id'],str(f),0,'image');self.data['assets']['logo']=[a]
  with self.assertRaises(Invalid):self.put()
  assign(self.s,self.p['id'],self.c['id']);self.assertEqual(self.put()['files']['logo'][0]['hash'],self.s.asset(a)['hash'])
  self.data['assets']['music']=[a]
  with self.assertRaises(Invalid):self.put(1)
 def test_modified_asset_and_invalid_preferences_are_blocked(self):
  assign(self.s,self.p['id'],self.c['id']);f=Path(self.tmp.name)/'logo.png';f.write_bytes(b'a');a=self.s.add_asset(self.p['id'],str(f),0,'image');f.write_bytes(b'b');self.data['assets']['logo']=[a]
  with self.assertRaises(Invalid):self.put()
  self.data=copy.deepcopy(DEFAULT);self.data['pace']=True
  with self.assertRaises(Invalid):self.put()
  self.data=copy.deepcopy(DEFAULT);self.data['color']='url(https://external)'
  with self.assertRaises(Invalid):self.put()
 def test_unknown_transition_and_duplicate_asset_rejected(self):
  self.data['transition_ids']=['missing']
  with self.assertRaises(Invalid):self.put()
  self.data=copy.deepcopy(DEFAULT);self.data['assets']['logo']=['a','a']
  with self.assertRaises(Invalid):self.put()

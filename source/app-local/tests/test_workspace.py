import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid,Conflict
from workspace import channels,save_channel,assign,assignments
class Workspace(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'data',[self.tmp.name]);self.p=self.s.create('original')
 def tearDown(self):self.tmp.cleanup()
 def test_empty_no_demo_channels(self):self.assertEqual(channels(self.s),[])
 def test_channel_assign_preserves_active_revision(self):
  c=save_channel(self.s,{'name':'قناة أصلية'});assign(self.s,self.p['id'],c['id']);self.assertEqual(assignments(self.s)[self.p['id']],c['id']);self.assertEqual(self.s.project(self.p['id'])['active'],self.p['active'])
 def test_stale_edit_and_unknown_profile_rejected(self):
  c=save_channel(self.s,{'name':'قناة'});save_channel(self.s,{'id':c['id'],'expected_version':1,'name':'جديدة'})
  with self.assertRaises(Conflict):save_channel(self.s,{'id':c['id'],'expected_version':1,'name':'متأخرة'})
  with self.assertRaises(Invalid):save_channel(self.s,{'name':'اختبار','profile':'missing'})
 def test_missing_style_does_not_assign(self):
  c=save_channel(self.s,{'name':'قناة'})
  with self.assertRaises(Invalid):assign(self.s,self.p['id'],c['id'],True)
  self.assertNotIn(self.p['id'],assignments(self.s))

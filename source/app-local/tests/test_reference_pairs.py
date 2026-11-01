import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid
from reference_pairs import save,list_pairs
class Pairs(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=Store(self.root/'data',[self.root]);self.p=self.s.create('test');self.ids=[]
  for i in range(2):
   f=self.root/(str(i)+'.mp4');f.write_bytes(str(i).encode());self.ids.append(self.s.add_asset(self.p['id'],str(f),6,'video'))
 def tearDown(self):self.tmp.cleanup()
 def test_local_pair_is_evidence_not_training_or_timeline_change(self):
  active=self.p['active'];result=save(self.s,{'project':self.p['id'],'before_asset':self.ids[0],'after_asset':self.ids[1],'notes':'اختبار'});self.assertFalse(result['model_trained']);self.assertEqual(self.s.project(self.p['id'])['active'],active);self.assertEqual(list_pairs(self.s,self.p['id'])[0]['before_hash'],self.s.asset(self.ids[0])['hash'])
 def test_same_file_malformed_remote_and_changed_source_blocked(self):
  data={'project':self.p['id'],'before_asset':self.ids[0],'after_asset':self.ids[0],'notes':'اختبار'}
  with self.assertRaises(Invalid):save(self.s,data)
  data['after_asset']='';data['after_url']='javascript:bad'
  with self.assertRaises(Invalid):save(self.s,data)
  data['after_url']='https://youtu.be/kXh4wrp_vic';r=save(self.s,data);self.assertFalse(r['remote_video_verified']);self.assertEqual(list_pairs(self.s,self.p['id'])[0]['after_url'],'https://www.youtube.com/watch?v=kXh4wrp_vic')
  Path(self.s.asset(self.ids[0])['path']).write_bytes(b'changed')
  with self.assertRaises(Invalid):save(self.s,data)

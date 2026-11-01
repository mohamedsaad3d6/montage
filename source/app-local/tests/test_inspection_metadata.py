import sys,tempfile,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,uid,dump
from media import file_hash
from inspection import describe
class Metadata(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=Store(self.root/'data',[self.root]);self.p=self.s.create('material');self.raw=self.root/'source.mp4';self.raw.write_bytes(b'fixture');self.asset=self.s.add_asset(self.p['id'],str(self.raw),6,'video');self.frame=self.root/'frame.jpg';self.frame.write_bytes(b'frame-fixture');self.job=uid();result={'asset_id':self.asset,'asset_sha256':file_hash(self.raw),'frames':[{'file':str(self.frame),'sha256':file_hash(self.frame)}]}
  with self.s.connect() as c:c.execute('INSERT INTO jobs(id,project,revision,kind,status,result,created) VALUES(?,?,?,?,?,?,?)',(self.job,self.p['id'],self.p['active'],'inspect_asset','completed',dump(result),1))
  self.metadata={'subjects':['saudi'],'visual_type':'place','visual_verified':True,'rights_verified':True}
 def tearDown(self):self.tmp.cleanup()
 def test_invalid_period_never_persists(self):
  with self.assertRaises(ValueError):describe(self.s,self.p['id'],self.job,{**self.metadata,'year_start':2026,'year_end':2020})
  self.assertEqual(json.loads(self.s.asset(self.asset)['metadata']),{})
 def test_changed_frame_never_certified(self):
  self.frame.write_bytes(b'changed')
  with self.assertRaises(ValueError):describe(self.s,self.p['id'],self.job,self.metadata)
 def test_required_credit_not_silently_removed(self):
  with self.assertRaises(ValueError):describe(self.s,self.p['id'],self.job,{**self.metadata,'credit_required':True})

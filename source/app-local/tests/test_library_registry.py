import sys,tempfile,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid
from library_registry import catalogue,reuse
class Library(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=Store(self.root/'data',[self.root]);self.p=self.s.create('source');self.target=self.s.create('target');self.path=self.root/'clip.mp4';self.path.write_bytes(b'original');self.a=self.s.add_asset(self.p['id'],str(self.path),6,'video')
  with self.s.connect() as c:c.execute('UPDATE assets SET metadata=? WHERE id=?',(json.dumps({'rights_verified':True,'subjects':['oil']}),self.a))
 def tearDown(self):self.tmp.cleanup()
 def test_explicit_reuse_does_not_change_sources_timeline_or_transfer_rights(self):
  result=reuse(self.s,self.target['id'],self.a);new=self.s.asset(result['asset_id']);self.assertEqual(self.path.read_bytes(),b'original');self.assertFalse(json.loads(new['metadata'])['rights_verified']);self.assertEqual(self.s.project(self.target['id'])['active'],self.target['active']);self.assertEqual(reuse(self.s,self.target['id'],self.a)['asset_id'],new['id'])
 def test_changed_source_and_review_evidence_rejected(self):
  self.path.write_bytes(b'changed')
  with self.assertRaises(Invalid):reuse(self.s,self.target['id'],self.a)
 def test_catalogue_has_no_file_paths_or_review_evidence(self):
  self.assertNotIn('path',catalogue(self.s)['items'][0]);self.assertEqual(catalogue(self.s,query='clip')['total'],1)
  with self.s.connect() as c:c.execute("UPDATE assets SET source_type='review_evidence' WHERE id=?",(self.a,))
  self.assertEqual(catalogue(self.s)['total'],0)
 def test_exclusion_changes_suggestions_without_touching_timeline(self):
  from library_registry import exclude
  from selection import shortlist
  active=self.s.project(self.p['id'])['active'];before=self.path.read_bytes();exclude(self.s,self.p['id'],self.a,True);a=self.s.asset(self.a);self.assertTrue(json.loads(a['metadata'])['excluded_from_suggestions']);self.assertEqual(shortlist('النفط',[a])['rejected'][0]['reason'],'excluded_by_editor');self.assertEqual(self.s.project(self.p['id'])['active'],active);self.assertEqual(self.path.read_bytes(),before)
  exclude(self.s,self.p['id'],self.a,False);self.assertFalse(json.loads(self.s.asset(self.a)['metadata'])['excluded_from_suggestions'])
  with self.assertRaises(Invalid):exclude(self.s,self.target['id'],self.a,True)

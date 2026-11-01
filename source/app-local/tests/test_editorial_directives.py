import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid,Conflict
from editorial_directives import save,list_directives,set_status
class Directives(unittest.TestCase):
 def test_versioned_human_directive_never_claims_automatic_enforcement(self):
  with tempfile.TemporaryDirectory() as tmp:
   s=Store(Path(tmp)/'data',[tmp]);p=s.create('test');rows=save(s,{'project':p['id'],'category':'visual','text':'توجيه تشخيص','reason':'اختبار'});r=rows[0];self.assertEqual(r['status'],'proposed');self.assertFalse(r['automatic_enforcement']);params={'project':p['id'],'id':r['id'],'expected_version':1,'status':'approved'};self.assertEqual(set_status(s,params)[0]['status'],'approved')
   with self.assertRaises(Conflict):set_status(s,params)
   with self.assertRaises(Invalid):save(s,{'project':p['id'],'category':'unknown','text':'x'})
   self.assertEqual(s.project(p['id'])['active'],p['active'])

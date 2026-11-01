import sys,unittest,tempfile,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid,Conflict
from script_plan import get,save,approve,scaffold,DEFAULT
from script_workspace import save as save_draft
class ScriptPlan(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'data',[self.tmp.name]);self.p=self.s.create('test');self.id=self.p['id'];self.data={'topic':'اختبار من مصدر معلن','sources':[{'id':'s1','title':'مصدر تشخيص','url':'https://example.org/test','date':'2026-10-29','kind':'other','language':'ar'}],'facts':[{'id':'f1','claim':'عبارة اختبار فقط','source_id':'s1','quote':'عبارة اختبار فقط','verified':True}],'outline':[{'id':'o1','title':'افتتاح تشخيص','summary':'هيكل اختباري','material':'card','start':0,'end':20,'fact_ids':['f1']}]}
 def tearDown(self):self.tmp.cleanup()
 def put(self,version=0):return save(self.s,{'project':self.id,'expected_version':version,'data':self.data})
 def approve(self,p):return approve(self.s,{'project':self.id,'expected_version':p['version'],'content_hash':p['content_hash'],'confirm_manual_review':True})
 def test_no_scaffold_until_manual_approval_and_any_edit_invalidates(self):
  p=self.put()
  with self.assertRaises(Invalid):scaffold(self.s,self.id)
  self.approve(p);result=scaffold(self.s,self.id);self.assertFalse(result['generated_by_model']);self.assertIn('عبارة اختبار فقط',result['text']);self.assertEqual(self.s.project(self.id)['active'],self.p['active'])
  self.data['outline'][0]['title']='تغيير';new=self.put(1);self.assertFalse(new['outline_approved'])
  with self.assertRaises(Invalid):scaffold(self.s,self.id)
 def test_missing_evidence_and_unverified_fact_block_approval(self):
  self.data['facts'][0]['verified']=False;p=self.put()
  with self.assertRaises(Invalid):self.approve(p)
  self.data['facts'][0]['verified']=True;self.data['facts'][0]['quote']=''
  with self.assertRaises(Invalid):self.put(1)
 def test_unknown_source_overlap_and_bad_link_rejected(self):
  self.data['facts'][0]['source_id']='bad'
  with self.assertRaises(Invalid):self.put()
  self.data['facts'][0]['source_id']='s1';self.data['sources'][0]['url']='javascript:alert(1)'
  with self.assertRaises(Invalid):self.put()
  self.data['sources'][0]['url']='https://example.org';second=copy.deepcopy(self.data['outline'][0]);second['id']='o2';self.data['outline'].append(second)
  with self.assertRaises(Invalid):self.put()
 def test_stale_version_and_changed_hash_block_approval(self):
  p=self.put();self.put(1)
  with self.assertRaises(Conflict):self.approve(p)
  with self.assertRaises(Conflict):self.put()
 def test_scaffold_draft_keeps_plan_hash_and_refuses_changed_plan(self):
  p=self.put();self.approve(p);result=scaffold(self.s,self.id)
  items=save_draft(self.s,{'project':self.id,'expected_version':0,**result});self.assertEqual(items[0]['plan_hash'],p['content_hash'])
  self.data['topic']='موضوع جديد';self.put(1)
  with self.assertRaises(Invalid):save_draft(self.s,{'project':self.id,'expected_version':1,**result})
 def test_source_change_clears_manual_fact_verification(self):
  p=self.put();self.approve(p);self.data['sources'][0]['date']='2026-10-28';new=self.put(1);self.assertFalse(new['data']['facts'][0]['verified']);self.assertFalse(new['outline_approved'])
  with self.assertRaises(Invalid):self.approve(new)

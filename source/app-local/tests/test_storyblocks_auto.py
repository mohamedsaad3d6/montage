import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid,Conflict
import storyblocks_auto as auto

def timeline(start=0,end=100,source=0,asset='v'):
 return {'fps':10,'tracks':[{'kind':'voice','clips':[{'asset_id':asset,'start_frame':start,'end_frame':end,'source_in_frame':source,'source_out_frame':source+end-start}]}]}

class AutomaticSelection(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=Store(self.root/'data',[self.root]);self.p=self.s.create('test')
  self.segments=[{'scene_id':'1','start_ms':1000,'end_ms':3000,'text':'ناقلة نفط في البحر'}]
  self.plan={'scenes':[{'scene_id':'1','query':'oil tanker sea','subject':'tanker','purpose':'شرح نقل النفط'}]}
  self.item={'id':123,'title':'Oil tanker','duration':8}
  self.scenes=[{**self.segments[0],'candidates':[self.item]}]
 def tearDown(self):self.tmp.cleanup()
 def decision(self,item=123,confidence=.9):
  return {'choices':[{'scene_id':'1','item_id':item,'reason':'ناقلات بحرية مناسبة','confidence':confidence}]}
 def test_complete_utterance_is_remapped_after_cut(self):
  result=auto.remap(self.segments,timeline(),timeline(0,70,20))
  self.assertEqual(result,[])
  result=auto.remap([{'text':'whole','start_ms':3000,'end_ms':5000}],timeline(),timeline(0,70,20))
  self.assertEqual((result[0]['start_ms'],result[0]['end_ms']),(1000,3000))
 def test_different_source_speed_and_unreliable_words_rejected(self):
  self.assertFalse(auto.remap(self.segments,timeline(),timeline(asset='other')))
  speed=timeline();speed['tracks'][0]['clips'][0]['source_out_frame']=200
  self.assertFalse(auto.remap(self.segments,timeline(),speed))
  self.assertFalse(auto.remap([{**self.segments[0],'unreliable_asr':True}],timeline(),timeline()))
 def test_plan_requires_known_distinct_scenes(self):
  self.assertEqual(len(auto.validate_plan(self.plan,self.segments)),1)
  for p in ({'scenes':[dict(self.plan['scenes'][0],scene_id='bad')]},{'scenes':self.plan['scenes']*2}):
   with self.assertRaises(Invalid):auto.validate_plan(p,self.segments)
 def test_short_or_low_confidence_or_null_not_selected(self):
  for d,scenes in [(self.decision(confidence=.4),self.scenes),(self.decision(None),self.scenes),(self.decision(),[{**self.scenes[0],'candidates':[dict(self.item,duration=1)]}])]:
   self.assertIsNone(auto.validate_choices(d,scenes)[0]['item'])
  self.assertFalse(auto.validate_choices(self.decision(),self.scenes)[0]['licensed'])
 def test_wrong_candidate_incomplete_and_duplicate_rejected(self):
  for d in (self.decision(999),{'choices':[]},{'choices':self.decision()['choices']*2}):
   with self.assertRaises(Invalid):auto.validate_choices(d,self.scenes)
  scenes=self.scenes+[dict(self.scenes[0],scene_id='2')]
  d={'choices':self.decision()['choices']+[dict(self.decision()['choices'][0],scene_id='2')]}
  with self.assertRaises(Invalid):auto.validate_choices(d,scenes)
 def test_opt_in_is_revision_checked_and_queues_only_once(self):
  with patch.object(auto,'narration',return_value=(self.segments,'transcript')):
   with self.assertRaises(Conflict):auto.configure(self.s,self.p['id'],'old',True)
   a=auto.configure(self.s,self.p['id'],self.p['active'],True)
   b=auto.configure(self.s,self.p['id'],self.p['active'],True)
   self.assertTrue(a['new_job']);self.assertIsNone(b['new_job'])
   other=self.s.enqueue(self.p['id'],'archive_search',{'query':'earth'})
   auto.configure(self.s,self.p['id'],self.p['active'],False)
  jobs={j['id']:j for j in self.s.project(self.p['id'])['jobs']}
  self.assertEqual(jobs[a['new_job']]['status'],'cancelled');self.assertEqual(jobs[other]['status'],'queued')
 def test_current_job_defers_auto_execution(self):
  self.s.enqueue(self.p['id'],'transcribe',{})
  with patch.object(auto,'narration',return_value=(self.segments,'transcript')):
   self.assertIsNone(auto.configure(self.s,self.p['id'],self.p['active'],True)['new_job'])
 def test_worker_research_does_not_download_or_change_revision(self):
  from worker import execute
  job=self.s.enqueue(self.p['id'],auto.KIND,{})
  with patch.object(auto,'narration',return_value=(self.segments,'transcript')),patch.object(auto,'decide',side_effect=[self.plan,self.decision()]),patch('storyblocks_connector.search',return_value={'results':[self.item]}),patch('storyblocks_connector.collect') as collect:
   execute(self.s,job)
  p=self.s.project(self.p['id']);j=next(x for x in p['jobs'] if x['id']==job)
  self.assertEqual(j['status'],'completed',j.get('error'))
  r=json.loads(j['result']);self.assertEqual(r['selected_count'],1);self.assertFalse(r['download_started']);self.assertEqual(p['active'],self.p['active']);collect.assert_not_called()

if __name__=='__main__':unittest.main()

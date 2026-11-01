import sys,json,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_lifecycle as fixture
from workflow import advance,tick,get
class AutomaticMontage(unittest.TestCase):
 def setUp(self):self.f=fixture.Lifecycle();self.f.setUp();self.s=self.f.s;self.p=self.f.p
 def tearDown(self):self.f.tearDown()
 def narration(self):
  j=self.s.enqueue(self.p['id'],'transcribe',{},revision=self.p['active'])
  with self.s.connect()as c:c.execute("UPDATE jobs SET status='completed' WHERE id=?",(j,))
  return j
 def test_audio_stage_hands_sources_and_montage_to_codex_director(self):
  self.narration()
  with patch('production.status',return_value={'next_action':{'kind':'montage'}}):step=advance(self.s,self.p['id'])
  self.assertIsNotNone(step['new_job'])
  with self.s.connect()as c:self.assertEqual(self.s.one(c,'SELECT kind FROM jobs WHERE id=?',(step['new_job'],))['kind'],'codex_plan')
  self.assertEqual(get(self.s,self.p['id'])['state'],'codex_controlled')
  calls=[];tick(self.s,calls.append);self.assertFalse(calls)
 def test_missing_current_narration_is_prepared_before_director_without_changing_cut(self):
  old=self.narration();p=self.s.project(self.p['id']);p=self.s.save(p['id'],p['active'],p['revision']['timeline'],'new cut');self.p=p
  with patch('production.status',return_value={'next_action':{'kind':'montage'}}):
   step=advance(self.s,p['id']);again=advance(self.s,p['id'])
   self.assertIsNone(again['new_job'])
   with self.s.connect()as c:
    j=self.s.one(c,'SELECT * FROM jobs WHERE id=?',(step['new_job'],));self.assertEqual(j['kind'],'transcribe');self.assertEqual(j['revision'],p['active']);self.assertNotEqual(j['id'],old)
    c.execute("UPDATE jobs SET status='completed' WHERE id=?",(j['id'],))
   calls=[];tick(self.s,calls.append)
  self.assertEqual(len(calls),1)
  with self.s.connect()as c:self.assertEqual(self.s.one(c,'SELECT kind FROM jobs WHERE id=?',(calls[0],))['kind'],'codex_plan')
  self.assertEqual(self.s.project(p['id'])['active'],p['active'])
 def test_no_fake_publication_or_repeat_montage_after_final_candidate(self):
  p=self.s.project(self.p['id']);t=p['revision']['timeline'];t['phase']='montage_candidate';self.s.save(p['id'],p['active'],t)
  with patch('production.status',return_value={'next_action':{'kind':'montage'}}):step=advance(self.s,p['id'])
  self.assertIsNone(step['new_job']);self.assertEqual(step['workflow']['state'],'ready_for_montage')
if __name__=='__main__':unittest.main()

import sys,tempfile,unittest,time,threading
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid
from job_activity import record,finish
from worker import execute
class JobActivity(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=Store(self.root/'data',[self.root]);self.p=self.s.create('activity fixture');self.job=self.s.enqueue(self.p['id'])
 def tearDown(self):self.tmp.cleanup()
 def start(self):
  with self.s.connect()as c:c.execute("UPDATE jobs SET status='running' WHERE id=?",(self.job,))
 def job_view(self):return next(j for j in self.s.project(self.p['id'])['jobs']if j['id']==self.job)
 def test_only_running_jobs_record_phases_and_timestamps_remain_immutable(self):
  self.assertFalse(record(self.s,self.job,'source_check'));self.start()
  with patch('job_activity.time.time',return_value=10):self.assertTrue(record(self.s,self.job,'source_check'))
  with patch('job_activity.time.time',return_value=20):self.assertFalse(record(self.s,self.job,'source_check'));self.assertTrue(record(self.s,self.job,'ctc'))
  with patch('job_activity.time.time',return_value=25):view=self.job_view()['activity']
  self.assertEqual([x['elapsed_seconds']for x in view['history']],[10,5]);self.assertEqual(view['current']['label'],'محاذاة الكلمات المصرية المستقلة');self.assertFalse(view['percent_estimated']);self.assertFalse(view['independent_review_granted'])
  with self.s.connect()as c:c.execute("UPDATE jobs SET status='completed' WHERE id=?",(self.job,))
  with patch('job_activity.time.time',return_value=26):finish(self.s,self.job)
  with patch('job_activity.time.time',return_value=999):self.assertEqual(self.job_view()['activity']['current']['elapsed_seconds'],6)
 def test_cancelled_job_never_records_another_stage_or_claims_missing_end_time(self):
  self.start();record(self.s,self.job,'asr')
  with self.s.connect()as c:c.execute("UPDATE jobs SET status='cancelled' WHERE id=?",(self.job,))
  self.assertFalse(record(self.s,self.job,'final_verify'));self.assertIsNone(self.job_view()['activity']['current']['elapsed_seconds']);finish(self.s,self.job);self.assertIsNotNone(self.job_view()['activity']['current']['finished'])
 def test_real_worker_emits_source_and_final_validation_without_creating_review_approval(self):
  execute(self.s,self.job);view=self.job_view();self.assertEqual(view['status'],'completed');self.assertEqual([x['phase']for x in view['activity']['history']],['source_check','final_verify']);self.assertTrue(all(x['finished']is not None for x in view['activity']['history']));self.assertFalse(view['activity']['independent_review_granted'])
 def test_phase_names_cannot_be_user_text_or_secret_paths(self):
  self.start()
  with self.assertRaises(Invalid):record(self.s,self.job,'/some/user/path')
 def test_analysis_failure_preserves_last_phase_for_diagnosis(self):
  p=self.s.project(self.p['id']);j=self.s.enqueue(p['id'],'transcribe');execute(self.s,j);view=next(x for x in self.s.project(p['id'])['jobs']if x['id']==j);self.assertEqual(view['status'],'failed');self.assertEqual(view['activity']['current']['phase'],'voice_prepare');self.assertIsNotNone(view['activity']['current']['finished'])

 def test_live_snapshot_omits_media_paths_results_and_does_not_claim_release(self):
  from job_activity import snapshot
  self.start();record(self.s,self.job,'asr');data=snapshot(self.s,self.p['id']);self.assertEqual(data['jobs'][0]['activity']['current']['phase'],'asr');self.assertNotIn('result',data['jobs'][0]);self.assertNotIn('assets',data);self.assertFalse(data['independent_review_granted']);self.assertFalse(data['publication_approved'])

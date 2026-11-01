import sys,json,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_lifecycle as fixture
from core import dump
from workflow import advance,pause,get,tick
from media import file_hash
class Workflow(unittest.TestCase):
 def setUp(self):self.f=fixture.Lifecycle();self.f.setUp();self.s=self.f.s;self.p=self.f.p
 def tearDown(self):self.f.tearDown()
 def complete(self,job,result):
  with self.s.connect()as c:c.execute("UPDATE jobs SET status='completed',result=? WHERE id=?",(dump(result),job))
 def test_continue_starts_one_stage_and_adopts_it_without_duplicate_jobs(self):
  a=advance(self.s,self.p['id']);b=advance(self.s,self.p['id']);self.assertIsNotNone(a['new_job']);self.assertIsNone(b['new_job']);self.assertEqual(a['workflow']['job'],b['workflow']['job'])
  with self.s.connect()as c:self.assertEqual(c.execute("SELECT count(*) FROM jobs WHERE project=?",(self.p['id'],)).fetchone()[0],1)
 def test_completion_advances_local_stage_and_stops_at_exact_output_consent(self):
  first=advance(self.s,self.p['id'])['new_job'];self.complete(first,{'retake_candidates':0});dispatched=[];tick(self.s,dispatched.append);self.assertEqual(len(dispatched),1);job=dispatched[0]
  with self.s.connect()as c:self.assertEqual(self.s.one(c,'SELECT kind FROM jobs WHERE id=?',(job,))['kind'],'render')
  self.complete(job,{'frames':96,'start_frame':0,'technical_decode':True,'file':str(self.f.file),'file_sha256':file_hash(self.f.file)});tick(self.s,dispatched.append);self.assertEqual(len(dispatched),1);self.assertEqual(get(self.s,self.p['id'])['state'],'needs_input')
  step=advance(self.s,self.p['id'],consent={'output_job':job,'output_sha256':'wrong','google_audio':True});self.assertIsNone(step['new_job'])
  step=advance(self.s,self.p['id'],consent={'output_job':job,'output_sha256':file_hash(self.f.file),'google_audio':True});self.assertIsNotNone(step['new_job'])
  with self.s.connect()as c:options=json.loads(self.s.one(c,'SELECT options FROM jobs WHERE id=?',(step['new_job'],))['options']);self.assertEqual(options['provider'],'studio')
 def test_pause_cancels_only_this_active_workflow_and_resume_restarts_only_its_stage(self):
  j=advance(self.s,self.p['id'])['new_job'];other=self.s.enqueue(self.f.other['id']);result=pause(self.s,self.p['id']);self.assertEqual(result['cancelled_jobs'],[j]);self.assertEqual(result['state'],'paused');sent=[];tick(self.s,sent.append);self.assertFalse(sent)
  with self.s.connect()as c:self.assertEqual(self.s.one(c,'SELECT status FROM jobs WHERE id=?',(other,))['status'],'queued')
  resumed=advance(self.s,self.p['id']);self.assertNotEqual(resumed['new_job'],j);self.assertEqual(self.s.project(self.p['id'])['active'],self.p['active'])
 def test_failed_stage_is_never_retried_automatically(self):
  j=advance(self.s,self.p['id'])['new_job']
  with self.s.connect()as c:c.execute("UPDATE jobs SET status='failed',error='fixture failure' WHERE id=?",(j,))
  sent=[];tick(self.s,sent.append);self.assertFalse(sent);self.assertEqual(get(self.s,self.p['id'])['state'],'failed');self.assertIsNotNone(advance(self.s,self.p['id'])['new_job'])
 def test_changed_revision_blocks_automatic_work_on_an_unapproved_new_version(self):
  j=advance(self.s,self.p['id'])['new_job'];self.complete(j,{'retake_candidates':0});new=self.s.save(self.p['id'],self.p['active'],self.p['revision']['timeline']);sent=[];tick(self.s,sent.append);self.assertFalse(sent);self.assertEqual(get(self.s,self.p['id'])['state'],'needs_input');self.assertEqual(get(self.s,self.p['id'])['revision'],new['active'])
 def test_no_automatic_work_runs_without_explicit_continue(self):
  sent=[];tick(self.s,sent.append);self.assertFalse(sent);self.assertEqual(get(self.s,self.p['id'])['state'],'idle')

class APIReviewWorkflow(unittest.TestCase):
 setUp=Workflow.setUp
 tearDown=Workflow.tearDown
 complete=Workflow.complete
 def test_api_mode_is_dispatched_only_after_exact_file_consent_and_free_gate(self):
  from unittest.mock import patch
  first=advance(self.s,self.p['id'])['new_job'];self.complete(first,{'retake_candidates':0});sent=[];tick(self.s,sent.append);output=sent[0];digest=file_hash(self.f.file);self.complete(output,{'frames':96,'start_frame':0,'technical_decode':True,'file':str(self.f.file),'file_sha256':digest});tick(self.s,sent.append)
  with patch('reviewer.check_free_connection',return_value='private-config')as check:
   refused=advance(self.s,self.p['id'],consent={'google_audio':True,'provider':'api','output_job':output,'output_sha256':'wrong'});self.assertIsNone(refused['new_job']);check.assert_not_called()
   step=advance(self.s,self.p['id'],consent={'google_audio':True,'provider':'api','output_job':output,'output_sha256':digest});check.assert_called_once()
  with self.s.connect()as c:options=json.loads(self.s.one(c,'SELECT options FROM jobs WHERE id=?',(step['new_job'],))['options'])
  self.assertEqual(options['provider'],'api');self.assertTrue(options['consent_google_audio'])

 def test_empty_studio_preparation_does_not_trap_api_review_or_repeat_render(self):
  from unittest.mock import patch
  first=advance(self.s,self.p['id'])['new_job'];self.complete(first,{'retake_candidates':0});sent=[];tick(self.s,sent.append);output=sent[0];digest=file_hash(self.f.file)
  self.complete(output,{'frames':96,'start_frame':0,'technical_decode':True,'file':str(self.f.file),'file_sha256':digest});tick(self.s,sent.append)
  prepared=self.s.enqueue(self.p['id'],'audio_review',{'provider':'studio','output_job':output,'consent_google_audio':True});self.complete(prepared,{'provider':'google_ai_studio_ui','output_job':output,'review_complete':False,'status':'awaiting_studio_results'})
  with patch('reviewer.check_free_connection',return_value='private-config'):
   step=advance(self.s,self.p['id'],consent={'google_audio':True,'provider':'api','output_job':output,'output_sha256':digest})
  self.assertIsNotNone(step['new_job'])
  with self.s.connect()as c:
   row=self.s.one(c,'SELECT kind,options FROM jobs WHERE id=?',(step['new_job'],));self.assertEqual(row['kind'],'audio_review');self.assertEqual(__import__('json').loads(row['options'])['provider'],'api')
   self.assertEqual(c.execute("SELECT count(*) FROM jobs WHERE kind='render'").fetchone()[0],1)

 def test_failed_api_review_is_not_resent_by_repeated_continue(self):
  from workflow import _put
  output=self.s.enqueue(self.p['id'],'render',{});self.complete(output,{'file':str(self.f.file),'file_sha256':file_hash(self.f.file)})
  j=self.s.enqueue(self.p['id'],'audio_review',{'provider':'api','output_job':output,'consent_google_audio':True})
  with self.s.connect()as c:c.execute("UPDATE jobs SET status='failed',error='Gemini HTTP 503' WHERE id=?",(j,))
  _put(self.s,self.p['id'],'failed',self.p['active'],j,'503')
  for _ in range(2):self.assertIsNone(advance(self.s,self.p['id'])['new_job'])
  with self.s.connect()as c:self.assertEqual(c.execute("SELECT count(*) FROM jobs WHERE kind='audio_review'").fetchone()[0],1)

class CreativePause(unittest.TestCase):
 setUp=Workflow.setUp
 tearDown=Workflow.tearDown
 def test_pause_and_resume_creative_job_preserves_its_frozen_options(self):
  job=self.s.enqueue(self.p['id'],'generate_music',{'seconds':12,'seed':6});step=advance(self.s,self.p['id']);self.assertEqual(step['workflow']['job'],job);result=pause(self.s,self.p['id']);self.assertEqual(result['cancelled_jobs'],[job]);resumed=advance(self.s,self.p['id']);self.assertIsNotNone(resumed['new_job'])
  with self.s.connect()as c:j=self.s.one(c,'SELECT kind,options FROM jobs WHERE id=?',(resumed['new_job'],))
  self.assertEqual(j['kind'],'generate_music');self.assertEqual(json.loads(j['options']),{'seconds':12,'seed':6})

class MachineTakeWorkflow(unittest.TestCase):
 def setUp(self):
  import test_take_review
  self.f=test_take_review.TakeReview();self.f.setUp();self.s=self.f.s;self.p=self.f.p
 def tearDown(self):self.f.tearDown()
 def test_local_draft_does_not_request_google_and_refuses_incomplete_word_evidence(self):
  from unittest.mock import patch
  with patch('reviewer.check_free_connection',side_effect=AssertionError('cloud must not be required')):
   step=advance(self.s,self.p['id'])
  self.assertIsNone(step['new_job']);self.assertEqual(step['workflow']['state'],'needs_input');self.assertIn('دليل الكلمات',step['workflow']['reason'])
  self.assertEqual(self.s.project(self.p['id'])['active'],self.p['active'])
 def test_machine_candidate_advances_to_transcribe_without_fake_human_record(self):
  import test_machine_cut
  from workflow import _put
  fixture=test_machine_cut.MachineCut();fixture.setUp()
  try:
   f=fixture.f;_put(f.s,f.p['id'],'running',f.p['active'],fixture.job,'test fixture')
   result=advance(f.s,f.p['id'],automatic=True);self.assertIsNotNone(result['new_job'])
   with f.s.connect()as c:row=f.s.one(c,'select kind from jobs where id=?',(result['new_job'],))
   self.assertEqual(row['kind'],'transcribe');p=f.s.project(f.p['id']);self.assertEqual(p['revision']['timeline']['phase'],'cut_candidate');self.assertTrue(p['revision']['timeline']['requires_new_independent_audio_review'])
  finally:fixture.tearDown()

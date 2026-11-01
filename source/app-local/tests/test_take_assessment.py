import sys,tempfile,wave,unittest,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'engine'))
from core import Store,Invalid,Conflict
from media import file_hash
from take_assessment import assess,validate,groups,safe_failure
class Assessment(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=Store(self.root/'data',[self.root]);self.p=self.store.create('isolated');self.wav=self.root/'source.wav'
  with wave.open(str(self.wav),'wb')as w:w.setparams((1,2,16000,0,'NONE','not compressed'));w.writeframes(b'\0\0'*16000*10)
  self.item={'key':'candidate-one','attempts':[{'start':1,'end':2,'text':'كلام'},{'start':3,'end':4,'text':'كلام كامل'}]}
  self.result={'wave_sha256':file_hash(self.wav),'plan_sha256':'plan'};self.options={'analysis_job':'source-job','audio_sha256':self.result['wave_sha256'],'plan_sha256':'plan','consent_google_audio':True};self.bound=({'id':'source-job','project':self.p['id'],'revision':self.p['active']},self.result,self.wav,10,[self.item])
  self.patches=[patch('take_assessment.bound',return_value=self.bound),patch('reviewer.check_free_connection',return_value='private-path'),patch('monteer.audio_review.pipeline.credentials',return_value='test-key')]
  for p in self.patches:p.start()
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
  self.tmp.cleanup()
 def run_assessment(self,folder,transport):
  folder=self.root/folder;folder.mkdir()
  return assess(self.store,self.p['revision'],folder,self.options,lambda:False,transport)
 def payload(self):return {'comparisons':[{'candidate':'candidate-one','classification':'restart','selected_attempt':0,'kept_complete':True,'pronunciation_clear':True,'reason':'اختيار مبني على الصوت التجريبي','quote':'كلام واضح'}]}
 def test_machine_evidence_reused_without_human_attestation_or_timeline_change(self):
  calls=[]
  def send(*args):calls.append(1);return self.payload()
  first=self.run_assessment('one',send);again=self.run_assessment('two',send)
  self.assertEqual(len(calls),1);self.assertFalse(first['cuts_applied']);self.assertFalse(first['human_listening_attested']);self.assertEqual(again['comparisons'],1);self.assertEqual(self.store.project(self.p['id'])['active'],self.p['active'])
 def test_uncertain_network_result_never_resent_by_new_job(self):
  calls=[]
  def send(*args):calls.append(1);raise TimeoutError()
  with self.assertRaises(Invalid):self.run_assessment('one',send)
  with self.assertRaisesRegex(Invalid,'غير محسوم'):self.run_assessment('two',send)
  self.assertEqual(len(calls),1)
  receipt=json.loads(next((self.store.root/'take-assessment-ledger').glob('*.json')).read_text());self.assertEqual(receipt['failure'],{'kind':'timeout'});self.assertTrue(receipt['stopped_needs_reconciliation'])
 def test_wrong_source_binding_is_rejected_before_network(self):
  self.options['audio_sha256']='changed'
  with self.assertRaises(Conflict):self.run_assessment('one',lambda *args:self.fail('network sent'))
 def test_bad_choice_and_missing_coverage_rejected(self):
  d=self.payload();d['comparisons'][0]['selected_attempt']=2
  with self.assertRaises(Invalid):validate(d,[self.item])
  with self.assertRaises(Invalid):validate({'comparisons':[]},[self.item])
 def test_groups_keep_context_and_never_exceed_budget(self):
  result=groups([self.item],10);self.assertEqual((result[0]['start'],result[0]['end']),(0,10))

 def test_failure_diagnostics_are_allowlisted_and_never_copy_secrets(self):
  self.assertEqual(safe_failure(RuntimeError('Gemini HTTP 503; stopped with no retry or fallback')),{'kind':'http','http_status':503})
  self.assertEqual(safe_failure(RuntimeError('https://secret.example/?key=private')),{'kind':'unknown'})
  self.assertEqual(safe_failure(TimeoutError('private-key')),{'kind':'timeout'})

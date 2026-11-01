import sys,json,unittest,array
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_take_review as fixture
from core import dump,Invalid
from media import file_hash
from take_review import bound
from machine_cut import apply,boundaries
from audit import validate_proof
class MachineCut(unittest.TestCase):
 def setUp(self):
  self.f=fixture.TakeReview();self.f.setUp();f=self.f
  plan=json.loads(f.plan.read_text());plan['retakes'][0]['attempts'][0]['text']='كلام كامل';plan['retakes'][0]['attempts'][1]['text']='كلام كامل';f.plan.write_text(dump(plan));f.result['plan_sha256']=file_hash(f.plan)
  wp=f.plan.parent/'words.json';wp.write_text(dump({'words':[{'w':'كلام كامل','s':.1,'e':.8},{'w':'كلام كامل','s':2.1,'e':2.8}]}));f.result.update(source_words_file=str(wp),source_words_sha256=file_hash(wp))
  with f.s.connect()as c:c.execute('UPDATE jobs SET result=? WHERE id=?',(dump(f.result),f.j))
  item=bound(f.s,f.j)[4][0];self.job=f.s.enqueue(f.p['id'],'take_assess',{});folder=f.s.root/'jobs'/self.job;folder.mkdir(parents=True)
  ledger=f.s.root/'take-assessment-ledger';ledger.mkdir();e=ledger/'test.json';e.write_text('{}')
  self.report=folder/'report.json';self.body={'analysis_job':f.j,'audio_sha256':f.result['wave_sha256'],'plan_sha256':f.result['plan_sha256'],'comparisons':[{'candidate':item['key'],'classification':'restart','selected_attempt':0,'kept_complete':True,'pronunciation_clear':True,'reason':'اختبار تجريبي لتطبيق الحدود','quote':'كلام كامل'}],'evidence':[{'file':str(e),'sha256':file_hash(e)}]};self.persist()
 def persist(self):
  f=self.f;self.report.write_text(dump(self.body));result={'report_file':str(self.report),'report_sha256':file_hash(self.report)}
  with f.s.connect()as c:c.execute("UPDATE jobs SET status='completed',result=? WHERE id=?",(dump(result),self.job))
 def tearDown(self):self.f.tearDown()
 def test_machine_candidate_maps_both_tracks_without_human_or_release_attestation(self):
  f=self.f;out=apply(f.s,f.p['id'],self.job,f.p['active']);t=out['revision']['timeline'];self.assertEqual(t['duration_frames'],72);self.assertEqual(t['phase'],'cut_candidate');self.assertTrue(t['requires_new_independent_audio_review']);validate_proof(f.s,t['cutting_proof']);self.assertFalse(t['cutting_proof']['decisions'][0]['human_listening_attested']);self.assertEqual(f.source.read_bytes(),b'raw fixture')
  with f.s.connect()as c:self.assertEqual(c.execute('select count(*)from control_take_decisions').fetchone()[0],0)if c.execute("select count(*)from sqlite_master where name='control_take_decisions'").fetchone()[0]else None
 def test_uncertain_review_never_applies_partial_edits(self):
  f=self.f;self.body['comparisons'][0].update(classification='uncertain',selected_attempt=None);self.persist()
  with self.assertRaises(Invalid):apply(f.s,f.p['id'],self.job,f.p['active'])
  self.assertEqual(f.s.project(f.p['id'])['active'],f.p['active'])
 def test_unique_words_or_loud_edges_are_rejected(self):
  item={'key':'x','attempts':[{'start':0,'end':1,'text':'كلام كامل'},{'start':2,'end':3,'text':'إضافة مهمة'}]}
  with self.assertRaises(Invalid):boundaries(item,0,[],array.array('h',[0]*64000),16000,24,96)
  item['attempts'][1]['text']='كلام كامل'
  with self.assertRaises(Invalid):boundaries(item,0,[],array.array('h',[15000]*64000),16000,24,96)

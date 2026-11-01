import sys,json,wave,array,unittest,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_take_review as fixture
from take_review import save,describe
from take_repair import preview,apply,audio
from core import Invalid,Conflict,dump
from media import file_hash
from audit import validate_proof
class TakeRepair(unittest.TestCase):
 def setUp(self):
  self.f=fixture.TakeReview();self.f.setUp();f=self.f;plan=json.loads(f.plan.read_text());plan['retakes'][0]['attempts'][0]['text']='نص التجربة كامل';plan['retakes'][0]['attempts'][1]['text']='نص التجربة';f.plan.write_text(dump(plan));f.result['plan_sha256']=file_hash(f.plan)
  with f.s.connect()as c:c.execute('UPDATE jobs SET result=? WHERE id=?',(dump(f.result),f.j))
  d=describe(f.s,f.j);f.payload.update(candidate=d['candidates'][0]['key'],plan_sha256=f.result['plan_sha256']);save(f.s,f.payload);wp=f.s.root/'jobs'/f.j/'words.json';wp.write_text(dump({'words':[{'w':'first','s':.1,'e':.5},{'w':'second','s':2.1,'e':2.5},{'w':'keep-tail','s':3.5,'e':3.8}]}));f.result.update(source_words_file=str(wp),source_words_sha256=file_hash(wp))
  with f.s.connect()as c:c.execute('UPDATE jobs SET result=? WHERE id=?',(dump(f.result),f.j))
  self.request={'project':f.p['id'],'job':f.j,'expected_revision':f.p['active'],'cuts':[{'candidate':f.payload['candidate'],'decision_version':1,'rejected_attempt':1,'start_frame':47,'end_frame':74,'reason':'Synthetic boundary test only; no human editorial approval asserted'}]}
 def tearDown(self):self.f.tearDown()
 def approve(self,result):return {'project':self.f.p['id'],'job':self.f.j,'proposal':result['id'],'expected_revision':self.f.p['active'],'listened_all_joins':True,'kept_meaning_complete':True}
 def test_preview_does_not_cut_and_apply_maps_camera_and_voice_with_auditable_words(self):
  f=self.f;r=preview(f.s,self.request);self.assertEqual(f.s.project(f.p['id'])['active'],f.p['active']);self.assertFalse(r['independent_audio_review_granted']);self.assertTrue(audio(f.s,f.j,r['id'],0).is_file());out=apply(f.s,self.approve(r));t=out['revision']['timeline'];self.assertEqual(t['duration_frames'],69);self.assertEqual(t['phase'],'cut_candidate');self.assertTrue(t['requires_new_independent_audio_review']);self.assertEqual(t['tracks'][0]['clips'][1]['source_in_frame'],74);self.assertEqual(next(tr for tr in t['tracks']if tr['kind']=='voice')['clips'][1]['source_in_frame'],74);validate_proof(f.s,t['cutting_proof']);self.assertEqual(t['cutting_proof']['decisions'][0]['word_ids'],[1]);self.assertEqual(f.source.read_bytes(),b'raw fixture')
  sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'engine'))
  from monteer.audio_review.word_audit import inspect
  plan=json.loads(Path(t['cutting_proof']['plan_file']).read_text());words=json.loads(Path(t['cutting_proof']['source_words_file']).read_text())['words'];self.assertFalse(inspect(plan,words,[])['passed']);self.assertTrue(inspect(plan,words,t['cutting_proof']['decisions'])['passed'])
  with f.s.connect()as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM jobs WHERE kind='audio_review'").fetchone()[0],0)
 def test_no_apply_without_both_listening_and_completeness_assertions(self):
  f=self.f;r=preview(f.s,self.request);d=self.approve(r);d['kept_meaning_complete']=False
  with self.assertRaises(Invalid):apply(f.s,d)
  d=self.approve(r);d['listened_all_joins']=False
  with self.assertRaises(Invalid):apply(f.s,d)
  self.assertEqual(f.s.project(f.p['id'])['active'],f.p['active'])
 def test_partial_unresolved_stale_overlap_chosen_and_loud_boundary_are_rejected(self):
  f=self.f;d=copy.deepcopy(self.request);d['cuts'][0]['start_frame']=0
  with self.assertRaises(Invalid):preview(f.s,d)
  d=copy.deepcopy(self.request);d['cuts'][0]['decision_version']=0
  with self.assertRaises(Conflict):preview(f.s,d)
  d=copy.deepcopy(f.payload);d.update(expected_version=1,choice='needs_review',selected_attempt=None,listened_all=False);save(f.s,d)
  with self.assertRaises(Invalid):preview(f.s,self.request)
  d.update(expected_version=2,choice='keep_attempt',selected_attempt=0,listened_all=True);save(f.s,d);self.request['cuts'][0]['decision_version']=3
  with wave.open(str(f.wav),'wb')as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(array.array('h',[12000]*64000).tobytes())
  f.result['wave_sha256']=file_hash(f.wav)
  with f.s.connect()as c:c.execute('UPDATE jobs SET result=? WHERE id=?',(dump(f.result),f.j));c.execute('UPDATE control_take_decisions SET audio_sha256=?',(f.result['wave_sha256'],))
  with self.assertRaisesRegex(Invalid,'صوت واضح'):preview(f.s,self.request)
 def test_changed_decision_or_join_file_cannot_be_applied(self):
  f=self.f;r=preview(f.s,self.request);path=audio(f.s,f.j,r['id'],0);original=path.read_bytes();path.write_bytes(b'changed')
  with self.assertRaises(Invalid):apply(f.s,self.approve(r))
  path.write_bytes(original);save(f.s,{**f.payload,'expected_version':1,'reason':'Different comparison decision invalidates old preview'})
  with self.assertRaises(Conflict):apply(f.s,self.approve(r))
 def test_evidence_change_invalidates_applied_word_proof(self):
  f=self.f;r=preview(f.s,self.request);out=apply(f.s,self.approve(r));proof=out['revision']['timeline']['cutting_proof'];Path(proof['decisions'][0]['boundary_attestation_file']).write_text('{}')
  with self.assertRaises(ValueError):validate_proof(f.s,proof)

 def test_external_voice_source_offset_is_preserved_on_both_sides_of_join(self):
  f=self.f;voice=f.root/'mic.wav';voice.write_bytes(b'synthetic external audio fixture');asset=f.s.add_asset(f.p['id'],str(voice),6,'audio')
  with f.s.connect()as c:
   rev=f.s.one(c,'SELECT timeline FROM revisions WHERE id=?',(f.p['active'],));t=json.loads(rev['timeline']);track=next(x for x in t['tracks']if x['kind']=='voice');track['clips'][0].update(asset_id=asset,source_in_frame=24,source_out_frame=120);c.execute('UPDATE revisions SET timeline=? WHERE id=?',(dump(t),f.p['active']));f.result.update(source_asset_id=asset,source_asset_sha256=file_hash(voice));c.execute('UPDATE jobs SET result=? WHERE id=?',(dump(f.result),f.j))
  r=preview(f.s,self.request);out=apply(f.s,self.approve(r));t=out['revision']['timeline'];v=next(x for x in t['tracks']if x['kind']=='voice')['clips'];picture=next(x for x in t['tracks']if x['kind']=='video')['clips'];self.assertEqual(v[1]['source_in_frame']-picture[1]['source_in_frame'],24);self.assertEqual(v[0]['source_in_frame'],24);self.assertEqual(v[1]['source_out_frame'],120)
 def test_unique_information_in_rejected_attempt_cannot_be_erased_by_attestation(self):
  f=self.f;plan=json.loads(f.plan.read_text());plan['retakes'][0]['attempts'][1]['text']='نص التجربة مع إضافة مهمة';f.plan.write_text(dump(plan));f.result['plan_sha256']=file_hash(f.plan)
  with f.s.connect()as c:c.execute('UPDATE jobs SET result=? WHERE id=?',(dump(f.result),f.j))
  d=describe(f.s,f.j);key=d['candidates'][0]['key'];save(f.s,{**f.payload,'candidate':key,'plan_sha256':f.result['plan_sha256'],'expected_version':0});self.request['cuts'][0]['candidate']=key
  with self.assertRaisesRegex(Invalid,'كلمات مختلفة'):preview(f.s,self.request)
 def test_boundary_cannot_cross_a_word_even_when_acoustically_quiet(self):
  f=self.f;wp=Path(f.result['source_words_file']);wp.write_text(dump({'words':[{'w':'uncertain stretched word','s':1.5,'e':2.5}]}));f.result['source_words_sha256']=file_hash(wp)
  with f.s.connect()as c:c.execute('UPDATE jobs SET result=? WHERE id=?',(dump(f.result),f.j))
  with self.assertRaisesRegex(Invalid,'مجال كلمة'):preview(f.s,self.request)
 def test_real_render_and_studio_preparation_preserve_cut_word_evidence_without_approval(self):
  from media import render
  from studio import prepare
  f=self.f;valid=Path(__file__).resolve().parents[1]/'.fixtures/take-repair-16/silent-ui-test.mp4'
  if not valid.is_file():self.skipTest('local silent render fixture unavailable')
  f.source.write_bytes(valid.read_bytes());digest=file_hash(f.source);f.result['source_asset_sha256']=digest
  with f.s.connect()as c:c.execute('UPDATE assets SET hash=? WHERE id=?',(digest,f.a));c.execute('UPDATE jobs SET result=? WHERE id=?',(dump(f.result),f.j))
  proposed=preview(f.s,self.request);p=apply(f.s,self.approve(proposed));folder=f.s.root/'jobs'/('a'*32);folder.mkdir();r=render(f.s,p['revision'],folder,{},lambda:False,lambda _:None);self.assertEqual(r['frames'],69);self.assertTrue(r['technical_decode']);self.assertTrue(r['voice_joined']);self.assertEqual(r['width'],640)
  with f.s.connect()as c:c.execute('INSERT INTO jobs(id,project,revision,kind,status,result,created) VALUES(?,?,?,?,?,?,?)',('a'*32,p['id'],p['active'],'render','completed',dump(r),2))
  review=f.s.root/'jobs'/('b'*32);review.mkdir();session=prepare(f.s,p['revision'],review,{'output_job':'a'*32,'consent_google_audio':True},lambda:False);binding=json.loads((review/'independent-review/word-audit-binding.json').read_text());self.assertEqual(binding['decisions'],p['revision']['timeline']['cutting_proof']['decisions']);self.assertFalse(session['review_complete']);self.assertEqual(session['gate']['status'],'blocked');self.assertFalse(session['api_success'])

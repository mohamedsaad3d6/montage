import sys,json,copy,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_take_repair as fixture
from take_repair import preview,apply
from core import dump,Invalid
from media import file_hash
class RepairBatch(unittest.TestCase):
 def setUp(self):self.f=fixture.TakeRepair();self.f.setUp()
 def tearDown(self):self.f.tearDown()
 def confirmed(self,cuts):
  path=self.f.f.s.root/'jobs'/self.f.f.j/'fixture-confirmed-pauses.json';plan={'cuts':cuts};path.write_text(dump(plan));return plan,path,file_hash(path)
 def quiet(self,a=24,b=36):return {'start_frame':a,'end_frame':b,'kind':'quiet_gap_only','removed_word_ids':[],'meaning_review':{'review_job':'synthetic-fixture-not-independent-evidence','output_sha256':'fixture','quote':'pause fixture','reason':'synthetic plumbing only'}}
 def test_manual_retakes_and_confirmed_pauses_share_one_synchronized_revision(self):
  f=self.f.f;request={**self.f.request,'include_confirmed_pauses':True};confirmed=self.confirmed([self.quiet()])
  with patch('pause_review.confirmed_plan',return_value=confirmed)as validate:
   r=preview(f.s,request);self.assertEqual(r['retake_cut_count'],1);self.assertEqual(r['quiet_cut_count'],1);self.assertEqual(f.s.project(f.p['id'])['active'],f.p['active']);out=apply(f.s,self.f.approve(r));self.assertEqual(validate.call_count,2)
  t=out['revision']['timeline'];self.assertEqual(t['duration_frames'],57);self.assertEqual(len(t['cutting_proof']['decisions']),1);self.assertEqual([x['source_in_frame']for x in next(tr for tr in t['tracks']if tr['kind']=='voice')['clips']],[0,36,74]);self.assertTrue(t['requires_new_independent_audio_review'])
 def test_overlap_is_reported_and_not_deleted_twice(self):
  f=self.f.f
  with patch('pause_review.confirmed_plan',return_value=self.confirmed([self.quiet(50,65)])):
   r=preview(f.s,{**self.f.request,'include_confirmed_pauses':True});self.assertEqual(r['quiet_cut_count'],0);self.assertEqual(len(r['skipped_overlapping_pauses']),1);out=apply(f.s,self.f.approve(r))
  self.assertEqual(out['revision']['timeline']['duration_frames'],69)
 def test_without_exact_raw_review_a_checkbox_cannot_authorize_pause_removal(self):
  with self.assertRaises(Invalid):preview(self.f.f.s,{**self.f.request,'include_confirmed_pauses':True})
  with patch('pause_review.confirmed_plan',side_effect=AssertionError('must not fetch review without selection')):self.assertEqual(preview(self.f.f.s,self.f.request)['quiet_cut_count'],0)
 def test_changed_pause_evidence_blocks_application(self):
  f=self.f.f;confirmed=self.confirmed([self.quiet()])
  with patch('pause_review.confirmed_plan',return_value=confirmed):r=preview(f.s,{**self.f.request,'include_confirmed_pauses':True})
  confirmed[1].write_text('{}')
  with self.assertRaises(Invalid):apply(f.s,self.f.approve(r))
  self.assertEqual(f.s.project(f.p['id'])['active'],f.p['active'])
 def test_quiet_label_cannot_erase_a_whole_word_between_boundaries(self):
  with patch('pause_review.confirmed_plan',return_value=self.confirmed([self.quiet(0,24)])):
   with self.assertRaisesRegex(Invalid,'تمس كلام'):preview(self.f.f.s,{**self.f.request,'include_confirmed_pauses':True})
 def test_pause_review_is_revalidated_after_preview_even_if_local_receipt_is_unchanged(self):
  f=self.f.f;confirmed=self.confirmed([self.quiet()])
  with patch('pause_review.confirmed_plan',return_value=confirmed):r=preview(f.s,{**self.f.request,'include_confirmed_pauses':True})
  with patch('pause_review.confirmed_plan',side_effect=Invalid('Independent review changed')):
   with self.assertRaisesRegex(Invalid,'changed'):apply(f.s,self.f.approve(r))
  self.assertEqual(f.s.project(f.p['id'])['active'],f.p['active'])
 def test_prior_per_cut_auditions_cannot_authorize_the_new_batch(self):
  f=self.f.f;r=preview(f.s,self.f.request);proposal=f.s.root/'jobs'/f.j/'manual-repairs'/r['id']/'proposal.json';content=json.loads(proposal.read_text());content.pop('audition_scope');proposal.write_text(dump(content))
  with self.assertRaisesRegex(Invalid,'قديمة'):apply(f.s,self.f.approve(r))

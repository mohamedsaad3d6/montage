import unittest,json
from unittest.mock import patch
import test_take_review as fixture
from core import dump,Invalid
from media import file_hash
from local_cut import apply
from audit import validate_proof
from workflow import advance,_put
class LocalCut(unittest.TestCase):
 def setUp(self):
  self.f=fixture.TakeReview();self.f.setUp();f=self.f
  wp=f.plan.parent/'words.json';wp.write_text(dump({'words':[{'w':'كلام','s':0,'e':1},{'w':'كلام','s':2,'e':3}]}));f.result.update(source_words_file=str(wp),source_words_sha256=file_hash(wp))
  plan=json.loads(f.plan.read_text());plan['cuts']=[{'start_frame':30,'end_frame':42,'kind':'quiet_gap_only','removed_word_ids':[]},{'start_frame':5,'end_frame':10,'kind':'quiet_gap_only','removed_word_ids':[]}];f.plan.write_text(dump(plan));f.result['plan_sha256']=file_hash(f.plan)
  with f.s.connect() as c:c.execute('UPDATE jobs SET result=? WHERE id=?',(dump(f.result),f.j))
 def tearDown(self):self.f.tearDown()
 def test_local_quiet_only_maps_tracks_preserves_all_ambiguous_speech_and_blocks_release(self):
  f=self.f;p=apply(f.s,f.p['id'],f.j,f.p['active']);t=p['revision']['timeline'];self.assertEqual(t['duration_frames'],84);self.assertEqual(t['local_cut_summary']['speech_deletions'],0);self.assertEqual(t['unresolved_take_comparisons'],1);self.assertTrue(t['requires_new_independent_audio_review']);validate_proof(f.s,t['cutting_proof'])
  for tr in t['tracks']:
   if tr['kind']in ('voice','video'):self.assertEqual(sum(c['end_frame']-c['start_frame'] for c in tr['clips']),84)
  from production import status
  self.assertFalse(status(p,f.s)['ready_for_montage']);self.assertEqual(status(p,f.s)['next_action']['kind'],'render')
 def test_continue_after_unresolved_google_runs_local_render_without_google_or_repeat_asr(self):
  f=self.f;j=f.s.enqueue(f.p['id'],'take_assess',{})
  with f.s.connect() as c:c.execute("UPDATE jobs SET status='failed',error='unresolved' WHERE id=?",(j,))
  _put(f.s,f.p['id'],'failed',f.p['active'],j,'unresolved')
  with patch('reviewer.check_free_connection',side_effect=AssertionError('cloud touched')):
   result=advance(f.s,f.p['id'])
  with f.s.connect()as c:row=f.s.one(c,'SELECT kind FROM jobs WHERE id=?',(result['new_job'],))
  self.assertEqual(row['kind'],'render')
 def test_words_tamper_blocks_all_changes(self):
  f=self.f;__import__('pathlib').Path(f.result['source_words_file']).write_text('{}')
  with self.assertRaises(Invalid):apply(f.s,f.p['id'],f.j,f.p['active'])
  self.assertEqual(f.s.project(f.p['id'])['active'],f.p['active'])

 def test_local_full_output_goes_to_exact_output_review_without_repeating_transcription(self):
  from production import status
  f=self.f;p=apply(f.s,f.p['id'],f.j,f.p['active']);t=p['revision']['timeline'];j=f.s.enqueue(p['id'],'render',{})
  with f.s.connect()as c:c.execute("UPDATE jobs SET status='completed',result=? WHERE id=?",(dump({'frames':t['duration_frames'],'start_frame':0,'file':str(f.source),'file_sha256':file_hash(f.source),'technical_decode':True}),j))
  after=status(f.s.project(p['id']),f.s);self.assertEqual(after['next_action']['kind'],'review');self.assertFalse(after['ready_for_montage']);self.assertFalse(after['publication_approved'])

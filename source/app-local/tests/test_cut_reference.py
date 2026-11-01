import unittest,sys,json,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cut_reference import anchors,words,normalize
from core import Store,Invalid
from intake import save,start
from workflow import begin,tick,get
from worker import execute

def phrase(text,start=0):return [{'n':x,'text':x,'start':start+i*.3,'end':start+(i+1)*.3} for i,x in enumerate(text.split())]
class CutReference(unittest.TestCase):
 def test_normalization_preserves_numbers_and_words(self):self.assertEqual(normalize('إِنهيارُ الشركة، ٢٠٢٦'),'انهيار الشركه ٢٠٢٦'.split())
 def test_skip_regions_have_distinct_source_offsets_and_are_candidates_only(self):
  a=phrase('في هذه السنه كانت شركه كبيره جدا',10);b=phrase('ثم حدث انهيار شديد في اسواق العالم',50);ref=phrase('في هذه السنه كانت شركه كبيره جدا',0)+phrase('ثم حدث انهيار شديد في اسواق العالم',3)
  report=anchors(a+b,ref);self.assertGreater(len(report['anchors']),1);self.assertFalse(report['automatic_cuts_applied']);self.assertTrue(report['requires_acoustic_boundary_verification']);self.assertFalse(report['independent_audio_review_passed']);self.assertEqual(report['anchors'][0]['source_start'],10)
 def test_repeated_takes_are_not_silently_selected(self):
  a=phrase('قال الرجل ان هذه الشركه كبيره جدا');report=anchors(a+phrase('قال الرجل ان هذه الشركه كبيره جدا',12),a);self.assertEqual(report['anchors'],[]);self.assertGreater(report['ambiguous_phrases'],0)
 def test_word_tokens_ignore_non_speech_tokens_and_preserve_clock(self):
  d={'transcription':[{'tokens':[{'text':'[_BEG_]'}, {'text':' الش','offsets':{'from':100,'to':150}},{'text':'ركة','offsets':{'from':150,'to':230}}]}]};w=words(d,10);self.assertEqual(w[0]['text'],'الشركة');self.assertEqual(w[0]['start'],10.1)
 def test_third_mode_is_explicit_not_guessed_from_duration_and_never_uses_constant_sync(self):
  with tempfile.TemporaryDirectory()as temp:
   root=Path(temp);s=Store(root/'data',[root]);p=s.create('three paths');raw=root/'v.mp4';raw.write_bytes(b'video');voice=root/'a.mp3';voice.write_bytes(b'edited audio');v=s.add_asset(p['id'],str(raw),120,'video');a=s.add_asset(p['id'],str(voice),80,'audio')
   state=save(s,{'project':p['id'],'expected_version':0,'video':v,'voice':a,'voice_mode':'external_cut'});j=begin(s,{'project':p['id'],'expected':p['active'],'input_version':state['version']})['new_job']
   report={'sync_status':'post_cut_reference_candidates','input_version':1,'matched_word_fraction':.9,'automatic_cuts_applied':False}
   with patch('media.probe',return_value={'streams':[{'codec_type':'video'},{'codec_type':'audio'}]}),patch('input_prepare.probe',return_value={'streams':[{'codec_type':'audio'}]}),patch('cut_reference.prepare',return_value=report) as method:execute(s,j);self.assertTrue(method.called)
   dispatched=[];tick(s,dispatched.append);self.assertEqual(len(dispatched),1);self.assertEqual(s.project(p['id'])['jobs'][0]['kind'],'reference_refine');self.assertEqual(get(s,p['id'])['state'],'running');self.assertEqual(s.project(p['id'])['active'],p['active'])
   with patch('media.probe',return_value={'streams':[{'codec_type':'audio'}]}):
    with self.assertRaises(Invalid):start(s,{'project':p['id'],'expected':p['active'],'input_version':1,'sync_job':j,'sync_confirmed':True})
   self.assertEqual(raw.read_bytes(),b'video');self.assertEqual(voice.read_bytes(),b'edited audio')
 def test_acoustic_check_does_not_promote_phrase_timing_to_cut_permission(self):
  import numpy as np
  from cut_reference import check_acoustic_samples
  row={'reference_start':2,'reference_end':5,'source_start':12}
  query=np.random.default_rng(11).normal(size=300);search=np.r_[np.zeros(200),query,np.zeros(200)]
  with patch('input_prepare.pcm',side_effect=[query,search]):samples=check_acoustic_samples({'path':'raw','duration':40},{'path':'master'},[row],Path('.'),lambda:False,lambda _:None)
  self.assertTrue(samples[0]['passed']);self.assertFalse(samples[0]['executable_cut_boundary']);self.assertEqual(samples[0]['source_start_measured'],12)
 def test_no_anchors_means_no_acoustic_claim(self):
  from cut_reference import check_acoustic_samples
  self.assertEqual(check_acoustic_samples({}, {}, [], Path('.'),lambda:False,lambda _:None),[])
 def test_coarse_search_checks_distributed_reference_samples_and_never_exposes_cut_permission(self):
  from cut_reference import coarse_acoustic_map
  import numpy as np
  with patch('input_prepare.pcm',return_value=np.ones(1000)),patch('input_prepare.match',return_value=(42,.82,.2)):
   samples=coarse_acoustic_map({'path':'raw','duration':150},{'path':'cut','duration':100},Path('.'),lambda:False,lambda _:None)
  self.assertEqual(len(samples),9);self.assertTrue(all(x['passed']for x in samples));self.assertTrue(all(x['executable_cut_boundary']is False for x in samples));self.assertGreater(max(x['reference_seconds']for x in samples),80)

class AcousticFirst(unittest.TestCase):
 def test_edited_audio_preparation_does_not_transcribe_whole_raw_first(self):
  from cut_reference import prepare
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp);s=Store(root/'data',[root]);p=s.create('acoustic-first');v=root/'v.mp4';v.write_bytes(b'raw');a=root/'a.wav';a.write_bytes(b'edited');vi=s.add_asset(p['id'],str(v),90,'video');ai=s.add_asset(p['id'],str(a),45,'audio');state=save(s,{'project':p['id'],'expected_version':0,'video':vi,'voice':ai,'voice_mode':'external_cut'});folder=root/'job';folder.mkdir()
   with patch('cut_reference.coarse_acoustic_map',return_value=[]),patch('cut_reference.transcribe')as asr:
    r=prepare(s,p['revision'],folder,{},lambda:False,lambda _:None,s.asset(vi),s.asset(ai),state)
   asr.assert_not_called();self.assertEqual(r['sync_status'],'post_cut_acoustic_candidates');self.assertFalse(r['automatic_cuts_applied']);self.assertTrue(r['asr_deferred_until_reference_timeline'])

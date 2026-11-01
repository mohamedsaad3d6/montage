import sys,unittest,tempfile,wave,array,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from editorial import norm,token_words,retakes,silence_proposals
from selection import shortlist

def words(text):return [{'id':i,'w':w,'n':norm(w),'s':i*.3,'e':i*.3+.2,'confidence':.95} for i,w in enumerate(text.split())]
def asset(id,subjects,**meta):return {'id':id,'kind':'video','duration':12,'metadata':{'rights_verified':True,'visual_verified':True,'verification_frames':['local-proof-hash'],'subjects':subjects,**meta}}
class Editorial(unittest.TestCase):
 def test_required_attribution_not_silently_stripped(self):
  r=shortlist('محمد بن سلمان',[asset('a',['mbs'],focus_person='mbs',visual_type='person',credit_required=True)])
  self.assertEqual(r['candidates'],[]);self.assertEqual(r['rejected'][0]['reason'],'requires_visible_credit_not_compatible_with_clean_style')

 def test_parallel_clauses_and_emphasis_not_retakes(self):
  self.assertEqual(retakes(words('بدأوا يضربوا أهداف داخل السعودية بدأوا يهددوا السفن والموانئ')),[])
  self.assertEqual(retakes(words('الموقف مهم جدا جدا ومحتاج تفكير')),[])
 def test_duplicate_phrase_is_only_candidate_not_last_take_wins(self):
  out=retakes(words('السعودية عندها نفط وموانئ السعودية عندها نفط وموانئ'))
  self.assertTrue(out);self.assertIsNone(out[0]['preferred_candidate']);self.assertFalse(out[0]['automatic_delete_allowed']);self.assertTrue(out[0]['requires_listening'])
 def test_unique_offscript_addition_not_deleted(self):
  out=retakes(words('السعودية عندها نفط وموانئ ومصانع السعودية عندها نفط فقط'))
  self.assertEqual(out,[])
 def test_ctc_spelling_variants_flag_long_repeat_only_for_listening(self):
  text='محمد بن سلمان اتكلم مع ترم وطلب منه مساعده عسكيه مباشره ضد الحوسيه محمد بن سلمان اكلم مع ترب وطلب منه مساعد عسكري مباشره ضد الحوسيه'
  self.assertEqual(retakes(words(text)),[])
  out=retakes(words(text),allow_ctc_variants=True);self.assertTrue(out);self.assertGreater(out[0]['approximate_word_matches'],0);self.assertFalse(out[0]['automatic_delete_allowed']);self.assertTrue(out[0]['requires_listening'])
 def test_ctc_variant_mode_still_retains_meaningful_added_words(self):
  self.assertEqual(retakes(words('محمد بن سلمان اتكلم مع ترامب وطلب مصانع ومدارس محمد بن سلمان اتكلم مع ترامب وطلب مساعدة فقط'),allow_ctc_variants=True),[])
 def test_arabic_subwords_reassembled_without_fake_exact_alignment(self):
  d={'transcription':[{'tokens':[{'text':' م','offsets':{'from':0,'to':100},'p':.9},{'text':'حمد','offsets':{'from':100,'to':300},'p':.8},{'text':' بن','offsets':{'from':300,'to':500},'p':.9}]}]}
  w=token_words(d);self.assertEqual([x['w'] for x in w],['محمد','بن']);self.assertEqual(w[0]['confidence'],.8);self.assertIn('not_forced_alignment',w[0]['timing_method'])
 def test_silence_never_overlaps_protected_speech(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'audio.wav'
   with wave.open(str(p),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(array.array('h',[0]*48000).tobytes())
   self.assertEqual(silence_proposals(p,[{'s':.2,'e':2.8}]),[])
   proposals=silence_proposals(p,[]);self.assertTrue(proposals);self.assertFalse(proposals[0]['automatic_delete_allowed'])
 def test_safe_subgap_survives_a_word_tail_near_the_silence_edge(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'edge.wav';rate=16000;data=array.array('h',[1000]*(8*rate))
   for i in range(round(2.39*rate),round(4.61*rate)):data[i]=0
   with wave.open(str(p),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(data.tobytes())
   result=silence_proposals(p,[{'s':2.02,'e':2.48},{'s':4.62,'e':4.98}]);self.assertEqual(len(result),1)
   a,b=result[0]['proposed_cut'];self.assertGreaterEqual(a,2.63);self.assertLessEqual(b,4.47)

class Selection(unittest.TestCase):
 def test_trump_cannot_replace_mbs_even_same_location(self):
  r=shortlist('محمد بن سلمان طلب مساعدة', [asset('trump',['trump','saudi'],focus_person='trump'),asset('mbs',['mbs','saudi'],focus_person='mbs')]);self.assertEqual([x['asset_id'] for x in r['candidates']],['mbs']);self.assertEqual(r['rejected'][0]['reason'],'wrong_or_missing_named_person')
 def test_map_does_not_document_houthi_attack(self):
  r=shortlist('الحوثيين شنوا هجمات على السعودية',[asset('map',['houthis','saudi'],visual_type='map')]);self.assertEqual(r['candidates'],[]);self.assertTrue(r['event_footage_required'])
 def test_wrong_period_and_unverified_frames_rejected(self):
  r=shortlist('مظاهرات اليمن سنة 1969',[asset('late',['yemen'],visual_type='event_footage',event_verified=True,year_start=2020,year_end=2020)]);self.assertEqual(r['rejected'][0]['reason'],'period_mismatch')
  r=shortlist('محمد بن سلمان',[{'id':'unknown','duration':20,'kind':'video','metadata':{'subjects':['mbs']}}]);self.assertEqual(r['candidates'],[])
 def test_real_event_and_geographic_context_use_different_materials(self):
  r=shortlist('مضيق هرمز بين موانئ الخليج',[asset('map',['hormuz'],visual_type='map')]);self.assertEqual(r['candidates'][0]['asset_id'],'map')
  r=shortlist('الحوثيين شنوا هجمات على السعودية',[asset('actual',['houthis','saudi'],visual_type='event_footage',event_verified=True)]);self.assertEqual(r['candidates'][0]['asset_id'],'actual')
 def test_short_clip_not_looped(self):
  a=asset('short',['hormuz'],visual_type='map');a['duration']=1;r=shortlist('مضيق هرمز',[a],seconds=5);self.assertEqual(r['rejected'][0]['reason'],'insufficient_unique_material_no_loop')
if __name__=='__main__':unittest.main(verbosity=2)

class UnreliableASR(unittest.TestCase):
 def test_uncertain_asr_protects_audio_without_generating_retake_candidates(self):
  from editorial import token_words,retakes
  d={'transcription':[{'text':'عبارة متخيلة','unreliable_asr':True,'offsets':{'from':i*30000,'to':(i+1)*30000}}for i in range(6)]}
  words=token_words(d);self.assertEqual(len(words),6);self.assertTrue(all(not w['n']for w in words));self.assertEqual(retakes(words),[]);self.assertEqual(words[-1]['e'],180)

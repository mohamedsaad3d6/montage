import sys,unittest,numpy as np
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reference_acoustic import verify
class Acoustic(unittest.TestCase):
 def test_known_offset_is_verified_but_not_a_release_or_audio_edit(self):
  rng=np.random.default_rng(8);reference=rng.normal(-3,.5,2000);source=np.r_[rng.normal(-3,.5,200),reference,rng.normal(-3,.5,200)];seeds=[{'passed':True,'source_seconds':t+2,'reference_seconds':t}for t in (2,8,14)];r=verify(source,reference,seeds);self.assertTrue(r['all_speech_verified']);self.assertEqual(r['offset_frames'],48);self.assertFalse(r['automatic_cuts_applied']);self.assertFalse(r['independent_audio_review_passed'])
 def test_piecewise_cut_cannot_be_accepted_as_one_offset(self):
  rng=np.random.default_rng(8);source=rng.normal(-3,.5,3000);reference=np.r_[source[200:1100],source[1400:2300]];seeds=[{'passed':True,'source_seconds':t+2,'reference_seconds':t}for t in (2,4,6)];r=verify(source,reference,seeds);self.assertFalse(r['all_speech_verified']);self.assertGreater(len(r['unverified_intervals']),0)

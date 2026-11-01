import sys,unittest,numpy as np
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from picture_alignment import align
class Piecewise(unittest.TestCase):
 def test_multiple_cuts_reconstruct_picture_not_reference_audio(self):
  source=np.random.default_rng(51).normal(-3,.7,5000);reference=np.r_[source[200:1200],source[1700:2700],source[3400:4400]];old=reference.copy();r=align(source,reference,max_global=40)
  self.assertTrue(r['mapping_ready'],r['issues']);self.assertEqual(len(r['segments']),3);self.assertEqual([s['source_in_frame']for s in r['segments']],[48,408,816]);np.testing.assert_array_equal(reference,old);self.assertFalse(r['independent_audio_review_passed'])
 def test_repeated_source_is_not_chosen_arbitrarily(self):
  q=np.random.default_rng(52).normal(-3,.7,1200);source=np.r_[q,np.zeros(200)-8,q];r=align(source,q,max_global=10);self.assertFalse(r['mapping_ready'])
 def test_missing_speech_section_blocks_application(self):
  source=np.random.default_rng(53).normal(-3,.7,2400);ref=source[200:2000].copy();ref[800:1000]=np.random.default_rng(54).normal(-3,.7,200);r=align(source,ref,max_global=20);self.assertFalse(r['mapping_ready']);self.assertTrue(r.get('issues'))
if __name__=='__main__':unittest.main()

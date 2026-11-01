import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from transcription_quality import inspect
class Quality(unittest.TestCase):
 def data(self,texts,seconds=10):return {'transcription':[{'text':t,'offsets':{'from':i*seconds*1000,'to':(i+1)*seconds*1000}}for i,t in enumerate(texts)]}
 def test_decoder_collapse_is_not_treated_as_confirmed_retake(self):
  r=inspect(self.data(['ترجمة نانسي قنقر']*20));self.assertTrue(r['requires_second_pass']);self.assertFalse(r['speech_deletion_allowed'])
 def test_short_intentional_refrain_is_not_rejected(self):self.assertFalse(inspect(self.data(['هذا حقنا']*3,2))['requires_second_pass'])
 def test_varied_speech_passes_only_this_narrow_check(self):self.assertEqual(inspect(self.data(['مقدمة','شرح الموضوع','نهاية']))['status'],'no_repetition_collapse_detected')

import sys,unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from studio import record,audio_file
class Studio(unittest.TestCase):
 def test_no_result_without_explicit_origin_attestation(self):
  with self.assertRaises(ValueError):record(None,'j',0,{'transcript':'x','issues':[]},'image',False)
 def test_audio_part_cannot_escape_review_folder(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);reviews=root/'review';reviews.mkdir();state={'chunks':[{'file':'../private.wav','sha256':'x'}]}
   with patch('studio.state_for',return_value=({}, {},root,reviews,state)):
    with self.assertRaises(ValueError):audio_file(None,'j',0)
    with self.assertRaises(ValueError):audio_file(None,'j',2)
if __name__=='__main__':unittest.main()

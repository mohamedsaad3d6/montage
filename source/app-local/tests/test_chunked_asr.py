import sys,tempfile,wave,json,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import chunked_asr
class Chunks(unittest.TestCase):
 def test_independent_chunks_rebase_all_token_offsets_and_reuse_exact_pcm(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp);wav=root/'voice.wav';model=root/'model';model.write_bytes(b'model');cli=root/'cli';cli.write_bytes(b'cli');folder=root/'out';folder.mkdir()
   with wave.open(str(wav),'wb')as w:w.setparams((1,2,100,0,'NONE','not compressed'));w.writeframes(b'\1\0'*12100)
   original=wav.read_bytes();calls=[]
   def spawn(args,**kwargs):
    calls.append(args);stem=Path(args[args.index('-of')+1]);stem.with_suffix('.json').write_text(json.dumps({'transcription':[{'text':' كلام مستقل','offsets':{'from':0,'to':900},'tokens':[{'text':' كلام','offsets':{'from':100,'to':500}}]}]}))
    class P:
     returncode=0
     def poll(self):return 0
    return P()
   with patch('chunked_asr.tool',return_value=str(cli)),patch('chunked_asr.subprocess.Popen',side_effect=spawn):
    first=chunked_asr.transcribe(wav,folder,model,root/'cache',lambda:False)
    again=chunked_asr.transcribe(wav,folder,model,root/'cache',lambda:False)
   self.assertEqual(len(calls),2);self.assertTrue(all(a[-2:]==['-mc','0']for a in calls))
   self.assertEqual(first['transcription'][1]['offsets']['from'],120000)
   self.assertEqual(first['transcription'][1]['tokens'][0]['offsets']['from'],120100)
   self.assertEqual(first,again);self.assertEqual(wav.read_bytes(),original)

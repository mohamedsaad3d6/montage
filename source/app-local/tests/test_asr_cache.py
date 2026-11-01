import sys,unittest,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from asr_cache import save,restore,key
class ASRCache(unittest.TestCase):
 def test_reuse_exact_input_only_and_preserve_arabic(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);a=root/'first.json';b=root/'second.json';a.write_text(json.dumps({'transcription':[{'text':'الجملة كاملة'}]},ensure_ascii=False));identity={'pcm_sha256':'a','model_sha256':'b','binary_sha256':'c','language':'ar'}
   save(root/'cache',identity,a);self.assertTrue(restore(root/'cache',identity,b));self.assertEqual(a.read_bytes(),b.read_bytes())
   for field in identity:self.assertFalse(restore(root/'cache',{**identity,field:'different'},root/'missing.json'))
 def test_corrupt_cached_result_is_not_reused(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);a=root/'first.json';a.write_text('{"transcription":[]}');identity={'pcm_sha256':'a'};save(root/'cache',identity,a)
   file=root/'cache'/(key(identity)+'.json');item=json.loads(file.read_text());item['response']='{"transcription":[{"text":"changed"}]}';file.write_text(json.dumps(item))
   self.assertFalse(restore(root/'cache',identity,root/'second.json'));self.assertFalse((root/'second.json').exists())
 def test_non_transcript_is_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);f=p/'wrong.json';f.write_text('{}')
   with self.assertRaises(ValueError):save(p/'cache',{},f)
if __name__=='__main__':unittest.main()

class TranscriptionReuse(unittest.TestCase):
 def test_new_job_reuses_verified_chunk_but_model_change_retranscribes(self):
  from unittest.mock import patch
  from cut_reference import transcribe
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);model=root/'model.bin';model.write_bytes(b'model-v1');cli=root/'cli';cli.write_bytes(b'cli-v1');calls=[]
   def extract(args,*unused):Path(args[-1]).write_bytes(b'identical-extracted-pcm')
   def spawn(args,**kwargs):
    calls.append(args);stem=Path(args[args.index('-of')+1]);stem.with_suffix('.json').write_text('{"transcription":[]}')
    class Process:
     returncode=0
     def poll(self):return 0
    return Process()
   with patch.dict('os.environ',{'MONTAJ_WHISPER_MODEL':str(model)}),patch('cut_reference.tool',return_value=str(cli)),patch('cut_reference.run',side_effect=extract),patch('cut_reference.subprocess.Popen',side_effect=spawn):
    for name in ('job-one','job-two'):transcribe('source',1,root/name,lambda:False,lambda _:None,'test',root/'cache')
    self.assertEqual(len(calls),1)
    model.write_bytes(b'model-v2');transcribe('source',1,root/'job-three',lambda:False,lambda _:None,'test',root/'cache');self.assertEqual(len(calls),2)

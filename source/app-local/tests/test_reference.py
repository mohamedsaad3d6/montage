import sys,json,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store
from reference import prepare
from audit import reference_receipt,validate_proof
from media import file_hash
FIXTURE=Path(__file__).resolve().parents[1]/'.fixtures/spoken.mp4'
class Reference(unittest.TestCase):
 def test_unchanged_whole_file_proves_no_new_word_deletion_without_fake_transcript(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);s=Store(p/'data',[FIXTURE.parent]);v=s.create('تشخيص تطابق كامل');a=s.add_asset(v['id'],str(FIXTURE),6,'video');t=v['revision']['timeline'];t['duration_frames']=144
   for tr in t['tracks']:
    if tr['kind'] in ['video','voice']:tr['clips']=[{'id':tr['kind'],'asset_id':a,'start_frame':0,'end_frame':144,'source_in_frame':0,'source_out_frame':144}]
   v=s.save(v['id'],v['active'],t);folder=p/'render';folder.mkdir();before=file_hash(FIXTURE);r=prepare(s,v['revision'],folder,{},lambda:False,lambda _:None)
   self.assertTrue(r['byte_identical_reference']);self.assertEqual(file_hash(r['file']),before);proof=reference_receipt(s,v['revision'],r);validate_proof(s,proof);self.assertEqual(proof['audit_method'],'full_source_byte_identity');self.assertNotIn('source_words_file',proof)
   Path(r['file']).write_bytes(Path(r['file']).read_bytes()+b'changed')
   with self.assertRaises(ValueError):validate_proof(s,proof)
   self.assertEqual(file_hash(FIXTURE),before)
if __name__=='__main__':unittest.main()

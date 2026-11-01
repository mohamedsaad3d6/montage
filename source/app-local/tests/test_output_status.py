import sys,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,uid,dump,Invalid
from media import file_hash
from output_status import status
class OutputStatus(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.store=Store(self.root/'data',[self.root]);self.p=self.store.create('اختبار');self.file=self.root/'output.mp4';self.file.write_bytes(b'exact-media');self.out=uid();self.result={'file':str(self.file),'file_sha256':file_hash(self.file),'duration':60,'width':1920,'height':1080,'frames':1440,'start_frame':0}
  with self.store.connect() as c:c.execute('INSERT INTO jobs(id,project,revision,kind,status,result,created) VALUES(?,?,?,?,?,?,?)',(self.out,self.p['id'],self.p['active'],'render','completed',dump(self.result),1))
 def tearDown(self):self.tmp.cleanup()
 def test_full_unreviewed_never_playable(self):
  x=status(self.store,self.out);self.assertFalse(x['audio_review_passed']);self.assertFalse(x['internal_diagnostic_playable']);self.assertFalse(x['publication_approved'])
 def test_changed_media_invalidates_even_cached_success(self):
  self.review('positive',True,2);self.file.write_bytes(b'changed')
  with patch('release.reviewed',return_value=True):x=status(self.store,self.out)
  self.assertFalse(x['media_identity_valid']);self.assertFalse(x['audio_review_passed'])
 def review(self,id,passed,at):
  result={'output_job':self.out,'review_complete':True,'output_sha256':self.result['file_sha256'],'gate':{'status':'passed_for_review' if passed else 'blocked'}}
  with self.store.connect() as c:c.execute('INSERT INTO jobs(id,project,revision,kind,status,result,created) VALUES(?,?,?,?,?,?,?)',(id,self.p['id'],self.p['active'],'audio_review','completed',dump(result),at))
 def test_newest_complete_review_is_the_only_candidate(self):
  self.review('positive',True,2);self.review('negative',False,3)
  with patch('release.reviewed',side_effect=lambda s,j,r:j['id']=='positive') as check:x=status(self.store,self.out)
  self.assertEqual(check.call_args[0][1]['id'],'negative');self.assertFalse(x['audio_review_passed'])
 def test_review_for_another_output_does_not_match(self):
  self.review('other',True,2)
  with self.store.connect() as c:c.execute('UPDATE jobs SET result=? WHERE id=?',(dump({'output_job':'other-output','review_complete':True}),'other'))
  with patch('release.reviewed') as check:x=status(self.store,self.out)
  check.assert_not_called();self.assertFalse(x['audio_review_passed'])
if __name__=='__main__':unittest.main()

import sys,unittest,tempfile,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Conflict
class ReviewReplay(unittest.TestCase):
 def test_uncertain_request_cannot_be_repeated_via_new_job_or_same_audio_export(self):
  with tempfile.TemporaryDirectory() as td:
   s=Store(td,[td]);v=s.create('تشخيص منع إعادة الإرسال');a=s.enqueue(v['id'],'render')
   with s.connect() as c:c.execute("UPDATE jobs SET status='completed',result=? WHERE id=?",(json.dumps({'audio_hash':'exact-audio','file_sha256':'media-one'}),a))
   review=s.enqueue(v['id'],'audio_review',{'output_job':a,'consent_google_audio':True})
   with s.connect() as c:c.execute("UPDATE jobs SET status='failed' WHERE id=?",(review,))
   folder=Path(td)/'jobs'/review/'independent-review';folder.mkdir(parents=True);(folder/'run.json').write_text(json.dumps({'status':'stopped_needs_reconciliation','chunks':[{'status':'in_flight'}]}))
   with self.assertRaises(Conflict):s.enqueue(v['id'],'audio_review',{'output_job':a,'consent_google_audio':True})
   b=s.enqueue(v['id'],'render')
   with s.connect() as c:c.execute("UPDATE jobs SET status='completed',result=? WHERE id=?",(json.dumps({'audio_hash':'exact-audio','file_sha256':'media-two'}),b))
   with self.assertRaises(Conflict):s.enqueue(v['id'],'audio_review',{'output_job':b,'consent_google_audio':True})
if __name__=='__main__':unittest.main()

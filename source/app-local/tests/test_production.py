import sys,unittest,tempfile,json,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from production import status
from audit import uncut_receipt,validate_proof
from core import Store
class Production(unittest.TestCase):
 def project(self):return {'active':'r1','revision':{'timeline':{'fps':24,'duration_frames':144,'phase':'cut_candidate'}},'jobs':[]}
 def job(self,kind,result,id='out',revision='r1'):return {'id':id,'revision':revision,'kind':kind,'status':'completed','result':json.dumps(result)}
 def test_render_or_analysis_never_means_review(self):
  p=self.project();p['jobs']=[self.job('transcribe',{}),self.job('render',{'start_frame':0,'frames':144,'technical_decode':True,'file_sha256':'x'})]
  r=status(p);self.assertFalse(r['ready_for_montage']);self.assertEqual(r['next_action']['kind'],'review')
 def test_partial_wrong_revision_or_changed_media_never_advance(self):
  with tempfile.TemporaryDirectory() as td:
   f=Path(td)/'media';f.write_bytes(b'exact');h=hashlib.sha256(f.read_bytes()).hexdigest();p=self.project()
   out=self.job('render',{'start_frame':0,'frames':144,'file_sha256':h,'file':str(f),'technical_decode':True})
   review=self.job('audio_review',{'output_job':'out','output_sha256':h,'review_complete':True,'gate':{'status':'passed_for_review'}},'review')
   p['jobs']=[out,review];self.assertTrue(status(p)['ready_for_montage']);self.assertFalse(status(p)['publication_approved'])
   f.write_bytes(b'changed');self.assertFalse(status(p)['ready_for_montage'])
   f.write_bytes(b'exact');review['revision']='old';self.assertFalse(status(p)['ready_for_montage'])
   review['revision']='r1';r=json.loads(out['result']);r['frames']=72;out['result']=json.dumps(r);self.assertFalse(status(p)['ready_for_montage'])
 def test_newer_completed_negative_review_overrides_older_pass(self):
  with tempfile.TemporaryDirectory() as td:
   f=Path(td)/'media';f.write_bytes(b'exact');h=hashlib.sha256(f.read_bytes()).hexdigest();p=self.project()
   out=self.job('render',{'start_frame':0,'frames':144,'file_sha256':h,'file':str(f),'technical_decode':True})
   positive=self.job('audio_review',{'output_job':'out','output_sha256':h,'review_complete':True,'gate':{'status':'passed_for_review'}},'old')
   negative=self.job('audio_review',{'output_job':'out','output_sha256':h,'review_complete':True,'gate':{'status':'blocked','reasons':['unresolved_editorial_issues_0']}},'new')
   p['jobs']=[negative,positive,out];self.assertFalse(status(p)['ready_for_montage'])
 def test_uncut_real_words_and_tamper_detection(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);s=Store(p/'data',[p]);v=s.create('تشخيص دليل كلمات');source=p/'voice.wav';source.write_bytes(b'source');a=s.add_asset(v['id'],str(source),3,'audio');t=v['revision']['timeline'];t['duration_frames']=72
   next(tr for tr in t['tracks'] if tr['kind']=='voice')['clips']=[{'id':'v','asset_id':a,'start_frame':0,'end_frame':72,'source_in_frame':0,'source_out_frame':72}]
   v=s.save(v['id'],v['active'],t)
   with self.assertRaises(ValueError):uncut_receipt(s,v['revision'],p)
   words=p/'analysis.json';words.write_text(json.dumps({'words':[{'w':'كلام','s':.1,'e':.8}]}));jid=s.enqueue(v['id'],'transcribe');h=hashlib.sha256(words.read_bytes()).hexdigest();asset=s.asset(a)
   result={'source_asset_id':a,'source_asset_sha256':asset['hash'],'analysis_file':str(words),'analysis_sha256':h}
   with s.connect() as c:c.execute("UPDATE jobs SET status='completed',result=? WHERE id=?",(json.dumps(result),jid))
   proof=uncut_receipt(s,v['revision'],p);validate_proof(s,proof)
   Path(proof['source_words_file']).write_text('{"words":[]}')
   with self.assertRaises(ValueError):validate_proof(s,proof)
if __name__=='__main__':unittest.main()

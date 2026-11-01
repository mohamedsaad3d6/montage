import sys,json,hashlib,tempfile,copy,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid
from montage import apply_plan
from media import file_hash
class Montage(unittest.TestCase):
 def test_audio_gate_blocks_visual_progress(self):
  with tempfile.TemporaryDirectory() as td:
   s=Store(td,[td]);v=s.create('تشخيص');
   with self.assertRaisesRegex(Invalid,'المراجعة السمعية'):apply_plan(s,v['id'],'none',v['active'])
 def test_new_visual_revision_preserves_voice_and_rejects_changed_plan(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);s=Store(root/'data',[root]);v=s.create('تشخيص ترتيب اللقطات');raw=root/'raw.mp4';raw.write_bytes(b'raw');broll=root/'broll.mp4';broll.write_bytes(b'other');a=s.add_asset(v['id'],str(raw),4,'video');b=s.add_asset(v['id'],str(broll),4,'video');t=v['revision']['timeline'];t.update(phase='raw',duration_frames=96,primary_video_asset_id=a)
   for tr in t['tracks']:
    if tr['kind'] in ['video','voice']:tr['clips']=[{'id':tr['kind'],'asset_id':a,'start_frame':0,'end_frame':96,'source_in_frame':0,'source_out_frame':96}]
   v=s.save(v['id'],v['active'],t);voice=copy.deepcopy(next(tr for tr in t['tracks'] if tr['kind']=='voice'));jid=s.enqueue(v['id'],'shot_plan');folder=s.root/'jobs'/jid;folder.mkdir(parents=True);f=folder/'shot-plan.json';asset=s.asset(b)
   # Controlled plan scaffolding tests mutation rules, not real-world semantic correctness.
   f.write_text(json.dumps({'source_revision':v['active'],'proposals':[{'suggested_asset_id':b,'narration':'جملة مكتملة.','start_ms':1000,'end_ms':3000}],'asset_evidence':{b:{'sha256':asset['hash'],'metadata_sha256':hashlib.sha256(asset['metadata'].encode()).hexdigest()}}}))
   with s.connect() as c:c.execute("UPDATE jobs SET status='completed',result=? WHERE id=?",(json.dumps({'plan_file':str(f),'plan_sha256':file_hash(f)}),jid))
   with patch('production.status',return_value={'ready_for_montage':True}):out=apply_plan(s,v['id'],jid,v['active'])
   self.assertNotEqual(out['active'],v['active']);self.assertEqual(next(tr for tr in out['revision']['timeline']['tracks'] if tr['kind']=='voice'),voice)
   self.assertEqual(out['revision']['timeline']['phase'],'montage_candidate');self.assertEqual(len(next(tr for tr in out['revision']['timeline']['tracks'] if tr['kind']=='video')['clips']),3)
   self.assertEqual(s.revision(v['active'])['timeline'],t)
if __name__=='__main__':unittest.main()

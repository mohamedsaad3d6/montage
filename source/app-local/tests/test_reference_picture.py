import sys,json,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,fingerprint,Invalid,Conflict
from intake import save
from reference_picture import apply
class PictureCompiler(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=Store(self.root/'data',[self.root]);self.p=self.s.create('reference picture');raw=self.root/'v.mp4';raw.write_bytes(b'raw');audio=self.root/'a.wav';audio.write_bytes(b'reference');self.v=self.s.add_asset(self.p['id'],str(raw),10,'video');self.a=self.s.add_asset(self.p['id'],str(audio),4,'audio');save(self.s,{'project':self.p['id'],'expected_version':0,'video':self.v,'voice':self.a,'voice_mode':'external_cut'});self.job=self.s.enqueue(self.p['id'],'reference_refine');folder=self.s.root/'jobs'/self.job;folder.mkdir(parents=True);self.file=folder/'map.json'
  self.report={'project':self.p['id'],'source_revision':self.p['active'],'input_version':1,'scope':'picture_only_reference_voice_not_edited','mapping_ready':True,'issues':[],'video_sha256':fingerprint(raw),'audio_sha256':fingerprint(audio),'fps':24,'duration_frames':96,'segments':[{'start_frame':0,'end_frame':48,'source_in_frame':24},{'start_frame':48,'end_frame':96,'source_in_frame':120}]};self.record()
 def tearDown(self):self.tmp.cleanup()
 def record(self):
  self.file.write_text(json.dumps(self.report));result={**self.report,'report_file':str(self.file),'report_sha256':fingerprint(self.file)}
  with self.s.connect()as c:c.execute("UPDATE jobs SET status='completed',result=? WHERE id=?",(json.dumps(result),self.job))
 def test_picture_pieces_preserve_continuous_voice_and_old_empty_revision(self):
  p=apply(self.s,self.p['id'],self.job,self.p['active']);t=p['revision']['timeline'];self.assertEqual(len(t['tracks'][0]['clips']),2);voice=next(x for x in t['tracks']if x['kind']=='voice')['clips'];self.assertEqual(len(voice),1);self.assertEqual(voice[0]['asset_id'],self.a);self.assertEqual(voice[0]['source_in_frame'],0);self.assertEqual(voice[0]['source_out_frame'],96);self.assertEqual(self.s.revision(self.p['active'])['timeline']['duration_frames'],0)
 def test_uncertain_mapping_and_modified_report_cannot_apply(self):
  self.report['issues']=[{'reason':'uncertain'}];self.record()
  with self.assertRaises(Invalid):apply(self.s,self.p['id'],self.job,self.p['active'])
  self.report['issues']=[];self.record();self.file.write_text('{}')
  with self.assertRaises(Invalid):apply(self.s,self.p['id'],self.job,self.p['active'])
 def test_changed_intake_invalidates_mapping(self):
  save(self.s,{'project':self.p['id'],'expected_version':1,'voice_mode':'camera'})
  with self.assertRaises(Conflict):apply(self.s,self.p['id'],self.job,self.p['active'])
if __name__=='__main__':unittest.main()

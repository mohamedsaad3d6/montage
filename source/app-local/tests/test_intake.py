import sys,unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid,Conflict
from intake import get,save,start
from script_workspace import save as save_script,drafts,export
class IntakeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=Store(self.root/'data',[self.tmp.name]);self.p=self.s.create('test')
  self.video=self.asset('video.mp4','video',6);self.voice=self.asset('voice.wav','audio',8);self.script=self.asset('script.txt','script',0)
 def tearDown(self):self.tmp.cleanup()
 def asset(self,name,kind,duration):
  file=self.root/name;file.write_bytes(name.encode());return self.s.add_asset(self.p['id'],str(file),duration,kind)
 def test_roles_are_explicit_and_do_not_change_timeline(self):
  state=save(self.s,{'project':self.p['id'],'expected_version':0,'video':self.video,'voice':self.voice,'script':self.script})
  self.assertEqual(state['version'],1);self.assertEqual(self.s.project(self.p['id'])['active'],self.p['active'])
  with self.assertRaises(Conflict):save(self.s,{'project':self.p['id'],'expected_version':0,'video':self.video})
 def test_wrong_kind_cross_project_and_changed_source_blocked(self):
  with self.assertRaises(Invalid):save(self.s,{'project':self.p['id'],'expected_version':0,'video':self.voice})
  other=self.s.create('other')
  with self.assertRaises(Invalid):save(self.s,{'project':other['id'],'expected_version':0,'video':self.video})
  (self.root/'video.mp4').write_bytes(b'changed')
  with self.assertRaises(Invalid):save(self.s,{'project':self.p['id'],'expected_version':0,'video':self.video})
 def test_external_audio_binding_has_exact_coverage_and_no_review_approval(self):
  save(self.s,{'project':self.p['id'],'expected_version':0,'video':self.video,'voice':self.voice,'voice_mode':'external','audio_offset_frames':24})
  data={'project':self.p['id'],'input_version':1,'expected':self.p['active']}
  with patch('media.probe',return_value={'streams':[{'codec_type':'audio'}]}):
   with self.assertRaises(Invalid):start(self.s,data)
   with self.assertRaises(Invalid):start(self.s,{**data,'sync_confirmed':True})
   j=self.s.enqueue(self.p['id'],'input_prepare',{'input_version':1})
   proof={'sync_status':'measured_three_windows','input_version':1,'video_sha256':self.s.asset(self.video)['hash'],'voice_sha256':self.s.asset(self.voice)['hash'],'voice_id':self.voice,'offset_frames':24}
   with self.s.connect() as c:c.execute("UPDATE jobs SET status='completed',result=? WHERE id=?",(json.dumps(proof),j))
   p=start(self.s,{**data,'sync_job':j})
  voice=next(x for x in p['revision']['timeline']['tracks']if x['kind']=='voice')['clips'][0]
  self.assertEqual((voice['asset_id'],voice['source_in_frame'],voice['source_out_frame']),(self.voice,24,168));self.assertFalse(p['revision']['timeline']['intake']['independent_audio_review_passed'])
  with patch('media.probe',return_value={'streams':[{'codec_type':'audio'}]}):
   with self.assertRaises(Invalid):start(self.s,{**data,'expected':p['active'],'sync_confirmed':True})
 def test_short_audio_and_missing_camera_audio_fail_without_creating_revision(self):
  save(self.s,{'project':self.p['id'],'expected_version':0,'video':self.video,'voice':self.voice,'voice_mode':'external','audio_offset_frames':100})
  with patch('media.probe',return_value={'streams':[{'codec_type':'audio'}]}):
   with self.assertRaises(Invalid):start(self.s,{'project':self.p['id'],'expected':self.p['active'],'input_version':1,'sync_confirmed':True})
  save(self.s,{'project':self.p['id'],'expected_version':1,'voice_mode':'camera'})
  with patch('media.probe',return_value={'streams':[{'codec_type':'video'}]}):
   with self.assertRaises(Invalid):start(self.s,{'project':self.p['id'],'expected':self.p['active'],'input_version':2})
  self.assertEqual(self.s.project(self.p['id'])['active'],self.p['active'])
 def test_script_history_and_exports_preserve_literal_words_and_markup(self):
  text='عنوان ٢٠٢٦\nنص <أصلي> & بيانات\n'
  items=save_script(self.s,{'project':self.p['id'],'expected_version':0,'text':text})
  with self.assertRaises(Conflict):save_script(self.s,{'project':self.p['id'],'expected_version':0,'text':'stale'})
  b,_=export(self.s,self.p['id'],items[0]['id'],'txt');self.assertEqual(b.decode(),text)
  b,_=export(self.s,self.p['id'],items[0]['id'],'docx');file=self.root/'out.docx';file.write_bytes(b)
  from media import read_script
  result=read_script(str(file));self.assertIn('نص <أصلي> & بيانات',result)
  with self.assertRaises(Invalid):export(self.s,self.p['id'],items[0]['id'],'srt')
  other=self.s.create('other')
  with self.assertRaises(Invalid):export(self.s,other['id'],items[0]['id'],'txt')
  self.assertEqual(self.s.project(self.p['id'])['active'],self.p['active'])

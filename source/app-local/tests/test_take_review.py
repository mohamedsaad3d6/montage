import sys,tempfile,unittest,json,wave,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid,Conflict,uid,dump
from media import file_hash
from take_review import describe,save,audio,pending_count
class TakeReview(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=Store(self.root/'data',[self.root]);self.p=self.s.create('isolated takes');self.source=self.root/'source.mp4';self.source.write_bytes(b'raw fixture');self.a=self.s.add_asset(self.p['id'],str(self.source),4,'video')
  t=self.p['revision']['timeline'];t.update(phase='raw',duration_frames=96,primary_video_asset_id=self.a)
  for tr in t['tracks']:
   if tr['kind'] in ['video','voice']:tr['clips']=[{'id':uid(),'asset_id':self.a,'start_frame':0,'end_frame':96,'source_in_frame':0,'source_out_frame':96,'properties':{}}]
  self.p=self.s.save(self.p['id'],self.p['active'],t,'raw fixture');self.j=uid();folder=self.s.root/'jobs'/self.j;folder.mkdir(parents=True);self.wav=folder/'audio.wav'
  with wave.open(str(self.wav),'wb')as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(b'\0\0'*64000)
  self.plan=folder/'plan.json';self.plan.write_text(json.dumps({'retakes':[{'id':'r0','word_stream':'whisper','attempts':[{'start':0,'end':1,'text':'محاولة أولى مكتملة'},{'start':2,'end':3,'text':'محاولة ثانية'}]}]}))
  self.result={'plan_file':str(self.plan),'plan_sha256':file_hash(self.plan),'wave_file':str(self.wav),'wave_sha256':file_hash(self.wav),'source_asset_id':self.a,'source_asset_sha256':file_hash(self.source),'retake_candidates':1}
  with self.s.connect()as c:c.execute('INSERT INTO jobs(id,project,revision,kind,status,result,created) VALUES(?,?,?,?,?,?,?)',(self.j,self.p['id'],self.p['active'],'editorial_plan','completed',dump(self.result),1))
  self.d=describe(self.s,self.j);self.payload={'job':self.j,'project':self.p['id'],'candidate':self.d['candidates'][0]['key'],'plan_sha256':self.d['plan_sha256'],'audio_sha256':self.d['audio_sha256'],'expected_revision':self.p['active'],'expected_version':0,'choice':'keep_attempt','selected_attempt':0,'reason':'المحاولة الأولى أوضح وأكمل في هذه التجربة','listened_all':True}
 def tearDown(self):self.tmp.cleanup()
 def test_first_take_can_be_selected_without_cutting_or_review_approval(self):
  before=self.s.project(self.p['id'])['active'];r=save(self.s,self.payload);self.assertFalse(r['cuts_applied']);self.assertFalse(r['independent_review_granted']);self.assertEqual(self.s.project(self.p['id'])['active'],before);record=describe(self.s,self.j)['candidates'][0]['decision'];self.assertEqual(record['selected_attempt'],0);self.assertEqual(audio(self.s,self.j),self.wav)
 def test_listening_and_non_default_selection_required(self):
  d=copy.deepcopy(self.payload);d['listened_all']=False
  with self.assertRaises(Invalid):save(self.s,d)
  d['listened_all']=True;d['selected_attempt']=None
  with self.assertRaises(Invalid):save(self.s,d)
  d.update(choice='needs_review',selected_attempt=None,listened_all=False);save(self.s,d);self.assertEqual(describe(self.s,self.j)['candidates'][0]['decision']['choice'],'needs_review')
 def test_versions_are_immutable_and_wrong_project_rejected(self):
  save(self.s,self.payload)
  with self.assertRaises(Conflict):save(self.s,self.payload)
  d=copy.deepcopy(self.payload);d.update(expected_version=1,choice='intentional_repeat',selected_attempt=None,reason='التكرار مقصود للتوكيد؛ لا حذف');save(self.s,d);self.assertEqual(describe(self.s,self.j)['candidates'][0]['history_count'],2)
  d['project']=self.s.create('other')['id']
  with self.assertRaises(Invalid):save(self.s,d)
 def test_stale_revision_or_content_fingerprints_are_rejected(self):
  d=copy.deepcopy(self.payload);d['audio_sha256']='bad'
  with self.assertRaises(Conflict):save(self.s,d)
  self.s.save(self.p['id'],self.p['active'],self.p['revision']['timeline'],'new revision')
  self.assertFalse(describe(self.s,self.j)['current_revision'])
  with self.assertRaises(Conflict):save(self.s,self.payload)
 def test_plan_wave_and_raw_tamper_are_rejected(self):
  original=self.plan.read_bytes();self.plan.write_bytes(b'changed')
  with self.assertRaises(Invalid):describe(self.s,self.j)
  self.plan.write_bytes(original);original=self.wav.read_bytes();self.wav.write_bytes(b'changed')
  with self.assertRaises(Invalid):audio(self.s,self.j)
  self.wav.write_bytes(original);self.source.write_bytes(b'changed')
  with self.assertRaises(Invalid):save(self.s,self.payload)

 def test_pending_navigation_hint_never_grants_approval(self):
  with self.s.connect()as c:job=self.s.one(c,'SELECT * FROM jobs WHERE id=?',(self.j,))
  self.assertEqual(pending_count(self.s,job),1);save(self.s,self.payload);self.assertEqual(pending_count(self.s,job),0);self.assertFalse(describe(self.s,self.j)['independent_review_granted'])
 def test_progress_routes_unresolved_takes_to_audition_without_opening_gate(self):
  from production import status
  p=self.s.project(self.p['id']);self.assertEqual(status(p,self.s)['next_action']['kind'],'takes');save(self.s,self.payload);after=status(self.s.project(self.p['id']),self.s);self.assertEqual(after['next_action']['kind'],'boundaries');self.assertFalse(after['ready_for_montage']);self.assertFalse(after['publication_approved'])

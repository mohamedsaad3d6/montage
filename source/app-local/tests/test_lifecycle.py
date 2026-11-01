import sys,tempfile,unittest,json,time,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid,Conflict,uid
from lifecycle import change,describe,usable
from library_registry import catalogue,reuse
class Lifecycle(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=Store(self.root/'data',[self.root]);self.p=self.s.create('source');self.file=self.root/'raw.mp4';self.file.write_bytes(b'original raw');self.a=self.s.add_asset(self.p['id'],str(self.file),4,'video');t=self.p['revision']['timeline'];t.update(phase='raw',duration_frames=96,primary_video_asset_id=self.a)
  for tr in t['tracks']:
   if tr['kind'] in ['video','voice']:tr['clips']=[{'id':uid(),'asset_id':self.a,'start_frame':0,'end_frame':96,'source_in_frame':0,'source_out_frame':96,'properties':{}}]
  self.p=self.s.save(self.p['id'],self.p['active'],t,'fixture');self.other=self.s.create('other')
 def tearDown(self):self.tmp.cleanup()
 def trash_project(self,version=0):return change(self.s,{'entity':'project','id':self.p['id'],'expected_version':version})
 def test_project_removal_cancels_only_its_jobs_and_restore_keeps_history(self):
  job=self.s.enqueue(self.p['id']);other=self.s.enqueue(self.other['id']);r=self.trash_project();self.assertEqual(r['cancelled_jobs'],[job]);self.assertNotIn(self.p['id'],[p['id']for p in self.s.projects()]);self.assertTrue(self.s.project(self.p['id'])['lifecycle']['deleted']);self.assertEqual(self.file.read_bytes(),b'original raw')
  with self.s.connect()as c:self.assertEqual(self.s.one(c,'SELECT status FROM jobs WHERE id=?',(other,))['status'],'queued')
  with self.assertRaises(Invalid):self.s.enqueue(self.p['id'])
  with self.assertRaises(Invalid):self.s.add_asset(self.p['id'],str(self.file),4,'video')
  with self.assertRaises(Invalid):self.s.save(self.p['id'],self.p['active'],self.p['revision']['timeline'])
  change(self.s,{'entity':'project','id':self.p['id'],'expected_version':1},True);p=self.s.project(self.p['id']);self.assertEqual(p['active'],self.p['active']);self.assertEqual(p['lifecycle']['version'],2)
  with self.s.connect()as c:self.assertEqual(self.s.one(c,'SELECT status FROM jobs WHERE id=?',(job,))['status'],'cancelled');self.assertEqual(c.execute('SELECT COUNT(*) FROM control_trash_events').fetchone()[0],2)
 def test_used_asset_removal_hides_it_and_blocks_processing_until_restored(self):
  job=self.s.enqueue(self.p['id']);r=change(self.s,{'entity':'asset','id':self.a,'project':self.p['id'],'expected_version':0});p=self.s.project(self.p['id']);self.assertEqual(r['cancelled_jobs'],[job]);self.assertEqual(p['active'],self.p['active']);self.assertEqual(p['assets'],[]);self.assertEqual(p['unavailable_assets'][0]['id'],self.a)
  with self.assertRaises(Invalid):self.s.enqueue(self.p['id'],'render')
  with self.assertRaises(Invalid):self.s.activate(self.p['id'],self.p['active'])
  change(self.s,{'entity':'asset','id':self.a,'project':self.p['id'],'expected_version':1},True);usable(self.s,self.p['id']);self.assertEqual(self.s.project(self.p['id'])['assets'][0]['lifecycle_version'],2)
 def test_unused_asset_removal_targets_only_dependent_jobs_and_clears_input_role(self):
  from intake import save,get
  script=self.root/'script.txt';script.write_text('test');a=self.s.add_asset(self.p['id'],str(script),0,'script');save(self.s,{'project':self.p['id'],'expected_version':0,'script':a});j=self.s.enqueue(self.p['id'],'inspect_asset',{'asset_id':a});other=self.s.enqueue(self.p['id'],'asset_integrity')
  r=change(self.s,{'entity':'asset','id':a,'project':self.p['id'],'expected_version':0});self.assertEqual(r['cancelled_jobs'],[j]);self.assertFalse(self.s.project(self.p['id'])['unavailable_assets']);self.assertIsNone(get(self.s,self.p['id'])['selection']['script']);self.assertEqual(get(self.s,self.p['id'])['version'],2)
  with self.s.connect()as c:self.assertEqual(self.s.one(c,'SELECT status FROM jobs WHERE id=?',(other,))['status'],'queued')
 def test_stale_wrong_project_and_evidence_removal_are_rejected(self):
  with self.assertRaises(Invalid):change(self.s,{'entity':'asset','id':self.a,'project':self.other['id'],'expected_version':0})
  self.trash_project()
  with self.assertRaises(Conflict):change(self.s,{'entity':'project','id':self.p['id'],'expected_version':0},True)
  change(self.s,{'entity':'project','id':self.p['id'],'expected_version':1},True)
  with self.s.connect()as c:c.execute("UPDATE assets SET source_type='review_evidence' WHERE id=?",(self.a,))
  with self.assertRaises(Invalid):change(self.s,{'entity':'asset','id':self.a,'project':self.p['id'],'expected_version':0})
 def test_shared_copy_and_physical_file_survive_source_project_removal(self):
  clone=reuse(self.s,self.other['id'],self.a)['asset_id'];self.trash_project();self.assertEqual([a['id']for a in catalogue(self.s)['items']],[clone]);self.assertEqual(self.s.asset(clone)['path'],str(self.file.resolve()));self.assertEqual(self.file.read_bytes(),b'original raw');self.assertFalse(describe(self.s)['raw_files_deleted']);self.assertNotIn('path',describe(self.s)['items'][0])
 def test_running_worker_does_not_resurrect_cancelled_project_job(self):
  from worker import execute
  j=self.s.enqueue(self.p['id']);thread=threading.Thread(target=execute,args=(self.s,j,.3));thread.start()
  for _ in range(100):
   with self.s.connect()as c:status=self.s.one(c,'SELECT status FROM jobs WHERE id=?',(j,))['status']
   if status=='running':break
   time.sleep(.01)
  self.trash_project();thread.join(4);self.assertFalse(thread.is_alive())
  with self.s.connect()as c:self.assertEqual(self.s.one(c,'SELECT status FROM jobs WHERE id=?',(j,))['status'],'cancelled')

 def test_trashed_asset_cannot_be_selected_again_as_input(self):
  from intake import save,get
  change(self.s,{'entity':'asset','id':self.a,'project':self.p['id'],'expected_version':0})
  with self.assertRaises(Invalid):save(self.s,{'project':self.p['id'],'expected_version':get(self.s,self.p['id'])['version'],'video':self.a})
 def test_undo_cannot_activate_a_revision_using_trashed_media(self):
  from timeline_ops import apply
  original=self.p['active'];t=json.loads(json.dumps(self.p['revision']['timeline']));t.pop('primary_video_asset_id',None)
  for tr in t['tracks']:tr['clips']=[]
  p=self.s.save(self.p['id'],original,t,'remove references in isolated test');change(self.s,{'entity':'asset','id':self.a,'project':p['id'],'expected_version':0})
  with self.assertRaises(Invalid):apply(self.s,p['id'],p['active'],{'type':'undo'})
  self.assertEqual(self.s.project(p['id'])['active'],p['active'])

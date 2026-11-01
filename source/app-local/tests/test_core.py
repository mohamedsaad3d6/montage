import sys,unittest,tempfile,json,copy,time,subprocess,os,signal,threading,urllib.request,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid,Conflict
from worker import execute
from server import App,Handler,ThreadingHTTPServer
class Registry(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name);self.s=Store(self.p/'data',[self.p]);self.project=self.s.create('حلقة اختبار');self.raw=self.p/'raw.mp4';self.raw.write_bytes(b'x'*1024);self.a=self.s.add_asset(self.project['id'],str(self.raw),10,'video')
  self.t=copy.deepcopy(self.project['revision']['timeline']);self.t['duration_frames']=240;self.t['tracks'][0]['clips']=[{'id':'c','asset_id':self.a,'start_frame':0,'end_frame':240,'source_in_frame':0,'source_out_frame':240,'properties':{}}]
 def tearDown(self):
  # A persisted completed row can precede child exit and dispatcher bookkeeping.
  # Do not remove the fixture database while that owner is still draining.
  app=getattr(self,'app',None)
  thread=app.dispatcher.thread if app else None
  if thread:
   thread.join(timeout=10)
   self.assertFalse(thread.is_alive(),'dispatcher did not finish before fixture cleanup')
  self.tmp.cleanup()
 def test_snapshot_conflict_restore(self):
  old=self.project['active'];v=self.s.save(self.project['id'],old,self.t);self.assertEqual(self.s.revision(old)['timeline']['duration_frames'],0)
  with self.assertRaises(Conflict):self.s.save(v['id'],old,self.t)
  self.s.activate(v['id'],old);reopen=Store(self.p/'data',[self.p]);self.assertEqual(reopen.project(v['id'])['active'],old);self.assertEqual(len(reopen.project(v['id'])['revisions']),2)
 def test_foreign_asset_and_bounds(self):
  other=self.s.create('آخر')
  with self.assertRaises(Invalid):self.s.save(other['id'],other['active'],self.t)
  bad=copy.deepcopy(self.t);bad['tracks'][0]['clips'][0]['source_out_frame']=300
  with self.assertRaises(Invalid):self.s.save(self.project['id'],self.project['active'],bad)
  bad=copy.deepcopy(self.t);bad['tracks'][0]['clips'][0]['start_frame']=-1
  with self.assertRaises(Invalid):self.s.validate(self.project['id'],bad)
 def test_path_allowlist(self):
  link=self.p/'escape.mp4';link.symlink_to('/etc/passwd')
  with self.assertRaises(Invalid):self.s.resolve(link)
 def test_feedback_scoped_to_revision(self):
  v=self.s.save(self.project['id'],self.project['active'],self.t);self.s.feedback(v['id'],v['active'],1200,'cards','الكارت سريع');f=self.s.project(v['id'])['feedback'][0];self.assertEqual(f['revision'],v['active']);self.assertEqual(f['status'],'recorded_not_learned')
  with self.assertRaises(Invalid):self.s.feedback(v['id'],v['active'],12000,'cards','خارج المدة')
 def test_changed_file_blocks_job(self):
  v=self.s.save(self.project['id'],self.project['active'],self.t);j=self.s.enqueue(v['id']);self.raw.write_bytes(b'changed');execute(self.s,j);self.assertEqual(self.s.project(v['id'])['jobs'][0]['status'],'failed')
 def test_worker_survives_caller_and_restart(self):
  v=self.s.save(self.project['id'],self.project['active'],self.t);j=self.s.enqueue(v['id']);app=App(self.p/'data',[self.p],1);self.app=app;app.start(j)
  for _ in range(100):
   x=Store(self.p/'data',[self.p]).project(v['id'])['jobs'][0]
   if x['status']=='completed':break
   time.sleep(.03)
  self.assertEqual(x['status'],'completed');self.assertEqual(x['checkpoint'],1)
 def test_cancel_and_recover_dead_worker(self):
  v=self.s.save(self.project['id'],self.project['active'],self.t);j=self.s.enqueue(v['id'])
  with self.s.connect() as c:c.execute("UPDATE jobs SET status='running',worker_pid=2147483646 WHERE id=?",(j,))
  app=App(self.p/'data',[self.p],1);self.app=app;app.recover()
  for _ in range(100):
   x=self.s.project(v['id'])['jobs'][0]
   if x['status']=='completed':break
   time.sleep(.03)
  self.assertEqual(x['status'],'completed');j2=self.s.enqueue(v['id'])
  with self.s.connect() as c:c.execute("UPDATE jobs SET status='cancelled' WHERE id=?",(j2,))
  execute(self.s,j2)
  self.assertEqual(self.s.project(v['id'])['jobs'][0]['status'],'cancelled')
class HTTP(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.port=self.http.server_port;self.app=App(self.root/'data',[self.root],self.port);self.http.app=self.app;self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start();self.url=f'http://127.0.0.1:{self.port}'
 def tearDown(self):self.http.shutdown();self.http.server_close();self.thread.join();self.tmp.cleanup()
 def test_csrf_and_range(self):
  boot=json.load(urllib.request.urlopen(self.url+'/api/bootstrap'));req=urllib.request.Request(self.url+'/api/projects',data=json.dumps({'name':'مشروع'}).encode(),headers={'Content-Type':'application/json'})
  with self.assertRaises(urllib.error.HTTPError) as err:urllib.request.urlopen(req)
  self.assertEqual(err.exception.code,403);req.add_header('Origin',self.url);req.add_header('X-Montaj-Token',boot['token']);v=json.load(urllib.request.urlopen(req));p=self.root/'tiny.mp4';p.write_bytes(b'1234567890');a=self.app.store.add_asset(v['id'],str(p),1,'video');r=urllib.request.urlopen(urllib.request.Request(self.url+'/media/'+a,headers={'Range':'bytes=2-5'}));self.assertEqual(r.status,206);self.assertEqual(r.read(),b'3456')
  with self.assertRaises(urllib.error.HTTPError) as er:urllib.request.urlopen(urllib.request.Request(self.url+'/media/'+a,headers={'Range':'bytes=20-30'}))
  self.assertEqual(er.exception.code,416)
 def test_cross_site_blocked(self):
  with self.assertRaises(urllib.error.HTTPError) as er:urllib.request.urlopen(urllib.request.Request(self.url+'/api/bootstrap',headers={'Sec-Fetch-Site':'cross-site'}))
  self.assertEqual(er.exception.code,403)

class ReleaseGateHTTP(unittest.TestCase):
 setUp=HTTP.setUp
 tearDown=HTTP.tearDown
 def test_unreviewed_full_candidate_is_not_exposed(self):
  v=self.app.store.create('ملف كامل غير مراجع');j=self.app.store.enqueue(v['id'],'render');p=self.root/'candidate.mp4';p.write_bytes(b'internal-only')
  with self.app.store.connect() as c:c.execute("UPDATE jobs SET status='completed',result=? WHERE id=?",(json.dumps({'file':str(p),'duration':31,'file_sha256':'unreviewed'}),j))
  with self.assertRaises(urllib.error.HTTPError) as er:urllib.request.urlopen(self.url+'/output/'+j)
  self.assertEqual(er.exception.code,403)

if __name__=='__main__':unittest.main(verbosity=2)

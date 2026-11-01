import sys,json,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_lifecycle as fixture
from server import Handler,ThreadingHTTPServer
class LifecycleHTTP(unittest.TestCase):
 def setUp(self):
  self.f=fixture.Lifecycle();self.f.setUp();self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.port=self.http.server_port;self.http.app=SimpleNamespace(store=self.f.s,token='test-token',port=self.port);self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start();self.url=f'http://127.0.0.1:{self.port}'
 def tearDown(self):self.http.shutdown();self.http.server_close();self.thread.join();self.f.tearDown()
 def request(self,path,data=None,token='test-token'):
  headers={'Origin':self.url,'X-Montaj-Token':token,'Content-Type':'application/json'}
  return urllib.request.urlopen(urllib.request.Request(self.url+path,None if data is None else json.dumps(data).encode(),headers=headers))
 def test_project_hidden_and_restored_without_changing_revision(self):
  p=self.f.p;payload={'entity':'project','id':p['id'],'expected_version':0}
  self.request('/api/trash/put',payload).read();boot=json.load(self.request('/api/bootstrap'));self.assertNotIn(p['id'],[x['id']for x in boot['projects']]);self.assertEqual(len(json.load(self.request('/api/trash'))['items']),1)
  self.request('/api/trash/restore',{**payload,'expected_version':1}).read();self.assertEqual(self.f.s.project(p['id'])['active'],p['active']);self.assertEqual(json.load(self.request('/api/trash'))['items'],[])
 def test_asset_media_blocked_until_restore_and_token_required(self):
  payload={'entity':'asset','id':self.f.a,'project':self.f.p['id'],'expected_version':0}
  with self.assertRaises(urllib.error.HTTPError)as error:self.request('/api/trash/put',payload,token='')
  self.assertEqual(error.exception.code,403);self.request('/api/trash/put',payload).read()
  with self.assertRaises(urllib.error.HTTPError)as error:self.request('/media/'+self.f.a)
  self.assertEqual(error.exception.code,400)
  self.request('/api/trash/restore',{**payload,'expected_version':1}).read();self.assertEqual(self.request('/media/'+self.f.a).read(),b'original raw')

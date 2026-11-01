import sys,json,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_take_repair as fixture
from server import Handler,ThreadingHTTPServer
class TakeRepairHTTP(unittest.TestCase):
 def setUp(self):
  self.f=fixture.TakeRepair();self.f.setUp();self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.port=self.http.server_port;self.http.app=SimpleNamespace(store=self.f.f.s,token='test-token',port=self.port);self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start();self.url=f'http://127.0.0.1:{self.port}'
 def tearDown(self):self.http.shutdown();self.http.server_close();self.thread.join();self.f.tearDown()
 def request(self,path,data=None,token='test-token',extra=None):
  return urllib.request.urlopen(urllib.request.Request(self.url+path,None if data is None else json.dumps(data).encode(),headers={'Origin':self.url,'X-Montaj-Token':token,'Content-Type':'application/json',**(extra or {})}))
 def test_preview_range_and_assertions_are_guarded(self):
  with self.assertRaises(urllib.error.HTTPError)as error:self.request('/api/take-repair/preview',self.f.request,token='')
  self.assertEqual(error.exception.code,403);r=json.load(self.request('/api/take-repair/preview',self.f.request));job=self.f.f.j;response=self.request('/take-repair-audio/'+job+'/'+r['id']+'/0',extra={'Range':'bytes=0-15'});self.assertEqual(response.status,206);self.assertEqual(response.read()[:4],b'RIFF')
  data=self.f.approve(r);data['listened_all_joins']=False
  with self.assertRaises(urllib.error.HTTPError)as error:self.request('/api/take-repair/apply',data)
  self.assertEqual(error.exception.code,400)
 def test_synthetic_http_apply_creates_new_version_and_keeps_final_review_blocked(self):
  r=json.load(self.request('/api/take-repair/preview',self.f.request));p=json.load(self.request('/api/take-repair/apply',self.f.approve(r)));self.assertNotEqual(p['active'],self.f.f.p['active']);self.assertTrue(p['revision']['timeline']['requires_new_independent_audio_review'])
  status=json.load(self.request('/api/production?id='+p['id']));self.assertFalse(status['ready_for_montage']);self.assertFalse(status['publication_approved'])

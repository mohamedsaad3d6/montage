import sys,json,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_take_review as fixtures
from server import Handler,ThreadingHTTPServer
class TakeReviewHTTP(unittest.TestCase):
 def setUp(self):
  self.fixture=fixtures.TakeReview();self.fixture.setUp();self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.port=self.http.server_port;self.http.app=SimpleNamespace(store=self.fixture.s,token='isolated-test-token',port=self.port);self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start();self.url=f'http://127.0.0.1:{self.port}'
 def tearDown(self):self.http.shutdown();self.http.server_close();self.thread.join();self.fixture.tearDown()
 def test_bound_audio_supports_range_and_record_round_trip(self):
  job=self.fixture.j;data=json.load(urllib.request.urlopen(self.url+'/api/take-review?job='+job));self.assertEqual(len(data['candidates']),1)
  r=urllib.request.urlopen(urllib.request.Request(self.url+'/take-audio/'+job,headers={'Range':'bytes=0-15'}));self.assertEqual(r.status,206);self.assertEqual(r.read(),self.fixture.wav.read_bytes()[:16])
  payload={**self.fixture.payload,'choice':'needs_review','selected_attempt':None,'listened_all':False};req=urllib.request.Request(self.url+'/api/take-review/save',json.dumps(payload).encode(),headers={'Content-Type':'application/json','Origin':self.url,'X-Montaj-Token':'isolated-test-token'});self.assertFalse(json.load(urllib.request.urlopen(req))['cuts_applied']);saved=json.load(urllib.request.urlopen(self.url+'/api/take-review?job='+job));self.assertEqual(saved['candidates'][0]['decision']['version'],1)
 def test_mutation_without_token_and_cross_site_audio_are_rejected(self):
  req=urllib.request.Request(self.url+'/api/take-review/save',json.dumps(self.fixture.payload).encode(),headers={'Content-Type':'application/json','Origin':self.url})
  with self.assertRaises(urllib.error.HTTPError)as error:urllib.request.urlopen(req)
  self.assertEqual(error.exception.code,403)
  req=urllib.request.Request(self.url+'/take-audio/'+self.fixture.j,headers={'Sec-Fetch-Site':'cross-site'})
  with self.assertRaises(urllib.error.HTTPError)as error:urllib.request.urlopen(req)
  self.assertEqual(error.exception.code,403)

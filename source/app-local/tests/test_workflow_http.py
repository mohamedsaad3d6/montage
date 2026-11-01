import sys,json,threading,unittest,urllib.request,urllib.error
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_lifecycle as fixture
from server import Handler,ThreadingHTTPServer
class WorkflowHTTP(unittest.TestCase):
 def setUp(self):
  self.f=fixture.Lifecycle();self.f.setUp();self.sent=[];self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.port=self.http.server_port;self.http.app=SimpleNamespace(store=self.f.s,token='test-token',port=self.port,start=self.sent.append);self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start();self.url=f'http://127.0.0.1:{self.port}'
 def tearDown(self):self.http.shutdown();self.http.server_close();self.thread.join();self.f.tearDown()
 def request(self,path,data=None,token='test-token'):
  return json.load(urllib.request.urlopen(urllib.request.Request(self.url+path,None if data is None else json.dumps(data).encode(),headers={'Origin':self.url,'X-Montaj-Token':token,'Content-Type':'application/json'})))
 def test_one_continue_dispatch_pause_and_resume_with_same_active_revision(self):
  p=self.f.p;first=self.request('/api/workflow/continue',{'project':p['id']});self.assertEqual(len(self.sent),1);paused=self.request('/api/workflow/pause',{'project':p['id']});self.assertEqual(paused['state'],'paused');self.assertEqual(paused['cancelled_jobs'],[first['new_job']]);self.request('/api/workflow/continue',{'project':p['id']});self.assertEqual(len(self.sent),2);state=self.request('/api/workflow?project='+p['id']);self.assertEqual(state['revision'],p['active']);self.assertFalse(state['automatic_publication']);self.assertEqual(self.f.file.read_bytes(),b'original raw')
 def test_missing_mutation_token_cannot_start_or_stop_a_workflow(self):
  with self.assertRaises(urllib.error.HTTPError)as error:self.request('/api/workflow/continue',{'project':self.f.p['id']},token='')
  self.assertEqual(error.exception.code,403);self.assertFalse(self.sent)
 def test_start_button_endpoint_dispatches_preparation_and_duplicate_click_adopts_it(self):
  from intake import save
  p=self.f.other;a=self.f.s.add_asset(p['id'],str(self.f.file),4,'video');save(self.f.s,{'project':p['id'],'expected_version':0,'video':a})
  data={'project':p['id'],'expected':p['active'],'input_version':1};first=self.request('/api/intake/begin',data);self.assertEqual(self.sent,[first['new_job']]);self.assertEqual(self.f.s.project(p['id'])['jobs'][0]['kind'],'input_prepare');second=self.request('/api/intake/begin',data);self.assertIsNone(second['new_job']);self.assertEqual(len(self.sent),1)
 def test_service_connection_routes_keep_credit_test_explicit(self):
  from unittest.mock import patch
  data=self.request('/api/service-links');self.assertFalse(data['keys_in_response'])
  with self.assertRaises(urllib.error.HTTPError)as error:self.request('/api/service-links/check',{'provider':'magnific'})
  self.assertEqual(error.exception.code,400)
  with patch('service_links.private_json',return_value={'api_key':'fixture-key'}),patch('service_links.get_json',return_value={'status_code':200,'data':{'credits':1}}):result=self.request('/api/service-links/check',{'provider':'auphonic'})
  self.assertTrue(result['ok']);self.assertFalse(result['processing_started']);self.assertEqual(self.sent,[])

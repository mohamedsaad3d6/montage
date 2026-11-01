import sys,unittest,tempfile,threading,json,urllib.request,urllib.error,zipfile,io
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import App,Handler,ThreadingHTTPServer
class IntakeHTTP(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.http=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.port=self.http.server_port;self.app=App(self.root/'data',[self.root],self.port);self.http.app=self.app;self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start();self.url=f'http://127.0.0.1:{self.port}';self.p=self.app.store.create('test')
 def tearDown(self):self.http.shutdown();self.http.server_close();self.thread.join();self.tmp.cleanup()
 def post(self,path,data):
  req=urllib.request.Request(self.url+path,json.dumps(data).encode(),headers={'Content-Type':'application/json','Origin':self.url,'X-Montaj-Token':self.app.token});return json.load(urllib.request.urlopen(req))
 def test_script_save_and_attachment_exports_are_real_and_versioned(self):
  data={'project':self.p['id'],'expected_version':0,'text':'اختبار ٢٠٢٦\nبلا تغيير للنص <>&'};items=self.post('/api/script-drafts/save',data);id=items[0]['id']
  for format in ['txt','docx']:
   r=urllib.request.urlopen(self.url+'/script-export?project='+self.p['id']+'&id='+id+'&format='+format);self.assertIn('attachment;',r.headers['Content-Disposition']);blob=r.read()
   if format=='txt':self.assertEqual(blob.decode(),data['text'])
   else:self.assertIn('word/document.xml',zipfile.ZipFile(io.BytesIO(blob)).namelist())
  with self.assertRaises(urllib.error.HTTPError)as e:self.post('/api/script-drafts/save',data)
  self.assertEqual(e.exception.code,409)
 def test_intake_saves_do_not_touch_revision_and_reject_stale_versions(self):
  p=self.root/'text.txt';p.write_text('test');id=self.app.store.add_asset(self.p['id'],str(p),0,'script');data={'project':self.p['id'],'expected_version':0,'script':id};saved=self.post('/api/intake/save',data);self.assertEqual(saved['selection']['script'],id);self.assertEqual(self.app.store.project(self.p['id'])['active'],self.p['active'])
  with self.assertRaises(urllib.error.HTTPError)as e:self.post('/api/intake/save',data)
  self.assertEqual(e.exception.code,409)
 def test_script_export_still_rejects_cross_site_requests(self):
  req=urllib.request.Request(self.url+'/api/script-drafts?project='+self.p['id'],headers={'Sec-Fetch-Site':'cross-site'})
  with self.assertRaises(urllib.error.HTTPError)as e:urllib.request.urlopen(req)
  self.assertEqual(e.exception.code,403)
 def test_existing_video_import_probes_streams_not_only_container_duration(self):
  from unittest.mock import patch
  p=self.root/'video.mp4';p.write_bytes(b'test stub; probing mocked only in this regression')
  with patch('media.probe',return_value={'format':{'duration':'4'},'streams':[{'codec_type':'video','duration':'4'},{'codec_type':'audio','duration':'4'}]})as probe:
   result=self.post('/api/assets',{'project':self.p['id'],'path':str(p),'kind':'video'});probe.assert_called_once_with(p.resolve())
  self.assertEqual(result['project']['assets'][0]['duration'],4)

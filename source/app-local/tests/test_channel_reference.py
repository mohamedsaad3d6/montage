import sys,tempfile,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid,Conflict
from workspace import save_channel,channels
import channel_reference as r
from channel_kit import get,save

URL='https://www.youtube.com/@reference'
CID='UC'+'a'*22
VID='abcdefghijk'
def raw():
 data={'metadata':{'channelMetadataRenderer':{'title':'قناة مثبتة','externalId':CID,'description':'وصف من المرجع','avatar':{'thumbnails':[{'url':'https://yt3.googleusercontent.com/avatar'}]}}},'contents':{'videoRenderer':{'videoId':VID,'title':{'runs':[{'text':'حلقة مرجعية'}]}}}}
 return ('var ytInitialData = '+json.dumps(data)+';').encode()
class ReferenceTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=Store(Path(self.tmp.name)/'data',[self.tmp.name]);self.p=self.s.create('preserve');self.c=save_channel(self.s,{'name':'اسم قديم','reviewer':'محمد'});self.active=self.p['active']
 def tearDown(self):self.tmp.cleanup()
 def loader(self,url,**kw):return b'\x89PNG\r\n\x1a\nfixture' if kw.get('image') else raw()
 def run_ref(self,consent=False,observer=None):
  run=r.start(self.s,self.c['id'],URL,consent);r.process(self.s,self.c['id'],run,self.loader,observer);return r.status(self.s,self.c['id'])
 def test_identity_preview_does_not_mutate_channel_and_apply_is_atomic_once(self):
  st=self.run_ref();self.assertEqual(st['state'],'identity_ready');self.assertEqual(channels(self.s)[0]['name'],'اسم قديم');self.assertTrue(r.logo(self.s,self.c['id'],st['run']).suffix=='.png')
  r.apply(self.s,self.c['id'],st['run']);self.assertEqual(channels(self.s)[0]['name'],'قناة مثبتة');self.assertEqual(channels(self.s)[0]['reviewer'],'محمد');self.assertEqual(get(self.s,self.c['id'])['data']['handle'],'@reference');self.assertEqual(self.s.project(self.p['id'])['active'],self.active)
  with self.assertRaises(Invalid):r.apply(self.s,self.c['id'],st['run'])
 def test_no_video_request_without_explicit_consent_and_partial_failure_is_honest(self):
  def fail(v):raise AssertionError('must not call')
  self.run_ref(observer=fail)
  def unavailable(v):raise Invalid('Google HTTP 503')
  st=self.run_ref(True,unavailable);self.assertEqual(st['state'],'identity_ready');self.assertNotIn('style',st['data']);self.assertIn('503',st['error'])
 def test_observations_are_grounded_to_sample_and_not_approved_rules(self):
  videos=[{'id':VID}];good={'observations':[{'category':'editing','text':'وصف مرصود','video_id':VID,'start':1,'end':4,'confidence':'medium'}]}
  style=r.validate_style(good,videos);self.assertFalse(style['independently_verified']);good['observations'][0]['end']=70
  with self.assertRaises(Invalid):r.validate_style(good,videos)
  good['observations'][0]['end']=4;good['observations'][0]['video_id']='wrong'
  with self.assertRaises(Invalid):r.validate_style(good,videos)
 def test_stale_versions_block_partial_apply(self):
  st=self.run_ref();save_channel(self.s,dict(self.c,expected_version=1,name='تعديل المستخدم'))
  with self.assertRaises(Conflict):r.apply(self.s,self.c['id'],st['run'])
  self.assertEqual(get(self.s,self.c['id'])['version'],0)
 def test_reentry_and_recovery_and_history(self):
  run=r.start(self.s,self.c['id'],URL)
  with self.assertRaises(Conflict):r.start(self.s,self.c['id'],URL)
  r.recover(self.s);self.assertEqual(r.status(self.s,self.c['id'])['state'],'interrupted');r.start(self.s,self.c['id'],URL)
  with self.s.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM control_channel_reference_history').fetchone()[0],1)
 def test_invalid_urls_and_logo_changes_are_rejected(self):
  for url in ['http://www.youtube.com/@a','https://127.0.0.1/@a','https://www.youtube.com.evil/@a','https://www.youtube.com:443/@a','https://www.youtube.com/watch?v='+VID]:
   with self.assertRaises(Invalid):r.normalize(url)
  st=self.run_ref();p=r.logo(self.s,self.c['id'],st['run']);p.write_bytes(b'changed')
  with self.assertRaises(Invalid):r.logo(self.s,self.c['id'],st['run'])
 def test_failed_metadata_is_not_fabricated(self):
  run=r.start(self.s,self.c['id'],URL);r.process(self.s,self.c['id'],run,lambda *a,**k:b'blocked')
  self.assertEqual(r.status(self.s,self.c['id'])['state'],'failed');self.assertEqual(channels(self.s)[0]['name'],'اسم قديم')

 def test_current_youtube_lockup_renderer_is_supported_without_playlist_or_ad(self):
  body=json.loads(raw().decode().split(' = ',1)[1][:-1]);body['contents']={'lockupViewModel':{'contentId':VID,'contentType':'LOCKUP_CONTENT_TYPE_VIDEO','metadata':{'lockupMetadataViewModel':{'title':{'content':'فيديو عام'}}}}}
  meta=r.parse(('var ytInitialData = '+json.dumps(body)+';').encode(),URL);self.assertEqual(meta['videos'][0]['id'],VID)
 def test_kit_conflict_preserves_identity_and_old_kit(self):
  st=self.run_ref();kit=get(self.s,self.c['id']);save(self.s,{'channel':self.c['id'],'expected_version':0,'data':kit['data']})
  with self.assertRaises(Conflict):r.apply(self.s,self.c['id'],st['run'])
  self.assertEqual(channels(self.s)[0]['name'],'اسم قديم');self.assertEqual(get(self.s,self.c['id'])['version'],1)
 def test_empty_style_response_never_claims_ready(self):
  with self.assertRaises(Invalid):r.validate_style({'observations':None},[{'id':VID}])

 def test_approved_reference_survives_failed_new_analysis_and_is_exposed_in_kit(self):
  st=self.run_ref();r.apply(self.s,self.c['id'],st['run']);r.start(self.s,self.c['id'],URL)
  self.assertEqual(get(self.s,self.c['id'])['reference']['run'],st['run']);self.assertTrue(r.logo(self.s,self.c['id'],st['run']).is_file())
 def test_video_transport_uses_bounded_generate_content_and_ignores_thought_parts(self):
  import io
  from unittest.mock import patch
  sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'engine'))
  good={'observations':[{'category':'editing','text':'وصف العينة','video_id':VID,'start':0,'end':3,'confidence':'medium'}]}
  payload={'candidates':[{'finishReason':'STOP','content':{'parts':[{'thought':True,'text':'not response JSON'},{'text':json.dumps(good)}]}}]}
  with patch('monteer.audio_review.pipeline.credentials',return_value='fixture-only'),patch('channel_reference.urllib.request.urlopen',return_value=io.BytesIO(json.dumps(payload).encode())) as call:
   style=r.observe([{'id':VID,'url':'https://www.youtube.com/watch?v='+VID}]);request=call.call_args[0][0];body=json.loads(request.data)
  self.assertEqual(style['observations'][0]['text'],'وصف العينة');self.assertTrue(request.full_url.endswith(':generateContent'));self.assertEqual(body['contents'][0]['parts'][1]['videoMetadata']['endOffset'],'60s')
 def test_video_timeout_is_explicit_and_has_no_retry(self):
  from unittest.mock import patch
  import socket
  sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'engine'))
  with patch('monteer.audio_review.pipeline.credentials',return_value='fixture-only'),patch('channel_reference.urllib.request.urlopen',side_effect=socket.timeout()) as call:
   with self.assertRaisesRegex(Invalid,'مهلة'):r.observe([{'id':VID,'url':'https://www.youtube.com/watch?v='+VID}])
   self.assertEqual(call.call_count,1)

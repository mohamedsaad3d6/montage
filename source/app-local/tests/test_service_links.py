import sys,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid
import service_links as s
class Links(unittest.TestCase):
 def test_archive_failure_is_not_reported_as_connected(self):
  for result in ({'status':'sources_unavailable','source_errors':[{'source':'commons'}],'results':[]},{'status':'partial','source_errors':[{'source':'commons'}],'results':[{}]},{'results':[]}):
   with self.subTest(result=result),patch('archive.search',return_value=result):
    self.assertFalse(s.check(self.store,'commons')['ok'])
 def test_empty_but_successful_archive_search_is_connectivity_only(self):
  with patch('archive.search',return_value={'status':'completed','source_errors':[],'results':[]}):
   r=s.check(self.store,'commons')
  self.assertTrue(r['ok']);self.assertEqual(r['results_count'],0);self.assertFalse(r['download_started'])
 def test_network_failure_is_recorded_without_secret_details(self):
  with patch('archive.search',side_effect=OSError('private-url-token')):
   r=s.check(self.store,'commons')
  self.assertFalse(r['ok']);self.assertNotIn('private-url-token',json.dumps(r))
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'data',[self.tmp.name])
 def tearDown(self):self.tmp.cleanup()
 def test_no_credits_action_without_explicit_approval(self):
  with patch('service_links.get_json')as call:
   with self.assertRaises(Invalid):s.check(self.store,'magnific')
   call.assert_not_called()
 def test_auphonic_authenticated_is_not_processing_or_free_credit_permission(self):
  with patch('service_links.private_json',return_value={'api_key':'test-secret'}),patch('service_links.get_json',return_value={'status_code':200,'data':{'credits':2,'email':'private@example.com','is_paying_user':True}}):r=s.check(self.store,'auphonic')
  self.assertTrue(r['ok']);self.assertTrue(r['paid_credit_pool']);self.assertFalse(r['processing_started']);self.assertNotIn('test-secret',json.dumps(r));self.assertNotIn('private@example.com',json.dumps(r))
 def test_key_presence_is_not_verified_connection_and_assistant_is_separate(self):
  s.put(self.store,'storyblocks',{'ok':True,'scope':'assistant_connector_search'})
  with patch('service_links.sb.available',return_value=False),patch('service_links.STORYBLOCKS',Path(self.tmp.name)/'absent.json'),patch('service_links.private_json',return_value={'api_key':'secret','magnific_api_key':'secret'}):d=s.describe(self.store)
  mg=next(x for x in d['services']if x['id']=='magnific');sb=next(x for x in d['services']if x['id']=='storyblocks');self.assertTrue(mg['configured']);self.assertFalse(mg['network_tested']);self.assertTrue(sb['assistant_search_verified']);self.assertFalse(sb['network_tested']);self.assertFalse(sb['configured']);self.assertNotIn('secret',json.dumps(d))
 def test_approved_magnific_test_is_one_search_without_download(self):
  with patch('service_links.private_json',return_value={'magnific_api_key':'secret'}),patch('service_links.get_json',return_value={'data':[]})as call:r=s.check(self.store,'magnific',True)
  self.assertTrue(r['ok']);self.assertEqual(call.call_count,1);self.assertIn('/videos?term=city',call.call_args[0][0]);self.assertFalse(r['download_started'])
 def test_failed_test_not_marked_connected(self):
  with patch('service_links.private_json',return_value={'api_key':'secret'}),patch('service_links.get_json',side_effect=Invalid('HTTP 401')):r=s.check(self.store,'auphonic')
  self.assertFalse(r['ok']);self.assertIn('401',r['error'])
 def test_storyblocks_test_keys_are_stored_private_outside_project_and_never_returned(self):
  path=Path(self.tmp.name)/'private/storyblocks.json'
  with patch('service_links.STORYBLOCKS',path):
   response=s.save_storyblocks(self.store,{'public_key':'public-key-fixture','secret_key':'private-key-fixture','test_only':True});self.assertTrue(__import__('os').name=='nt' or path.stat().st_mode&0o077==0);self.assertNotIn('private-key-fixture',json.dumps(response));self.assertFalse(response['verified'])
   with self.assertRaises(Invalid):s.save_storyblocks(self.store,{'test_only':False})
 def test_direct_storyblocks_signature_does_not_send_private_key(self):
  path=Path(self.tmp.name)/'private.json'
  with patch('service_links.sb.available',return_value=False),patch('service_links.STORYBLOCKS',path),patch('service_links.Path.is_file',return_value=True),patch('service_links.private_json',return_value={'public_key':'public-key-fixture','secret_key':'private-key-fixture','test_only':True}),patch('service_links.get_json',return_value={'results':[]})as call:
   r=s.check(self.store,'storyblocks');url=call.call_args[0][0]
  self.assertTrue(r['ok']);self.assertIn('HMAC=',url);self.assertNotIn('private-key-fixture',url);self.assertFalse(r['production_downloads_enabled'])
  self.assertNotIn('project_id',url);self.assertNotIn('user_id',url)
 def test_local_storyblocks_search_does_not_claim_download_tested(self):
  with patch('service_links.sb.available',return_value=True),patch('service_links.sb.search',return_value={'results':[{'id':1}]})as search:
   r=s.check(self.store,'storyblocks')
  self.assertTrue(r['ok']);self.assertEqual(r['scope'],'local_codex_connector_search');self.assertFalse(r['licensed_download_tested']);self.assertFalse(r['download_started']);self.assertEqual(search.call_count,1)
 def test_gemini_metadata_probe_never_claims_audio_review(self):
  import sys
  sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'engine'))
  with patch('monteer.audio_review.pipeline.credentials',return_value='fixture-only'),patch('service_links.get_json',return_value={'name':'models/test'}):r=s.check(self.store,'gemini')
  self.assertTrue(r['ok']);self.assertFalse(r['audio_sent']);self.assertFalse(r['independent_audio_review_verified'])
 def test_prepared_only_user_choice_blocks_even_old_credit_consent(self):
  s.put(self.store,'magnific',{'prepared_only':True})
  with patch('service_links.get_json')as call:
   with self.assertRaises(Invalid):s.check(self.store,'magnific',True)
   call.assert_not_called()

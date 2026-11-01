import sys,unittest,json,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from archive import search
from transition_catalog import query
from health import report
class Discovery(unittest.TestCase):
 def test_metadata_never_becomes_verified_asset(self):
  response={'query':{'pages':{'1':{'pageid':1,'title':'Test file','imageinfo':[{'descriptionurl':'https://commons.wikimedia.org/wiki/File:test','url':'https://upload.wikimedia.org/test.jpg','extmetadata':{'LicenseShortName':{'value':'CC0'}}}]}}}}
  with patch('archive.get',return_value=response):r=search('Saudi',['commons'])
  self.assertEqual(len(r['results']),1);self.assertFalse(r['results'][0]['rights_verified']);self.assertFalse(r['results'][0]['visual_verified']);self.assertFalse(r['automatic_download'])
 def test_source_failure_is_explicit_not_silent_success(self):
  with patch('archive.get',side_effect=TimeoutError()):r=search('Saudi',['commons','internet_archive'])
  self.assertEqual(r['status'],'sources_unavailable');self.assertEqual(len(r['source_errors']),2)
  with self.assertRaises(ValueError):search('query',['unknown'])
 def test_full_transition_catalog_paginated_and_honestly_labelled(self):
  r=query();self.assertEqual(r['total'],10000);self.assertEqual(len(r['choices']),50);self.assertEqual(r['next_offset'],50);self.assertFalse(r['all_individually_verified'])
  second=query(offset=50);self.assertFalse(set(x['id'] for x in r['choices'])&set(x['id'] for x in second['choices']))
  with self.assertRaises(ValueError):query(family='invalid')
 def test_health_no_keys_or_network(self):
  with tempfile.TemporaryDirectory() as td:r=report(td)
  self.assertFalse(r['credentials_included']);self.assertFalse(r['automatic_episode']);self.assertTrue(r['checks'])
if __name__=='__main__':unittest.main()

class MusicDiscovery(unittest.TestCase):
 def test_audio_search_is_sent_to_both_archives_and_not_certified(self):
  seen=[]
  def get(url):seen.append(url);return {}
  with patch('archive.get',side_effect=get):r=search('cinematic music',['commons','internet_archive'],'audio')
  from urllib.parse import urlsplit,parse_qs
  args=[parse_qs(urlsplit(u).query)for u in seen]
  self.assertIn('filetype:audio',args[0]['gsrsearch'][0]);self.assertIn('mediatype:audio',args[1]['q'][0]);self.assertFalse(r['automatic_download']);self.assertEqual(r['media_type'],'audio')
 def test_invalid_kind_rejected_before_network(self):
  with patch('archive.get')as get:
   with self.assertRaises(ValueError):search('test',['commons'],'private')
   get.assert_not_called()

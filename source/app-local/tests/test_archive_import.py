import sys,json,tempfile,unittest,io
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from archive_import import checked_url,download,collect,select_archive_file,archive_kind,MAX_BYTES
from core import Store,Invalid
class PublicArchiveImport(unittest.TestCase):
 def test_movie_uses_video_not_smaller_thumbnail_or_audio(self):
  files=[{'name':'thumb.jpg','size':20},{'name':'sound.mp3','size':30},{'name':'clip.webm','size':100},{'name':'clip.mp4','size':200}]
  self.assertEqual(select_archive_file(files,'video'),'clip.mp4')
  self.assertEqual(select_archive_file(files,'audio'),'sound.mp3')
  with self.assertRaises(Invalid):select_archive_file(files,'image')
 def test_image_prefers_original_and_excludes_preview_tiles(self):
  files=[{'name':'__ia_thumb.jpg','size':8511,'source':'original','format':'Item Tile'},{'name':'6901184_thumb.jpg','size':4675,'source':'derivative'},{'name':'6901184.jpg','size':223907,'source':'original'},{'name':'preview.jpg','size':13000,'source':'derivative'}]
  self.assertEqual(select_archive_file(files,'image'),'6901184.jpg')
 def test_no_oversized_movie_fallback_to_thumbnail(self):
  with self.assertRaises(Invalid):select_archive_file([{'name':'clip.mp4','size':MAX_BYTES+1},{'name':'thumb.jpg','size':20}],'video')
 def test_archive_type_preserved_or_rejected_without_guessing(self):
  self.assertEqual(archive_kind({'mediatype':'movies'},{},'visual'),'video')
  self.assertEqual(archive_kind({},{'mediatype':'image'},'visual'),'image')
  with self.assertRaises(Invalid):archive_kind({},{},'visual')
  with self.assertRaises(Invalid):archive_kind({'mediatype':'audio'},{},'visual')
 def test_archive_formats_are_accepted_by_asset_store(self):
  with tempfile.TemporaryDirectory()as tmp:
   s=Store(Path(tmp)/'data',[tmp]);p=s.create('formats')
   for ext,kind in (('.ogv','video'),('.ogg','audio'),('.flac','audio')):
    path=Path(tmp)/('fixture'+ext);path.write_bytes(b'fixture')
    self.assertTrue(s.add_asset(p['id'],str(path),2,kind))
 def test_archive_movie_probed_as_audio_is_rejected_and_removed(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp);s=Store(root/'data',[root]);p=s.create('wrong media');j=s.enqueue(p['id'],'archive_search')
   result={'media_type':'visual','results':[{'source':'internet_archive','id':'movie','title':'movie','mediatype':'movies'}]}
   with s.connect()as c:c.execute("UPDATE jobs SET status='completed',result=? WHERE id=?",(json.dumps(result),j))
   def fetch(url,path,cancel):Path(path).write_bytes(b'fixture')
   with patch('archive_import.get',return_value={'files':[{'name':'clip.mp4','size':100}]}),patch('archive_import.download',side_effect=fetch),patch('archive_import.probe',return_value={'streams':[{'codec_type':'audio'}],'format':{'duration':'2'}}):
    with self.assertRaises(Invalid):collect(s,p['revision'],root/'collected',{'search_job':j,'source':'internet_archive','item_id':'movie'})
   self.assertFalse((root/'collected/archive-material.mp4').exists());self.assertEqual(s.project(p['id'])['assets'],[])
 def test_rejects_untrusted_urls_and_encoded_parent_paths(self):
  for url in ('http://archive.org/a','https://archive.org.evil.example/a','https://127.0.0.1/a','https://user:pass@archive.org/a','https://archive.org/%2e%2e/a','https://upload.wikimedia.org:9000/a'):
   with self.assertRaises((Invalid,ValueError)):checked_url(url)
 def test_stream_budget_stops_and_removes_partial_file(self):
  with tempfile.TemporaryDirectory()as tmp:
   class Response(io.BytesIO):
    headers={}
    def geturl(self):return 'https://upload.wikimedia.org/test.wav'
   class Opener:
    def open(self,*args,**kwargs):return Response(b'1234567')
   target=Path(tmp)/'f.wav'
   with patch('archive_import.urllib.request.build_opener',return_value=Opener()):
    with self.assertRaises(Invalid):download('https://upload.wikimedia.org/test.wav',target,max_bytes=5)
   self.assertFalse(target.exists());self.assertEqual(list(Path(tmp).iterdir()),[])
 def test_saved_result_is_collected_but_never_grants_rights_or_changes_timeline(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp);s=Store(root/'data',[root]);p=s.create('collect');j=s.enqueue(p['id'],'archive_search');result={'results':[{'source':'commons','id':'1','title':'Public candidate','media_url':'https://upload.wikimedia.org/test.wav','page_url':'https://commons.wikimedia.org/wiki/File:test.wav','license_claim':'CC0'}]}
   with s.connect()as c:c.execute("UPDATE jobs SET status='completed',result=? WHERE id=?",(json.dumps(result),j))
   folder=root/'material'
   def fetch(url,path,cancel):Path(path).write_bytes(b'real-fixture-stand-in')
   with patch('archive_import.download',side_effect=fetch),patch('archive_import.probe',return_value={'streams':[{'codec_type':'audio'}],'format':{'duration':'2'}}):r=collect(s,p['revision'],folder,{'search_job':j,'source':'commons','item_id':'1'})
   self.assertTrue(r['collected']);self.assertEqual(r['kind'],'audio');self.assertFalse(r['rights_verified']);self.assertFalse(r['timeline_changed']);self.assertEqual(s.project(p['id'])['active'],p['active']);m=json.loads(s.asset(r['asset_id'])['metadata']);self.assertEqual(m['license_claim'],'CC0');self.assertFalse(m['rights_verified'])
if __name__=='__main__':unittest.main()

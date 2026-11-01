import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid,Conflict
from media import Cancelled
import storyblocks_connector as sb

class Storyblocks(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.s=Store(self.root/'data',[self.root]);self.p=self.s.create('isolated');self.rev=self.p['revision'];self.folder=self.root/'job';self.folder.mkdir()
  self.item={'id':123,'source':'storyblocks','title':'City','page_url':'https://www.storyblocks.com/video/stock/city'}
  self.job=self.s.enqueue(self.p['id'],'storyblocks_search',{'query':'city','subject':'city'})
  with self.s.connect()as c:c.execute("UPDATE jobs SET status='completed',result=? WHERE id=?",(json.dumps({'results':[self.item]}),self.job))
  self.options={'search_job':self.job,'item_id':123,'consent_license':True}
 def tearDown(self):self.tmp.cleanup()
 def client(self):
  client=MagicMock();client.__enter__.return_value=client;return client
 def test_options_and_selected_item_are_strict(self):
  for opts in ({'query':'city','subject':'city','page':True},{'query':'city','subject':''},{'query':'city','subject':'city','url':'https://x'}):
   with self.assertRaises(Invalid):sb.options_for(opts)
  for opts in ({**self.options,'consent_license':False},{**self.options,'item_id':456},{**self.options,'item_id':True}):
   with self.assertRaises(Invalid):sb.selected(self.s,self.p['id'],self.p['active'],opts)
  with self.assertRaises(Invalid):sb.selected(self.s,self.s.create('other')['id'],self.p['active'],self.options)
  self.assertEqual(sb.selected(self.s,self.p['id'],self.p['active'],self.options)['id'],123)
 def test_search_only_calls_read_only_tool_and_strips_bad_previews(self):
  c=self.client();c.call.return_value={'results':[{'id':123,'title':'City','preview_url':'http://localhost/private','thumbnail_url':'https://dm0qx8t0i9gc9.cloudfront.net/thumbnails/city.jpg'}]}
  with patch.object(sb,'Connector',return_value=c):r=sb.search(self.folder,{'query':'city streets','subject':'city'})
  c.call.assert_called_once_with('search_videos',{'keywords':'city streets','required_keywords':'city','page':1,'results_per_page':12});self.assertFalse(r['licensed']);self.assertIsNone(r['results'][0]['preview_url'])
 def test_download_selection_preserves_signature_and_rejects_preview(self):
  url='https://cdn.cloudfront.net/original/2160p.mp4?Policy=a%2Bb&Signature=xyz'
  r=sb.download_choice({'MP4':{'_2160p':url,'_1080p':'https://cdn.cloudfront.net/original/1080p.mp4'},'preview_url':'https://cdn.cloudfront.net/preview/8k.mp4'})
  self.assertEqual(r,(url,'.mp4'))
  for url in ('http://cdn.cloudfront.net/a.mp4','https://storyblocks.com.evil.test/a.mp4','https://user:secret@storyblocks.com/a.mp4','https://cdn.cloudfront.net/watermarks/a.mp4','https://127.0.0.1/a.mp4'):
   with self.assertRaises(Invalid):sb.checked_download(url)
 def test_uncertain_license_is_recorded_and_never_repeated(self):
  c=self.client();c.call.side_effect=[{'download_formats':{'MP4':{}}},Invalid('timeout')]
  with patch.object(sb,'Connector',return_value=c):
   with self.assertRaises(Invalid):sb.collect(self.s,self.rev,self.folder,self.options)
   with self.assertRaises(Conflict):sb.collect(self.s,self.rev,self.folder,self.options)
  receipt=next((self.s.root/'storyblocks-receipts').glob('*.json'));self.assertEqual(json.loads(receipt.read_text())['state'],'needs_reconciliation');self.assertEqual(receipt.stat().st_mode&0o777,0o600);self.assertEqual(c.call.call_count,2)
 def test_licensed_file_import_is_not_automatic_editorial_approval(self):
  c=self.client();url='https://cdn.cloudfront.net/original.mp4?Signature=private'
  c.call.side_effect=[{'download_formats':{'MP4':{}}},{'download_url':url}]
  info={'streams':[{'codec_type':'video','duration':'2','width':1920,'height':1080}],'format':{'duration':'2'}}
  def save(url,path,cancel):path.write_bytes(b'fixture media only')
  with patch.object(sb,'Connector',return_value=c),patch.object(sb,'download',side_effect=save),patch.object(sb,'probe',return_value=info):r=sb.collect(self.s,self.rev,self.folder,self.options)
  self.assertTrue(r['collected']);self.assertFalse(r['rights_verified']);self.assertFalse(r['visual_verified']);self.assertFalse(r['timeline_changed']);self.assertNotIn('Signature',json.dumps(r));self.assertEqual(self.s.project(self.p['id'])['active'],self.p['active'])
  asset=self.s.asset(r['asset_id']);self.assertEqual(asset['source_type'],'archive');self.assertTrue(json.loads(asset['metadata'])['license_download_recorded']);c.call.assert_any_call('get_download_url',{'contentClass':'videos','stockItemId':123})
 def test_cancel_before_license_makes_no_remote_call(self):
  with patch.object(sb,'Connector')as c:
   with self.assertRaises(Cancelled):sb.collect(self.s,self.rev,self.folder,self.options,lambda:True)
   c.assert_not_called()
 def test_worker_runs_search_through_normal_queue(self):
  from worker import execute
  job=self.s.enqueue(self.p['id'],'storyblocks_search',{'query':'city','subject':'city'})
  with patch.object(sb,'search',return_value={'results':[self.item],'licensed':False}):execute(self.s,job)
  result=next(j for j in self.s.project(self.p['id'])['jobs']if j['id']==job);self.assertEqual(result['status'],'completed');self.assertFalse(json.loads(result['result'])['licensed'])

if __name__=='__main__':unittest.main()

import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid
class Reuse(unittest.TestCase):
 def test_duplicate_file_alias_cannot_bypass_visual_reuse_guard(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);s=Store(p/'data',[p]);v=s.create('تشخيص منع تكرار الصور');raw=p/'raw.mp4';raw.write_bytes(b'presenter');clip=p/'clip.mp4';clip.write_bytes(b'archival');a=s.add_asset(v['id'],str(raw),2,'video');b=s.add_asset(v['id'],str(clip),2,'video');alias=s.add_asset(v['id'],str(clip),2,'video')
   t=v['revision']['timeline'];t.update(duration_frames=24,primary_video_asset_id=a)
   next(tr for tr in t['tracks'] if tr['kind']=='voice')['clips']=[{'id':'voice','asset_id':a,'start_frame':0,'end_frame':24,'source_in_frame':0,'source_out_frame':24}]
   video=next(tr for tr in t['tracks'] if tr['kind']=='video');video['clips']=[{'id':str(i),'asset_id':asset,'start_frame':i*12,'end_frame':i*12+12,'source_in_frame':0,'source_out_frame':12} for i,asset in enumerate([b,alias])]
   with self.assertRaisesRegex(Invalid,'مستخدم بالفعل'):s.save(v['id'],v['active'],t)
   video['clips'][1].update(source_in_frame=12,source_out_frame=24);s.save(v['id'],v['active'],t)
if __name__=='__main__':unittest.main()

import sys,unittest,tempfile,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store
from worker import execute
class Queue(unittest.TestCase):
 def test_heavy_jobs_are_serialized_and_both_complete(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);s=Store(p/'data',[p]);source=p/'source.mp4';source.write_bytes(b'diagnostic');ids=[]
   for name in ['one','two']:
    v=s.create(name);a=s.add_asset(v['id'],str(source),1,'video');t=v['revision']['timeline'];t['duration_frames']=24
    for tr in t['tracks']:
     if tr['kind'] in ['video','voice']:tr['clips']=[{'id':tr['kind'],'asset_id':a,'start_frame':0,'end_frame':24,'source_in_frame':0,'source_out_frame':24}]
    v=s.save(v['id'],v['active'],t);ids.append(s.enqueue(v['id']))
   threads=[threading.Thread(target=execute,args=(s,j,.4)) for j in ids]
   for t in threads:t.start()
   while any(t.is_alive() for t in threads):
    with s.connect() as c:count=c.execute("SELECT COUNT(*) FROM jobs WHERE status='running'").fetchone()[0]
    self.assertLessEqual(count,1);time.sleep(.02)
   for t in threads:t.join()
   with s.connect() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM jobs WHERE status='completed'").fetchone()[0],2)
if __name__=='__main__':unittest.main()

import sys,unittest,tempfile,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store
from dispatcher import Dispatcher
class Dispatch(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.s=Store(self.root/'data',[self.root]);self.jobs=[]
  for i in range(3):self.jobs.append(self.s.enqueue(self.s.create(str(i))['id']))
 def tearDown(self):self.temp.cleanup()
 def wait(self,d):
  deadline=time.monotonic()+5
  while d.thread is not None and time.monotonic()<deadline:time.sleep(.01)
  self.assertIsNone(d.thread)
 def test_duplicate_dispatch_serial_and_cancelled_queue_not_spawned(self):
  entered=threading.Event();release=threading.Event();calls=[];store=self.s
  def spawn(args,**kwargs):
   job=args[-1];calls.append(job)
   class Process:
    def wait(self):
     if len(calls)==1:entered.set();release.wait(3)
     with store.connect() as c:c.execute("UPDATE jobs SET status='completed' WHERE id=? AND status='queued'",(job,))
     return 0
   return Process()
  d=Dispatcher(self.s,self.root,spawn);d.start(self.jobs[0]);self.assertTrue(entered.wait(2))
  for _ in range(5):
   for j in self.jobs:d.start(j)
  with self.s.connect() as c:c.execute("UPDATE jobs SET status='cancelled' WHERE id=?",(self.jobs[1],))
  self.assertEqual(calls,[self.jobs[0]]);release.set();self.wait(d);self.assertEqual(calls,[self.jobs[0],self.jobs[2]])
 def test_spawn_failure_is_recorded_without_infinite_retry(self):
  calls=[]
  def spawn(args,**kwargs):calls.append(args[-1]);raise OSError('test')
  d=Dispatcher(self.s,self.root,spawn);d.start(self.jobs[0]);self.wait(d)
  self.assertEqual(len(calls),3)
  with self.s.connect() as c:self.assertEqual(c.execute("SELECT count(*) FROM jobs WHERE status='failed'").fetchone()[0],3)
 def test_exit_without_result_is_failure_not_success(self):
  class Process:
   def wait(self):return 0
  d=Dispatcher(self.s,self.root,lambda *args,**kw:Process());d.start(self.jobs[0]);self.wait(d)
  with self.s.connect() as c:self.assertEqual(c.execute("SELECT count(*) FROM jobs WHERE status='failed'").fetchone()[0],3)
if __name__=='__main__':unittest.main()

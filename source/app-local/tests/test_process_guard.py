import sys,subprocess,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from process_guard import wait
from media import Cancelled
class Guard(unittest.TestCase):
 def process(self):return subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'],start_new_session=True)
 def test_timeout_terminates_and_reaps_process(self):
  p=self.process()
  with self.assertRaises(TimeoutError):wait(p,lambda:False,.05)
  self.assertIsNotNone(p.poll())
 def test_cancel_terminates_and_reaps_process(self):
  p=self.process()
  with self.assertRaises(Cancelled):wait(p,lambda:True)
  self.assertIsNotNone(p.poll())
 def test_nonzero_exit_is_not_success(self):
  p=subprocess.Popen([sys.executable,'-c','raise SystemExit(7)'],start_new_session=True)
  self.assertEqual(wait(p,lambda:False,5),7)

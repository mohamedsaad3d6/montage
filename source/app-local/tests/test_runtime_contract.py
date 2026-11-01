import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from runtime_contract import Contract
class RuntimeContract(unittest.TestCase):
 def test_new_source_invalidates_running_build_until_restart(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp);f=root/'worker.py';f.write_text('old');c=Contract(root);self.assertFalse(c.describe()['restart_required']);running=c.running;f.write_text('new code');self.assertTrue(c.describe()['restart_required']);self.assertEqual(c.running,running);self.assertFalse(Contract(root).describe()['restart_required'])
 def test_added_frontend_file_is_a_different_build(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp);c=Contract(root);d=root/'web/control';d.mkdir(parents=True);(d/'a.js').write_text('new UI');self.assertTrue(c.describe()['restart_required'])
if __name__=='__main__':unittest.main()

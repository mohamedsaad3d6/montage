import sys,tempfile,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,uid,Invalid
from render_stages import begin,mark,describe
class Stages(unittest.TestCase):
 def test_old_output_does_not_get_fabricated_stage_completion(self):
  with tempfile.TemporaryDirectory() as tmp:
   s=Store(Path(tmp)/'data',[tmp]);p=s.create('old');j=uid()
   with s.connect() as c:c.execute('INSERT INTO jobs(id,project,revision,kind,status,created) VALUES(?,?,?,?,?,?)',(j,p['id'],p['active'],'render','completed',1))
   data=describe(s,j);self.assertFalse(data['measured_stages']);self.assertFalse(data['publication_approved']);self.assertEqual(data['stages'],[])
 def test_running_and_skipped_are_distinct_and_wrong_revision_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   s=Store(Path(tmp)/'data',[tmp]);p=s.create('new');j=uid();folder=s.root/'jobs'/j;folder.mkdir(parents=True)
   with s.connect() as c:c.execute('INSERT INTO jobs(id,project,revision,kind,status,created) VALUES(?,?,?,?,?,?)',(j,p['id'],p['active'],'render','running',1))
   begin(folder,p['active']);mark(folder,'plan','running');mark(folder,'transitions','not_required');data=describe(s,j);self.assertEqual(data['stages'][0]['status'],'running');self.assertEqual(next(x for x in data['stages'] if x['id']=='transitions')['status'],'not_required');self.assertFalse(data['publication_approved'])
   begin(folder,'other')
   with self.assertRaises(Invalid):describe(s,j)

 def test_terminal_worker_does_not_leave_stage_running_or_certify_remaining_steps(self):
  for state in ('failed','cancelled'):
   with self.subTest(state=state),tempfile.TemporaryDirectory() as tmp:
    s=Store(Path(tmp)/'data',[tmp]);p=s.create('interrupted');j=uid();folder=s.root/'jobs'/j;folder.mkdir(parents=True)
    with s.connect() as c:c.execute('INSERT INTO jobs(id,project,revision,kind,status,created) VALUES(?,?,?,?,?,?)',(j,p['id'],p['active'],'render',state,1))
    begin(folder,p['active']);mark(folder,'plan','completed');mark(folder,'encode','running')
    data=describe(s,j);stages={x['id']:x for x in data['stages']}
    self.assertEqual(stages['encode']['status'],state)
    self.assertEqual(stages['encode']['terminal_state_source'],'job_status')
    self.assertEqual(stages['technical']['status'],'waiting')
    self.assertEqual(stages['plan']['status'],'completed')
    self.assertFalse(data['publication_approved'])

import sys,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import test_lifecycle as fixture
from core import dump,Invalid
from codex_agent import start,state,tick,validate
class CodexAgent(unittest.TestCase):
 def setUp(self):self.f=fixture.Lifecycle();self.f.setUp();self.s=self.f.s;self.p=self.f.p
 def tearDown(self):self.f.tearDown()
 def decision(self,action='wait'):return {'action':action,'reason':'Google غير متاح؛ لا مراجعة سمعية مكتملة','evidence':['failed review'],'next_steps':['تسوية الطلب'],'ready_for_release':False}
 def test_start_is_durable_and_duplicate_start_does_not_spawn_second_codex(self):
  a=start(self.s,self.p['id']);b=start(self.s,self.p['id']);self.assertIsNone(b['new_job']);self.assertEqual(state(self.s,self.p['id'])['job'],a['new_job'])
 def test_wait_decision_is_not_fake_execution_or_release(self):
  a=start(self.s,self.p['id']);j=a['new_job']
  with self.s.connect()as c:c.execute("UPDATE jobs SET status='completed',result=? WHERE id=?",(dump({'decision':self.decision()}),j))
  called=[];tick(self.s,called.append);self.assertFalse(called);self.assertEqual(state(self.s,self.p['id'])['state'],'needs_attention');self.assertEqual(self.s.project(self.p['id'])['active'],self.p['active'])
 def test_invalid_release_or_repeat_review_is_rejected(self):
  d=self.decision();d['ready_for_release']=True
  with self.assertRaises(Invalid):validate(d,{'ready_for_montage':False},[])
  with self.assertRaises(Invalid):validate(self.decision('audio_review'),{'ready_for_montage':False},[{'kind':'audio_review','status':'failed'}])
 def test_tool_request_is_enqueued_inside_agent_not_executed_by_chat(self):
  a=start(self.s,self.p['id']);j=a['new_job']
  with self.s.connect()as c:c.execute("UPDATE jobs SET status='completed',result=? WHERE id=?",(dump({'decision':self.decision('transcribe')}),j))
  called=[];tick(self.s,called.append);self.assertEqual(len(called),1)
  with self.s.connect()as c:self.assertEqual(c.execute('SELECT kind FROM jobs WHERE id=?',(called[0],)).fetchone()[0],'transcribe')
 def test_inspect_reads_saved_unknown_request_once_without_sending_audio(self):
  a=start(self.s,self.p['id']);j=a['new_job'];folder=self.s.root/'jobs'/j;folder.mkdir(parents=True,exist_ok=True)
  review=self.s.enqueue(self.p['id'],'transcribe',{})
  with self.s.connect()as c:c.execute("UPDATE jobs SET kind='audio_review' WHERE id=?",(review,))
  evidence=self.s.root/'jobs'/review/'independent-review';evidence.mkdir(parents=True)
  (evidence/'run.json').write_text(dump({'status':'stopped_needs_reconciliation','chunks':[{'status':'in_flight'}],'network_calls':1}))
  with self.s.connect()as c:
   c.execute("UPDATE jobs SET status='completed',result=? WHERE id=?",(dump({'decision':self.decision('inspect')}),j))
   c.execute("UPDATE jobs SET status='failed',error='503' WHERE id=?",(review,))
  called=[];tick(self.s,called.append);self.assertEqual(len(called),1)
  with self.s.connect()as c:n=dict(c.execute('SELECT * FROM jobs WHERE id=?',(called[0],)).fetchone())
  options=json.loads(n['options']);self.assertFalse(options['inspection']['network_requests_sent']);self.assertEqual(options['inspection']['review_records'][0]['chunk_states'],['in_flight']);self.assertEqual(n['kind'],'codex_plan')

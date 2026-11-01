import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store
from telemetry import report,start,finish,export_csv
class Telemetry(unittest.TestCase):
 def test_unknown_is_not_zero_and_measured_time_is_preserved(self):
  with tempfile.TemporaryDirectory() as tmp:
   s=Store(Path(tmp)/'data',[tmp]);p=s.create('=unsafe');self.assertIsNone(report(s)['rows'][0]['measured_seconds']);j=s.enqueue(p['id']);m=start(s,j);finish(s,m,2.75,'completed');finish(s,m,100,'completed');r=report(s)['rows'][0];self.assertEqual(r['measured_seconds'],2.75);self.assertIsNone(r['external_cost']);self.assertIn("'=unsafe",export_csv(s).decode('utf-8-sig'))
 def test_calendar_period_filters_measurements_without_inventing_costs(self):
  from telemetry import period_start
  from core import Invalid
  import datetime
  now=datetime.datetime(2026,10,29,1,0,tzinfo=datetime.timezone.utc).timestamp()
  with tempfile.TemporaryDirectory() as tmp:
   s=Store(Path(tmp)/'data',[tmp]);p=s.create('period');j=s.enqueue(p['id']);old=start(s,j);finish(s,old,10,'completed');recent=start(s,j);finish(s,recent,3,'completed')
   with s.connect() as c:
    c.execute('UPDATE execution_metrics SET started=? WHERE id=?',(now-40*86400,old));c.execute('UPDATE execution_metrics SET started=? WHERE id=?',(now,recent))
   result=report(s,period='month',now=now);self.assertEqual(result['total_measured_seconds'],3);self.assertEqual(result['measured_projects'],1);self.assertEqual(sum(result['local_by_kind'].values()),3);self.assertEqual(report(s,now=now)['total_measured_seconds'],13)
   with self.assertRaises(Invalid):report(s,period='invalid')
  self.assertGreater(period_start('week',now),period_start('month',now))

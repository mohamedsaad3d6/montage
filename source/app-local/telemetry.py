"""Measured local execution time only; unknown external costs never become zero."""
import csv,io,time,datetime
from core import uid,Invalid

def init(store):
 with store.connect() as c:c.execute('CREATE TABLE IF NOT EXISTS execution_metrics(id TEXT PRIMARY KEY,job TEXT,started REAL,ended REAL,elapsed REAL,status TEXT)')
def start(store,job):
 init(store);id=uid()
 with store.connect() as c:c.execute('INSERT INTO execution_metrics VALUES(?,?,?,?,?,?)',(id,job,time.time(),None,None,'running'))
 return id
def finish(store,id,seconds,status):
 with store.connect() as c:c.execute('UPDATE execution_metrics SET ended=?,elapsed=?,status=? WHERE id=? AND ended IS NULL',(time.time(),max(0,seconds),status,id))
def period_start(period,now=None):
 if period not in ['all','week','month']:raise Invalid('فترة الاستخدام غير صالحة')
 now=time.time() if now is None else now
 # Respect Cairo calendar boundaries and daylight-saving changes.
 from zoneinfo import ZoneInfo
 local=datetime.datetime.fromtimestamp(now,ZoneInfo('Africa/Cairo'))
 if period=='all':return 0
 day=local.replace(hour=0,minute=0,second=0,microsecond=0)
 return (day.replace(day=1) if period=='month' else day-datetime.timedelta(days=day.weekday())).timestamp()
def report(store,project=None,period='all',now=None):
 init(store);cutoff=period_start(period,now)
 with store.connect() as c:
  projects=[dict(x) for x in c.execute('SELECT id,name FROM projects')];jobs=[dict(x) for x in c.execute('SELECT id,project,status,kind,created FROM jobs')];attempts=[dict(x) for x in c.execute('SELECT * FROM execution_metrics WHERE started>=?',(cutoff,))]
 rows=[];breakdown={}
 for p in projects:
  if project and project!=p['id']:continue
  all_jobs=[j for j in jobs if j['project']==p['id']];ids={j['id'] for j in all_jobs};measured=[a for a in attempts if a['job'] in ids and a['elapsed'] is not None];measured_ids={a['job'] for a in measured};recent_jobs=[j for j in all_jobs if j['created']>=cutoff]
  for a in measured:
   kind=next(j['kind'] for j in all_jobs if j['id']==a['job']);breakdown[kind]=breakdown.get(kind,0)+a['elapsed']
  rows.append({'project':p['id'],'name':p['name'],'measured_seconds':round(sum(a['elapsed'] for a in measured),3) if measured else None,'measured_attempts':len(measured),'unmeasured_jobs':sum(j['status'] in ['completed','failed','cancelled'] and j['id'] not in measured_ids for j in recent_jobs),'external_cost':None,'currency':None})
 measured_rows=[r for r in rows if r['measured_seconds'] is not None]
 return {'rows':rows,'period':period,'period_start':cutoff,'measured_projects':len(measured_rows),'total_measured_seconds':round(sum(r['measured_seconds'] for r in measured_rows),3),'average_measured_seconds':round(sum(r['measured_seconds'] for r in measured_rows)/len(measured_rows),3) if measured_rows else None,'local_by_kind':{k:round(v,3) for k,v in breakdown.items()},'external_costs_available':False,'scope':'measured local attempts since instrumentation; not per-episode end-to-end time or billing','not_a_billing_verification':True}
def export_csv(store,period='all'):
 result=report(store,period=period);f=io.StringIO();writer=csv.writer(f);writer.writerow(['الحلقة','ثواني التنفيذ المقاسة','محاولات مقاسة','مهام بلا قياس','التكلفة الخارجية'])
 for r in result['rows']:
  name=r['name'];name="'"+name if name.lstrip().startswith(('=','+','-','@','\t','\r')) else name
  writer.writerow([name,r['measured_seconds'] if r['measured_seconds'] is not None else 'غير مقاس',r['measured_attempts'],r['unmeasured_jobs'],'غير متاحة'])
 return ('\ufeff'+f.getvalue()).encode('utf-8')

"""Google supplies meaning-level pause candidates; local acoustics alone supply cut boundaries."""
import copy,json,sys
from pathlib import Path
from core import Invalid,uid
from media import ROOT,file_hash

def evidence(store,review_job,render_result):
 summary=json.loads(review_job.get('result') or '{}')
 if summary.get('review_complete') is not True or summary.get('output_sha256')!=render_result.get('file_sha256'):return None
 folder=store.root/'jobs'/review_job['id'];sys.path.insert(0,str(ROOT/'engine'))
 from monteer.audio_review.gate import check
 gate=check(render_result['file'],folder/'independent-review',folder/'technical-checks.json')
 if any(not x.startswith('unresolved_editorial_issues_') for x in gate['reasons']):return None
 state=json.loads((folder/'independent-review/run.json').read_text());issues=[]
 for chunk in state['chunks']:
  result=json.loads((folder/'independent-review'/chunk['result']).read_text())
  for issue in result['issues']:
   if issue['action']=='investigate':issues.append({**issue,'start':chunk['start']+issue['start'],'end':chunk['start']+issue['end']})
 return {'review_job':review_job['id'],'output_sha256':render_result['file_sha256'],'issues':issues}

def confirmed_plan(store,project,original,folder):
 t=project['revision']['timeline'];jobs=project['jobs'];byid={j['id']:j for j in jobs};reviewed=[]
 for j in jobs:
  if j['kind']!='audio_review' or j['revision']!=project['active'] or j['status']!='completed':continue
  summary=json.loads(j['result'] or '{}');output=byid.get(summary.get('output_job'))
  if not output or output['status']!='completed':continue
  r=json.loads(output['result'])
  if r.get('frames')!=t['duration_frames'] or r.get('start_frame')!=0 or not r.get('audio_unchanged'):continue
  item=evidence(store,j,r)
  if item:reviewed.append(item);break
 if not reviewed:raise Invalid('راجع صوت الخام كاملًا في Studio أولًا؛ السكتة الهادئة قد تكون مقصودة للمعنى')
 pauses=[(review,issue) for review in reviewed for issue in review['issues'] if issue['kind']=='pause'];cuts=[]
 for cut in original['cuts']:
  midpoint=(cut['start_frame']+cut['end_frame'])/2/t['fps']
  match=next(((r,i) for r,i in pauses if i['start']-.75<=midpoint<=i['end']+.75),None)
  if match:cuts.append({**cut,'meaning_review':{'review_job':match[0]['review_job'],'output_sha256':match[0]['output_sha256'],'quote':match[1]['quote'],'reason':match[1]['reason']}})
 if not cuts:raise Invalid('لا توجد فجوة هادئة تتطابق مع ملاحظة سكتة مؤكدة؛ لا قصّ تلقائي')
 plan=copy.deepcopy(original);plan['cuts']=cuts;plan['keeps']=[];cursor=0
 for cut in cuts:
  if cursor<cut['start_frame']:plan['keeps'].append({'start_frame':cursor,'end_frame':cut['start_frame']})
  cursor=cut['end_frame']
 if cursor<t['duration_frames']:plan['keeps'].append({'start_frame':cursor,'end_frame':t['duration_frames']})
 path=Path(folder)/('meaning-confirmed-pause-plan-'+uid()+'.json');path.write_text(json.dumps(plan,ensure_ascii=False,indent=2))
 return plan,path,file_hash(path)

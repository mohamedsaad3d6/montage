"""Loopback-only Montaj adapter; stdlib, no cloud, no legacy engine execution."""
import argparse,hashlib,json,mimetypes,os,secrets,subprocess,sys,threading,urllib.parse,shutil
from pathlib import Path
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from core import Store,Invalid,Conflict
BASE=Path(__file__).parent.resolve();ROOT=BASE.parent
class App:
 def __init__(self,data,allowed,port):
  self.store=Store(data,[*allowed,str(Path(data).resolve())]);self.token=secrets.token_urlsafe(32);self.port=port;self.allowed=allowed
  from dispatcher import Dispatcher
  self.dispatcher=Dispatcher(self.store,BASE)
  from runtime_contract import Contract
  self.contract=Contract(BASE)
 def start(self,j):
  self.dispatcher.start(j)
 def watch_workflows(self):
  def loop():
   from workflow import tick
   while True:
    threading.Event().wait(2)
    if not self.contract.describe()['restart_required']:
     tick(self.store,self.start)
     from codex_agent import tick as codex_tick
     codex_tick(self.store,self.start)
     from storyblocks_auto import tick as storyblocks_tick
     storyblocks_tick(self.store,self.start)
  threading.Thread(target=loop,daemon=True).start()
 def recover(self):
  from channel_reference import recover
  import psutil
  recover(self.store)
  with self.store.connect() as c:
   for j in c.execute("SELECT * FROM jobs WHERE status='running'").fetchall():
    try:
     if not j['worker_pid']:raise OSError('Missing worker PID')
     command=' '.join(psutil.Process(j['worker_pid']).cmdline())
     if 'worker.py' not in command or j['id'] not in command:raise OSError('Previous worker no longer owns process')
    except (OSError,TypeError,subprocess.SubprocessError,psutil.Error):c.execute("UPDATE jobs SET status='queued',worker_pid=NULL WHERE id=?",(j['id'],))
   ids=[r[0] for r in c.execute("SELECT id FROM jobs WHERE status='queued'")]
  for j in ids:self.start(j)
class Handler(BaseHTTPRequestHandler):
 server_version='MontajLocal'
 def log_message(self,*args):pass
 def send(self,status,data,ctype='application/json; charset=utf-8',filename=None):
  body=json.dumps(data,ensure_ascii=False).encode() if ctype.startswith('application/json') else data
  self.send_response(status)
  if filename:self.send_header('Content-Disposition','attachment; filename="'+filename+'"')
  self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer');self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https://dm0qx8t0i9gc9.cloudfront.net; media-src 'self' blob: https://dm0qx8t0i9gc9.cloudfront.net; connect-src 'self'; frame-ancestors 'self'; object-src 'none'; base-uri 'self'");self.end_headers();self.wfile.write(body)
 def guard(self,write=False):
  hosts=[f'127.0.0.1:{self.server.app.port}',f'localhost:{self.server.app.port}']
  if self.headers.get('Host') not in hosts:raise PermissionError('عنوان محلي غير صالح')
  if self.headers.get('Sec-Fetch-Site')=='cross-site':raise PermissionError('الطلب من خارج التطبيق مرفوض')
  if write and (self.headers.get('Origin') not in ['http://'+h for h in hosts] or self.headers.get('X-Montaj-Token')!=self.server.app.token):raise PermissionError('طلب تعديل غير موثق من الواجهة المحلية')
  contract=getattr(self.server.app,'contract',None)
  if write and contract and contract.describe()['restart_required'] and urllib.parse.urlsplit(self.path).path not in ['/api/workflow/pause','/api/jobs/cancel']:
   raise Conflict('يجري تحديث التطبيق؛ يلزم إعادة تشغيل الخادم قبل بدء عمل جديد. الإيقاف متاح والمصادر محفوظة.')
 def do_GET(self):
  try:
   self.guard();u=urllib.parse.urlsplit(self.path);q=urllib.parse.parse_qs(u.query);s=self.server.app.store
   if u.path=='/api/editorial-directives':
    from editorial_directives import list_directives
    return self.send(200,list_directives(s,q['project'][0]))
   if u.path=='/api/reference-pairs':
    from reference_pairs import list_pairs
    return self.send(200,list_pairs(s,q['project'][0]))
   if u.path=='/api/workflow':
    from workflow import describe
    return self.send(200,describe(s,q['project'][0]))
   if u.path=='/api/trash':
    from lifecycle import describe
    return self.send(200,describe(s))
   if u.path=='/api/library':
    from library_registry import catalogue
    return self.send(200,catalogue(s,q.get('query',[''])[0],q.get('kind',[''])[0],int(q.get('offset',['0'])[0])))
   if u.path=='/api/render-stages':
    from render_stages import describe
    return self.send(200,describe(s,q['job'][0]))
   if u.path=='/api/usage':
    from telemetry import report
    return self.send(200,report(s,q.get('project',[None])[0],q.get('period',['all'])[0]))
   if u.path=='/usage.csv':
    from telemetry import export_csv
    return self.send(200,export_csv(s,q.get('period',['all'])[0]),'text/csv; charset=utf-8')
   if u.path=='/api/take-review':
    from take_review import describe
    return self.send(200,describe(s,q['job'][0]))
   if u.path.startswith('/take-repair-audio/'):
    from take_repair import audio
    parts=u.path.split('/')
    if len(parts)!=5:raise Invalid('رابط وصلة غير صالح')
    return self.media(audio(s,parts[2],parts[3],int(parts[4])))
   if u.path.startswith('/take-audio/'):
    from take_review import audio
    return self.media(audio(s,u.path.rsplit('/',1)[-1]))
   if u.path=='/api/waveform':
    from waveform import peaks
    return self.send(200,peaks(s,q['job'][0]))
   if u.path=='/api/channel-reference':
    from channel_reference import status
    return self.send(200,status(s,q['channel'][0]))
   if u.path.startswith('/channel-reference-logo/'):
    from channel_reference import logo
    parts=u.path.split('/')
    if len(parts)!=4:raise Invalid('رابط شعار غير صالح')
    return self.media(logo(s,parts[2],parts[3]))
   if u.path=='/api/channel-kit':
    from channel_kit import get
    return self.send(200,get(s,q['channel'][0]))
   if u.path=='/api/channels':
    from workspace import channels,assignments
    return self.send(200,{'channels':channels(s),'assignments':assignments(s)})
   if u.path=='/api/output-status':
    from output_status import status
    return self.send(200,status(s,q['job'][0]))
   if u.path=='/api/studio':
    from studio import describe
    return self.send(200,describe(s,q['job'][0]))
   if u.path.startswith('/studio-audio/'):
    from studio import audio_file
    parts=u.path.split('/')
    if len(parts)!=4:raise Invalid('رابط جزء غير صالح')
    return self.media(audio_file(s,parts[2],int(parts[3])))
   if u.path=='/api/service-links':
    from service_links import describe
    return self.send(200,describe(s))
   if u.path=='/api/styles':
    from profiles import list_profiles
    return self.send(200,list_profiles(s))
   if u.path=='/api/codex-agent':
    from codex_agent import state
    return self.send(200,state(s,q['project'][0]))
   if u.path=='/api/storyblocks/automatic':
    from storyblocks_auto import state
    return self.send(200,state(s,q['project'][0]))
   if u.path=='/api/creative-tools':
    from creative_tools import describe
    return self.send(200,describe(s.root))
   if u.path=='/api/health':
    from health import report
    return self.send(200,report(s.root))
   if u.path=='/api/bootstrap':return self.send(200,{'token':self.server.app.token,'projects':s.projects(),'defaults':json.loads((BASE/'export-policy.json').read_text()),'runtime':self.server.app.contract.describe() if hasattr(self.server.app,'contract') else {'protocol':2,'restart_required':False},'capabilities':{'library_jobs':['generate_graphic','generate_music','preview_transition','archive_search','archive_collect','storyblocks_search','storyblocks_collect','storyblocks_autoselect'],'input_prepare_three_modes':True,'editing_metadata':True,'review_render':True,'automatic_episode':False,'external_providers':False,'google_studio_review_bridge':True,'autonomous_browser_review':False,'learning_rules':'project_scoped_explicit_approval'}})
   if u.path=='/api/project':
    if q.get('jobs_only')==['1']:
     from job_activity import snapshot
     return self.send(200,snapshot(s,q['id'][0]))
    from production import status
    project=s.project(q['id'][0]);project['production']=status(project,s)
    return self.send(200,project)
   if u.path=='/api/production':
    from production import status
    return self.send(200,status(s.project(q['id'][0]),s))
   if u.path=='/api/transition-catalog':
    from transition_catalog import query
    return self.send(200,query(q.get('family',[''])[0],int(q.get('offset',['0'])[0])))
   if u.path=='/api/transitions':
    f=ROOT/'library/our-transitions-01/validation.json';v=json.loads(f.read_text());return self.send(200,{'recipes':v['recipe_count'],'families':v['algorithm_families'],'rendered':v['rendered_representatives'],'individually_untested':v['not_individually_rendered'],'choices':[x for x in json.loads((ROOT/'library/our-transitions-01/catalog.json').read_text())['recipes'] if x['id'] in v['rendered_ids']]})
   if u.path.startswith('/inspection-frame/'):
    parts=u.path.split('/')
    if len(parts)!=4:raise Invalid('رابط صورة غير صالح')
    with s.connect() as c:j=s.one(c,'SELECT * FROM jobs WHERE id=?',(parts[2],))
    if j['kind']!='inspect_asset' or j['status']!='completed':raise Invalid('الفحص غير مكتمل')
    result=json.loads(j['result']);idx=int(parts[3])
    if not 0<=idx<len(result['frames']):raise Invalid('صورة غير موجودة')
    from media import file_hash
    f=result['frames'][idx]
    if file_hash(f['file'])!=f['sha256']:raise Invalid('الصورة تغيرت')
    return self.media(Path(f['file']))
   if u.path in ['/api/editorial','/api/shot-plan']:
    from media import file_hash
    with s.connect() as c:j=s.one(c,'SELECT * FROM jobs WHERE id=?',(q['job'][0],))
    kind='editorial_plan' if u.path=='/api/editorial' else 'shot_plan'
    if j['kind']!=kind or j['status']!='completed':raise Invalid('الخطة غير مكتملة')
    r=json.loads(j['result']);p=Path(r['plan_file']).resolve()
    if s.root not in p.parents or file_hash(p)!=r['plan_sha256']:raise Invalid('الخطة تغيرت')
    return self.send(200,json.loads(p.read_text()))
   if u.path=='/api/asset-info':
    from lifecycle import open_asset
    open_asset(s,q['id'][0])
    from media import probe,file_hash
    a=s.asset(q['id'][0]);file=s.resolve(a['path'])
    if file_hash(file)!=a['hash']:raise Invalid('ملف المصدر تغير')
    result={'id':a['id'],'kind':a['kind'],'bytes':file.stat().st_size,'duration':a['duration'],'fingerprint_verified':True}
    if a['kind'] in ['video','audio']:
     info=probe(file);video=next((x for x in info['streams'] if x['codec_type']=='video'),{});audio=next((x for x in info['streams'] if x['codec_type']=='audio'),{})
     result.update({'width':video.get('width'),'height':video.get('height'),'fps':video.get('avg_frame_rate'),'sample_rate':audio.get('sample_rate'),'audio_channels':audio.get('channels')})
    return self.send(200,result)
   if u.path=='/api/intake':
    from intake import get
    return self.send(200,get(s,q['project'][0]))
   if u.path=='/api/script-plan':
    from script_plan import get
    return self.send(200,get(s,q['project'][0]))
   if u.path=='/api/script-scaffold':
    from script_plan import scaffold
    return self.send(200,scaffold(s,q['project'][0]))
   if u.path=='/api/script-drafts':
    from script_workspace import drafts
    return self.send(200,drafts(s,q['project'][0]))
   if u.path=='/script-export':
    from script_workspace import export
    format=q.get('format',['txt'])[0];body,ctype=export(s,q['project'][0],q['id'][0],format);return self.send(200,body,ctype,'script.'+format)
   if u.path=='/api/script':
    from media import read_script
    a=s.asset(q['id'][0])
    if a['kind']!='script':raise Invalid('الملف ليس سكريبتًا')
    return self.send(200,{'text':read_script(a['path'])})
   if u.path=='/api/graphics':return self.send(200,json.loads((BASE/'graphics/catalog.json').read_text()))
   if u.path.startswith('/graphic-poster/'):
    with s.connect() as c:j=s.one(c,'SELECT * FROM jobs WHERE id=?',(u.path.split('/')[-1],))
    if j['kind']!='generate_graphic' or j['status']!='completed':raise Invalid('الموشن غير مكتمل')
    return self.media(s.root/'jobs'/j['id']/'poster.png')
   if u.path.startswith('/transition-output/'):
    from media import file_hash
    with s.connect() as c:j=s.one(c,'SELECT * FROM jobs WHERE id=?',(u.path.split('/')[-1],))
    if j['kind']!='preview_transition' or j['status']!='completed':raise Invalid('معاينة الانتقال غير مكتملة')
    r=json.loads(j['result']);p=Path(r['file']).resolve()
    if s.root not in p.parents or file_hash(p)!=r['file_sha256']:raise Invalid('معاينة غير صالحة')
    return self.media(p)
   if u.path.startswith('/transition-preview/'):
    import re
    id=u.path.split('/')[-1]
    if not re.fullmatch(r'OT-\d{5}',id):raise Invalid('معرّف انتقال غير صالح')
    p=ROOT/'library/our-transitions-01/previews'/(id+'.mp4')
    if not p.is_file():raise Invalid('الانتقال لم يصدر له مثال منفرد')
    return self.media(p)
   if u.path.startswith('/output/'):
    with s.connect() as c:j=s.one(c,'SELECT * FROM jobs WHERE id=?',(u.path.split('/')[-1],))
    if j['status']!='completed' or j['kind']!='render':raise Invalid('الناتج غير مكتمل')
    result=json.loads(j['result'])
    if result['duration']>30:
     with s.connect() as c:reviews=[dict(x) for x in c.execute("SELECT * FROM jobs WHERE kind='audio_review' AND status='completed' AND project=? AND revision=? ORDER BY created DESC",(j['project'],j['revision']))]
     from release import reviewed
     matches=[x for x in reviews if json.loads(x['result']).get('output_job')==j['id'] and json.loads(x['result']).get('review_complete') is True]
     valid=bool(matches) and reviewed(s,matches[0],result)
     if not valid:raise PermissionError('النسخة الكاملة لم تجتز المراجعة السمعية المستقلة؛ لا تُعرض كنسخة جاهزة')
    p=Path(result['file']).resolve()
    if s.root not in p.parents or not p.is_file():raise Invalid('ملف الإخراج غير موجود')
    if result['duration']>30:
     from media import file_hash
     if file_hash(p)!=result.get('file_sha256'):raise PermissionError('ملف الناتج تغير بعد المراجعة')
    return self.media(p)
   if u.path.startswith('/media/'):
    a=s.asset(u.path.split('/')[-1]);from lifecycle import open_asset
    open_asset(s,a['id']);p=s.resolve(a['path']);return self.media(p)
   rel=u.path.lstrip('/') or 'montaj.html';p=(BASE/'web'/rel).resolve()
   if (BASE/'web') not in p.parents or not p.is_file():return self.send(404,{'error':'الصفحة غير موجودة'})
   return self.send(200,p.read_bytes(),mimetypes.guess_type(p)[0] or 'application/octet-stream')
  except PermissionError as e:self.send(403,{'error':str(e)})
  except (Invalid,KeyError,ValueError) as e:self.send(400,{'error':str(e)})
  except (BrokenPipeError,ConnectionResetError):pass
 def do_POST(self):
  try:
   self.guard(True)
   if urllib.parse.urlsplit(self.path).path=='/api/upload':return self.upload()
   if not self.headers.get('Content-Type','').startswith('application/json'):raise Invalid('صيغة الطلب غير صالحة')
   n=int(self.headers.get('Content-Length','0'))
   if not 0<n<=2*1024*1024:raise Invalid('حجم الطلب غير صالح')
   d=json.loads(self.rfile.read(n));s=self.server.app.store;path=urllib.parse.urlsplit(self.path).path
   if path not in ['/api/trash/put','/api/trash/restore'] and d.get('project'):
    from lifecycle import open_project
    open_project(s,d['project'])
   if path=='/api/storyblocks/automatic':
    if self.server.app.contract.describe()['restart_required']:raise Conflict('يلزم تحديث التطبيق قبل بدء مهمة جديدة')
    from storyblocks_auto import configure
    v=configure(s,d['project'],d['expected'],d['enabled'])
    if v['new_job']:self.server.app.start(v['new_job'])
   elif path=='/api/service-links/storyblocks':
    from service_links import save_storyblocks
    v=save_storyblocks(s,d)
   elif path=='/api/service-links/check':
    from service_links import check
    v=check(s,d['provider'],d.get('allow_credit_test')is True)
   elif path=='/api/intake/begin':
    from workflow import begin
    v=begin(s,d)
    if v['new_job']:self.server.app.start(v['new_job'])
   elif path=='/api/codex-agent/start':
    from codex_agent import start
    v=start(s,d['project'],goal=d.get('goal'))
    if v['new_job']:self.server.app.start(v['new_job'])
   elif path=='/api/workflow/pause':
    from workflow import pause
    v=pause(s,d['project'])
   elif path=='/api/workflow/continue':
    from workflow import advance
    v=advance(s,d['project'],consent=d.get('consent'))
    if v['new_job']:self.server.app.start(v['new_job'])
   elif path=='/api/trash/put':
    from lifecycle import change
    v=change(s,d)
   elif path=='/api/trash/restore':
    from lifecycle import change
    v=change(s,d,True)
   elif path=='/api/projects':v=s.create(d['name'])
   elif path=='/api/assets':
    p=s.resolve(d['path']);kind=d['kind'];dur=0
    if kind in ['video','audio']:
     from media import probe,duration
     dur=duration(probe(p),kind)
    a=s.add_asset(d['project'],str(p),dur,kind);v={'asset_id':a,'project':s.project(d['project'])}
   elif path=='/api/channel-reference/analyze':
    from channel_reference import start,process,status
    run=start(s,d['channel'],d['url'],d.get('video_consent') is True)
    threading.Thread(target=process,args=(s,d['channel'],run),daemon=True).start()
    v=status(s,d['channel'])
   elif path=='/api/channel-reference/apply':
    from channel_reference import apply
    v=apply(s,d['channel'],d['run'])
   elif path=='/api/channel-kit/save':
    from channel_kit import save
    v=save(s,d)
   elif path=='/api/channels/save':
    from workspace import save_channel
    v=save_channel(s,d)
   elif path=='/api/channels/assign':
    from workspace import assign
    v=assign(s,d['project'],d['channel'],d.get('apply_style') is True)
   elif path=='/api/editorial-directives/save':
    from editorial_directives import save
    v=save(s,d)
   elif path=='/api/editorial-directives/status':
    from editorial_directives import set_status
    v=set_status(s,d)
   elif path=='/api/reference-pairs/save':
    from reference_pairs import save
    v=save(s,d)
   elif path=='/api/library/exclude':
    from library_registry import exclude
    v=exclude(s,d['project'],d['asset'],d['excluded'])
   elif path=='/api/library/reuse':
    from library_registry import reuse
    v=reuse(s,d['project'],d['asset'])
   elif path=='/api/timeline/action':
    from timeline_ops import apply
    v=apply(s,d['project'],d['expected'],d['operation'])
   elif path=='/api/revisions':v=s.save(d['project'],d['expected'],d['timeline'],str(d.get('summary','تعديل التايملاين'))[:200])
   elif path=='/api/activate':v=s.activate(d['project'],d['revision'])
   elif path=='/api/jobs':
    j=s.enqueue(d['project'],d.get('kind','asset_integrity'),d.get('options',{}),revision=d.get('revision'));self.server.app.start(j);v={'id':j}
   elif path=='/api/take-repair/preview':
    from take_repair import preview
    v=preview(s,d)
   elif path=='/api/take-repair/apply':
    from take_repair import apply
    v=apply(s,d)
   elif path=='/api/take-review/save':
    from take_review import save
    v=save(s,d)
   elif path=='/api/cancel':
    with s.connect() as c:c.execute("UPDATE jobs SET status='cancelled' WHERE id=? AND status IN ('queued','running')",(d['id'],))
    v={'ok':True}
   elif path=='/api/assets/describe':
    from inspection import describe
    v=describe(s,d['project'],d['inspection_job'],d['metadata'])
   elif path=='/api/cuts/apply-quiet':
    from media import file_hash
    from cutplan import apply as apply_cuts
    with s.connect() as c:j=s.one(c,'SELECT * FROM jobs WHERE id=?',(d['job'],))
    if j['kind']!='editorial_plan' or j['status']!='completed':raise Invalid('خطة التنظيف غير مكتملة')
    v=s.project(j['project'])
    if v['active']!=j['revision'] or d['expected']!=v['active']:raise Conflict('النسخة اتغيرت بعد التحليل')
    r=json.loads(j['result'])
    for path_key,hash_key in [('plan_file','plan_sha256'),('source_words_file','source_words_sha256'),('wave_file','wave_sha256')]:
     if file_hash(r[path_key])!=r[hash_key]:raise Invalid('دليل التحليل تغير')
    asset=s.asset(r['source_asset_id'])
    if file_hash(asset['path'])!=r['source_asset_sha256']:raise Invalid('الخام تغير بعد التحليل')
    plan=json.loads(Path(r['plan_file']).read_text())
    from pause_review import confirmed_plan
    plan,confirmed_file,confirmed_sha=confirmed_plan(s,v,plan,s.root/'jobs'/j['id'])
    r={**r,'plan_file':str(confirmed_file),'plan_sha256':confirmed_sha}
    if not plan['cuts']:raise Invalid('لا توجد فجوات مثبتة للقص؛ لم تتغير النسخة')
    t=apply_cuts(v['revision']['timeline'],plan);t['cleaning_job']=j['id'];t['requires_new_independent_audio_review']=True;t['cutting_proof']={'plan_file':r['plan_file'],'plan_sha256':r['plan_sha256'],'source_words_file':r['source_words_file'],'source_words_sha256':r['source_words_sha256'],'source_asset_id':r['source_asset_id'],'source_asset_sha256':r['source_asset_sha256']};v=s.save(v['id'],v['active'],t,'تقصير فجوات هادئة فقط — نسخة داخلية تحتاج مراجعة؛ لا حذف محاولات',trusted_cut_proof=True)
   elif path=='/api/plans':
    from plans import propose
    v=propose(s,d['project'],d['text'])
   elif path=='/api/plans/apply':
    from plans import apply
    v=apply(s,d['plan'])
   elif path=='/api/shot-plan/apply':
    from montage import apply_plan
    v=apply_plan(s,d['project'],d['job'],d['expected'])
   elif path=='/api/studio/record':
    from studio import record
    v=record(s,d['job'],d['chunk'],d['result'],d['evidence_asset'],d.get('reviewed_in_google_studio'))
   elif path=='/api/styles/save':
    from profiles import save_profile
    v=save_profile(s,d['project'],d['name'])
   elif path=='/api/styles/apply':
    from profiles import apply_profile
    v=apply_profile(s,d['project'],d['profile'])
   elif path=='/api/styles/default':
    from profiles import set_default
    v=set_default(s,d['profile'])
   elif path=='/api/rules/propose':v=s.propose_rule(d['project'],d['feedback'],d['key'],d['value'])
   elif path=='/api/rules/status':v=s.rule_status(d['project'],d['rule'],d['status'])
   elif path=='/api/intake/save':
    from intake import save
    v=save(s,d)
   elif path=='/api/intake/start':
    from intake import start
    v=start(s,d)
   elif path=='/api/script-plan/save':
    from script_plan import save
    v=save(s,d)
   elif path=='/api/script-plan/approve':
    from script_plan import approve
    v=approve(s,d)
   elif path=='/api/script-drafts/save':
    from script_workspace import save
    v=save(s,d)
   elif path=='/api/timeline/start':
    v=s.project(d['project']);a=s.asset(d['asset'])
    if a['project']!=v['id'] or a['kind']!='video':raise Invalid('اختَر الفيديو الخام من نفس الحلقة')
    from media import probe
    info=probe(a['path']);t={'phase':'raw','primary_video_asset_id':a['id'],'fps':24,'duration_frames':int(a['duration']*24),'tracks':[{'id':k,'kind':k,'clips':[]} for k in ['video','text','voice','graphics','music','effects']]}
    for k in ['video','voice']:
     if k=='voice' and not any(x['codec_type']=='audio' for x in info['streams']):continue
     next(x for x in t['tracks'] if x['kind']==k)['clips']=[{'id':secrets.token_hex(12),'asset_id':a['id'],'start_frame':0,'end_frame':t['duration_frames'],'source_in_frame':0,'source_out_frame':t['duration_frames'],'properties':{'volume':1}}]
    v=s.save(v['id'],d['expected'],t,'تهيئة مسودة من الخام دون حذف كلمات')
   elif path=='/api/feedback':s.feedback(d['project'],d['revision'],d['time_ms'],d['category'],d['note'],d.get('output_job'));v=s.project(d['project'])
   else:return self.send(404,{'error':'الوظيفة غير متاحة'})
   self.send(200,v)
  except PermissionError as e:self.send(403,{'error':str(e)})
  except Conflict as e:self.send(409,{'error':str(e)})
  except (Invalid,KeyError,ValueError,TypeError,AttributeError,json.JSONDecodeError) as e:self.send(400,{'error':str(e)})
  except (OSError,subprocess.SubprocessError) as e:self.send(400,{'error':'تعذر فحص الملف المحلي. تأكد من صلاحيته وإعداد أداة الوسائط.'})
 def upload(self):
  s=self.server.app.store;q=urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query);project=q['project'][0];from lifecycle import open_project
  open_project(s,project);s.project(project);name=Path(urllib.parse.unquote(self.headers.get('X-File-Name','video.mp4'))).name;ext=Path(name).suffix.lower()
  if ext not in ['.mp4','.mov','.webm','.mkv','.wav','.mp3','.m4a','.opus','.png','.jpg','.jpeg','.webp','.txt','.srt','.docx','.md']:raise Invalid('نوع الملف غير مدعوم')
  size=int(self.headers.get('Content-Length','0'))
  if not 0<size<=8*1024**3 or shutil.disk_usage(s.root).free-size<5*1024**3:raise Invalid('الملف كبير أو مساحة الجهاز غير كافية')
  folder=s.root/'uploads'/secrets.token_hex(16);folder.mkdir(parents=True);p=folder/name;temp=folder/'upload.part'
  try:
   with temp.open('wb') as f:
    remaining=size
    while remaining:
     block=self.rfile.read(min(1024*1024,remaining))
     if not block:raise Invalid('رفع الملف لم يكتمل')
     f.write(block);remaining-=len(block)
   temp.replace(p);kind='video' if ext in ['.mp4','.mov','.webm','.mkv'] else 'audio' if ext in ['.wav','.mp3','.m4a','.opus'] else 'image' if ext in ['.png','.jpg','.jpeg','.webp'] else 'script';duration=0
   from media import probe,read_script,duration as media_duration
   if kind in ['video','audio']:duration=media_duration(probe(p),kind)
   if kind=='script':read_script(p)
   a=s.add_asset(project,str(p),duration,kind);self.send(200,{'asset_id':a,'project':s.project(project)})
  except Exception:
   if temp.exists():temp.unlink()
   raise
 def media(self,p):
  size=p.stat().st_size;start=0;end=size-1;range_=self.headers.get('Range');status=200
  if range_:
   try:
    if not range_.startswith('bytes=') or ',' in range_:raise ValueError()
    lo,hi=range_[6:].split('-')
    if lo:start=int(lo);end=min(int(hi),end) if hi else end
    else:start=max(0,size-int(hi))
    if start<0 or start>end or start>=size:raise ValueError()
    status=206
   except ValueError:
    self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return
  self.send_response(status);self.send_header('Content-Type',mimetypes.guess_type(p)[0] or 'application/octet-stream');self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
  if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
  self.end_headers()
  with p.open('rb') as f:
   f.seek(start);left=end-start+1
   while left:
    b=f.read(min(256*1024,left))
    if not b:break
    self.wfile.write(b);left-=len(b)
def main():
 p=argparse.ArgumentParser();p.add_argument('--data',default=str(BASE/'.local-data'));p.add_argument('--port',type=int,default=8877);p.add_argument('--allow',action='append');a=p.parse_args();app=App(a.data,a.allow or [str(ROOT)],a.port);server=ThreadingHTTPServer(('127.0.0.1',a.port),Handler);server.app=app;app.recover();app.watch_workflows();print(f'Montaj local: http://127.0.0.1:{a.port}',flush=True);server.serve_forever()
if __name__=='__main__':main()

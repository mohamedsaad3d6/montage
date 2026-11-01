"""Explicit raw inputs; selection alone never changes speech or starts processing."""
import copy,json,math,time
from core import Invalid,Conflict,uid,dump,fingerprint

def init(store):
 with store.connect() as c:c.execute('CREATE TABLE IF NOT EXISTS control_intake(project TEXT PRIMARY KEY,version INTEGER,data TEXT)')

def get(store,project):
 store.project(project);init(store)
 with store.connect() as c:r=c.execute('SELECT * FROM control_intake WHERE project=?',(project,)).fetchone()
 return {'project':project,'version':r['version'] if r else 0,'selection':json.loads(r['data']) if r else {'video':None,'script':None,'voice':None,'voice_mode':'camera','audio_offset_frames':0}}

def checked_asset(store,project,id,kind):
 from lifecycle import open_asset
 open_asset(store,id);a=store.asset(id)
 if a['project']!=project or a['kind']!=kind or a['source_type']=='review_evidence':raise Invalid('اختَر نوع الملف الصحيح من نفس الحلقة')
 if fingerprint(store.resolve(a['path']))!=a['hash']:raise Invalid('الملف تغير بعد إضافته؛ أضف الأصل الصحيح مجددًا')
 return a

def save(store,data):
 project=data['project'];old=get(store,project)
 if type(data.get('expected_version'))!=int or old['version']!=data['expected_version']:raise Conflict('المدخلات تغيرت؛ حدّث الصفحة')
 selection=copy.deepcopy(old['selection'])
 for key,kind in [('video','video'),('voice','audio'),('script','script')]:
  if key in data:
   if data[key]:checked_asset(store,project,data[key],kind)
   selection[key]=data[key] or None
 if 'voice_mode' in data:
  if data['voice_mode'] not in ['camera','external','external_cut']:raise Invalid('اختَر مصدر الصوت')
  selection['voice_mode']=data['voice_mode']
 if 'audio_offset_frames' in data:
  n=data['audio_offset_frames']
  if type(n)!=int or n<0:raise Invalid('بداية الصوت تحتاج عدد إطارات غير سالب؛ لا نمدد أو نقتطع الكاميرا خفية')
  selection['audio_offset_frames']=n
 with store.connect() as c:
  c.execute('BEGIN IMMEDIATE');from lifecycle import open_project,open_asset
  open_project(store,project,c)
  for key in ['video','voice','script']:
   if selection.get(key):open_asset(store,selection[key],c)
  r=c.execute('SELECT version FROM control_intake WHERE project=?',(project,)).fetchone()
  if (r['version'] if r else 0)!=old['version']:raise Conflict('المدخلات تغيرت أثناء الحفظ')
  c.execute('INSERT OR REPLACE INTO control_intake VALUES(?,?,?)',(project,old['version']+1,dump(selection)))
 return get(store,project)

def start(store,data):
 project=data['project'];p=store.project(project);state=get(store,project)
 if state['version']!=data.get('input_version'):raise Conflict('اختيارات الملفات تغيرت؛ حدّث الصفحة')
 if p['active']!=data['expected']:raise Conflict('نسخة الحلقة تغيرت')
 if p['revision']['timeline']['duration_frames']:raise Invalid('الحلقة بها نسخة بالفعل؛ أنشئ حلقة مستقلة لتجربة خام جديد')
 sel=state['selection']
 if not sel['video']:raise Invalid('اختَر الفيديو الخام أولًا')
 video=checked_asset(store,project,sel['video'],'video')
 from media import probe
 info=probe(video['path']);fps=24;n=int(video['duration']*fps)
 if n<1:raise Invalid('الفيديو بلا مدة صالحة')
 voice=video;offset=0
 if sel['voice_mode']=='external_cut':raise Invalid('الصوت بعد التقطيع يحتاج خطة مطابقة مقاطع موثقة، وليس إزاحة توقيت واحدة')
 if sel['voice_mode']=='external':
  if not sel['voice']:raise Invalid('اختَر ملف الصوت الخام')
  voice=checked_asset(store,project,sel['voice'],'audio')
  with store.connect() as c:job=c.execute("SELECT * FROM jobs WHERE id=? AND project=? AND revision=? AND kind='input_prepare' AND status='completed'",(data.get('sync_job'),project,p['active'])).fetchone()
  proof=json.loads(job['result'] or '{}') if job else {}
  if proof.get('sync_status')!='measured_three_windows' or proof.get('input_version')!=state['version'] or proof.get('video_sha256')!=video['hash'] or proof.get('voice_sha256')!=voice['hash'] or proof.get('voice_id')!=voice['id']:raise Invalid('فحص التزامن التلقائي مطلوب قبل ربط الصوت الخارجي؛ اضغط ابدأ الشغل')
  offset=proof['offset_frames']
  if offset+n>math.floor(voice['duration']*fps):raise Invalid('ملف الصوت لا يغطي الفيديو كاملًا عند البداية المختارة؛ لن نكرر أو نمدد الصوت')
  if not any(x['codec_type']=='audio' for x in probe(voice['path'])['streams']):raise Invalid('ملف الصوت بلا قناة صوتية')
 elif not any(x['codec_type']=='audio' for x in info['streams']):raise Invalid('الفيديو بلا صوت كاميرا؛ اختَر صوتًا خارجيًا')
 t={'phase':'raw','primary_video_asset_id':video['id'],'fps':fps,'duration_frames':n,'tracks':[{'id':k,'kind':k,'clips':[]} for k in ['video','text','voice','graphics','music','effects']], 'intake':{'version':state['version'],'script_asset_id':sel['script'],'external_sync_user_confirmed':False,'sync_job':data.get('sync_job'),'external_sync_measured':sel['voice_mode']=='external','independent_audio_review_passed':False}}
 for kind,asset,begin in [('video',video,0),('voice',voice,offset)]:next(x for x in t['tracks'] if x['kind']==kind)['clips']=[{'id':uid(),'asset_id':asset['id'],'start_frame':0,'end_frame':n,'source_in_frame':begin,'source_out_frame':begin+n,'properties':{'volume':1}}]
 return store.save(project,data['expected'],t,'تجهيز الخام من المدخلات المختارة دون حذف كلام أو اعتماد مراجعة')

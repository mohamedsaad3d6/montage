"""Observed worker phases and measured durations; never estimated completion percentages."""
import time
from core import Invalid
LABELS={'storyblocks_autoselect':'اختيار لقطات الحلقة تلقائيًا','storyblocks_plan':'فهم جمل الحلقة وتحديد اللقطات المطلوبة','storyblocks_rank':'مقارنة اللقطات بالكلام واستبعاد غير المناسب','storyblocks_search':'البحث في Storyblocks عن لقطات الحلقة','storyblocks_collect':'تنزيل لقطة Storyblocks المختارة وإضافتها للمكتبة','codex_thinking':'Codex يفهم الحلقة ويختار الخطوة التالية','codex_plan':'قرار مدير الحلقة Codex','take_assess':'مقارنة المحاولات سمعيًا آليًا','generate_music':'تأليف موسيقى أصلية محليًا وضبط مدتها','archive_collect':'تنزيل الخامة وفحصها وإضافتها للمكتبة','reference_acoustic_full':'التحقق الصوتي الموسع لمطابقة الصورة','reference_coarse_match':'البحث عن مقاطع الصوت المرجعي داخل الخام كاملًا','reference_acoustic_match':'التحقق الصوتي من عينات الجمل المتطابقة','reference_camera_asr':'تفريغ كلام الفيديو الخام للمطابقة','reference_master_asr':'تفريغ الصوت بعد التقطيع كمرجع','reference_word_match':'مطابقة الجمل والمحاولات بين الخام والمرجع','sync_beginning':'فحص تزامن الصوت في البداية','sync_middle':'فحص تزامن الصوت في المنتصف','sync_ending':'فحص تزامن الصوت في النهاية','source_check':'التحقق من الملفات الأصلية','voice_prepare':'تجهيز مسار الصوت المتزامن','audio_extract':'استخراج صوت التحليل','asr':'تفريغ الكلام العربي','reuse':'استرجاع تفريغ يطابق بصمة الصوت','word_candidates':'استخراج الكلمات والمواضع المرشحة','ctc':'محاذاة الكلمات المصرية المستقلة','forced':'تدقيق توقيت حدود الكلمات','breath':'فحص مواضع النَّفَس','cut_plan':'بناء خطة التقطيع المرشحة','final_verify':'التحقق من بقاء المصادر سليمة','render':'إخراج الصوت والصورة','generate_graphic':'توليد الموشن المحلي','preview_transition':'تجهيز معاينة الانتقال','archive_search':'البحث في المصادر الأرشيفية','inspect_asset':'فحص الخامة','shot_plan':'مقارنة الخامات بالكلام','audio_review':'تجهيز المراجعة الصوتية'}

def record(store,job,phase):
 if phase not in LABELS:raise Invalid('مرحلة تشغيل غير معروفة')
 now=time.time()
 with store.connect()as c:
  c.execute('BEGIN IMMEDIATE');j=store.one(c,'SELECT status FROM jobs WHERE id=?',(job,))
  if j['status']!='running':return False
  previous=c.execute('SELECT sequence,phase FROM control_job_activity WHERE job=? ORDER BY sequence DESC LIMIT 1',(job,)).fetchone()
  if previous and previous['phase']==phase:return False
  sequence=previous['sequence']+1 if previous else 1
  c.execute('UPDATE control_job_activity SET finished=? WHERE job=? AND finished IS NULL',(now,job));c.execute('INSERT INTO control_job_activity VALUES(?,?,?,?,?)',(job,sequence,phase,now,None))
 return True

def finish(store,job):
 with store.connect()as c:
  c.execute('BEGIN IMMEDIATE');j=store.one(c,'SELECT status FROM jobs WHERE id=?',(job,))
  if j['status'] in ['completed','failed','cancelled']:c.execute('UPDATE control_job_activity SET finished=? WHERE job=? AND finished IS NULL',(time.time(),job))

def attach(store,project,jobs):
 with store.connect()as c:rows=[dict(r)for r in c.execute('SELECT a.* FROM control_job_activity a JOIN jobs j ON j.id=a.job WHERE j.project=? ORDER BY a.sequence',(project,))]
 now=time.time();byjob={}
 for r in rows:byjob.setdefault(r['job'],[]).append(r)
 for job in jobs:
  history=[]
  for r in byjob.get(job['id'],[]):
   end=r['finished'] if r['finished'] is not None else now if job['status']=='running' else None
   history.append({'phase':r['phase'],'label':LABELS.get(r['phase'],'مرحلة محفوظة'),'started':r['started'],'finished':r['finished'],'elapsed_seconds':max(0,end-r['started']) if end is not None else None})
  job['activity']={'current':history[-1] if history else None,'history':history,'percent_estimated':False,'independent_review_granted':False}
 return jobs


def snapshot(store,project):
 """Lightweight read for the live banner, with no render hashing or release decisions."""
 from lifecycle import open_project
 open_project(store,project)
 with store.connect()as c:
  p=store.one(c,'SELECT id,active FROM projects WHERE id=?',(project,));jobs=[dict(j)for j in c.execute('SELECT id,revision,kind,status,checkpoint,total,created FROM jobs WHERE project=? ORDER BY created DESC',(project,))]
 attach(store,project,jobs)
 return {**p,'jobs':jobs,'independent_review_granted':False,'publication_approved':False}

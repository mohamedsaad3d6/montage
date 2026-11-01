"""Small, explicit edit plans. Unsupported requests never become guessed cuts."""
import copy,json,re,time
from core import Invalid,Conflict,uid,dump

def init(store):
 with store.connect() as c:c.execute('CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY,project TEXT,base TEXT,request TEXT,operations TEXT,status TEXT,result_revision TEXT,created REAL)')
def propose(store,project,text):
 init(store);v=store.project(project);text=str(text).strip()
 if not text or len(text)>4000:raise Invalid('اكتب طلب التعديل')
 normalized=text.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩','0123456789'));ops=[]
 if re.search(r'(الكارت|الكروت|العنوان).*(سريع|بسرعة|قراء|مدة)',text):ops.append({'type':'card_duration','seconds':4,'description':'إطالة العناوين إلى ٤ ثوانٍ حيث تسمح مساحة التايملاين دون تداخل'})
 match=re.search(r'(?:العنوان|عنوان)\s*[:：]\s*(.{1,200})',text)
 if match:ops.append({'type':'title','text':match.group(1),'seconds':4,'description':'إضافة أو تعديل العنوان المهم الأول لمدة ٤ ثوانٍ'})
 vol=re.search(r'(?:الصوت|صوت)\D{0,12}(\d{1,3})\s*(?:%|٪|بالمية)',normalized)
 if vol:
  level=int(vol.group(1))
  if not 0<=level<=100:raise Invalid('اختَر مستوى صوت من صفر إلى مئة')
  ops.append({'type':'volume','value':level/100,'description':'ضبط مستوى التعليق الصوتي حسب النسبة المطلوبة'})
 status='proposed' if ops else 'needs_editorial_review';pid=uid()
 with store.connect() as c:c.execute('INSERT INTO plans VALUES(?,?,?,?,?,?,?,?)',(pid,project,v['active'],text,dump(ops),status,None,time.time()))
 return get(store,pid)
def get(store,p):
 with store.connect() as c:v=store.one(c,'SELECT * FROM plans WHERE id=?',(p,))
 v['operations']=json.loads(v['operations']);return v

def apply(store,p):
 plan=get(store,p)
 if plan['status']!='proposed':raise Invalid('هذه الخطة غير قابلة للتطبيق أو طُبقت سابقًا')
 v=store.project(plan['project'])
 if v['active']!=plan['base']:raise Conflict('النسخة اتغيرت بعد اقتراح الخطة؛ راجع خطة جديدة')
 t=copy.deepcopy(v['revision']['timeline']);fps=t['fps'];text=next(x for x in t['tracks'] if x['kind']=='text')
 for op in plan['operations']:
  if op['type']=='volume':
   for tr in t['tracks']:
    if tr['kind']=='voice':
     for c in tr['clips']:c.setdefault('properties',{})['volume']=op['value']
  elif op['type']=='title':
   if not t['duration_frames']:raise Invalid('أضف فيديو قبل تعديل عنوان')
   if not text['clips']:text['clips'].append({'id':uid(),'start_frame':0,'end_frame':min(t['duration_frames'],4*fps),'properties':{}})
   text['clips'][0].setdefault('properties',{})['text']=op['text']
  elif op['type']=='card_duration':
   ordered=sorted(text['clips'],key=lambda x:x['start_frame'])
   if not ordered:raise Invalid('لا توجد عناوين بعد؛ أضف عنوانًا أولًا')
   for i,c in enumerate(ordered):
    end=c['start_frame']+round(op['seconds']*fps);limit=ordered[i+1]['start_frame'] if i+1<len(ordered) else t['duration_frames']
    if end>limit:raise Invalid('إطالة العنوان ستتداخل مع عنوان آخر؛ يلزم توزيع التوقيت أولًا')
    c['end_frame']=max(c['end_frame'],end)
 result=store.save(v['id'],plan['base'],t,'تطبيق خطة تعديل معتمدة')
 with store.connect() as c:c.execute("UPDATE plans SET status='applied',result_revision=? WHERE id=?",(result['active'],p))
 return result

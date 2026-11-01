"""Versioned channel planning kit. References are not implicit render approvals."""
import json,math,re,time
from core import Invalid,Conflict,dump
from workspace import init as init_channels
SLOTS={'logo':{'image'},'intro':{'video'},'outro':{'video'},'music':{'audio'},'effects':{'audio'}}
DEFAULT={'handle':'','color':'#F2A93B','font':'','pace':50,'video_share':70,'graphics':35,'transition_ids':[],'assets':{k:[] for k in SLOTS}}
def init(store):
 init_channels(store)
 with store.connect() as c:c.execute('CREATE TABLE IF NOT EXISTS control_channel_kits(channel TEXT,version INTEGER,data TEXT,created REAL,PRIMARY KEY(channel,version))')
def get(store,channel):
 init(store)
 with store.connect() as c:
  store.one(c,'SELECT id FROM control_channels WHERE id=?',(channel,))
  r=c.execute('SELECT * FROM control_channel_kits WHERE channel=? ORDER BY version DESC LIMIT 1',(channel,)).fetchone()
 value={'channel':channel,'version':r['version'] if r else 0,'data':json.loads(r['data']) if r else json.loads(dump(DEFAULT)),'automatic_application':False}
 from channel_reference import approved
 value['reference']=approved(store,channel)
 value['files']={}
 for slot,ids in value['data']['assets'].items():
  value['files'][slot]=[]
  for id in ids:
   a=store.asset(id);value['files'][slot].append({k:a[k] for k in ['id','project','name','kind','hash']})
 return value

def save(store,payload):
 channel=payload.get('channel');current=get(store,channel);data=payload.get('data')
 if not isinstance(data,dict) or set(data)-set(DEFAULT):raise Invalid('إعدادات كيت غير صالحة')
 out=json.loads(dump(DEFAULT));out.update(data)
 for key,limit in [('handle',100),('font',120)]:
  if not isinstance(out[key],str) or len(out[key])>limit or any(ord(x)<32 for x in out[key]):raise Invalid('النص المختار غير صالح')
 if not isinstance(out['color'],str) or not re.fullmatch('#[0-9a-fA-F]{6}',out['color']):raise Invalid('لون القناة غير صالح')
 for key in ['pace','video_share','graphics']:
  if type(out[key])!=int or not 0<=out[key]<=100:raise Invalid('تفضيلات القناة يجب أن تكون بين صفر ومئة')
 ids=out['transition_ids']
 if not isinstance(ids,list) or len(ids)>30 or any(not isinstance(x,str) for x in ids) or len(set(ids))!=len(ids):raise Invalid('قائمة انتقالات غير صالحة')
 if ids:
  from pathlib import Path
  catalogue=json.loads((Path(__file__).resolve().parents[1]/'library/our-transitions-01/catalog.json').read_text())
  known={x['id'] for x in catalogue['recipes']}
  if any(id not in known for id in ids):raise Invalid('انتقال غير موجود بالمكتبة')
 assets=out['assets']
 if not isinstance(assets,dict) or set(assets)!=set(SLOTS):raise Invalid('فئات ملفات القناة غير صالحة')
 from media import file_hash
 with store.connect() as c:
  assigned={x['project'] for x in c.execute('SELECT project FROM control_project_channels WHERE channel=?',(channel,))}
 for slot,ids in assets.items():
  if not isinstance(ids,list) or len(ids)>30 or any(not isinstance(x,str) for x in ids) or len(set(ids))!=len(ids):raise Invalid('قائمة ملفات مكررة أو كبيرة')
  for id in ids:
   a=store.asset(id)
   if a['kind'] not in SLOTS[slot] or a['project'] not in assigned:raise Invalid('اربط حلقة الملف بنفس القناة واختر نوعًا يناسب الفئة')
   if a['source_type']=='review_evidence' or file_hash(store.resolve(a['path']))!=a['hash']:raise Invalid('الملف تغير أو هو دليل مراجعة وليس خامة')
 with store.connect() as c:
  version=c.execute('SELECT COALESCE(MAX(version),0) FROM control_channel_kits WHERE channel=?',(channel,)).fetchone()[0]
  if type(payload.get('expected_version'))!=int or version!=payload['expected_version']:raise Conflict('كيت القناة تغير؛ أعد تحميل الصفحة')
  c.execute('INSERT INTO control_channel_kits VALUES(?,?,?,?)',(channel,version+1,dump(out),time.time()))
 return get(store,channel)

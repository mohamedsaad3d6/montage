"""Real connection probes. No subscription changes, implicit credits, or private-key responses."""
import json,time,urllib.request,urllib.parse,urllib.error,threading,hmac,hashlib,os
from pathlib import Path
from core import Invalid
import storyblocks_connector as sb
LOCK=threading.Lock()
NAMES={'gemini','auphonic','magnific','commons','internet_archive','storyblocks'}
KEYS=Path.home()/'.config/monteer/keys.json'
AUPHONIC=Path.home()/'.config/montage/auphonic.json'
STORYBLOCKS=Path.home()/'.config/montaj/service-links/storyblocks.json'
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*a,**kw):raise Invalid('أعادت الخدمة توجيه الطلب؛ لم نرسل المفتاح إلى عنوان آخر')
def private_json(path):
 if not path.is_file():return {}
 if os.name!='nt' and path.stat().st_mode&0o077:raise Invalid('ملف اتصال الخدمة يحتاج صلاحيات خاصة لصاحب الجهاز')
 try:
  value=json.loads(path.read_text())
  if not isinstance(value,dict):raise Invalid('إعداد الخدمة يجب أن يكون سجلًا صالحًا')
  return value
 except (ValueError,OSError):raise Invalid('تعذر قراءة إعداد الخدمة المحلي')from None

def get_json(url,headers=None):
 try:
  with urllib.request.build_opener(NoRedirect).open(urllib.request.Request(url,headers=headers or {}),timeout=25)as r:
   data=r.read(4_000_001)
   if len(data)>4_000_000:raise Invalid('استجابة الخدمة أكبر من الحد المسموح')
   return json.loads(data)
 except urllib.error.HTTPError as e:raise Invalid('الخدمة أعادت HTTP '+str(e.code))from None
 except (urllib.error.URLError,TimeoutError,OSError,ValueError):raise Invalid('لم يكتمل اختبار الاتصال؛ لا إعادة تلقائية')from None

def records(s):
 path=s.root/'service-links.json'
 try:
  value=json.loads(path.read_text())
  if not isinstance(value,dict):raise Invalid('إعداد الخدمة يجب أن يكون سجلًا صالحًا')
  return value
 except (OSError,ValueError):return {}
def put(s,provider,value):
 with LOCK:
  data=records(s);data[provider]=value;path=s.root/'service-links.json';temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2));temp.replace(path)
 return value

def describe(s):
 data=records(s)
 try:keys=private_json(KEYS);ap=private_json(AUPHONIC);local_error=''
 except Invalid as e:keys={};ap={};local_error=str(e)
 out=[]
 for id in sorted(NAMES):
  configured={'auphonic':bool(ap.get('api_key')),'magnific':bool(keys.get('magnific_api_key')),'commons':True,'internet_archive':True,'storyblocks':(STORYBLOCKS.is_file() or sb.available()),'gemini':(Path.home()/'.config/monteer/gemini/connection.json').is_file()}[id]
  latest=data.get(id,{})
  age=time.time()-latest.get('checked_epoch',0)
  out.append({'id':id,'configured':bool(configured),'local_connector_available':id=='storyblocks' and sb.available(),'last_test':latest,'test_fresh':bool(latest and age<86400),'network_tested':latest.get('ok')is True and latest.get('scope')!='assistant_connector_search','assistant_search_verified':latest.get('scope')=='assistant_connector_search'and latest.get('ok')is True,'local_error':local_error,'automatic_processing':False,'credit_actions_require_explicit_consent':id in ('magnific','auphonic'),'assistant_only':id=='storyblocks'and not configured,'prepared_only':latest.get('prepared_only')is True,'can_test':(id!='storyblocks'or STORYBLOCKS.is_file()or sb.available())and not latest.get('prepared_only',False)})
 return {'services':out,'keys_in_response':False,'automatic_billing':False}

def check(s,provider,allow_credit_test=False):
 if provider not in NAMES:raise Invalid('خدمة غير معروفة')
 if provider=='storyblocks'and not STORYBLOCKS.is_file()and not sb.available():raise Invalid('ثبّت Codex وسجّل الدخول لتفعيل Storyblocks على هذا الجهاز')
 if provider=='magnific'and records(s).get('magnific',{}).get('prepared_only'):raise Invalid('استهلاك Magnific مقفول بطلبك؛ الربط مجهز فقط دون اختبار')
 if provider=='magnific'and allow_credit_test is not True:raise Invalid('اختبار Magnific قد يستهلك رصيدًا؛ يحتاج موافقة صريحة على طلب بحث واحد')
 value={'checked_epoch':time.time(),'ok':False,'provider':provider,'processing_started':False,'download_started':False,'billing_changed':False}
 try:
  if provider=='gemini':
   import sys
   sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'engine'))
   from monteer.audio_review.pipeline import credentials,MODEL
   try:key=credentials(str(Path.home()/'.config/monteer/gemini/connection.json'))
   except Exception:raise Invalid('إعداد Google المجاني يحتاج مراجعة؛ لم نرسل صوتًا')from None
   payload=get_json('https://generativelanguage.googleapis.com/v1beta/models/'+MODEL,{'x-goog-api-key':key})
   if not payload.get('name'):raise Invalid('لم يُثبت الوصول للنموذج المطلوب')
   value.update({'ok':True,'scope':'model_metadata_only','model':MODEL,'audio_sent':False,'independent_audio_review_verified':False})
  elif provider=='auphonic':
   cfg=private_json(AUPHONIC);key=cfg.get('api_key')
   if not key:raise Invalid('مفتاح Auphonic غير موجود في الإعداد الخاص خارج المشروع')
   payload=get_json('https://auphonic.com/api/user.json',{'Authorization':'bearer '+key});user=payload.get('data',{})
   if payload.get('status_code')!=200:raise Invalid('Auphonic لم يؤكد نجاح المصادقة')
   value.update({'ok':True,'scope':'account_read_only','remaining_hours':user.get('credits'),'paid_credit_pool':bool(user.get('is_paying_user')or user.get('onetime_credits',0)),'processing_requires_separate_approval':True})
  elif provider=='storyblocks' and sb.available():
   folder=s.root/'storyblocks-check';folder.mkdir(exist_ok=True)
   result=sb.search(folder,{'query':'city','subject':'city'})
   value.update({'ok':True,'scope':'local_codex_connector_search','results_count':len(result['results']),'licensed_download_tested':False,'production_downloads_enabled':True})
  elif provider=='storyblocks':
   cfg=private_json(STORYBLOCKS)
   if cfg.get('test_only')is not True:raise Invalid('هذا المحول يسمح بمفاتيح الاختبار الداخلي فقط دون تنزيل أو استخدام إنتاجي')
   path='/api/v2/videos/search';expires=str(int(time.time())+120);signature=hmac.new((cfg['secret_key']+expires).encode(),path.encode(),hashlib.sha256).hexdigest();params={'APIKEY':cfg['public_key'],'EXPIRES':expires,'HMAC':signature,'keywords':'oil tanker','results_per_page':1}
   response=get_json('https://api.storyblocks.com'+path+'?'+urllib.parse.urlencode(params))
   if not isinstance(response,dict) or not isinstance(response.get('results'),list) or response.get('error') or response.get('errors'):raise Invalid('استجابة Storyblocks غير صالحة')
   value.update({'ok':True,'scope':'local_test_api_search_only','production_downloads_enabled':False})
  elif provider=='magnific':
   key=private_json(KEYS).get('magnific_api_key')
   if not key:raise Invalid('مفتاح Magnific غير موجود في الإعداد الخاص خارج المشروع')
   payload=get_json('https://api.magnific.com/v1/videos?term=city&page=1',{'x-magnific-api-key':key,'Accept':'application/json'});items=payload.get('data')
   if not isinstance(items,list):raise Invalid('صيغة نتائج Magnific غير متوقعة')
   value.update({'ok':True,'scope':'one_explicitly_approved_stock_search','results_count':len(items),'credit_consumption_unknown':True})
  else:
   from archive import search
   result=search('oil tanker',[provider]);errors=result.get('source_errors')or result.get('errors')or[]
   if errors or result.get('status')!='completed':raise Invalid('لم ينجح اختبار المصدر الأرشيفي')
   value.update({'ok':True,'scope':'public_metadata_search','results_count':len(result.get('results',[]))})
 except Invalid as e:value['error']=str(e)
 except (OSError,ValueError,KeyError,TypeError):value['error']='تعذر الاتصال بالخدمة أو قراءة استجابتها؛ لم ينجح الاختبار'
 return put(s,provider,value)

def save_storyblocks(s,data):
 if data.get('test_only')is not True:raise Invalid('مطلوب تأكيد أنها مفاتيح اختبار داخلي')
 out={k:data.get(k)for k in ('public_key','secret_key')}
 if any(not isinstance(v,str)or not 8<=len(v)<=500 or any(c.isspace()for c in v)for v in out.values()):raise Invalid('أدخل مفتاحي الاختبار في حقول الربط المحلية')
 out['test_only']=True;STORYBLOCKS.parent.mkdir(parents=True,exist_ok=True);os.chmod(STORYBLOCKS.parent,0o700)
 temporary=STORYBLOCKS.with_suffix('.tmp');fd=os.open(str(temporary),os.O_CREAT|os.O_WRONLY|os.O_TRUNC,0o600)
 try:
  os.fchmod(fd,0o600)
  with os.fdopen(fd,'w')as f:json.dump(out,f)
  os.replace(temporary,STORYBLOCKS)
 except Exception:
  if temporary.exists():temporary.unlink()
  raise
 return {'saved':True,'verified':False,'test_only':True,'secrets_returned':False}

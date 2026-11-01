"""Bounded public-archive collection. No credentials, arbitrary URLs, or rights certification."""
import json,re,urllib.request,urllib.parse,urllib.error
from pathlib import Path
from core import Invalid
from media import probe,duration,Cancelled
from archive import get
MAX_BYTES=128*1024*1024
ALLOWED_EXT={'.mp4','.webm','.ogv','.mov','.jpg','.jpeg','.png','.webp','.mp3','.wav','.ogg','.flac','.m4a'}
MEDIA_EXT={'video':{'.mp4','.webm','.ogv','.mov'},'image':{'.jpg','.jpeg','.png','.webp'},'audio':{'.mp3','.wav','.ogg','.flac','.m4a'}}
def archive_kind(item,metadata,search_type):
 kind={'movies':'video','image':'image','audio':'audio'}.get(item.get('mediatype')or metadata.get('mediatype'))
 if search_type=='audio':return 'audio'
 if kind=='audio'and search_type=='visual':raise Invalid('نتيجة صوتية لا تطابق طلب خامة بصرية')
 if kind:return kind
 raise Invalid('نوع خامة الأرشيف غير محدد؛ لن نختار صورة مصغرة بدل الفيديو')

def select_archive_file(files,kind):
 candidates=[]
 for f in files:
  name=str(f.get('name',''));ext=Path(name).suffix.lower()
  if ext not in MEDIA_EXT[kind]or name.startswith('/')or '..'in name.split('/'):continue
  try:size=int(f.get('size',0))
  except (ValueError,TypeError):continue
  if not 0<size<=MAX_BYTES:continue
  if kind=='image':
   # Archive derivatives include tiny preview tiles; never use those as montage material.
   if 'thumb' in name.lower() or str(f.get('format','')).lower() in ('jpeg thumb','item tile'):continue
   candidates.append((0 if f.get('source')=='original'else 1,-size,name))
  else:candidates.append((0 if ext=='.mp4'else 1,size,name))
 if not candidates:raise Invalid('لا ملف من نوع الخامة المطلوبة داخل حد التنزيل')
 return min(candidates)[2]
def checked_url(url):
 u=urllib.parse.urlsplit(url);host=(u.hostname or '').lower()
 if u.scheme!='https'or u.username or u.password or u.port not in (None,443)or u.fragment or not(host=='upload.wikimedia.org'or host=='archive.org'or host.endswith('.archive.org')):raise Invalid('عنوان تنزيل خارج مصادر الأرشيف المسموحة')
 if any(x=='..'for x in urllib.parse.unquote(u.path).split('/')):raise Invalid('مسار تنزيل غير صالح')
 return url
class Redirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,req,fp,code,msg,headers,newurl):
  checked_url(newurl);return super().redirect_request(req,fp,code,msg,headers,newurl)
def download(url,path,cancel=lambda:False,max_bytes=MAX_BYTES):
 checked_url(url);path=Path(path);temp=path.with_suffix(path.suffix+'.part')
 try:
  request=urllib.request.Request(url,headers={'User-Agent':'MontajLocal/0.4 (public archive collection)'})
  with urllib.request.build_opener(Redirect).open(request,timeout=25)as response:
   checked_url(response.geturl());size=int(response.headers.get('Content-Length','0'))
   if size>max_bytes:raise Invalid('الخامة أكبر من حد التنزيل؛ اختَر ملفًا أخف')
   total=0
   with temp.open('xb')as output:
    while True:
     if cancel():raise Cancelled()
     block=response.read(256*1024)
     if not block:break
     total+=len(block)
     if total>max_bytes:raise Invalid('الخامة تجاوزت حد التنزيل؛ أوقفنا الاستيراد')
     output.write(block)
  if not total:raise Invalid('المصدر أعاد ملفًا فارغًا')
  temp.replace(path)
 except BaseException:
  temp.unlink(missing_ok=True);raise

def collect(store,rev,folder,options,cancel=lambda:False):
 with store.connect()as c:j=store.one(c,'SELECT * FROM jobs WHERE id=?',(options.get('search_job'),))
 if j['project']!=rev['project']or j['revision']!=rev['id']or j['kind']!='archive_search'or j['status']!='completed':raise Invalid('اختَر نتيجة بحث محفوظة من نفس الحلقة والنسخة')
 saved=json.loads(j['result']or'{}');items=saved.get('results',[]);item=next((x for x in items if x['source']==options.get('source')and str(x['id'])==str(options.get('item_id'))),None)
 if item is None:raise Invalid('الخامة ليست ضمن نتيجة البحث المختارة')
 url=item.get('media_url');claim=item.get('license_claim');license_url=item.get('license_url');expected_kind=None
 if saved.get('media_type')=='audio':expected_kind='audio'
 if item['source']=='internet_archive':
  identifier=str(item['id'])
  if not re.fullmatch('[A-Za-z0-9_.-]{1,160}',identifier):raise Invalid('معرّف أرشيف غير صالح')
  meta=get('https://archive.org/metadata/'+urllib.parse.quote(identifier,safe=''))
  expected_kind=archive_kind(item,meta.get('metadata',{}),saved.get('media_type'))
  name=select_archive_file(meta.get('files',[]),expected_kind);url='https://archive.org/download/'+urllib.parse.quote(identifier,safe='')+'/'+urllib.parse.quote(name,safe='/')
  claim=meta.get('metadata',{}).get('licenseurl',claim);license_url=claim
 if not url:raise Invalid('لا رابط ملف مباشر متاح لهذه النتيجة')
 checked_url(url);ext=Path(urllib.parse.unquote(urllib.parse.urlsplit(url).path)).suffix.lower()
 if ext not in ALLOWED_EXT:raise Invalid('نوع الملف ليس من الوسائط المدعومة؛ لم ننزله')
 folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);path=folder/('archive-material'+ext);download(url,path,cancel)
 try:
  info=probe(path);streams=info.get('streams',[]);moving=[x for x in streams if x.get('codec_type')=='video'and not x.get('disposition',{}).get('attached_pic')]
  kind='image'if ext in {'.jpg','.jpeg','.png','.webp'}else 'video'if moving else 'audio'if any(x.get('codec_type')=='audio'for x in streams)else None
  if kind is None:raise Invalid('الملف ليس فيديو أو صورة أو صوتًا صالحًا')
  if expected_kind and kind!=expected_kind:raise Invalid('محتوى الملف لا يطابق نوع الخامة المطلوبة')
  if saved.get('media_type')=='visual'and kind=='audio':raise Invalid('طلب الخامة بصري لكن المصدر أعاد صوتًا فقط')
  seconds=0 if kind=='image'else duration(info,kind)
  asset_id=store.add_asset(rev['project'],str(path),seconds,kind)
 except Exception:
  path.unlink(missing_ok=True);raise
 metadata={'archive_source':item['source'],'archive_id':str(item['id']),'page_url':item.get('page_url'),'download_url':url,'license_claim':claim,'license_url':license_url,'rights_verified':False,'visual_verified':False,'audio_content_verified':False,'requires_rights_review_for_this_project':True,'collected_from_search_job':j['id']}
 with store.connect()as c:c.execute("UPDATE assets SET name=?,source_type='archive',metadata=? WHERE id=?",(str(item['title'])[:240],json.dumps(metadata,ensure_ascii=False),asset_id))
 return {'asset_id':asset_id,'kind':kind,'collected':True,'rights_verified':False,'visual_verified':False,'timeline_changed':False,'source':item['source'],'bytes':path.stat().st_size,'scope':'downloaded_and_probed_not_editorially_approved'}

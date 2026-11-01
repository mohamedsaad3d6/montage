"""Public archive discovery only. No automatic download or rights/visual certification."""
import json,urllib.request,urllib.parse

def get(url):
 req=urllib.request.Request(url,headers={'User-Agent':'MontajLocal/0.3 (local editorial research; public metadata only)','Accept':'application/json'})
 with urllib.request.urlopen(req,timeout=18) as r:
  data=r.read(3*1024*1024+1)
  if len(data)>3*1024*1024:raise ValueError('استجابة الأرشيف أكبر من الحد المسموح')
  return json.loads(data)

def search(query,sources,media_type='visual'):
 query=str(query).strip()
 if not 2<=len(query)<=180:raise ValueError('اكتب كلمات بحث بين حرفين و١٨٠ حرفًا')
 if not isinstance(sources,list) or not sources or any(x not in ['commons','internet_archive'] for x in sources):raise ValueError('مصدر بحث غير صالح')
 if media_type not in ('visual','audio'):raise ValueError('نوع خامة غير صالح')
 results=[];errors=[]
 for source in dict.fromkeys(sources):
  try:
   if source=='commons':
    args={'action':'query','format':'json','generator':'search','gsrsearch':query+(' filetype:audio' if media_type=='audio' else ''),'gsrnamespace':6,'gsrlimit':10,'prop':'imageinfo','iiprop':'url|extmetadata','iiurlwidth':320}
    data=get('https://commons.wikimedia.org/w/api.php?'+urllib.parse.urlencode(args))
    if not isinstance(data,dict)or data.get('error'):raise ValueError('Archive metadata API rejected the query')
    for page in data.get('query',{}).get('pages',{}).values():
     image=next(iter(page.get('imageinfo',[])),{});meta=image.get('extmetadata',{})
     results.append({'source':source,'id':str(page['pageid']),'title':page['title'],
                     'page_url':image.get('descriptionurl'),'media_url':image.get('url'),
                     'thumbnail_url':image.get('thumburl'),'license_claim':meta.get('LicenseShortName',{}).get('value',''),
                     'license_url':meta.get('LicenseUrl',{}).get('value',''),
                     'rights_verified':False,'visual_verified':False,'automatic_download':False})
   else:
    args=[('q',f'({query}) AND '+('(mediatype:audio)' if media_type=='audio' else '(mediatype:movies OR mediatype:image)')),('output','json'),('rows','10')]
    args.extend(('fl[]',x) for x in ['identifier','title','date','mediatype','licenseurl'])
    data=get('https://archive.org/advancedsearch.php?'+urllib.parse.urlencode(args))
    if not isinstance(data,dict)or data.get('error')or 'response'not in data:raise ValueError('Archive metadata API rejected the query')
    for item in data.get('response',{}).get('docs',[]):
     results.append({'source':source,'id':item['identifier'],'title':str(item.get('title','')),
                     'page_url':'https://archive.org/details/'+urllib.parse.quote(item['identifier'],safe=''),
                     'date':item.get('date'),'mediatype':item.get('mediatype'),'license_claim':item.get('licenseurl'),
                     'rights_verified':False,'visual_verified':False,'automatic_download':False})
  except (OSError,ValueError,KeyError) as e:
   errors.append({'source':source,'status':'unavailable','error_type':type(e).__name__})
 return {'query':query,'media_type':media_type,'status':'completed' if not errors else 'partial' if results else 'sources_unavailable',
         'results':results,'source_errors':errors,'automatic_download':False,
         'note':'نتائج اكتشاف، ليست مواد مرخصة أو مطابقة تلقائيًا. راجع المصدر واللقطات قبل الاستيراد.'}

"""Bounded source tools exposed to the episode director, using the existing queue."""
import json
from pathlib import Path
from core import Invalid
from media import ROOT

ACTIONS = ('storyblocks_search', 'archive_search', 'archive_collect', 'generate_graphic', 'generate_music', 'inspect_asset', 'preview_transition')
SOURCES = ('commons', 'internet_archive')

def parsed(value, default=None):
 if isinstance(value, str):
  try:return json.loads(value)
  except ValueError:return {} if default is None else default
 return value if value is not None else ({} if default is None else default)

def options_for(action, value, project):
 if action not in ACTIONS:raise Invalid('أداة المصادر غير مسموحة لمدير الحلقة')
 options = parsed(value)
 if not isinstance(options, dict):raise Invalid('إعدادات أداة المصادر غير صالحة')
 keys = {'storyblocks_search': {'query','subject','page'}, 'archive_search': {'query','sources','media_type'}, 'archive_collect': {'search_job','source','item_id'}, 'generate_graphic': {'template'}, 'generate_music': {'seconds','seed'}, 'inspect_asset': {'asset_id'}, 'preview_transition': {'from_asset_id','to_asset_id','recipe_id'}}[action]
 if set(options)-keys:raise Invalid('إعدادات غير مسموحة لأداة المصادر')
 assets = {a['id']: a for a in project['assets']}
 if action == 'storyblocks_search':
  from storyblocks_connector import options_for as sb_options, available
  if not available():raise Invalid('اتصال Storyblocks عبر Codex غير متاح على هذا الجهاز')
  options=sb_options(options)
 elif action == 'archive_search':
  q = options.get('query');sources = options.get('sources', list(SOURCES));media = options.get('media_type','visual')
  if not isinstance(q,str) or not 2<=len(q.strip())<=180 or not isinstance(sources,list) or not sources or any(s not in SOURCES for s in sources) or media not in ('visual','audio'):raise Invalid('استعلام بحث أو مصدر غير صالح')
  options = {'query':q.strip(),'sources':list(dict.fromkeys(sources)),'media_type':media}
 elif action == 'archive_collect':
  job = next((j for j in project['jobs'] if j['id']==options.get('search_job') and j['revision']==project['active'] and j['kind']=='archive_search' and j['status']=='completed'),None)
  if not job or not any(r.get('source')==options.get('source') and str(r.get('id'))==str(options.get('item_id')) for r in parsed(job.get('result')).get('results',[])):raise Invalid('الخامة ليست نتيجة بحث محفوظة من النسخة الحالية')
 elif action == 'generate_graphic':
  if options.get('template') not in {x['id'] for x in json.loads((ROOT/'app-local/graphics/catalog.json').read_text())}:raise Invalid('قالب موشن غير موجود')
 elif action == 'generate_music':
  if type(options.get('seconds')) not in (int,float) or not 6<=options['seconds']<=600 or type(options.get('seed',1)) is not int:raise Invalid('مدة الموسيقى أو إعدادها غير صالح')
 else:
  ids = [options.get('asset_id')] if action=='inspect_asset' else [options.get('from_asset_id'),options.get('to_asset_id')]
  if any(i not in assets or assets[i]['kind'] not in ('video','image') for i in ids):raise Invalid('اختَر خامات بصرية من الحلقة نفسها')
  if action=='preview_transition':
   from transitions import catalog
   if options.get('recipe_id') not in {r['id'] for r in catalog()['recipes']}:raise Invalid('الانتقال غير موجود بالمكتبة')
 # No blind retry of the same source request; the next decision must use another input/source.
 for j in project['jobs']:
  if j['revision']==project['active'] and j['kind']==action and parsed(j.get('options'))==options and j['status'] in ('queued','running','failed','completed'):
   raise Invalid('هذا الطلب مسجل بالفعل؛ استخدم نتيجته أو اختر خامة أو مصدرًا آخر')
 return options

def context(project):
 from transitions import catalog
 recipes=catalog()['recipes'];representatives={}
 for r in recipes:representatives.setdefault(r['family'],{'id':r['id'],'family':r['family']})
 searches=[]
 narration=[];narration_job=None;total_segments=0
 for job in project['jobs']:
  if job['revision']!=project['active'] or job['status']!='completed' or job['kind'] not in ('transcribe','editorial_plan'):continue
  segments=parsed(job.get('result')).get('transcript',[])
  if not segments:continue
  narration_job=job['id'];total_segments=len(segments)
  narration=[{k:s.get(k) for k in ('start_ms','end_ms','text','unreliable_asr')} for s in segments[:600]]
  break
 for job in project['jobs']:
  if job['revision']!=project['active'] or job['kind'] not in ACTIONS:continue
  r=parsed(job.get('result'))
  item={'job_id':job['id'],'kind':job['kind'],'status':job['status'],'options':parsed(job.get('options')),'error':job.get('error')}
  item['result']={k:r[k] for k in ('asset_id','status','collected','source','kind','source_errors','visual_verified') if k in r}
  if job['kind'] in ('archive_search','storyblocks_search'):item['result']['results']=[{k:x.get(k) for k in ('id','source','title','mediatype','license_claim','page_url','duration')} for x in r.get('results',[])[:20]]
  searches.append(item)
 automatic=[{'job_id':j['id'],**parsed(j.get('result'))} for j in project['jobs'] if j['revision']==project['active'] and j['kind']=='storyblocks_autoselect' and j['status']=='completed']
 return {'automatic_storyblocks':automatic[:1],'narration':{'job_id':narration_job,'revision':project['active'],'segments':narration,'total_segments':total_segments,'truncated':total_segments>len(narration),'note':'Use speech content for source selection. No transcript means no inferred episode content from its title.'},'available_tools':[a for a in ACTIONS if a!='storyblocks_search' or __import__('storyblocks_connector').available()],'archive_sources':list(SOURCES),'graphic_templates':json.loads((ROOT/'app-local/graphics/catalog.json').read_text()),'transition_count':len(recipes),'transition_family_examples':list(representatives.values()),'assets':[{'id':a['id'],'name':a['name'],'kind':a['kind'],'duration':a['duration'],'source_type':a.get('source_type'),'metadata':{k:v for k,v in parsed(a.get('metadata')).items() if k in ('subjects','visual_type','rights_verified','visual_verified','own_original','illustrative','represents_real_event','archive_source')}} for a in project['assets'][:150]],'source_jobs':searches[:40],'rules':['Use tool_options_json as a JSON object string with the fields documented for the chosen tool.','Use another source or item after failure; never repeat an identical request.','Collecting or generating an asset does not verify its meaning, license or suitability.','Do not change or approve the timeline through source tools.','Storyblocks search is available via the local connector. Previews are watermarked and cannot be used as assets. A user must select a specific item to authorize its licensed download in the library. Use collected and reviewed assets only.','Do not use Magnific, Auphonic processing, or an unconfigured provider.'],'option_fields':{'storyblocks_search':'query, subject (singular primary subject noun), page integer 1..100', 'archive_search':'query, sources [commons,internet_archive], media_type visual|audio','archive_collect':'search_job, source, item_id from a saved search','generate_graphic':'template from graphic_templates','generate_music':'seconds 6..600, seed integer','inspect_asset':'asset_id from assets','preview_transition':'from_asset_id, to_asset_id, recipe_id'}}

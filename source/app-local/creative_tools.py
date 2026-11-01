"""Typed production adapters: installation, binding and tested execution stay distinct."""
import json,os,shutil
from pathlib import Path
from media import ROOT
from creative_verification import verified

def describe(data_root):
 base=ROOT/'app-local';node=bool(os.environ.get('MONTAJ_NODE')or shutil.which('node'));browser=Path(os.environ.get('MONTAJ_CHROME','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')).is_file();deps=(base/'node_modules/@remotion/renderer').is_dir();python=Path(os.environ.get('MONTAJ_ML_PYTHON',str(ROOT.parent/'AI agent/monteer_data/envs/ml/bin/python'))).is_file()
 templates=json.loads((base/'graphics/catalog.json').read_text());catalog=json.loads((ROOT/'library/our-transitions-01/catalog.json').read_text());proof={}
 proof=verified(base,data_root,ROOT)
 items=[{'id':'motion','label':'الموشن والخرائط','available':node and browser and deps,'worker_job':'generate_graphic','choices':len(templates),'scope':'توليد محلي ثم إضافة خامة للمكتبة'},
 {'id':'graphics','label':'العناوين والجرافيك','available':node and browser and deps,'worker_job':'render','scope':'طبقات عربية متحركة داخل الإخراج الفعلي'},
 {'id':'transitions','label':'مكتبة الترانزيشن','available':node and browser and deps,'worker_job':'preview_transition','choices':len(catalog['recipes']),'families':len(set(x['family']for x in catalog['recipes'])),'all_recipes_individually_tested':False,'scope':'المعاينة والإخراج يستخدمان نفس محرك المكتبة'},
 {'id':'music','label':'الموسيقى والمؤثرات','available':python and (ROOT/'engine/monteer/music/code_bed.py').is_file(),'worker_job':'generate_music','scope':'توليد موسيقى محلي ومزج عدة مقاطع ومؤثرات وخفض تحت الكلام'},
 {'id':'archives','label':'تجميع خامات الأرشيف','available':True,'worker_job':'archive_collect','sources':['commons','internet_archive'],'scope':'بحث وتنزيل وفحص وربط بالمكتبة؛ لا اعتماد حقوق أو مناسبة تلقائيًا'}]
 for item in items:item.update(execution_verified=proof.get(item['id'],{}).get('passed')is True,verification_scope=proof.get(item['id'],{}).get('scope','لم يُسجّل اختبار تنفيذ مطابق لهذه الأداة بعد'))
 return {'tools':items,'external_requests_started':False,'automatic_episode':False,'verification_not_publication_approval':True}

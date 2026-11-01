"""Compile fully verified acoustic picture mapping; reference voice remains continuous."""
import json,math
from pathlib import Path
from core import Invalid,Conflict,uid,fingerprint
from intake import get,checked_asset

def apply(store,project,job_id,expected):
 p=store.project(project);state=get(store,project)
 if p['active']!=expected or p['revision']['timeline']['duration_frames']:raise Conflict('النسخة تغيرت؛ لا استبدال تلقائي لنسخة موجودة')
 with store.connect()as c:j=store.one(c,'SELECT * FROM jobs WHERE id=?',(job_id,))
 if j['project']!=project or j['revision']!=expected or j['kind']!='reference_refine'or j['status']!='completed':raise Invalid('خطة الصورة ليست من نفس الحلقة والنسخة')
 data=json.loads(j['result']or'{}');file=Path(data.get('report_file','')).resolve()
 if store.root not in file.parents or not file.is_file()or fingerprint(file)!=data.get('report_sha256'):raise Invalid('تقرير مطابقة الصورة تغير')
 report=json.loads(file.read_text())
 if report.get('mapping_ready')is not True or report.get('issues')or report.get('scope')!='picture_only_reference_voice_not_edited':raise Invalid('توجد مواضع صورة غير محسومة؛ لا تطبيق لخطة تقريبية')
 if report.get('source_revision')!=expected or report.get('project')!=project or report.get('input_version')!=state['version']or state['selection']['voice_mode']!='external_cut':raise Conflict('مرجع المطابقة لم يعد يطابق المدخلات')
 video=checked_asset(store,project,state['selection']['video'],'video');voice=checked_asset(store,project,state['selection']['voice'],'audio')
 if report.get('video_sha256')!=video['hash']or report.get('audio_sha256')!=voice['hash']:raise Invalid('المصادر لا تطابق دليل المطابقة')
 fps=report.get('fps');n=math.ceil(voice['duration']*fps)if type(fps)is int else 0
 if fps!=24 or n<1 or abs(n-report.get('duration_frames',-100))>1:raise Invalid('مدة خطة الصورة لا تغطي المرجع الصوتي')
 clips=[];cursor=0;source_end=-1
 for item in report['segments']:
  start=item['start_frame'];end=item['end_frame'];si=item['source_in_frame']
  if any(type(x)is not int for x in (start,end,si))or start!=cursor or end<=start or si<source_end:raise Invalid('خطة صورة غير متصلة أو تكرر المصدر')
  clips.append({'id':uid(),'asset_id':video['id'],'start_frame':start,'end_frame':end,'source_in_frame':si,'source_out_frame':si+end-start,'properties':{}});cursor=end;source_end=si+end-start
 if not clips or abs(cursor-n)>1:raise Invalid('خطة الصورة غير مكتملة')
 # At most one trailing picture frame covers the fractional end of the unchanged audio.
 clips[-1]['end_frame']=n;clips[-1]['source_out_frame']+=n-cursor
 t={'phase':'reference','fps':fps,'duration_frames':n,'primary_video_asset_id':video['id'],'tracks':[{'id':k,'kind':k,'clips':[]}for k in ['video','text','voice','graphics','music','effects']], 'intake':{'version':state['version'],'script_asset_id':state['selection'].get('script'),'voice_mode':'external_cut','picture_mapping_job':job_id,'independent_audio_review_passed':False},'picture_mapping':{'job':job_id,'report_file':str(file),'report_sha256':data['report_sha256'],'voice_source_unchanged':True,'scope':'picture_only'}}
 next(x for x in t['tracks']if x['kind']=='video')['clips']=clips
 next(x for x in t['tracks']if x['kind']=='voice')['clips']=[{'id':uid(),'asset_id':voice['id'],'start_frame':0,'end_frame':n,'source_in_frame':0,'source_out_frame':n,'properties':{'volume':1}}]
 def guard(c):
  row=c.execute('SELECT version FROM control_intake WHERE project=?',(project,)).fetchone()
  if not row or row['version']!=state['version']:raise Conflict('المدخلات تغيرت أثناء حفظ خطة الصورة')
 return store.save(project,expected,t,'إعادة بناء الصورة من مطابقة صوتية متعددة المقاطع؛ الصوت المرجعي كامل دون حذف؛ يحتاج مراجعة مستقلة',commit_guard=guard)

"""Verify a constant source mapping against post-cut audio; reject unverified speech/cuts.
This may verify a special case; it is not a general piecewise-EDL reconstruction.
"""
import json,math
from pathlib import Path
import numpy as np
from core import Invalid,fingerprint
from input_prepare import pcm,match

def intervals(points,step=1):
 out=[]
 for t in points:
  if out and t<=out[-1][1]+.001:out[-1][1]=t+step
  else:out.append([t,t+step])
 return out

def verify(source,reference,seeds,fps=24,cancel=lambda:False):
 offsets=[x['source_seconds']-x['reference_seconds']for x in seeds if x.get('passed')]
 if len(offsets)<3:raise Invalid('لا توجد مراسي صوتية كافية لفحص مطابقة الصورة')
 offset_frames=round(float(np.median(offsets))*fps);offset=offset_frames/fps
 # An affine proposal is accepted only after every reference window is checked.
 samples=[];bad=[];speech=0;good=0;quiet=0
 for sec in range(max(1,math.ceil(len(reference)/100)-2)):
  if cancel():
   from media import Cancelled
   raise Cancelled()
  q=reference[sec*100:min(len(reference),(sec+3)*100)]
  if len(q)<100:continue
  is_quiet=float(np.percentile(q,90))<math.log(.0025)
  if is_quiet:quiet+=1;continue
  speech+=1;left=max(0,sec+offset-1);right=min(len(source)/100,sec+offset+4);b=source[round(left*100):round(right*100)]
  try:
   lag,score,margin=match(q,b);measured=left+lag-sec;aligned=abs(measured-offset)<=.055;passed=score>=.65 and margin>=.025 and aligned
  except Invalid:score=0;margin=0;measured=None;passed=False
  if passed:good+=1
  else:bad.append(sec)
  # Keep all measurements for verification, no fake 100% from interpolation.
  samples.append({'reference_seconds':sec,'offset_seconds':measured,'correlation':score,'peak_margin':margin,'passed':passed})
 return {'proposal':'constant_offset_special_case','offset_frames':offset_frames,'fps':fps,'speech_windows':speech,'matched_speech_windows':good,'quiet_windows':quiet,'matched_fraction':good/speech if speech else 0,'unverified_intervals':intervals(bad),'all_speech_verified':bool(speech)and not bad,'measurements':samples,'automatic_cuts_applied':False,'independent_audio_review_passed':False}

def inspect(store,job,folder,cancel=lambda:False,expected_project=None,expected_revision=None):
 with store.connect()as c:j=store.one(c,'SELECT * FROM jobs WHERE id=?',(job,))
 if expected_project is not None and(j['project']!=expected_project or j['revision']!=expected_revision):raise Invalid('تقرير المطابقة من حلقة أو نسخة أخرى')
 if j['kind']!='input_prepare'or j['status']!='completed':raise Invalid('مطلوب تقرير مطابقة مكتمل')
 data=json.loads(j['result']or'{}')
 if data.get('sync_status')not in ('post_cut_reference_candidates','post_cut_acoustic_candidates'):raise Invalid('ليس مرجع صوت بعد التقطيع')
 v=store.asset(data['video_id']);a=store.asset(data['voice_id'])
 for asset,key in [(v,'video_sha256'),(a,'voice_sha256')]:
  if fingerprint(store.resolve(asset['path']))!=data[key]:raise Invalid('المصدر تغير بعد التحليل؛ لا خطة قابلة للتنفيذ')
 folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
 source=pcm(v['path'],0,v['duration'],folder,cancel);reference=pcm(a['path'],0,a['duration'],folder,cancel)
 from picture_alignment import align
 result=align(source,reference,data.get('coarse_acoustic_samples',[]),cancel=cancel)
 result['input_version']=data['input_version']
 result.update({'source_job':job,'source_revision':j['revision'],'project':j['project'],'video_sha256':v['hash'],'audio_sha256':a['hash'],'audio_unchanged':True,'video_asset_id':v['id'],'audio_asset_id':a['id']})
 report_file=folder/'acoustic-verification.json';report_file.write_text(json.dumps(result,ensure_ascii=False,indent=2));result.update(report_file=str(report_file),report_sha256=fingerprint(report_file));return result

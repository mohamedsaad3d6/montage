"""Piecewise acoustic picture mapping. Never removes/changes reference narration.
Unknown/ambiguous sections block application; ASR timestamps are not edit boundaries.
"""
import math
import numpy as np
from input_prepare import match
from core import Invalid
from media import Cancelled

def _runs(labels):
 starts=np.r_[0,np.flatnonzero(labels[1:]!=labels[:-1])+1];ends=np.r_[starts[1:],len(labels)]
 return [(int(a),int(b),int(labels[a]))for a,b in zip(starts,ends)]

def align(source,reference,seeds=(),fps=24,cancel=lambda:False,max_global=80):
 source=np.asarray(source,dtype=float);reference=np.asarray(reference,dtype=float)
 if not len(reference) or not len(source) or not np.isfinite(source).all() or not np.isfinite(reference).all():raise Invalid('عينات مطابقة الصورة غير صالحة')
 if np.std(reference)<.08:raise Invalid('مرجع صامت لا يثبت مطابقة الكلام')
 observations=[];global_calls=0
 def collect(pos,length=300):
  nonlocal global_calls
  if cancel():raise Cancelled()
  q=reference[pos:pos+length]
  if len(q)<100 or np.std(q)<.08 or np.percentile(q,90)<math.log(.0025):return
  guesses=[]
  for offset in {round(x['source_seconds']*100-x['reference_seconds']*100)for x in observations}:
   left=max(0,pos+offset-8);right=min(len(source),pos+offset+len(q)+8)
   if right-left<len(q):continue
   try:
    lag,score,margin=match(q,source[left:right]);guesses.append((score,margin,left+round(lag*100)-pos))
   except Invalid:pass
  # A local match only extends an independently established offset; changes require global evidence.
  if guesses and max(guesses)[0]>=.85:return
  if global_calls>=max_global:return
  global_calls+=1
  try:lag,score,margin=match(q,source)
  except Invalid:return
  if score>=.78 and margin>=.04:observations.append({'reference_seconds':pos/100,'source_seconds':lag,'correlation':score,'peak_margin':margin,'passed':True})
 for seed in seeds:
  if seed.get('passed'):
   pos=round(seed['reference_seconds']*100);collect(pos,min(600,len(reference)-pos))
 # Distributed probes discover multiple offsets rather than assuming one global delay.
 step=max(100,math.ceil(len(reference)/max(1,max_global))*1)
 for pos in range(0,max(1,len(reference)-299),step):collect(pos)
 offsets=[]
 for x in observations:
  value=round((x['source_seconds']-x['reference_seconds'])*100)
  if not any(abs(value-v)<=5 for v in offsets):offsets.append(value)
 offsets.sort()
 if not offsets:return {'mapping_ready':False,'reason':'no_unique_acoustic_offsets','segments':[],'automatic_cuts_applied':False,'independent_audio_review_passed':False}
 if len(offsets)>128:raise Invalid('مطابقة معقدة تتجاوز حد الذاكرة؛ لا خطة تقريبية')
 # Estimate gain/floor per offset from independently matched probes, not speech spelling.
 fitted=[]
 for off in offsets:
  rows=[x for x in observations if abs(round((x['source_seconds']-x['reference_seconds'])*100)-off)<=5];xs=[];ys=[]
  for x in rows:
   a=round(x['reference_seconds']*100);b=min(len(reference),a+300);lo=a+off
   if lo>=0 and lo+b-a<=len(source):xs.extend(source[lo:lo+b-a]);ys.extend(reference[a:b])
  slope,bias=np.polyfit(xs,ys,1) if len(xs)>10 and np.std(xs)>.05 else (1,0)
  fitted.append((float(slope),float(bias)))
 n=len(reference);k=len(offsets);back=np.zeros((n,k),dtype=np.uint8);cost=np.zeros(k);scale=max(.1,float(np.std(reference)));penalty=12.
 for i,value in enumerate(reference):
  if i%1000==0 and cancel():raise Cancelled()
  positions=i+np.asarray(offsets);valid=(positions>=0)&(positions<len(source));indices=np.clip(positions,0,len(source)-1)
  emission=np.minimum(25,((np.asarray([x[0]for x in fitted])*source[indices]+np.asarray([x[1]for x in fitted])-value)/scale)**2);emission[~valid]=1e9
  # Ordered offsets prohibit moving backwards/repeating the same original picture interval.
  minimum=np.minimum.accumulate(cost);earliest=np.zeros(k,dtype=int);best=0
  for j in range(k):
   if cost[j]<cost[best]:best=j
   earliest[j]=best
  change=minimum+penalty;use=change<cost;back[i]=np.where(use,earliest,np.arange(k));cost=np.where(use,change,cost)+emission
 labels=np.empty(n,dtype=np.uint8);state=int(np.argmin(cost))
 for i in range(n-1,-1,-1):labels[i]=state;state=int(back[i,state])
 runs=_runs(labels);segments=[];issues=[];measurements=[]
 for a,b,state in runs:
  off=offsets[state];si=round((a+off)*fps/100);start=round(a*fps/100);end=round(b*fps/100)
  if b-a<60 or end<=start:issues.append({'start':a/100,'end':b/100,'reason':'fragment_too_short_for_independent_match'});continue
  # Independently verify every non-quiet window inside this source interval.
  for pos in range(a,b,100):
   stop=min(b,pos+300)
   if stop-pos<60:pos=max(a,b-100);stop=b
   q=reference[pos:stop];quiet=np.percentile(q,90)<math.log(.0025)
   if quiet:continue
   left=max(0,pos+off-10);right=min(len(source),stop+off+10)
   try:lag,score,margin=match(q,source[left:right]);passed=score>=.70 and abs(left+round(lag*100)-pos-off)<=4
   except Invalid:score=0;passed=False
   measurements.append({'reference_seconds':pos/100,'end_seconds':stop/100,'score':float(score),'passed':bool(passed)})
   if not passed:issues.append({'start':pos/100,'end':stop/100,'reason':'local_acoustic_mismatch'})
  # Repeated takes must remain ambiguous even when ordered-path costs prefer one.
  q=reference[a:min(b,a+600)]
  if len(q)>=100 and np.std(q)>.08:
   try:
    lag,score,margin=match(q,source)
    if score<.78 or margin<.025 or abs(round(lag*100)-a-off)>5:issues.append({'start':a/100,'end':min(b,a+600)/100,'reason':'non_unique_source_interval'})
   except Invalid:issues.append({'start':a/100,'end':b/100,'reason':'unverified_interval_identity'})
  segments.append({'start_frame':start,'end_frame':end,'source_in_frame':si,'source_out_frame':si+end-start,'offset_samples':off})
 # Check frame-rounded output continuity and source bounds; never invent a missing edge.
 expected=round(len(reference)*fps/100);cursor=0;source_end=-1
 for seg in segments:
  if seg['start_frame']!=cursor or seg['source_in_frame']<source_end or seg['source_in_frame']<0 or seg['source_out_frame']>len(source)*fps/100:issues.append({'reason':'invalid_or_non_monotone_frame_mapping'})
  cursor=seg['end_frame'];source_end=seg['source_out_frame']
 if cursor!=expected:issues.append({'reason':'uncovered_reference_end'})
 return {'mapping_ready':bool(segments)and not issues,'scope':'picture_only_reference_voice_not_edited','fps':fps,'duration_frames':expected,'segments':segments,'issues':issues,'measurements':measurements,'offsets_samples':offsets,'global_probes':global_calls,'automatic_cuts_applied':False,'independent_audio_review_passed':False}

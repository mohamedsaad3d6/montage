"""Runs in the installed local ML environment; no network, credentials or default project."""
import json,sys,math
from pathlib import Path
import numpy as np
from monteer.cut import breath
wav=Path(sys.argv[1]);words=json.loads(Path(sys.argv[2]).read_text())['words'];out=Path(sys.argv[3]);F=breath.features(wav);ib,isp=breath.train_labels(F,words);half=len(F['db'])//2;result={'status':'insufficient_training_evidence','breaths':[],'clear_breath_frames':len(ib),'clear_speech_frames':len(isp),'deletion_approved':False}
if min(len(ib),len(isp))>=80 and all(min(sum(x<half for x in ib),sum(x>=half for x in ib),sum(x<half for x in isp),sum(x>=half for x in isp))>=20 for _ in [0]):
 p,acc=breath.breath_prob(F,words,check=True);result['heldout_metrics']=acc
 if all(math.isfinite(x) for row in acc for x in row) and min(row[0] for row in acc)>=.85 and min(row[1] for row in acc)>=.9:
  _,B,_=breath.masks(F['db'],words,p);result['status']='candidate_classifier_passed_local_checks'
  for a,b in breath.runs(B & (p>=.97)):
   lo=a*.01;hi=b*.01
   if hi-lo<.08 or hi-lo>1.2 or any(w['s']-.15<hi and w['e']+.15>lo for w in words):continue
   result['breaths'].append({'start':lo,'end':hi,'kind':'isolated_breath_candidate','posterior_min':float(p[a:b].min()),'automatic_delete_allowed':False,'reason':'صوت نفس منفصل محتمل؛ ليس جزءًا ملاصقًا لكلمة، ويحتاج مراجعة سمعية.'})
 else:result['status']='classifier_validation_failed_no_cuts'
out.write_text(json.dumps(result,ensure_ascii=False,indent=2))

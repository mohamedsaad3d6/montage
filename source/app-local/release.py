"""Recheck stored review evidence before opening a full export; no cached approval alone."""
import json,sys
from pathlib import Path
from media import ROOT

def reviewed(store,review_job,result):
 r=json.loads(review_job.get('result') or '{}')
 if r.get('review_complete') is not True or r.get('output_sha256')!=result.get('file_sha256'):return False
 if r.get('gate',{}).get('status')!='passed_for_review':return False
 folder=store.root/'jobs'/review_job['id'];sys.path.insert(0,str(ROOT/'engine'))
 try:
  from monteer.audio_review.gate import check
  return check(result['file'],folder/'independent-review',folder/'technical-checks.json')['status']=='passed_for_review'
 except (OSError,ValueError,KeyError,TypeError):return False

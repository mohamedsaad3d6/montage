"""Read-only output/review identity status, shared by the new control surface."""
import json
from core import Invalid
from media import file_hash

def status(store,job_id):
 with store.connect() as c:
  job=store.one(c,'SELECT * FROM jobs WHERE id=?',(job_id,))
  reviews=[dict(x) for x in c.execute("SELECT * FROM jobs WHERE project=? AND revision=? AND kind='audio_review' AND status='completed' ORDER BY created DESC",(job['project'],job['revision']))]
 if job['kind']!='render' or job['status']!='completed':raise Invalid('ملف الإخراج لم يكتمل')
 out=json.loads(job['result']);matches=[j for j in reviews if json.loads(j.get('result') or '{}').get('output_job')==job_id]
 completed=[j for j in matches if json.loads(j.get('result') or '{}').get('review_complete') is True]
 valid=False
 if completed:
  from release import reviewed
  valid=reviewed(store,completed[0],out)
 try:identity=file_hash(out['file'])==out.get('file_sha256')
 except OSError:identity=False
 valid=valid and identity
 latest=matches[0] if matches else None
 return {'job':job_id,'revision':job['revision'],'media_identity_valid':identity,'audio_review_passed':valid,
         'internal_diagnostic_playable':identity and out.get('duration',0)<=30,'publication_approved':False,
         'latest_review_job':latest['id'] if latest else None,'complete_review_job':completed[0]['id'] if completed else None,
         'width':out['width'],'height':out['height'],'duration':out['duration'],'frames':out['frames'],
         'start_frame':out['start_frame'],'output_sha256':out.get('file_sha256')}

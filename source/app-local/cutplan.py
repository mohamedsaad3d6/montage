"""Frame-safe quiet-gap draft cutting; retakes still need listening and selection."""
import copy,math,uuid
from editorial import silence_proposals

def plan(analysis,ctc,wav,fps):
 if not analysis.get('words') or not ctc:raise ValueError('يلزم تفريغ ومحاذاة ثانية قبل القص')
 protected=[*analysis['words'],*ctc];candidates=silence_proposals(wav,protected);cuts=[]
 for item in candidates:
  a=math.ceil(item['proposed_cut'][0]*fps);b=math.floor(item['proposed_cut'][1]*fps)
  if b<=a:continue
  if any(w['s']-.12<b/fps and w['e']+.12>a/fps for w in protected):continue
  cuts.append({'start_frame':a,'end_frame':b,'kind':'quiet_gap_only','removed_word_ids':[],'proof':'PCM below -50 dB, protected by both ASR and Egyptian CTC word intervals','requires_independent_final_review':True})
 return {'fps':fps,'cuts':cuts,'retakes':analysis['retakes'],'retake_deletions':0,'status':'internal_draft_only','automatic_speech_deletion':False}
def apply(timeline,cut_plan):
 if timeline.get('phase')!='raw':raise ValueError('التنظيف الأولي يعمل على الخام فقط؛ المرجع المعتمد والمونتاج لا يتغيران')
 if any(tr['clips'] for tr in timeline['tracks'] if tr['kind'] not in ['video','voice']):raise ValueError('نفذ مراجعة الصوت قبل إضافة المونتاج')
 for c in cut_plan['cuts']:
  if c.get('kind')!='quiet_gap_only' or c.get('removed_word_ids'):raise ValueError('قص غير صالح أو يحذف كلامًا')
 return splice(timeline,cut_plan['cuts'])

def splice(timeline,cuts):
 """Pure synchronized range mapping. Callers must separately prove the editorial decision."""
 total=timeline['duration_frames'];cuts=sorted(cuts,key=lambda x:x['start_frame']);cursor=0;keeps=[]
 for c in cuts:
  a,b=c['start_frame'],c['end_frame']
  if type(a)!=int or type(b)!=int or not 0<=cursor<=a<b<=total:raise ValueError('حدود القص غير صالحة أو متداخلة')
  if cursor<a:keeps.append((cursor,a))
  cursor=b
 if cursor<total:keeps.append((cursor,total))
 if not keeps:raise ValueError('لا يمكن حذف الحلقة كاملة')
 out=copy.deepcopy(timeline);out['phase']='cut_candidate';out['duration_frames']=sum(b-a for a,b in keeps);out['raw_to_output']=[];at=0
 for a,b in keeps:out['raw_to_output'].append({'input_start_frame':a,'input_end_frame':b,'output_start_frame':at,'output_end_frame':at+b-a});at+=b-a
 for tr in out['tracks']:
  original=next(x for x in timeline['tracks'] if x['id']==tr['id'])['clips'];clips=[];at=0
  for a,b in keeps:
   for c in original:
    lo=max(a,c['start_frame']);hi=min(b,c['end_frame'])
    if hi<=lo:continue
    x=copy.deepcopy(c);x['id']=uuid.uuid4().hex;x['start_frame']=at+lo-a;x['end_frame']=at+hi-a
    if x.get('asset_id'):x['source_in_frame']=c.get('source_in_frame',0)+lo-c['start_frame'];x['source_out_frame']=x['source_in_frame']+hi-lo
    if lo!=c['start_frame']:x.get('properties',{}).pop('transition',None)
    clips.append(x)
   at+=b-a
  tr['clips']=clips
 return out

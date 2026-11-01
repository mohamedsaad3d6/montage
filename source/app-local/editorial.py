"""Evidence-first Arabic cut proposals. Candidates are never executable ASR timestamps."""
import hashlib,json,math,re,unicodedata,wave,array
from difflib import SequenceMatcher

def norm(s):
 s=unicodedata.normalize('NFKC',s).translate(str.maketrans('أإآىة٠١٢٣٤٥٦٧٨٩','ااايه0123456789'))
 return re.sub(r'[^\w\s]','',re.sub('[\u064b-\u065f\u0670\u0640]','',s)).strip().lower()
def token_words(data):
 words=[]
 for seg in data.get('transcription',[]):
  if seg.get('unreliable_asr'):
   offsets=seg.get('offsets',{});start=offsets.get('from',0)/1000;end=offsets.get('to',0)/1000
   if 0<=start<end:words.append({'w':'[تفريغ غير موثوق — يُحفظ الصوت]','s':start,'e':end,'confidence':0,'unreliable_asr':True,'timing_method':'uncertainty_protection_interval_not_spoken_word'})
   continue
  current=None
  for tok in seg.get('tokens',[]):
   text=tok.get('text','');off=tok.get('offsets',{});start=off.get('from',-1)/1000;end=off.get('to',-1)/1000
   if not text.strip() or text.startswith('[_') or start<0 or end<=start:continue
   if text[0].isspace() or current is None:
    if current and norm(current['w']):words.append(current)
    current={'w':text.strip(),'s':start,'e':end,'confidence':float(tok.get('p',0)),'timing_method':'asr_token_estimate_not_forced_alignment'}
   else:current['w']+=text;current['e']=max(current['e'],end);current['confidence']=min(current['confidence'],float(tok.get('p',0)))
  if current and norm(current['w']):words.append(current)
 for i,w in enumerate(words):w['id']=i;w['n']=''if w.get('unreliable_asr')else norm(w['w'])
 return words

def retakes(words,allow_ctc_variants=False):
 """Find nearby multiword restarts, retaining ambiguity and meaningful additions."""
 out=[];seen=set();n=len(words)
 for i in range(n):
  for j in range(i+3,min(n,i+45)):
   if words[j]['s']-words[i]['s']>30:break
   if not words[i]['n'] or words[i]['n']!=words[j]['n']:continue
   if j+2>=n or any(words[i+k]['n']!=words[j+k]['n'] for k in range(3)):continue
   a=[w['n'] for w in words[i:j]]
   # A repeated lead-in alone is normal parallel speech, not a retake.
   best=None
   for length in range(3,min(28,n-j)+1):
    b=[w['n'] for w in words[j:j+length]];m=SequenceMatcher(None,a,b,autojunk=False);blocks=[x for x in m.get_matching_blocks() if x.size]
    exact_common=sum(x.size for x in blocks);common=exact_common;fuzzy_a=set();prefix=0
    if allow_ctc_variants and exact_common>=max(5,math.ceil(.6*len(a))):
     proposed=[]
     for tag,alo,ahi,blo,bhi in m.get_opcodes():
      if tag!='replace' or ahi-alo!=bhi-blo:continue
      for ai,bi in zip(range(alo,ahi),range(blo,bhi)):
       if min(len(a[ai]),len(b[bi]))>=3 and SequenceMatcher(None,a[ai],b[bi],autojunk=False).ratio()>=.6:proposed.append(ai)
     if len(proposed)<=min(4,math.floor(.35*len(a))):fuzzy_a=set(proposed);common+=len(fuzzy_a)
    coverage=common/max(1,len(a))
    for x,y in zip(a,b):
     if x!=y:break
     prefix+=1
    if prefix<3 or common<3 or coverage<.88:continue
    # Equal lexical content needs listening, not a confidence/last-attempt shortcut.
    changed_a=[a[k] for k in range(len(a)) if k not in fuzzy_a and not any(x.a<=k<x.a+x.size for x in blocks)]
    if any(len(w)>1 for w in changed_a):continue
    score=(coverage,common,-abs(len(a)-len(b)))
    if best is None or score>best[0]:best=(score,length,common,prefix,len(fuzzy_a))
   if best is None:continue
   length=best[1];key=(i,j)
   if any(x<=i<y for x,y in seen):continue
   seen.add(key);a_end=j;b_end=j+length
   # A repeated prefix followed by a second complete clause can be intentional.
   preferred='later_more_complete_candidate' if length>len(a) else None
   out.append({'id':f'retake-{i}-{j}','kind':'retake_candidate','attempts':[{'word_ids':list(range(i,a_end)),'start':words[i]['s'],'end':words[a_end-1]['e'],'text':' '.join(w['w'] for w in words[i:a_end])},{'word_ids':list(range(j,b_end)),'start':words[j]['s'],'end':words[b_end-1]['e'],'text':' '.join(w['w'] for w in words[j:b_end])}], 'preferred_candidate':preferred,'selection_basis':'ctc_spelling_variants_require_listening' if best[4] else 'lexical_completeness_only_not_pronunciation','approximate_word_matches':best[4],'requires_listening':True,'requires_forced_alignment':True,'automatic_delete_allowed':False,'reason':'إعادة محتملة متعددة الكلمات؛ لا اختيار تلقائي لآخر محاولة ولا حذف إضافة مفيدة.'})
 return out

def silence_proposals(wav,words,min_gap=.9,retain=.35):
 with wave.open(str(wav),'rb') as w:
  if w.getnchannels()!=1 or w.getsampwidth()!=2:raise ValueError('Expected mono PCM16 analysis audio')
  rate=w.getframerate();samples=array.array('h',w.readframes(w.getnframes()))
 frame=max(1,round(rate*.01));levels=[]
 for i in range(0,len(samples),frame):
  s=samples[i:i+frame];rms=math.sqrt(sum(float(x)*x for x in s)/max(1,len(s)))/32768;levels.append(20*math.log10(max(1e-8,rms)))
 # Conservative silence threshold; breath/noise is never silently called empty speech.
 threshold=-50;out=[];start=None
 for i,db in enumerate(levels+[0]):
  if db<threshold and start is None:start=i
  if db>=threshold and start is not None:
   a=start*.01;b=i*.01;start=None
   if b-a<min_gap:continue
   available=[(a,b)]
   for word in words:
    lo,hi=word['s']-.15,word['e']+.15;pieces=[]
    for left,right in available:
     if hi<=left or lo>=right:pieces.append((left,right));continue
     if left<lo:pieces.append((left,min(right,lo)))
     if hi<right:pieces.append((max(left,hi),right))
    available=pieces
   for left,right in available:
    if right-left<min_gap:continue
    cut_a=max(left,a+retain/2);cut_b=min(right,b-retain/2)
    if cut_b-cut_a<.25:continue
    out.append({'id':f'pause-{len(out)}','kind':'pause_candidate','source_start':a,'source_end':b,
                'proposed_cut':[round(cut_a,3),round(cut_b,3)],'removed_seconds':round(cut_b-cut_a,3),
                'word_ids_intersecting':[],'automatic_delete_allowed':False,'requires_boundary_review':True,
                'reason':'جزء هادئ مثبت خارج الكلمات وهوامش حمايتها؛ الوقفة المعنوية تحتاج مراجعة.'})
 return out

def analyze(data,wav):
 words=token_words(data)
 if not words:raise ValueError('لا توجد كلمات مؤقتة صالحة؛ لم تقترح قصّات')
 return {'schema_version':1,'status':'candidates_not_approved','words':words,'retakes':retakes(words),'pauses':silence_proposals(wav,words),'source_timing':'local_analysis_audio','automatic_cuts_applied':False,'guardrails':['choose_complete_take_not_last','retain_meaningful_additions','asr_times_are_not_cut_boundaries','breath_not_equal_silence','independent_final_audio_review_required']}

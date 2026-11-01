"""Detect decoder repetition without deleting or rewriting source speech."""
from collections import Counter
from editorial import norm

def inspect(data):
 segments=data.get('transcription',[]);texts=[norm(x.get('text',''))for x in segments];nonempty=[x for x in texts if x]
 counts=Counter(nonempty);top,count=counts.most_common(1)[0] if counts else ('',0)
 repeated_seconds=sum(max(0,x.get('offsets',{}).get('to',0)-x.get('offsets',{}).get('from',0))/1000 for x,t in zip(segments,texts)if t==top)
 suspect=count>=3 and count/max(1,len(nonempty))>=.6 and repeated_seconds>=30
 return {'status':'decoder_repetition_suspected'if suspect else 'no_repetition_collapse_detected','segment_count':len(segments),'dominant_phrase_count':count,'dominant_phrase_seconds':round(repeated_seconds,3),'requires_second_pass':suspect,'speech_deletion_allowed':False,'not_editorial_approval':True}

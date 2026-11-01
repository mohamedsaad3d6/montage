"""Short join auditions from the complete proposed edit, never independent review audio."""
import array,wave
from media import file_hash

def build(samples,rate,fps,keeps,cuts,folder):
 pieces=[];spans=[];cursor=0
 for keep in keeps:
  lo=round(keep['input_start_frame']/fps*rate);hi=round(keep['input_end_frame']/fps*rate);piece=array.array('h',samples[lo:hi])
  if not piece:continue
  # Same short fade policy as the production joiner; this remains a 16kHz diagnostic.
  if len(keeps)>1:
   fade=min(round(.004*rate),max(1,len(piece)//8))
   for k in range(fade):piece[k]=round(piece[k]*k/fade);piece[-1-k]=round(piece[-1-k]*k/fade)
  pieces.append(piece);spans.append({**keep,'sample_start':cursor,'sample_end':cursor+len(piece)});cursor+=len(piece)
 joined=array.array('h')
 for piece in pieces:joined.extend(piece)
 if not joined:raise ValueError('لا يوجد صوت متبقٍ لمعاينة الوصلات')
 previews=[]
 for i,cut in enumerate(cuts):
  completed=[span for span in spans if span['input_end_frame']<=cut['start_frame']];join=sum(span['sample_end']-span['sample_start'] for span in completed);output_frame=sum(span['input_end_frame']-span['input_start_frame'] for span in completed);lo=max(0,join-2*rate);hi=min(len(joined),join+2*rate);output=folder/f'join-{i}.wav'
  with wave.open(str(output),'wb')as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(rate);f.writeframes(joined[lo:hi].tobytes())
  previews.append({'index':i,'file':output.name,'sha256':file_hash(output),'context_start':lo/rate,'context_end':hi/rate,'context_clock':'edited_candidate','join_seconds':(join-lo)/rate,'join_output_frame':output_frame,'source_start_frame':cut['start_frame'],'source_end_frame':cut['end_frame'],'duration':(hi-lo)/rate,'kind':cut['kind']})
 return previews

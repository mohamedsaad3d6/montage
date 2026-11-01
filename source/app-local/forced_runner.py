"""Offline acoustic CTC alignment of literal ASR words in bounded windows."""
import json,sys,math
from pathlib import Path
import numpy as np,torch
from scipy.io import wavfile
from transformers import Wav2Vec2ForCTC,Wav2Vec2Processor
from torchaudio.functional import forced_align,merge_tokens
config=json.loads(Path(sys.argv[1]).read_text());sr,x=wavfile.read(config['wav']);assert sr==16000 and x.ndim==1
processor=Wav2Vec2Processor.from_pretrained(config['model'],local_files_only=True)
model=Wav2Vec2ForCTC.from_pretrained(config['model'],local_files_only=True).eval();torch.set_num_threads(6)
vocab=processor.tokenizer.get_vocab();blank=processor.tokenizer.pad_token_id;space=processor.tokenizer.word_delimiter_token_id
results=[];windows=[]
for window in config['windows']:
 a,b=window['start'],window['end'];targets=[];owners=[];unsupported=False
 for i,word in enumerate(window['words']):
  for character in word['normalized']:
   if character not in vocab:unsupported=True;break
   targets.append(vocab[character]);owners.append(word['index'])
  if i<len(window['words'])-1:targets.append(space);owners.append(None)
 if unsupported or not targets:
  windows.append({'start':a,'end':b,'status':'unsupported_literal_tokens_no_refinement'});continue
 audio=x[int(a*sr):int(b*sr)].astype(np.float32)/32768
 inputs=processor(audio,sampling_rate=sr,return_tensors='pt').input_values
 with torch.no_grad():log_probs=model(inputs).logits.log_softmax(-1).cpu().contiguous()
 try:
  aligned,scores=forced_align(log_probs,torch.tensor([targets],dtype=torch.int32),blank=blank)
  spans=merge_tokens(aligned[0],scores[0],blank=blank)
 except (RuntimeError,ValueError):
  windows.append({'start':a,'end':b,'status':'alignment_failed_no_refinement'});continue
 if [int(s.token) for s in spans]!=targets:
  windows.append({'start':a,'end':b,'status':'token_sequence_mismatch_no_refinement'});continue
 grouped={}
 for owner,span in zip(owners,spans):
  if owner is not None:grouped.setdefault(owner,[]).append(span)
 step=model.config.inputs_to_logits_ratio/sr
 for index,parts in grouped.items():
  probability=math.exp(sum(float(s.score) for s in parts)/len(parts));minimum=min(math.exp(float(s.score)) for s in parts)
  results.append({'index':index,'s':a+min(s.start for s in parts)*step,'e':a+max(s.end for s in parts)*step,
                  'alignment_mean_posterior':probability,'alignment_min_char_posterior':minimum,
                  'method':'acoustic_ctc_forced_alignment_literal_target','window':[a,b]})
 windows.append({'start':a,'end':b,'status':'aligned_not_editorially_approved'})
Path(config['output']).write_text(json.dumps({'words':results,'windows':windows,'automatic_speech_deletion':False},ensure_ascii=False,indent=2))

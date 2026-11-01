"""Original transparent Arabic lower thirds with whole-layer motion and fades."""
from pathlib import Path
import json,subprocess,shutil,time,os,signal
from media import ROOT,Cancelled
from media import run,eastern

def add(args,filters,current,clips,start,end,fps,width,height,folder,font,first_input,cancel):
 count=0;folder=Path(folder);margin=max(18,round(width*.035));distance=max(16,round(height*.045));items=[]
 for i,c in enumerate(clips):
  if min(end,c['end_frame'])<=max(start,c['start_frame']) or not c.get('properties',{}).get('text'):continue
  text=c['properties']['text']
  if len(text)>140 or text.count('\n')>1:raise ValueError('اكتب عنوانًا مهمًا قصيرًا للكارت؛ لا فقرة طويلة')
  items.append({'text':eastern(text),'width':round(width*.78)//2*2,
                'height':max(60,round(height*.17))//2*2,'fontSize':max(18,round(height*.045)),
                'output':str(folder/f'title-{i}.png')})
 if items:
  config=folder/'cards.json';config.write_text(json.dumps(items,ensure_ascii=False))
  with (folder/'cards.log').open('wb') as log:
   node=os.environ.get('MONTAJ_NODE') or shutil.which('node')
   proc=subprocess.Popen([node,str(ROOT/'app-local/cards/render.mjs'),str(config)],stdout=log,stderr=log,start_new_session=True)
   from process_guard import wait
   wait(proc,cancel,timeout_seconds=300)
   if proc.returncode:raise ValueError('تعذر رسم العناوين العربية؛ التفاصيل في سجل المهمة')
 for i,c in enumerate(clips):
  lo=max(start,c['start_frame']);hi=min(end,c['end_frame']);text=c.get('properties',{}).get('text','')
  if hi<=lo or not text:continue
  # Headline, not a slide full of paragraphs. Newlines remain explicit and escaped by textfile.
  if len(text)>140 or text.count('\n')>1:raise ValueError('اكتب عنوانًا مهمًا قصيرًا للكارت؛ لا فقرة طويلة')
  png=folder/f'title-{i}.png'
  duration=(hi-lo)/fps;fade=min(.28,duration/4);ss=(lo-start)/fps;ee=(hi-start)/fps
  entry=(c['start_frame']-start)/fps;exit_=(c['end_frame']-start)/fps
  index=first_input+count;args+=['-loop','1','-t',duration,'-i',png]
  layer=f'card{i}';chain=f'[{index}:v]format=rgba'
  if lo==c['start_frame']:chain+=f',fade=t=in:st=0:d={fade}:alpha=1'
  if hi==c['end_frame']:chain+=f',fade=t=out:st={duration-fade}:d={fade}:alpha=1'
  chain+=f',setpts=PTS-STARTPTS+{ss}/TB[{layer}]';filters.append(chain)
  motion=(f'{distance}*pow(max(0,min(1,1-(t-({entry}))/{fade})),3)'
          f'+{distance}*pow(max(0,min(1,(t-({exit_}-{fade}))/{fade})),3)')
  out=f'withcard{i}'
  filters.append(f"[{current}][{layer}]overlay=x=W-w-{margin}:y='H-h-{margin}+{motion}':"
                 f"eof_action=pass:repeatlast=0:enable='gte(t,{ss})*lt(t,{ee})'[{out}]")
  current=out;count+=1
 return current,count

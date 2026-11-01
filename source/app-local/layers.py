"""Timed graphic overlays independent of the narration and picture edit list."""
import math

def add(store,args,filters,current,clips,start,end,fps,width,height,first_input):
 count=0
 for i,c in enumerate(clips):
  lo=max(start,c['start_frame']);hi=min(end,c['end_frame'])
  if hi<=lo:continue
  if not c.get('asset_id'):raise ValueError('طبقة الجرافيك تحتاج مادة بصرية')
  a=store.asset(c['asset_id']);props=c.get('properties',{});scale=props.get('scale',.4);position=props.get('position','top_left')
  if a['kind'] not in ['video','image']:raise ValueError('طبقة الجرافيك ليست مادة بصرية')
  if type(scale) not in [float,int] or not math.isfinite(scale) or not .1<=scale<=1:raise ValueError('حجم طبقة الجرافيك غير صالح')
  positions={'top_left':('30','30'),'top_right':('W-w-30','30'),'bottom_left':('30','H-h-30'),'bottom_right':('W-w-30','H-h-30'),'center':('(W-w)/2','(H-h)/2')}
  if position not in positions:raise ValueError('موضع طبقة الجرافيك غير صالح')
  index=first_input+count;duration=(hi-lo)/fps;ss=(lo-start)/fps;ee=(hi-start)/fps
  args+=(['-loop','1'] if a['kind']=='image' else ['-ss',(c.get('source_in_frame',0)+lo-c['start_frame'])/fps])
  args+=['-t',duration,'-threads','1','-i',a['path']]
  w=round(width*scale)//2*2;h=round(height*scale)//2*2;fade=min(.25,duration/4)
  chain=f'[{index}:v]setpts=PTS-STARTPTS,scale={w}:{h}:force_original_aspect_ratio=decrease,format=rgba'
  if lo==c['start_frame']:chain+=f',fade=t=in:st=0:d={fade}:alpha=1'
  if hi==c['end_frame']:chain+=f',fade=t=out:st={duration-fade}:d={fade}:alpha=1'
  layer=f'graphic{i}';out=f'withgraphic{i}';chain+=f',setpts=PTS-STARTPTS+{ss}/TB[{layer}]';filters.append(chain)
  x,y=positions[position]
  filters.append(f"[{current}][{layer}]overlay=x='{x}':y='{y}':eof_action=pass:repeatlast=0:enable='gte(t,{ss})*lt(t,{ee})'[{out}]")
  current=out;count+=1
 return current,count

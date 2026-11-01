"""Deterministic per-shot color corrections used by preview and final render paths."""
import math
PRESETS={
 'neutral':{},
 'warm':{'temperature':.10,'saturation':1.06},
 'documentary_cool':{'temperature':-.10,'saturation':.92,'contrast':1.04}
}
def normalized(value):
 if value is None:return None
 if not isinstance(value,dict):raise ValueError('إعدادات اللون غير صالحة')
 preset=value.get('preset','neutral')
 if preset not in PRESETS:raise ValueError('ستايل اللون غير موجود')
 out={**PRESETS[preset],**value}
 limits={'brightness':(-.3,.3,0),'contrast':(.5,1.8,1),'saturation':(0,2,1),'gamma':(.5,2,1),'temperature':(-.3,.3,0)}
 result={'preset':preset}
 for key,(lo,hi,default) in limits.items():
  n=out.get(key,default)
  if type(n) not in [int,float] or not math.isfinite(n) or not lo<=n<=hi:raise ValueError('قيمة اللون خارج النطاق: '+key)
  result[key]=n
 for region in ['shadows','midtones','highlights']:
  item=out.get(region,{})
  if not isinstance(item,dict):raise ValueError('توازن ألوان غير صالح')
  result[region]={}
  for channel in ['r','g','b']:
   n=item.get(channel,0)
   if type(n) not in [int,float] or not math.isfinite(n) or not -.3<=n<=.3:raise ValueError('قيمة توازن اللون خارج النطاق')
   result[region][channel]=n
 return result

def filters(properties):
 c=normalized(properties.get('color'))
 if c is None:return ''
 # All values above are finite bounded numbers; no user filter expressions are accepted.
 eq='eq=brightness={brightness}:contrast={contrast}:saturation={saturation}:gamma={gamma}'.format(**c)
 balance={}
 for key,suffix in [('shadows','s'),('midtones','m'),('highlights','h')]:
  for channel in ['r','g','b']:balance[channel+suffix]=c[key][channel]
 balance['rm']=max(-.3,min(.3,balance['rm']+c['temperature']))
 balance['bm']=max(-.3,min(.3,balance['bm']-c['temperature']))
 return eq+',colorbalance='+':'.join(k+'='+str(v) for k,v in balance.items())

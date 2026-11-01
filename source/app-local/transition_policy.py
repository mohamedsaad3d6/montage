"""Conservative automatic transition choice from our real renderer, with source handles."""
import json
from media import ROOT

def assign(store,clips,fps):
 cat=json.loads((ROOT/'library/our-transitions-01/catalog.json').read_text());family={}
 for item in cat['recipes']:family.setdefault(item['family'],item['id'])
 decisions=[]
 for previous,current in zip(clips,clips[1:]):
  if previous['end_frame']!=current['start_frame']or previous['asset_id']==current['asset_id']:continue
  left=store.asset(previous['asset_id']);right=store.asset(current['asset_id']);lm=json.loads(left.get('metadata')or'{}');rm=json.loads(right.get('metadata')or'{}')
  # No fades to black or arbitrary decorative wipes; use verified continuity metadata if present.
  shared=set(lm.get('subjects',[]))&set(rm.get('subjects',[]));direction=rm.get('motion_direction');choice='parallax'if lm.get('visual_type')=='map'and rm.get('visual_type')=='map'else 'pan'if direction in ('left','right','up','down')else 'matchline'if shared else 'defocus'
  n=min(round(fps*.3),current['end_frame']-current['start_frame'],previous['end_frame']-previous['start_frame'])
  if n<4:continue
  boundary=current['start_frame'];left_source=previous['source_in_frame']+boundary-previous['start_frame'];right_source=current['source_in_frame']
  if any(a['kind']=='video'and source+n>a['duration']*fps for a,source in [(left,left_source),(right,right_source)]):
   decisions.append({'boundary':boundary,'used':False,'reason':'insufficient_source_handles_no_loop_or_freeze'});continue
  recipe={'recipe_id':family[choice],'duration_frames':n,'strength':.08}
  if choice=='pan':recipe['direction']=direction
  current.setdefault('properties',{})['transition']=recipe;decisions.append({'boundary':boundary,'used':True,'family':choice,'recipe':recipe,'reason':'geographic_continuity'if choice=='parallax'else 'verified_motion_direction'if choice=='pan'else 'shared_subject'if shared else 'gentle_focus_change'})
 return decisions

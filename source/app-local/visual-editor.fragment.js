const material=e('select',null,{class:'flow-input','aria-label':'المادة البصرية'});
for(const a of state.assets.filter(a=>['video','image'].includes(a.kind)))material.append(e('option',a.name,{value:a.id}));
const seconds=e('input',null,{class:'flow-input','aria-label':'مدة المادة',value:'٤'}),effect=e('select',null,{class:'flow-input','aria-label':'الانتقال للمادة'});
effect.append(e('option','بدون انتقال',{value:''}));
for(const r of tr.choices||[])effect.append(e('option',r.label+' — '+r.id,{value:r.id}));
editBox.append(e('h3','مادة بصرية فوق نفس الكلام'),material,e('p','تبدأ من توقيت المعاينة الحالي. الصوت المعتمد لا يتغير.',{class:'flow-note'}),seconds,effect,
b('معاينة نوع الانتقال',async()=>{if(!effect.value)return;const demo=e('video',null,{src:'/transition-preview/'+effect.value,controls:'',style:'width:100%'});editBox.append(demo);demo.play()}),
b('أضف المادة في نسخة جديدة',async()=>{
 const a=state.assets.find(a=>a.id===material.value),duration=parse(seconds.value);
 if(!a||!Number.isFinite(duration)||duration<=0||duration>60)throw Error('اختَر مادة ومدة صالحة');
 const start=Math.round(video.currentTime*t.fps),end=Math.min(t.duration_frames,start+Math.round(duration*t.fps));
 if(end<=start)throw Error('التوقيت خارج الحلقة');
 if(a.kind==='video'&&(end-start)>a.duration*t.fps)throw Error('المادة أقصر من المدة المطلوبة');
 const track=t.tracks.find(x=>x.kind==='video'),clips=[];
 for(const c of track.clips){
  if(c.end_frame<=start||c.start_frame>=end){clips.push(c);continue}
  if(c.start_frame<start)clips.push({...c,id:crypto.randomUUID(),end_frame:start,source_out_frame:c.source_in_frame+start-c.start_frame});
  if(c.end_frame>end)clips.push({...c,id:crypto.randomUUID(),start_frame:end,source_in_frame:c.source_in_frame+end-c.start_frame});
 }
 clips.push({id:crypto.randomUUID(),asset_id:a.id,start_frame:start,end_frame:end,source_in_frame:0,source_out_frame:end-start,properties:effect.value&&start>0?{transition:{recipe_id:effect.value}}:{}});
 track.clips=clips.sort((a,b)=>a.start_frame-b.start_frame);
 await api('/api/revisions',{project:state.id,expected:baseRevision,timeline:t,summary:'إضافة مادة بصرية دون تغيير الكلام'});
 await load(state.id);
}));

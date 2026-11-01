import {clampFrame,pointerFrame,rulerTicks} from './timeline-math.mjs';

export function timelineView(ctx,{timeline,timecode,onSelect,onSeek,onLock}) {
 const {el,button,row,num}=ctx,t=timeline;
 const panel=el('section',null,{class:'nle-timeline','aria-label':'تايملاين الحلقة'});
 const tools=row(),clock=el('output',timecode(0),{'aria-label':'موضع مؤشر التايملاين'});
 const zoom=el('input',null,{type:'range',min:1,max:8,step:.5,value:1,'aria-label':'تكبير التايملاين'}),scale=el('output','١×');
 tools.classList.add('nle-timeline-tools');tools.append(clock,el('span','مؤشر المعاينة',{class:'note'}),el('label','تكبير'),zoom,scale);
 const scroll=el('div',null,{class:'nle-scroll'}),content=el('div',null,{class:'nle-time-content'}),rulerRow=el('div',null,{class:'nle-ruler-row'}),label=el('span','الزمن',{class:'nle-track-label'}),ruler=el('div',null,{class:'nle-ruler',role:'slider',tabindex:0,'aria-label':'موضع الحلقة بالإطارات','aria-valuemin':0,'aria-valuemax':Math.max(0,t.duration_frames-1),'aria-valuenow':0});
 rulerRow.append(label,ruler);content.append(rulerRow);
 const colors={video:'#3664c8',text:'#c98a1e',graphics:'#6a4fc4',voice:'#1f6e47',music:'#1b6672',effects:'#7a3f6c'},names={video:'الصورة',text:'العناوين',graphics:'الجرافيك',voice:'صوت المذيع',music:'الموسيقى',effects:'المؤثرات'};
 const clips=new Map(),heads=[];
 const addHead=parent=>{const head=el('i',null,{class:'nle-playhead','aria-hidden':'true'});parent.append(head);heads.push(head)};addHead(ruler);
 // Display compositing tracks above picture and sound, independently of storage order.
 for(const kind of ['text','graphics','video','voice','music','effects']) for(const track of t.tracks.filter(x=>x.kind===kind)) {
  const line=el('div',null,{class:'nle-track-row'}),name=el('div',null,{class:'nle-track-label'}),lock=button(track.locked?'🔒':'🔓',()=>onLock(track));lock.setAttribute('aria-label',(track.locked?'افتح مسار ':'اقفل مسار ')+names[kind]);lock.title=lock.getAttribute('aria-label');name.append(el('span',names[kind]),lock);
  const lane=el('div',null,{class:'nle-clip-lane','aria-label':'مقاطع '+names[kind]});
  for(const clip of track.clips){const clipButton=button(clip.properties?.text||ctx.assetName(clip.asset_id)||names[kind],()=>onSelect(track,clip));clipButton.style.left=(100*clip.start_frame/t.duration_frames)+'%';clipButton.style.width=(100*(clip.end_frame-clip.start_frame)/t.duration_frames)+'%';clipButton.style.setProperty('--track-color',colors[kind]);clipButton.title=clipButton.textContent+' · '+timecode(clip.start_frame)+' — '+timecode(clip.end_frame);clipButton.setAttribute('aria-label',names[kind]+' · '+clipButton.title);clipButton.setAttribute('aria-pressed','false');lane.append(clipButton);clips.set(clip.id,clipButton)}
  addHead(lane);line.append(name,lane);content.append(line);
 }
 scroll.append(content);panel.append(tools,scroll);let frame=0;
 const setFrame=value=>{frame=clampFrame(value,t.duration_frames);clock.textContent=timecode(frame);ruler.setAttribute('aria-valuenow',frame);ruler.setAttribute('aria-valuetext',timecode(frame));for(const head of heads)head.style.left=(100*frame/Math.max(1,t.duration_frames))+'%'};
 const seek=value=>{setFrame(value);onSeek(frame)};
 function drawTicks(){for(const tick of ruler.querySelectorAll('.nle-tick'))tick.remove();for(const f of rulerTicks(t.duration_frames,t.fps,Number(zoom.value))){const tick=el('span',timecode(f),{class:'nle-tick'});tick.style.left=(100*f/Math.max(1,t.duration_frames))+'%';ruler.append(tick)}}
 ruler.addEventListener('pointerdown',event=>{if(event.button!==0)return;ruler.setPointerCapture(event.pointerId);seek(pointerFrame(event.clientX,ruler.getBoundingClientRect().left,ruler.getBoundingClientRect().width,t.duration_frames));event.preventDefault()});
 ruler.addEventListener('pointermove',event=>{if(!ruler.hasPointerCapture(event.pointerId))return;seek(pointerFrame(event.clientX,ruler.getBoundingClientRect().left,ruler.getBoundingClientRect().width,t.duration_frames))});
 ruler.addEventListener('pointerup',event=>{if(ruler.hasPointerCapture(event.pointerId))ruler.releasePointerCapture(event.pointerId)});
 ruler.addEventListener('keydown',event=>{const delta={ArrowRight:1,ArrowLeft:-1,PageDown:t.fps,PageUp:-t.fps}[event.key];if(delta!==undefined){event.preventDefault();seek(frame+delta)}else if(event.key==='Home'){event.preventDefault();seek(0)}else if(event.key==='End'){event.preventDefault();seek(t.duration_frames-1)}});
 zoom.oninput=()=>{content.style.width=(100*Number(zoom.value))+'%';scale.textContent=num(zoom.value)+'×';drawTicks()};drawTicks();
 return {panel,setFrame,get frame(){return frame},get zoom(){return Number(zoom.value)},setZoom(value){zoom.value=Math.min(8,Math.max(1,Number(value)||1));zoom.oninput()},select(id){for(const [key,b]of clips){b.classList.toggle('selected',key===id);b.setAttribute('aria-pressed',String(key===id))}},tools};
}

import {wheelBalance,balancePoint} from './timeline-math.mjs';
export function colorWheel({el,num,fields,parse,title}) {
 const wheel=el('div',null,{class:'balance-wheel',role:'group','aria-label':'عجلة '+title}),point=el('i',null,{class:'balance-point','aria-hidden':'true'});
 const read=()=>Object.fromEntries(Object.entries(fields).map(([k,x])=>[k,parse(x.value)]));
 const set=event=>{const rect=wheel.getBoundingClientRect();let x=(event.clientX-rect.left)/rect.width*2-1,y=(event.clientY-rect.top)/rect.height*2-1;const values=wheelBalance(x,y);for(const [k,field]of Object.entries(fields))field.value=num(values[k]);sync()};
 function sync(){const {x,y}=balancePoint(read());point.style.left=(50+50*x)+'%';point.style.top=(50+50*y)+'%'}
 wheel.append(point);wheel.setAttribute('tabindex','0');
 wheel.addEventListener('pointerdown',event=>{if(event.button!==0)return;wheel.setPointerCapture(event.pointerId);set(event);event.preventDefault()});
 wheel.addEventListener('pointermove',event=>{if(wheel.hasPointerCapture(event.pointerId))set(event)});
 wheel.addEventListener('pointerup',event=>{if(wheel.hasPointerCapture(event.pointerId))wheel.releasePointerCapture(event.pointerId)});
 wheel.addEventListener('keydown',event=>{const deltas={ArrowRight:[.03,0],ArrowLeft:[-.03,0],ArrowDown:[0,.03],ArrowUp:[0,-.03],Home:[0,0]};if(!deltas[event.key])return;event.preventDefault();const old=balancePoint(read()),[dx,dy]=deltas[event.key],v=event.key==='Home'?wheelBalance(0,0):wheelBalance(old.x+dx,old.y+dy);for(const [k,field]of Object.entries(fields))field.value=num(v[k]);sync()});
 for(const field of Object.values(fields))field.addEventListener('input',sync);sync();
 return {element:wheel,sync};
}

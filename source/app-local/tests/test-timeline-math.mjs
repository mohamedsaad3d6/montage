import test from 'node:test';
import assert from 'node:assert/strict';
import {clampFrame,pointerFrame,cursorInPreview,rulerTicks,selectionAt} from '../web/control/timeline-math.mjs';
test('zoomed and horizontally scrolled ruler coordinates map to integer output frames',()=>{
 assert.equal(pointerFrame(250,-50,600,144),72);
 assert.equal(pointerFrame(250,-350,1200,144),72);
 assert.equal(pointerFrame(-100,0,100,144),0);
 assert.equal(pointerFrame(1000,0,100,144),143);
 assert.equal(pointerFrame(0,0,0,144),0);
});
test('preview time bounds never seek into another output window',()=>{
 assert.equal(cursorInPreview(240,240,72),true);
 assert.equal(cursorInPreview(311,240,72),true);
 assert.equal(cursorInPreview(312,240,72),false);
 assert.equal(cursorInPreview(239,240,72),false);
 assert.equal(cursorInPreview(240.5,240,72),false);
 assert.equal(clampFrame(Infinity,144),0);
});
test('ruler scales for short and full episodes without thousands of marks',()=>{
 for(const duration of [1,144,24596,24*3600])for(const zoom of [1,4,8]){
  const ticks=rulerTicks(duration,24,zoom);assert.ok(ticks.length>0&&ticks.length<=100);
  assert.ok(ticks.every(f=>Number.isInteger(f)&&f>=0&&f<duration));
 }
 assert.deepEqual(rulerTicks(0,24),[]);
});
test('workspace selection keeps the current shot or resolves a shot at the cursor',()=>{
 const tracks=[{id:'video',kind:'video',clips:[{id:'a',start_frame:0,end_frame:72},{id:'b',start_frame:72,end_frame:144}]}];
 assert.equal(selectionAt(tracks,'video',100)?.clip.id,'b');
 assert.equal(selectionAt(tracks,'video',100,'a')?.clip.id,'a');
 assert.equal(selectionAt(tracks,'voice',100),null);
});

import {wheelBalance,balancePoint} from '../web/control/timeline-math.mjs';
test('color wheel yields bounded finite renderer RGB values including out-of-circle drags',()=>{
 assert.deepEqual(wheelBalance(0,0),{r:0,g:0,b:0});
 for(const [x,y]of [[1,0],[-1,0],[.3,.4],[100,-100],[NaN,Infinity]]){
  const rgb=wheelBalance(x,y);assert.ok(Object.values(rgb).every(n=>Number.isFinite(n)&&n>=-.3&&n<=.3));
 }
 const point=balancePoint(wheelBalance(.2,-.6));assert.ok(Math.abs(point.x-.2)<.005&&Math.abs(point.y+.6)<.005);
 assert.ok(Math.hypot(...Object.values(balancePoint({r:.3,g:-.3,b:-.3})))<=1.001);
});

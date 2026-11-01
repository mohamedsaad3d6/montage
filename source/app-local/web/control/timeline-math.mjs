// Timeline coordinates are output frames. Never convert these into speech-cut evidence.
export function clampFrame(value, duration) {
  if (!Number.isSafeInteger(duration) || duration <= 0) return 0;
  return Math.min(duration - 1, Math.max(0, Math.round(Number.isFinite(value) ? value : 0)));
}
export function pointerFrame(clientX, left, width, duration) {
  if (![clientX,left,width].every(Number.isFinite) || width <= 0) return 0;
  return clampFrame((clientX-left)/width*duration, duration);
}
export function cursorInPreview(frame, start, length) {
  return Number.isSafeInteger(frame) && Number.isSafeInteger(start) && Number.isSafeInteger(length)
    && length > 0 && frame >= start && frame < start + length;
}
export function rulerTicks(duration, fps, zoom=1) {
  if (!Number.isSafeInteger(duration) || duration <= 0 || !Number.isFinite(fps) || fps <= 0) return [];
  const target=duration / fps / (10*Math.min(8,Math.max(1,zoom)));
  const steps=[1/fps,.25,.5,1,2,5,10,15,30,60,120,300,600,1200,3600];
  const step=Math.max(1,Math.round((steps.find(n=>n>=target)||target)*fps));
  const result=[];for(let frame=0;frame<duration;frame+=step) result.push(frame);
  return result;
}
export function selectionAt(tracks, kind, frame, previousId) {
  const candidates=tracks.filter(t=>t.kind===kind).flatMap(track=>track.clips.map(clip=>({track,clip})));
  return candidates.find(x=>x.clip.id===previousId)
    ||candidates.find(x=>x.clip.start_frame<=frame&&frame<x.clip.end_frame)
    ||candidates[0]||null;
}

// Bounded chroma offsets for the renderer's three RGB balance channels.
export function wheelBalance(x,y) {
  if (![x,y].every(Number.isFinite)) return {r:0,g:0,b:0};
  const radius=Math.max(1,Math.hypot(x,y));x/=radius;y/=radius;
  const clean=n=>Math.round(n*1000)/1000||0;
  return {r:clean(.3*x),g:clean(.3*(-.5*x+Math.sqrt(3)/2*y)),b:clean(.3*(-.5*x-Math.sqrt(3)/2*y))};
}
export function balancePoint({r=0,g=0,b=0}={}) {
  if (![r,g,b].every(Number.isFinite)) return {x:0,y:0};
  const x=(2*r-g-b)/.9,y=(g-b)/(.3*Math.sqrt(3)),radius=Math.max(1,Math.hypot(x,y));
  return {x:x/radius,y:y/radius};
}

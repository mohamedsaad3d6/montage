// Measured work only: never infer whole-film completion from transcription chunks.
export function transcriptionProgress(project,workflow,intake){
 const preparation=workflow.input_preparation;
 if(!preparation)return null;
 const job=project.jobs.find(j=>j.id===preparation.job);let options;try{options=JSON.parse(job?.options||'{}')}catch{return null}
 if(!intake||options.input_version!==intake.version||intake.selection.voice_mode!=='external_cut')return null;
 const sources=[['camera',intake.selection.video],['master',intake.selection.voice]],chunks=new Map((preparation.chunks||[]).map(x=>[x.source,x]));let done=0,total=0;
 for(const [source,id]of sources){const a=project.assets.find(a=>a.id===id);if(!a||!Number.isFinite(a.duration)||a.duration<=0)return null;total+=a.duration;const n=chunks.get(source)?.completed_seconds??0;if(!Number.isFinite(n)||n<0)return null;done+=Math.min(a.duration,n)}
 return {percent:Math.min(100,Math.floor(100*done/total)),completedSeconds:done,totalSeconds:total,label:'تقدم تفريغ الملفين',scope:'transcription_only'};
}
// Fixed ordered milestones. Percent is work progress, never a quality approval or ETA.
export function episodeProgress(stages,project,workflow,intake,render){
 const complete=s=>['complete','technical_complete','not_required'].includes(s.status);let index=stages.findIndex(s=>!complete(s));if(index<0)return {percent:100,completed:stages.length,total:stages.length,label:'اكتملت مراحل العمل',detail:'حالة الاعتماد مستقلة عن النسبة'};
 let fraction=0;const current=stages[index],jobs=project.jobs.filter(j=>j.revision===project.active),job=jobs.find(j=>['queued','running'].includes(j.status));
 if(current.status==='running'&&current.id==='words'){
  const measured=transcriptionProgress(project,workflow,intake);if(measured)fraction=measured.percent/100;
  else if(job?.total>0&&job.checkpoint>=0)fraction=Math.min(.95,job.checkpoint/job.total);
 }
 if(current.status==='running'&&['render','final_render'].includes(current.id)&&render?.stages?.length){
  const steps=render.stages;const n=steps.filter(s=>['completed','not_required'].includes(s.status)).length;let part=0;
  if(steps.some(s=>['materials','encode'].includes(s.id)&&s.status==='running')&&job?.total>0)part=Math.min(.95,Math.max(0,job.checkpoint/job.total));
  fraction=Math.min(.99,(n+part)/steps.length);
 }
 return {percent:Math.floor(100*(index+Math.max(0,Math.min(.99,fraction)))/stages.length),completed:index,total:stages.length,label:current.title,detail:current.status==='blocked'?'التقدم محفوظ؛ هذه المرحلة متعطلة وتحتاج استكمالًا':'النسبة من مراحل متتابعة فعلية؛ ليست وقتًا متبقيًا أو اعتماد جودة'};
}

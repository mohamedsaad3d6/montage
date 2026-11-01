export function activityPanel(ctx,p){
 const {el,box,row,num,fmt}=ctx,working=p.jobs.filter(j=>['queued','running'].includes(j.status));if(!working.length)return null;
 const panel=box(el('h2','شغّال دلوقتي'));panel.classList.add('job-activity');panel.append(el('p','دي مراحل بدأها المحرك فعلًا، وليست نسبة إنجاز أو وقت انتهاء متوقّع.',{class:'note'}));
 for(const job of working){const current=job.activity?.current,version=p.revisions.find(v=>v.id===job.revision),card=el('div',null,{class:'activity-now'});card.append(el('strong',job.status==='queued'?'في انتظار دور المعالجة':current?.label||'بدأت المهمة — في انتظار أول مرحلة مسجلة'),el('span','نسخة '+num(version?.number||'؟')+(job.revision!==p.active?' · سابقة':' · الحالية'),{class:'chip wait'}));if(current?.elapsed_seconds!=null&&job.status==='running')card.append(el('p','وقت المرحلة حتى الآن: '+fmt(Math.floor(current.elapsed_seconds)),{class:'note'}));if(job.status==='queued')card.append(el('p','المهام الثقيلة تعمل بالتتابع؛ انتظار الدور لا يعني أن التحليل بدأ.',{class:'note'}));panel.append(card)}
 return panel;
}
export function activityHistory(ctx,job){
 const {el,num,fmt}=ctx,history=job.activity?.history;if(!history?.length)return null;const details=el('details',null,{class:'activity-history'});details.append(el('summary','خطوات المهمة المسجلة · '+num(history.length)));
 for(const item of history){const row=el('div',null,{class:'activity-event'});row.append(el('span',item.label),el('time',new Intl.DateTimeFormat('ar-EG',{timeZone:'Africa/Cairo',hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(new Date(item.started*1000))),el('span',item.elapsed_seconds==null?'نهاية المرحلة غير مسجلة':fmt(Math.floor(item.elapsed_seconds))));details.append(row)}return details;
}

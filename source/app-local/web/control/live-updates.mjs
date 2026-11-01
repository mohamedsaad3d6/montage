import {busyJobs,stateSignature,liveLabel} from './live-state.mjs';
// This component owns only its banner. Never replace the page, forms, players or navigation. Status spans may update in place.
export function createLiveUpdates(ctx,initial){
 const {root,el,box,button,api,num,reload}=ctx,baseline=stateSignature(initial),panel=box(),title=el('h2','متابعة الشغل'),note=el('p','حالة المهمة تتحدّث هنا؛ الصفحة والسماع والبيانات التي تكتبها ثابتة.',{class:'note'}),status=el('p','',{class:'live-status'}),list=el('div'),changes=el('p','',{class:'note'}),manual=button('عرض الحالة والنتائج المحدثة',reload);
 panel.classList.add('live-updates');panel.setAttribute('aria-label','متابعة المهمة دون إعادة تحميل');panel.append(title,note,status,list,changes,manual);root.insertBefore(panel,root.children[1]||null);
 const entries=new Map();let stopped=false;
 function draw(state){
  for(const node of root.querySelectorAll('[data-job-status]')){const job=(state.jobs||[]).find(j=>j.id===node.dataset.jobStatus);if(job){node.textContent=({completed:'اكتملت',queued:'في الطابور',running:'جارٍ التنفيذ',failed:'فشلت',cancelled:'ملغاة'})[job.status]||job.status;node.className='chip '+(job.status==='failed'?'fail':job.status==='completed'?'':'wait')}}
  for(const node of root.querySelectorAll('[data-job-cancel]')){const job=(state.jobs||[]).find(j=>j.id===node.dataset.jobCancel);if(job&&!['queued','running'].includes(job.status))node.disabled=true}
  const busy=busyJobs(state);status.textContent=busy.length?'مهام في التنفيذ أو الانتظار: '+num(busy.length):'انتهت المهام الجارية أو توقفت. افتح النتائج لمعرفة حالتها.';
  const jobs=busy.length?busy:(state.jobs||[]).filter(j=>!(initial.jobs||[]).some(old=>old.id===j.id&&old.status===j.status));
  for(const j of jobs){let item=entries.get(j.id);if(!item){const card=el('div',null,{class:'live-job'}),text=el('p'),elapsed=el('small');card.append(text,elapsed);list.append(card);item={card,text,elapsed};entries.set(j.id,item)}item.text.textContent=liveLabel(j);const current=j.activity?.current;item.elapsed.textContent=j.status==='running'&&current?.elapsed_seconds!=null?'وقت المرحلة: '+num(Math.floor(current.elapsed_seconds))+' ثانية':'';}
  for(const [id,item]of entries)if(!jobs.some(j=>j.id===id)){item.card.remove();entries.delete(id)}
  changes.textContent=stateSignature(state)!==baseline?'فيه نتيجة أو حالة جديدة. احفظ أي تعديلات قبل عرضها؛ لن نعيد تحميل الصفحة تلقائيًا.':'عرض النتائج الجديدة يتم بالزر فقط؛ اكتمال المهمة لا يمنح اعتماد الصوت أو النشر.';return busy.length>0;
 }
 draw(initial);
 return {async poll(){if(stopped||!ctx.isCurrent())return false;try{const state=await api('/api/project?id='+initial.id+'&jobs_only=1');if(stopped||!ctx.isCurrent())return false;return draw(state)}catch(error){if(ctx.isCurrent())status.textContent='تعذّر تحديث حالة المهمة؛ ده لا يؤكد توقف المعالجة. يمكنك عرض الحالة يدويًا.';return false}},stop(){stopped=true}};
}

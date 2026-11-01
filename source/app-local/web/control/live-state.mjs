export const busyJobs=state=>(state.jobs||[]).filter(j=>['queued','running'].includes(j.status));
export function stateSignature(state){return JSON.stringify([state.active,(state.jobs||[]).map(j=>[j.id,j.status,j.revision]).sort((a,b)=>String(a[0]).localeCompare(String(b[0])))])}
export function liveLabel(job){
 if(job.status==='queued')return 'في انتظار دور المعالجة';
 if(job.status==='running')return job.activity?.current?.label||'المهمة جارية — تفاصيل المرحلة غير مسجلة';
 return {completed:'اكتملت المهمة فنيًا — المراجعة مستقلة',failed:'توقفت المهمة بخطأ',cancelled:'المهمة ملغاة'}[job.status]||'حالة مسجلة';
}

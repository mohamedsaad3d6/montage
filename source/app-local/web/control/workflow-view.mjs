// Display measured evidence; release authority stays in the exact-file server gate.
export function workflowView(project){
 const t=project.revision.timeline,jobs=project.jobs||[],active=jobs.filter(j=>j.revision===project.active),read=j=>{try{return JSON.parse(j?.result||'{}')}catch{return {}}},done=kind=>active.filter(j=>j.kind===kind&&j.status==='completed'),busy=kind=>active.some(j=>j.kind===kind&&['running','queued'].includes(j.status));
 const inherited=t.local_cut_analysis_job?jobs.find(j=>j.id===t.local_cut_analysis_job&&j.kind==='editorial_plan'&&j.status==='completed'):null;
 const analysis=active.find(j=>['transcribe','editorial_plan'].includes(j.kind)&&j.status==='completed')||inherited;
 const preparation=active.find(j=>j.kind==='input_prepare'&&['running','queued','completed'].includes(j.status)),phase=preparation?.activity?.current?.phase;
 const referenceWords=['reference_camera_asr','reference_master_asr','reference_word_match','reference_acoustic_match'].includes(phase),sourcesChecked=referenceWords||preparation?.activity?.history?.some(x=>x.phase==='source_check'&&x.finished!=null);
 const approved=project.production.ready_for_montage===true,montage=t.phase==='montage_candidate',picture=t.duration_frames>0,cut=!!t.cutting_proof||t.phase==='cut_candidate';
 const plan=jobs.find(j=>j.id===t.montage_plan&&j.kind==='shot_plan'&&j.status==='completed'),sourceJobs=plan?jobs.filter(j=>j.revision===plan.revision):[];
 const sourceReviewed=sourceJobs.some(j=>j.kind==='audio_review'&&j.status==='completed'&&read(j).review_complete===true&&read(j).gate?.status==='passed_for_review');
 const preApproved=montage?sourceReviewed:approved,candidates=read(analysis).retake_candidates??t.unresolved_take_comparisons??null;
 const localDone=cut||!!t.local_cut_analysis_job||preApproved,draftDone=montage?sourceJobs.some(j=>j.kind==='render'&&j.status==='completed'):done('render').length>0;
 const creative=['shot_plan','generate_graphic','generate_music','archive_search','archive_collect','inspect_asset','preview_transition'].some(busy);
 const stages=[
 {id:'intake',title:'استيراد الملفات وفحصها',status:picture||sourcesChecked?'complete':busy('input_prepare')?'running':'waiting',detail:picture?'الملفات مرتبطة بالحلقة والأصل محفوظ':'فحص الفيديو والصوت والسكريبت قبل المعالجة'},
 {id:'words',title:'التفريغ والمحاذاة',status:analysis?'complete':busy('transcribe')||busy('editorial_plan')||busy('reference_refine')||referenceWords&&busy('input_prepare')?'running':'waiting',detail:analysis?'التحليل محفوظ ومرتبط بالمصدر':'تفريغ الكلمات وتحديد مواضعها ومطابقة الصوت عند الحاجة'},
 {id:'cuts',title:'التقطيع المحلي وتجهيز الوصلات',status:localDone?'complete':busy('take_assess')?'running':'waiting',detail:localDone?'خطة محلية محفوظة؛ '+(candidates==null?'حسم الجودة في المراجعة التالية':candidates+' مقارنة محتملة محفوظة للمراجعة دون حذف تخميني'):'فحص التكرار والسكتات والنفس وحفظ غير المحسوم'},
 {id:'render',title:'إخراج مسودة التقطيع وفحصها',status:!montage&&busy('render')?'running':draftDone?'technical_complete':'waiting',detail:'إنشاء ملف المسودة اللازم للاستماع؛ هذه ليست النسخة النهائية'},
 {id:'audio',title:'مراجعة الصوت والإصلاح',status:!montage&&busy('audio_review')?'running':preApproved?'complete':draftDone?'blocked':'waiting',gate:true,detail:'مراجعة نفس الملف وحسم المقارنات ثم إعادة فحص الإصلاح قبل المونتاج'},
 {id:'montage',title:'الخامات والمونتاج',status:creative?'running':montage&&plan?'complete':preApproved?'available':'waiting',detail:'اختيار اللقطات والجرافيك والخرائط والانتقالات على جمل مكتملة'},
 {id:'final_render',title:'إخراج المونتاج وفحصه',status:montage&&busy('render')?'running':montage&&done('render').length?'technical_complete':'waiting',detail:'تجميع الصورة والصوت والموسيقى وفحص النسخة المركبة'},
 {id:'visual',title:'المراجعة النهائية والاعتماد',status:montage&&busy('audio_review')?'running':project.production.publication_approved?'complete':montage&&done('render').length?'needs_review':'waiting',gate:true,detail:'مراجعة صوت وصورة النسخة النهائية؛ لا اعتماد من مجرد نجاح الرندر'}
 ];
 const current=stages.find(s=>s.status==='running')||stages.find(s=>!['complete','not_required','technical_complete'].includes(s.status));
 return {stages,current:current?.id||'visual',analysis,approved,canApplyQuiet:!!analysis&&project.production.raw_review_complete===true&&t.phase==='raw'};
}

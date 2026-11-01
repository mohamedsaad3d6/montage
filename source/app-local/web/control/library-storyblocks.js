export async function storyblocksLibrary(ctx,p,content,enqueue){
 const {el,box,row,button,num,api}=ctx;
 const info=el('p','جارٍ قراءة حالة الاختيار…',{class:'note'}),toggle=button('فعّل الاختيار التلقائي',change,true),automatic=box(el('h2','اختيار لقطات للحلقة تلقائيًا'),info,toggle),proposals=el('div');
 content.append(automatic,proposals);
 automatic.append(el('p','Codex يقرأ كلام الحلقة ويختار لقطات مع توقيتها وسبب اختيارها. الدفعة الأولى حتى ٦ جمل؛ المعاينة والتنزيل لكل لقطة من النتائج أدناه.',{class:'note'}));
 let status,lastJob=null,busyChange=false;
 async function change(){
  if(!status||busyChange)return;busyChange=true;toggle.disabled=true;
  try{status=await api('/api/storyblocks/automatic',{project:p.id,expected:p.active,enabled:!status.enabled});await update()}catch(e){info.textContent=e.message}finally{busyChange=false;toggle.disabled=false}
 }
 async function update(){
  status=await api('/api/storyblocks/automatic?project='+p.id);if(!ctx.isCurrent())return;
  toggle.textContent=status.enabled?'أوقف الاختيار التلقائي':'فعّل الاختيار التلقائي';toggle.disabled=busyChange;
  const j=status.job,labels={queued:'في انتظار المهمة الحالية',running:'يختار لقطات الآن',completed:'اكتمل اختيار الدفعة الأولى',failed:'تعذّر إكمال الاختيار',cancelled:'توقف الاختيار'};
  info.textContent=status.enabled?(j?labels[j.status]+(j.error?' — '+j.error:''):'مفعّل؛ يبدأ تلقائيًا عند توفر تفريغ مطابق وانتهاء المهمة الحالية'):'الاختيار التلقائي غير مفعّل لهذه الحلقة';
  const key=j?.id+':'+j?.status;if(key!==lastJob&&j?.status==='completed'){
   lastJob=key;proposals.replaceChildren();const result=JSON.parse(j.result||'{}');
   proposals.append(el('h2','اختيارات مرتبطة بكلام الحلقة — '+num(result.selected_count||0)+' لقطات'));
   if(!result.choices?.length)proposals.append(el('p','لم يجد الاختيار جملًا مناسبة لهذه الدفعة.',{class:'notice'}));
   for(const choice of result.choices||[]){const scene=box(el('h3',choice.text),el('p',time(choice.start_ms)+' — '+time(choice.end_ms),{class:'note'}),el('p',choice.reason));if(choice.item)scene.append(itemCard(choice.item,j));else scene.append(el('p','لم تُقبل لقطة مناسبة؛ لن تُستخدم لقطة لا تطابق الكلام.',{class:'note'}));proposals.append(scene)}
   if(result.source_errors?.length)proposals.append(el('p','تعذر بحث '+num(result.source_errors.length)+' من الجمل؛ لم تُستبدل بنتائج غير مطابقة.',{class:'notice'}));
  }
 }
 function time(ms){const s=Math.floor(ms/1000);return num(Math.floor(s/60))+':'+num(String(s%60).padStart(2,'0'))}
 function itemCard(item,j){
  const card=box(el('h3',item.title),el('p',item.duration?num(item.duration)+' ثانية':'',{class:'note'}));
  if(item.preview_url){const video=el('video',null,{src:item.preview_url,controls:'',preload:'none','aria-label':item.title});if(item.thumbnail_url)video.poster=item.thumbnail_url;video.style.width='100%';card.append(video)}else if(item.thumbnail_url)card.append(el('img',null,{src:item.thumbnail_url,alt:item.title,class:'image',loading:'lazy'}));
  if(item.page_url)card.append(el('a','تفاصيل اللقطة',{href:item.page_url,target:'_blank',rel:'noopener noreferrer'}));
  const previous=p.jobs.find(x=>x.kind==='storyblocks_collect'&&JSON.parse(x.options||'{}').item_id===item.id);
  const download=button(previous?.status==='completed'?'أضيفت للمكتبة':previous?'طلب التنزيل مسجل':'نزّل هذه اللقطة إلى المكتبة',()=>enqueue('storyblocks_collect',{search_job:j.id,item_id:item.id,consent_license:true}),true);download.disabled=!!previous;
  card.append(el('p','الاختيار مبني على وصف اللقطة؛ شاهد المعاينة للتحقق منها. التنزيل يسجل ترخيص هذه اللقطة في حساب Storyblocks المتصل.',{class:'note'}),download);return card;
 }
 const query=el('input',null,{'aria-label':'وصف لقطة Storyblocks',placeholder:'مثال: oil tanker at sea'}),subject=el('input',null,{'aria-label':'العنصر الأساسي في اللقطة',placeholder:'مثال: tanker'});
 const find=button('ابحث عن لقطات',()=>enqueue('storyblocks_search',{query:query.value,subject:subject.value,page:1}),true);
 content.append(box(el('h2','بحث إضافي'),query,subject,find));
 for(const j of p.jobs.filter(j=>j.kind==='storyblocks_search'&&j.status==='completed'&&j.revision===p.active)){
  const result=JSON.parse(j.result||'{}'),section=box(el('h2','نتائج: '+result.query)),grid=el('div',null,{class:'material-grid'});section.append(grid);content.append(section);
  for(const item of result.results||[])grid.append(itemCard(item,j));
  if(!result.results?.length)grid.append(el('p','لم تظهر لقطات مطابقة. غيّر وصف البحث.',{class:'empty'}));
  if(result.results?.length&&result.page<100)section.append(row(button('نتائج أكثر',()=>enqueue('storyblocks_search',{query:result.query,subject:result.subject,page:(result.page||1)+1}))));
 }
 await update();
 async function poll(){if(!ctx.isCurrent())return;try{await update()}catch(e){info.textContent='تعذر تحديث الحالة؛ الاختيار المحفوظ لم يتغير.'}if(ctx.isCurrent())setTimeout(poll,2000)}
 setTimeout(poll,2000);
}

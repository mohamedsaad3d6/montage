const labels={presentation:'طريقة العرض',editing:'التقطيع والإيقاع',transitions:'الانتقالات',motion_graphics:'الموشن جرافيك',maps:'الخرائط',titles:'العناوين والكروت',audio:'الصوت والموسيقى',workflow:'تسلسل المشاهد'};
export async function channelReference(ctx,channel,host,head){
 const {api,el,row,button,num,reload}=ctx;let state=await api('/api/channel-reference?channel='+channel.id);if(!ctx.isCurrent())return;
 const panel=el('section',null,{class:'reference-import'}),url=el('input',null,{type:'url','aria-label':'رابط مرجع القناة',placeholder:'https://www.youtube.com/@channel',dir:'ltr'});url.value=state.url||(/^https:\/\/www\.youtube\.com\//.test(channel.reviewer)?channel.reviewer:'');
 const label=el('label','رابط مرجع القناة');label.append(url);const consent=el('input',null,{type:'checkbox','aria-label':'تحليل عينات الفيديو عبر Google المجاني'}),consentLabel=el('label','تحليل أول دقيقة من ثلاثة فيديوهات عامة عبر Google المجاني؛ يرسل الروابط فقط، دون رفع ملفاتك');consentLabel.prepend(consent);
 const message=el('p',null,{class:'note','aria-live':'polite'}),results=el('div');let last='';
 const analyze=button('حلّل المرجع واملأ هوية القناة',async()=>{message.textContent='جارٍ قراءة المرجع…';state=await api('/api/channel-reference/analyze',{channel:channel.id,url:url.value,video_consent:consent.checked});draw();watch()},true);
 panel.append(el('h3','المطابقة بالمرجع'),label,consentLabel,row(analyze),message,results);host.append(panel);
 function draw(){
  analyze.disabled=state.state==='running';url.disabled=analyze.disabled;consent.disabled=analyze.disabled;
  message.textContent=({empty:'أضف مرجعًا، ثم شغّل التحليل. ستراجع النتيجة قبل حفظها.',running:'جارٍ تحليل المرجع؛ تقدر تسيب الصفحة وترجع لها.',identity_ready:'هوية القناة جاهزة. أسلوب الفيديو لم يكتمل.',ready:'الهوية وملاحظات العينات جاهزة للمراجعة.',applied:'تم حفظ هوية المرجع؛ قواعد التقطيع والنسخ الحالية محفوظة.',interrupted:'توقف التحليل مع إغلاق التطبيق؛ يمكنك إعادة تشغيله.',failed:'لم يكتمل التحليل؛ بيانات القناة لم تتغير.'}[state.state]||'')+(state.error?' '+state.error:'');
  const signature=JSON.stringify([state.state,state.run,state.data]);if(last===signature)return;last=signature;results.replaceChildren();const d=state.data||{},m=d.identity;
  if(!m)return;
  results.append(el('h3',m.name),el('p',m.description),el('a','افتح المرجع',{href:m.source_url,target:'_blank',rel:'noopener noreferrer'}));
  if(m.logo_preview){results.append(el('img',null,{src:m.logo_preview,alt:'شعار القناة من المرجع',class:'kit-logo-preview'}));if(state.state==='applied'){const logo=el('img',null,{src:m.logo_preview,alt:m.name,class:'channel-letter large'});head.firstChild.replaceWith(logo)}}
  if(m.palette?.length){const colors=row(el('span','ألوان مستخرجة من الشعار: '));for(const c of m.palette){const swatch=el('span',c,{class:'chip',dir:'ltr'});swatch.style.border='2px solid '+c;colors.append(swatch)}results.append(colors)}
  if(d.logo_error)results.append(el('p',d.logo_error,{class:'notice'}));
  if(d.style){results.append(el('h3','أسلوب العرض المرصود — اقتراح للمراجعة'));for(const x of d.style.observations){const line=el('p');line.append(el('strong',(labels[x.category]||x.category)+': '),document.createTextNode(x.text+' '),el('a',num(x.start)+'–'+num(x.end)+' ثانية',{href:'https://www.youtube.com/watch?v='+x.video_id+'&t='+Math.floor(x.start),target:'_blank',rel:'noopener noreferrer'}),el('small',' · '+({high:'ثقة مرتفعة',medium:'ثقة متوسطة',low:'ثقة محدودة'}[x.confidence])));results.append(line)}for(const x of d.style.limitations)results.append(el('p',x,{class:'note'}))}
  else results.append(el('p','إيقاع القطع والانتقالات والخط وألوان الفيديو لم تُستنتج من اسم القناة أو الشعار. تحتاج تحليل عينات فيديو.',{class:'note'}));
  if(['ready','identity_ready'].includes(state.state))results.append(button('اعتمد البيانات المستخرجة واحفظها',async()=>{await api('/api/channel-reference/apply',{channel:channel.id,run:state.run});await reload()},true));
  results.append(el('p','يحفظ الاسم والوصف والحساب والشعار وملاحظات الأسلوب. لا يغيّر الفيديوهات أو قواعد الصوت المعتمدة، ولا يحوّل ملاحظات النموذج تلقائيًا إلى أوامر قص.',{class:'note'}));
 }
 let timer;function watch(){clearTimeout(timer);if(state.state!=='running')return;timer=setTimeout(async()=>{if(!ctx.isCurrent())return;try{state=await api('/api/channel-reference?channel='+channel.id);if(!ctx.isCurrent())return;draw();watch()}catch{message.textContent='تعذر تحديث الحالة. أعد فتح الصفحة للتحقق؛ لا تعِد الطلب تلقائيًا.'}},2000)}draw();watch();return state;
}

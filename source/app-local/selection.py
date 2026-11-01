"""Auditable semantic shortlist. Unverified frames and mismatched events are rejected."""
import json,re
from editorial import norm
ALIASES={
 'mbs':['محمد بن سلمان','ولي العهد السعودي','ابن سلمان'],
 'trump':['ترامب','ترمب','دونالد ترامب'],
 'houthis':['الحوثيين','الحوثي','الحوثيون'],
 'saudi':['السعودية','المملكة العربية السعودية'],
 'yemen':['اليمن','يمني'],
 'hormuz':['هرمز'], 'redsea':['البحر الاحمر'], 'bab':['باب المندب'],
 'economy':['اقتصاد','الاقتصاد','نمو','النمو'], 'oil':['نفط','النفط','البترول','بترول','الطاقة'], 'trade':['تجارة','التجارة','التجارة العالمية'], 'inflation':['التضخم','الأسعار','اسعار'], 'diplomacy':['العلاقات الدولية','تحالف','تحالفات'], 'policy':['قرارات','سياسة','السياسة'],
 'patriot':['باتريوت'], 'ship':['السفن','ناقلة','ناقلات','الملاحة','سفينة']}
ACTUAL_EVENT=['هجوم','هجمات','هاجم','قصف','قصفوا','ضربوا','مظاهرات','متظاهرين','تظاهروا','معركة']
MAP_WORDS=['خريطة','مضيق','موقع','جغرافيا','بين','حدود','قناة','خليج','شرق','غرب','شمال','جنوب','كيلومتر','يمتد','مسار']
def tags(text):
 n=' '+norm(text)+' ';return {k for k,aliases in ALIASES.items() if any(' '+norm(a)+' ' in n for a in aliases)}
def shortlist(text,assets,seconds=4):
 wanted=tags(text);n=norm(text);event=any(norm(w) in n.split() for w in ACTUAL_EVENT);geo=any(norm(w) in n.split() for w in MAP_WORDS);people=wanted&{'mbs','trump'};year=re.search(r'\b(19\d\d|20\d\d)\b',n);accepted=[];rejected=[]
 for a in assets:
  m=a.get('metadata',{});m=json.loads(m) if isinstance(m,str) else m;subject=set(m.get('subjects',[]));reason=None;kind=m.get('visual_type','unknown')
  if a.get('source_type')=='review_evidence':reason='review_evidence_is_not_visual_material'
  elif m.get('excluded_from_suggestions') is True:reason='excluded_by_editor'
  elif not m.get('rights_verified'):reason='usage_rights_not_verified'
  elif m.get('credit_required'):reason='requires_visible_credit_not_compatible_with_clean_style'
  elif not m.get('visual_verified') or not m.get('verification_frames'):reason='actual_frames_not_verified'
  elif a.get('duration',0)<seconds and a.get('kind')!='image':reason='insufficient_unique_material_no_loop'
  elif people and not people.issubset(subject):reason='wrong_or_missing_named_person'
  elif len(people)==1 and m.get('focus_person') not in people:reason='person_focus_not_verified'
  elif event and (kind not in ['event_footage','event_photo'] or not m.get('event_verified')):reason='map_or_generic_material_cannot_document_event'
  elif kind=='map' and not geo:reason='no_geographic_purpose'
  elif year and not m.get('illustrative',False) and not (m.get('year_start',9999)<=int(year[1])<=m.get('year_end',0)):reason='period_mismatch'
  elif wanted and not (wanted&subject):reason='no_subject_match'
  elif not wanted:reason='insufficient_semantic_evidence'
  if reason:rejected.append({'asset_id':a['id'],'reason':reason});continue
  score=len(wanted&subject)*10+len(people&subject)*30+(10 if geo and kind=='map' else 0)
  accepted.append({'asset_id':a['id'],'score':score,'subjects_matched':sorted(wanted&subject),'reason':'فرد/موضوع وحقبة وطبيعة لقطة موثقة، وليست مجرد تطابق اسم المكان.'})
 accepted.sort(key=lambda x:(-x['score'],x['asset_id']))
 return {'narration':text,'required_subjects':sorted(wanted),'event_footage_required':event,'candidates':accepted,'rejected':rejected,'status':'proposed_requires_review' if accepted else 'retain_presenter_no_verified_match','automatic_apply':False}

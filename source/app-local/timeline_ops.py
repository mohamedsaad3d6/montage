"""Frame-exact visual edits. Narration, duration and source speech never change here."""
import copy
from core import Invalid,Conflict,uid

def integer(data,key):
 value=data.get(key)
 if type(value)!=int:raise Invalid('التوقيت يحتاج عدد إطارات صحيحًا')
 return value

def apply(store,project,expected,operation):
 p=store.project(project)
 if p['active']!=expected:raise Conflict('النسخة تغيرت؛ حدّث المحرر قبل التعديل')
 if not isinstance(operation,dict):raise Invalid('عملية تعديل غير صالحة')
 kind=operation.get('type')
 if kind in ['undo','redo','restore']:
  target=operation.get('revision')
  if kind=='undo':target=p['revision']['parent']
  if not target:raise Invalid('لا توجد نسخة للرجوع إليها')
  rev=store.revision(target)
  if rev['project']!=project:raise Invalid('النسخة من حلقة أخرى')
  if kind=='redo' and rev['parent']!=expected:raise Invalid('اختَر فرع إعادة تابعًا للنسخة الحالية')
  with store.connect() as c:
   c.execute('BEGIN IMMEDIATE')
   from lifecycle import usable
   usable(store,project,target,c)
   if store.one(c,'SELECT active FROM projects WHERE id=?',(project,))['active']!=expected:raise Conflict('النسخة تغيرت أثناء التعديل')
   c.execute('UPDATE projects SET active=? WHERE id=?',(target,project))
  return store.project(project)
 t=copy.deepcopy(p['revision']['timeline']);track=next((x for x in t['tracks'] if x['id']==operation.get('track')),None)
 if not track:raise Invalid('المسار غير موجود')
 if kind=='lock':
  if type(operation.get('locked'))!=bool:raise Invalid('حالة القفل غير صالحة')
  track['locked']=operation['locked']
 else:
  if track.get('locked'):raise Invalid('المسار مقفول؛ افتحه قبل التعديل')
  if track['kind']=='voice':raise Invalid('أدوات الصورة لا تقص الكلام؛ تعديل الكلام يحتاج خطة كلمات ومراجعة مستقلة')
  clips=sorted(track['clips'],key=lambda x:x['start_frame']);clip=next((c for c in clips if c['id']==operation.get('clip')),None)
  if not clip:raise Invalid('اختَر لقطة من المسار')
  index=clips.index(clip)
  if kind=='split':
   if track['kind']!='video':raise Invalid('التقسيم الحالي للصورة فقط')
   at=integer(operation,'frame')
   if not clip['start_frame']<at<clip['end_frame']:raise Invalid('موضع التقسيم لازم يكون داخل اللقطة')
   right=copy.deepcopy(clip);right['id']=uid();right['start_frame']=at;right['source_in_frame']=clip.get('source_in_frame',0)+at-clip['start_frame'];right.setdefault('properties',{}).pop('transition',None)
   clip['end_frame']=at;clip['source_out_frame']=clip.get('source_in_frame',0)+at-clip['start_frame'];clips.insert(index+1,right)
  elif kind=='slip':
   if track['kind']!='video':raise Invalid('الانزلاق الحالي للصورة فقط')
   offset=integer(operation,'source_in_frame');clip['source_in_frame']=offset;clip['source_out_frame']=offset+clip['end_frame']-clip['start_frame'];clip.setdefault('properties',{}).pop('transition',None)
  elif kind=='roll':
   if track['kind']!='video' or index==len(clips)-1:raise Invalid('تعديل الوصلة يحتاج لقطة تالية في مسار الصورة')
   after=clips[index+1];boundary=integer(operation,'frame');old=clip['end_frame']
   if old!=after['start_frame'] or not clip['start_frame']<boundary<after['end_frame']:raise Invalid('حد الوصلة غير صالح')
   delta=boundary-old;clip['end_frame']=boundary;clip['source_out_frame']+=delta;after['start_frame']=boundary;after['source_in_frame']+=delta;after.setdefault('properties',{}).pop('transition',None)
  elif kind=='reorder':
   if track['kind']!='video':raise Invalid('إعادة الترتيب الحالية للصورة فقط')
   target=integer(operation,'index')
   if not 0<=target<len(clips):raise Invalid('ترتيب خارج المسار')
   cursor=0
   for item in clips:
    if item['start_frame']!=cursor:raise Invalid('المسار يحتاج تغطية متصلة قبل إعادة الترتيب')
    cursor=item['end_frame']
   if cursor!=t['duration_frames']:raise Invalid('مسار الصورة لا يغطي الحلقة')
   clips.pop(index);clips.insert(target,clip);cursor=0
   for item in clips:
    length=item['end_frame']-item['start_frame'];item['start_frame']=cursor;item['end_frame']=cursor+length;item.setdefault('properties',{}).pop('transition',None);cursor+=length
  elif kind=='move_overlay':
   if track['kind'] not in ['text','graphics','music','effects']:raise Invalid('النقل الحر للطبقات فقط؛ لا تُترك فجوة في الصورة')
   start=integer(operation,'frame');length=clip['end_frame']-clip['start_frame'];clip['start_frame']=start;clip['end_frame']=start+length
  else:raise Invalid('أداة التعديل غير مدعومة')
  track['clips']=clips
 # A visual tool cannot silently alter speech or the episode clock.
 old=p['revision']['timeline']
 if t['duration_frames']!=old['duration_frames'] or [x for x in t['tracks'] if x['kind']=='voice']!=[x for x in old['tracks'] if x['kind']=='voice']:
  if kind!='lock':raise Invalid('تعديل الصورة حاول تغيير الصوت أو مدة الحلقة')
 t['manual_visual_edit']=True
 return store.save(project,expected,t,{'split':'تقسيم الصورة دون تغيير الكلام','slip':'انزلاق خامة داخل نافذة الصورة','roll':'ضبط وصلة صورتين مع ثبات الصوت','reorder':'إعادة ترتيب الصور مع ثبات التعليق','move_overlay':'نقل طبقة دون تغيير الكلام','lock':'تغيير قفل المسار'}[kind])

"""Versioned local script drafts and truthful exports; no invented research or ASR."""
import json,time,html,io,zipfile
from core import Invalid,Conflict,uid,dump

def init(store):
 with store.connect() as c:
  c.execute('CREATE TABLE IF NOT EXISTS control_scripts(id TEXT PRIMARY KEY,project TEXT,version INTEGER,text TEXT,source TEXT,created REAL)')
  if 'plan_hash' not in {r[1] for r in c.execute('PRAGMA table_info(control_scripts)')}:c.execute('ALTER TABLE control_scripts ADD COLUMN plan_hash TEXT')

def drafts(store,project):
 store.project(project);init(store)
 with store.connect() as c:return [dict(x)for x in c.execute('SELECT * FROM control_scripts WHERE project=? ORDER BY version DESC',(project,))]

def save(store,data):
 project=data['project'];items=drafts(store,project);latest=items[0]['version'] if items else 0
 if type(data.get('expected_version'))!=int or data['expected_version']!=latest:raise Conflict('السكريبت تغير؛ حدّث الصفحة قبل الحفظ')
 text=data.get('text');source=str(data.get('source','manual'))
 if not isinstance(text,str) or not text.strip() or len(text)>250000:raise Invalid('اكتب سكريبتًا صالحًا حتى ٢٥٠ ألف حرف')
 if source not in ['manual','uploaded','transcript','outline_scaffold']:raise Invalid('مصدر السكريبت غير صالح')
 if source=='outline_scaffold':
  from script_plan import get
  plan=get(store,project)
  if not plan['outline_approved'] or data.get('plan_hash')!=plan['content_hash']:raise Invalid('الهيكل تغير أو لم يُعتمد؛ أعد تحميله')
 with store.connect() as c:
  c.execute('BEGIN IMMEDIATE');r=c.execute('SELECT MAX(version) FROM control_scripts WHERE project=?',(project,)).fetchone()
  if (r[0] or 0)!=latest:raise Conflict('السكريبت تغير أثناء الحفظ')
  if source=='outline_scaffold':
   current=c.execute('SELECT content_hash,approved_at FROM control_script_plans WHERE project=? ORDER BY version DESC LIMIT 1',(project,)).fetchone()
   if not current or current['approved_at'] is None or current['content_hash']!=data.get('plan_hash'):raise Conflict('الخطة تغيرت قبل حفظ المسودة')
  id=uid();c.execute('INSERT INTO control_scripts(id,project,version,text,source,created,plan_hash) VALUES(?,?,?,?,?,?,?)',(id,project,latest+1,text,source,time.time(),data.get('plan_hash') if source=='outline_scaffold' else None))
 return drafts(store,project)

def export(store,project,id,format):
 items=drafts(store,project);item=next((x for x in items if x['id']==id),None)
 if not item:raise Invalid('اختَر نسخة سكريبت محفوظة من نفس الحلقة')
 text=item['text']
 if format=='txt':return text.encode('utf-8'),'text/plain; charset=utf-8'
 if format=='docx':
  paragraphs=''.join('<w:p><w:pPr><w:bidi/><w:jc w:val="start"/><w:spacing w:after="120" w:line="360" w:lineRule="auto"/></w:pPr><w:r><w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/><w:sz w:val="28"/><w:szCs w:val="28"/><w:rtl/></w:rPr><w:t xml:space="preserve">'+html.escape(line)+'</w:t></w:r></w:p>'for line in text.split('\n'))
  document='<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+paragraphs+'<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440"/></w:sectPr></w:body></w:document>'
  buf=io.BytesIO()
  with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED)as z:
   z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
   z.writestr('_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
   z.writestr('word/document.xml',document)
  return buf.getvalue(),'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
 raise Invalid('اختَر TXT أو DOCX؛ لا ملف ترجمة بتوقيتات غير مثبتة')

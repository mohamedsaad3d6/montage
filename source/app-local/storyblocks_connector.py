"""Storyblocks through the signed-in local Codex app-server.

Search is read-only. Licensing requires a specific saved item and explicit user action.
Receipts are persisted before the non-idempotent call; uncertain calls are never retried.
"""
import json, os, queue, shutil, subprocess, threading, time
import urllib.parse, urllib.request, urllib.error
from pathlib import Path
from core import Invalid, Conflict, fingerprint
from media import Cancelled, probe, duration

MAX_BYTES = 512 * 1024 * 1024
TOOLS = {'search_videos', 'get_stock_item_details', 'get_download_url'}

def available():
    return bool(shutil.which('codex'))

def options_for(value):
    if not isinstance(value, dict) or set(value) - {'query', 'subject', 'page'}:
        raise Invalid('إعدادات بحث Storyblocks غير صالحة')
    query_text = value.get('query', '')
    subject = value.get('subject', '')
    page = value.get('page', 1)
    if not isinstance(query_text, str) or not 2 <= len(query_text.strip()) <= 180:
        raise Invalid('اكتب وصف اللقطة للبحث')
    if not isinstance(subject, str) or not 2 <= len(subject.strip()) <= 80:
        raise Invalid('حدد العنصر الأساسي المطلوب ظهوره في اللقطة')
    if type(page) is not int or not 1 <= page <= 100:
        raise Invalid('صفحة البحث غير صالحة')
    return {'query': query_text.strip(), 'subject': subject.strip(), 'page': page}

class Connector:
    def __init__(self, cwd, cancel=lambda: False):
        self.cwd = str(Path(cwd).resolve()); self.cancel = cancel
        self.process = None; self.messages = queue.Queue(); self.serial = 0

    def __enter__(self):
        binary = shutil.which('codex')
        if not binary: raise Invalid('ثبّت Codex وسجّل الدخول لربط Storyblocks')
        try:
            self.process = subprocess.Popen([binary, 'app-server', '--stdio'], cwd=self.cwd,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf-8', bufsize=1)
            def read():
                try:
                    for line in self.process.stdout:
                        try: self.messages.put(json.loads(line))
                        except ValueError: pass
                finally: self.messages.put(None)
            threading.Thread(target=read, daemon=True).start()
            self.rpc('initialize', {'clientInfo': {'name': 'montaj-storyblocks', 'version': '1.0.0'},
                'capabilities': {'experimentalApi': True}})
            self.write({'method': 'initialized', 'params': {}})
            result = self.rpc('thread/start', {'cwd': self.cwd, 'ephemeral': True,
                'sandbox': 'read-only', 'approvalPolicy': 'never', 'config': {'features.apps': True}})
            self.thread = result['thread']['id']
            return self
        except BaseException:
            self.__exit__(None, None, None); raise

    def write(self, obj):
        try:
            self.process.stdin.write(json.dumps(obj) + '\n'); self.process.stdin.flush()
        except (OSError, BrokenPipeError):
            raise Invalid('انقطع اتصال Storyblocks المحلي') from None

    def rpc(self, method, params, timeout=60):
        self.serial += 1; serial = self.serial
        self.write({'id': serial, 'method': method, 'params': params})
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if self.cancel(): raise Cancelled()
            try: message = self.messages.get(timeout=min(.25, max(.01, end-time.monotonic())))
            except queue.Empty: continue
            if message is None: raise Invalid('انقطع اتصال Storyblocks المحلي')
            if message.get('id') != serial: continue
            if 'error' in message: raise Invalid('تعذر طلب Storyblocks من اتصال Codex؛ راجع تسجيل الدخول وتفعيل الخدمة')
            return message.get('result', {})
        raise Invalid('انتهت مهلة Storyblocks؛ لم نكرر الطلب تلقائيًا')

    def call(self, tool, arguments):
        if tool not in TOOLS: raise Invalid('أداة Storyblocks غير مسموحة')
        result = self.rpc('mcpServer/tool/call', {'server': 'codex_apps',
            'tool': 'storyblocks.' + tool, 'threadId': self.thread, 'arguments': arguments})
        if not isinstance(result, dict) or result.get('isError'):
            raise Invalid('Storyblocks لم يؤكد نجاح الطلب؛ راجع الاتصال والحساب')
        value = result.get('structuredContent')
        if value is None:
            for block in result.get('content', []):
                if block.get('type') == 'text':
                    try: value = json.loads(block['text']); break
                    except (ValueError, KeyError): pass
        if not isinstance(value, dict) or value.get('error') or value.get('errors') or value.get('success') is False:
            raise Invalid('استجابة Storyblocks غير مكتملة؛ لم نعتبر العملية ناجحة')
        return value

    def __exit__(self, *args):
        p = self.process
        if p:
            if p.poll() is None:
                p.terminate()
                try: p.wait(timeout=3)
                except subprocess.TimeoutExpired: p.kill(); p.wait(timeout=3)
            for stream in (p.stdin, p.stdout):
                if stream: stream.close()

def search(folder, options, cancel=lambda: False):
    options = options_for(options)
    with Connector(folder, cancel) as client:
        payload = client.call('search_videos', {'keywords': options['query'],
            'required_keywords': options['subject'], 'page': options['page'], 'results_per_page': 12})
    if not isinstance(payload.get('results'), list): raise Invalid('لم تصل قائمة نتائج Storyblocks')
    results = []
    for item in payload['results']:
        if not isinstance(item, dict) or type(item.get('id')) is not int: continue
        results.append({'id': item['id'], 'source': 'storyblocks', 'title': str(item.get('title', ''))[:500],
            'duration': item.get('duration'), 'contentClass': 'videos',
            'page_url': safe_preview(item.get('details_url'), page=True),
            'thumbnail_url': safe_preview(item.get('thumbnail_url')),
            'preview_url': safe_preview(item.get('preview_url')),
            'orientation': item.get('orientation'), 'aspectRatio': item.get('aspectRatio')})
    return {'status': 'completed', 'source': 'storyblocks', 'query': options['query'],
        'subject': options['subject'], 'page': options['page'], 'results': results,
        'total_results': payload.get('total_results'), 'licensed': False,
        'scope': 'local_codex_connector_search', 'download_started': False}

def safe_preview(url, page=False):
    if not isinstance(url, str): return None
    try:
        u = urllib.parse.urlsplit(url)
        host = u.hostname or ''
        if u.scheme == 'https' and not u.username and not u.password and u.port in (None,443):
            if page and host in ('storyblocks.com','www.storyblocks.com'): return url
            if not page and host == 'dm0qx8t0i9gc9.cloudfront.net': return url
    except ValueError: pass
    return None

def selected(store, project, revision, options):
    if not isinstance(options, dict) or set(options) - {'search_job','item_id','consent_license'}:
        raise Invalid('اختيار لقطة Storyblocks غير صالح')
    if options.get('consent_license') is not True:
        raise Invalid('اختَر اللقطة واضغط تنزيلها؛ كل تنزيل يسجل ترخيصًا في Storyblocks')
    if type(options.get('item_id')) is not int:
        raise Invalid('معرّف لقطة Storyblocks غير صالح')
    with store.connect() as c:
        job = store.one(c, 'SELECT * FROM jobs WHERE id=?', (options.get('search_job'),))
    if job['project'] != project or job['revision'] != revision or job['kind'] not in ('storyblocks_search','storyblocks_autoselect') or job['status'] != 'completed':
        raise Invalid('اختَر لقطة من بحث Storyblocks المحفوظ لهذه الحلقة والنسخة')
    item = next((x for x in json.loads(job['result'] or '{}').get('results', [])
        if x.get('id') == options['item_id'] and x.get('source') == 'storyblocks'), None)
    if not item: raise Invalid('اللقطة ليست ضمن نتائج البحث المختارة')
    return item

def private_write(path, value):
    temp = path.with_suffix('.tmp')
    fd = os.open(temp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        if os.name != 'nt':
            os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, ensure_ascii=False); stream.flush(); os.fsync(stream.fileno())
    os.replace(temp, path)

def checked_download(url):
    try:
        u = urllib.parse.urlsplit(url); host = u.hostname or ''
        trusted = host in ('storyblocks.com','www.storyblocks.com','api.storyblocks.com') or host.endswith('.storyblocks.com') or host.endswith('.cloudfront.net')
        if u.scheme != 'https' or not trusted or u.username or u.password or u.port not in (None,443) or u.fragment:
            raise ValueError()
        path = urllib.parse.unquote(u.path).lower()
        if any(x in path for x in ('watermark', 'thumbnail', '/preview')): raise ValueError()
        return url  # Preserve signed query exactly.
    except (ValueError, TypeError):
        raise Invalid('لا رابط تنزيل أصلي موثوق لهذه اللقطة؛ لن نستخدم المعاينة') from None

class DownloadRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked_download(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def download_choice(payload):
    candidates = []
    def visit(obj, keys=()):
        if isinstance(obj, dict):
            for key, value in obj.items(): visit(value, keys+(str(key),))
        elif isinstance(obj, list):
            for value in obj: visit(value, keys)
        elif isinstance(obj, str) and obj.startswith('https://'):
            label = ' '.join(keys).lower()
            if any(x in label for x in ('preview','thumbnail','watermark','details','license_url')): return
            try: checked_download(obj)
            except Invalid: return
            path = urllib.parse.urlsplit(obj).path.lower()
            if path.endswith('.mp4') or 'mp4' in label:
                resolution = next((n for n in (4320,2160,1080,720,480) if str(n) in label+path),0)
                if '4k' in label: resolution = max(resolution,2160)
                candidates.append((resolution, obj, '.mp4'))
            elif path.endswith('.mov') or 'mov' in label: candidates.append((-1,obj,'.mov'))
            elif any(x in label for x in ('download_url','downloadurl','downloadurl')):
                candidates.append((-2,obj,'.mp4'))
    visit(payload)
    if not candidates: raise Invalid('لم يصل رابط ملف الفيديو الأصلي بصيغة مدعومة؛ سجل الترخيص محفوظ دون تكرار')
    _, url, ext = max(candidates)
    return url, ext

def download(url, path, cancel=lambda:False):
    checked_download(url); temp=path.with_suffix(path.suffix+'.part'); total=0; deadline=time.monotonic()+300
    temp.unlink(missing_ok=True)
    try:
        request=urllib.request.Request(url, headers={'User-Agent':'MontajLocal/0.4'})
        with urllib.request.build_opener(DownloadRedirect).open(request, timeout=25) as response:
            checked_download(response.geturl())
            if int(response.headers.get('Content-Length','0')) > MAX_BYTES:
                raise Invalid('اللقطة أكبر من حد التنزيل الحالي؛ الترخيص محفوظ دون إعادة طلب')
            with temp.open('xb') as output:
                while True:
                    if cancel(): raise Cancelled()
                    if time.monotonic()>deadline: raise Invalid('انتهت مهلة تنزيل الملف؛ سجل الترخيص محفوظ دون تكرار')
                    block=response.read(256*1024)
                    if not block: break
                    total+=len(block)
                    if total>MAX_BYTES: raise Invalid('تجاوزت اللقطة حد التنزيل الحالي')
                    output.write(block)
        if not total: raise Invalid('ملف Storyblocks فارغ')
        temp.replace(path)
    except (urllib.error.URLError, OSError, ValueError):
        raise Invalid('لم يكتمل تنزيل الملف؛ الترخيص محفوظ ولا يُعاد طلبه تلقائيًا') from None
    finally: temp.unlink(missing_ok=True)

def collect(store, rev, folder, options, cancel=lambda:False):
    item=selected(store,rev['project'],rev['id'],options)
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    receipts=store.root/'storyblocks-receipts';receipts.mkdir(mode=0o700,exist_ok=True)
    # One licensing claim for a given item/project. Concurrent jobs cannot double-license.
    receipt=receipts/(rev['project']+'-'+str(item['id'])+'.json')
    if receipt.exists():
        raise Conflict('طلب تنزيل هذه اللقطة مسجل بالفعل؛ راجع نتيجته ولا تكرر الترخيص')
    if cancel(): raise Cancelled()
    with Connector(folder,cancel) as client:
        # Establish connector and validate item before claiming a license.
        details=client.call('get_stock_item_details',{'contentClass':'videos','stockItemId':item['id'],'extended':'download_formats'})
        if not details.get('download_formats'): raise Invalid('لا صيغ تنزيل متاحة لهذه اللقطة')
        if cancel(): raise Cancelled()
        state={'state':'in_flight','project':rev['project'],'revision':rev['id'],'item_id':item['id'],
            'job':folder.name,'created':time.time(),'search_job':options['search_job']}
        try: fd=os.open(receipt,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        except FileExistsError: raise Conflict('يوجد طلب ترخيص سابق لهذه اللقطة') from None
        with os.fdopen(fd,'w') as stream:
            json.dump(state,stream);stream.flush();os.fsync(stream.fileno())
        try:
            payload=client.call('get_download_url',{'contentClass':'videos','stockItemId':item['id']})
        except BaseException:
            state['state']='needs_reconciliation';private_write(receipt,state);raise
        # Private response may contain signed URLs. Never put it in public job JSON.
        state.update(state='licensed_response_received',response=payload);private_write(receipt,state)
    url,ext=download_choice(payload);path=folder/('storyblocks-'+str(item['id'])+ext)
    if cancel(): raise Cancelled()
    download(url,path,cancel)
    info=probe(path)
    if not any(x.get('codec_type')=='video' and not x.get('disposition',{}).get('attached_pic') for x in info.get('streams',[])):
        path.unlink(missing_ok=True);raise Invalid('الملف المنزّل ليس فيديو صالحًا')
    seconds=duration(info,'video')
    if cancel(): raise Cancelled()
    asset=store.add_asset(rev['project'],str(path),seconds,'video')
    metadata={'archive_source':'storyblocks','archive_id':str(item['id']),'page_url':item.get('page_url'),
        'license_download_recorded':True,'license_scope':'Storyblocks connected account; project use must match its license',
        'rights_verified':False,'visual_verified':False,'requires_rights_review_for_this_project':True,
        'collected_from_search_job':options['search_job'],'storyblocks_collect_job':folder.name}
    with store.connect() as c:
        c.execute("UPDATE assets SET name=?,source_type='archive',metadata=? WHERE id=?",
            (item['title'][:240],json.dumps(metadata,ensure_ascii=False),asset))
    state.update(state='collected',asset_id=asset,file_sha256=fingerprint(path));private_write(receipt,state)
    return {'asset_id':asset,'source':'storyblocks','kind':'video','collected':True,
        'license_download_recorded':True,'visual_verified':False,'rights_verified':False,
        'timeline_changed':False,'bytes':path.stat().st_size,'scope':'licensed_download_imported_not_editorially_approved'}

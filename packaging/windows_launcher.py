"""Per-user Windows installer/launcher. Episode data and accounts stay on the receiving PC."""
import hashlib,json,os,queue,shutil,subprocess,sys,threading,time,urllib.request,urllib.error,webbrowser,zipfile
from pathlib import Path
BUNDLE=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))
APP_HOME=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'Montaj'
APP=APP_HOME/'app'; RUNTIME=APP/'runtime'; DATA=APP_HOME/'data'; CACHE=APP_HOME/'downloads'; EVENTS=queue.Queue()
VERSION='0.1.0-rc.1'
TOOLS=[
 ('uv','https://github.com/astral-sh/uv/releases/download/0.13.6/uv-x86_64-pc-windows-msvc.zip','a2a8820d5eea32f08ef467ef3b7f66883a9b076d5737a2fc2fbb5f458d1bb50f'),
 ('ffmpeg','https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-10-31-12-59/ffmpeg-n9.0.2-39-g7adfbe40dc-win64-gpl-9.0.zip','693f3e224bc184b40524a62ca47526cfebaf2504414021b92fe75f677ad868b9'),
 ('whisper','https://github.com/ggml-org/whisper.cpp/releases/download/b5454/whisper-bin-x64.zip','6ba69e3482d7826214f90a6a9c84ca07782aec1e1d0c6a7c30c994fd5d816ccb')]
CODEX=[
 ('codex','dd13bdb162a184fa04039488b234a8258ef9b76f84e926c505d5742b19249a6a'),
 ('codex-command-runner','4b1f3369cf4f9a1fd6ecebb8c7caef0d6a33a4a3af77650c277525d3b4e34c76'),
 ('codex-app-server','9526f00e454edba5942822d89674c9857f18d7322f788f3c75d2256f692deb46'),
 ('codex-code-mode-host','9f865a748c984492ca9b69aac75680e4954f31311c43ec33ddbdae0ed77bd4bd'),
 ('codex-windows-sandbox-service','1feb1c264e9ad33ca78a0be4f3bba012f396c0c3de0564b856e05ef9c09567e7'),
 ('codex-windows-sandbox-setup','b30ec190ac0b43c6e4a7c26fbc533f5321674b57fe85bb7306872641bc0bd40b')]
def say(text):EVENTS.put(text)
def digest(p):
 h=hashlib.sha256()
 with p.open('rb')as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def download(url,path,sha):
 if path.is_file()and digest(path)==sha:return
 path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_suffix(path.suffix+'.part')
 try:
  with urllib.request.urlopen(url,timeout=60)as response,temp.open('wb')as f:
   total=int(response.headers.get('Content-Length','0')) if hasattr(response,'headers') else 0
   received=0;last=time.monotonic()
   while True:
    block=response.read(1024*1024)
    if not block:break
    f.write(block);received+=len(block)
    if time.monotonic()-last>2:
     say(f'{path.name}: {received//1048576} MB'+(f' / {total//1048576} MB' if total else ''));last=time.monotonic()
  if digest(temp)!=sha:raise ValueError('بصمة ملف التنزيل لا تطابق الإصدار؛ لن يتم تشغيله')
  os.replace(temp,path)
 finally:
  if temp.exists():temp.unlink()
def unpack(archive,dest):
 dest.mkdir(parents=True,exist_ok=True)
 with zipfile.ZipFile(archive)as z:
  for item in z.infolist():
   if not (dest/item.filename).resolve().is_relative_to(dest.resolve()):raise ValueError('مسار غير آمن في الحزمة')
  z.extractall(dest)
def run(args,env=None,timeout=1800,cwd=None):
 with (APP_HOME/'setup.log').open('ab')as log:subprocess.run(list(map(str,args)),stdin=subprocess.DEVNULL,stdout=log,stderr=log,check=True,timeout=timeout,env=env,cwd=cwd or APP_HOME,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
def find_one(folder,name):
 hits=list(folder.rglob(name))
 if not hits:raise FileNotFoundError('ملف تشغيل مفقود: '+name)
 return hits[0]
def bundle_hash():return digest(BUNDLE/'source-files.json')
def check_embedded_bundle():
 manifest=json.loads((BUNDLE/'source-files.json').read_text(encoding='utf-8'))
 root=(BUNDLE/'source').resolve();errors=[]
 for name,sha in manifest.items():
  file=(root/name).resolve()
  if not file.is_relative_to(root)or not file.is_file()or digest(file)!=sha:errors.append(name)
 for name in ('models.json','node.json','requirements-windows.txt'):
  if not(BUNDLE/'packaging'/name).is_file():errors.append('packaging/'+name)
 return {'ok':not errors,'source_files':len(manifest),'errors':errors,'network_used':False}
def profile_current(profile):
 return profile.get('source_sha256')==bundle_hash() and all(Path(profile.get(k,'missing')).is_file()for k in ('python','node','chrome','codex'))
def running_server():
 try:
  with urllib.request.urlopen('http://127.0.0.1:8877/api/bootstrap',timeout=2)as response:result=json.load(response)
  if not isinstance(result,dict) or 'runtime'not in result:raise RuntimeError('المنفذ ٨٨٧٧ مستخدم بواسطة برنامج آخر')
  return result
 except urllib.error.HTTPError:raise RuntimeError('المنفذ ٨٨٧٧ مستخدم؛ لن يتم إيقاف أي برنامج تلقائيًا')
 except urllib.error.URLError:return None

def provision():
 if os.name!='nt':raise RuntimeError('هذه حزمة Windows فقط')
 if not check_embedded_bundle()['ok']:raise RuntimeError('ملفات البرنامج غير مكتملة؛ أعد تنزيل ملف التشغيل من الإصدار الرسمي')
 if running_server():raise RuntimeError('نسخة محلية تعمل الآن. أوقفها بعد انتهاء شغلها قبل تركيب إصدار مختلف')
 APP_HOME.mkdir(parents=True,exist_ok=True);CACHE.mkdir(exist_ok=True);DATA.mkdir(exist_ok=True)
 if shutil.disk_usage(APP_HOME).free<20*1024**3:raise ValueError('التجهيز يحتاج ٢٠ جيجابايت مساحة متاحة على الأقل')
 say('تجهيز ملفات البرنامج — بيانات الحلقات محفوظة منفصلة')
 # Replace only application code; never copy developer databases or touch episode data.
 target=APP/'source';pending=APP/'source.pending'
 if pending.exists():shutil.rmtree(pending)
 shutil.copytree(BUNDLE/'source',pending)
 previous=APP/'source.previous'
 if previous.exists():shutil.rmtree(previous)
 if target.exists():target.rename(previous)
 pending.rename(target)
 for name,url,sha in TOOLS:
  say('تجهيز أداة '+name);archive=CACHE/(name+'.zip');download(url,archive,sha);unpack(archive,RUNTIME/name)
 bindir=RUNTIME/'bin';bindir.mkdir(parents=True,exist_ok=True)
 for name,folder in [('ffmpeg.exe','ffmpeg'),('ffprobe.exe','ffmpeg'),('whisper-cli.exe','whisper')]:
  found=find_one(RUNTIME/folder,name)
  for file in found.parent.iterdir():
   if file.suffix.lower()in ('.exe','.dll'):shutil.copy2(file,bindir/file.name)
 for name,sha in CODEX:
  say('تجهيز ربط Codex: '+name)
  download('https://github.com/openai/codex/releases/download/rust-v0.162.1/'+name+'-x86_64-pc-windows-msvc.exe',bindir/(name+'.exe'),sha)
 uv=find_one(RUNTIME/'uv','uv.exe');env=os.environ.copy();env.update(PYTHONUTF8='1',UV_PYTHON_INSTALL_DIR=str(RUNTIME/'python-managed'),UV_CACHE_DIR=str(CACHE/'uv'),UV_NO_PROGRESS='1')
 say('تجهيز Python واعتمادات الصوت — أول تشغيل فقط')
 run([uv,'venv','--allow-existing','--python','3.11',RUNTIME/'ml'],env)
 python=RUNTIME/'ml/Scripts/python.exe'
 run([uv,'pip','install','--python',python,'-r',BUNDLE/'packaging/requirements-windows.txt'],env)
 # CPU is a portable baseline, not a claim that NVIDIA acceleration has been validated.
 run([uv,'pip','install','--python',python,'torch==2.6.0','torchaudio==2.6.0','--index-url','https://download.pytorch.org/whl/cpu'],env)
 models=json.loads((BUNDLE/'packaging/models.json').read_text(encoding='utf-8'))
 for name,model in models.items():
  for file in model['files']:
   say('تجهيز نموذج الصوت: '+name+' / '+file['path']);download(file['url'],RUNTIME/'models'/model['dest']/file['path'],file['sha256'])
 say('تجهيز محرك الموشن والعناوين')
 node=json.loads((BUNDLE/'packaging/node.json').read_text());archive=CACHE/'node.zip';download(node['url'],archive,node['sha256']);unpack(archive,RUNTIME/'node');node=find_one(RUNTIME/'node','node.exe')
 env['PATH']=str(node.parent)+os.pathsep+str(bindir)+os.pathsep+env.get('PATH','')
 npm=node.parent/'node_modules/npm/bin/npm-cli.js'
 run([node,npm,'ci','--no-audit','--no-fund'],env,cwd=target/'app-local')
 run([node,npm,'exec','--','remotion','browser','ensure'],env,cwd=target/'app-local')
 browsers=list((target/'app-local').rglob('chrome-headless-shell.exe'))+list((target/'app-local').rglob('chrome.exe'))
 if not browsers:raise ValueError('محرك رسم الموشن لم يجهز؛ سجل التجهيز محفوظ')
 profile={'version':VERSION,'source_sha256':bundle_hash(),'python':str(python),'node':str(node),'chrome':str(browsers[0]),'codex':str(bindir/'codex.exe'),'mode':'cpu_baseline','windows_acceptance_test_passed':False}
 (APP_HOME/'runtime.json').write_text(json.dumps(profile,indent=2),encoding='utf-8');return profile

def environment(profile):
 env=os.environ.copy();env.update({'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1','MONTAJ_ML_PYTHON':profile['python'],'MONTAJ_NODE':profile['node'],'MONTAJ_CHROME':profile['chrome'],'MONTAJ_WHISPER_MODEL':str(RUNTIME/'models/whisper/ggml-large-v3-turbo.bin'),'MONTAJ_CTC_MODEL':str(RUNTIME/'models/wav2vec2-egyptian'),'MONTEER_DATA':str(RUNTIME),'MONTAJ_FFMPEG':str(RUNTIME/'bin/ffmpeg.exe'),'MONTAJ_FFPROBE':str(RUNTIME/'bin/ffprobe.exe'),'MONTAJ_WHISPER-CLI':str(RUNTIME/'bin/whisper-cli.exe')})
 env['PATH']=str(Path(profile['node']).parent)+os.pathsep+str(RUNTIME/'bin')+os.pathsep+env.get('PATH','');return env

def launch(profile):
 say('فحص التشغيل المحلي');running=running_server()
 if not running:
  with (APP_HOME/'server.log').open('ab')as log:subprocess.Popen([profile['python'],str(APP/'source/app-local/server.py'),'--port','8877','--data',str(DATA)],stdin=subprocess.DEVNULL,stdout=log,stderr=log,env=environment(profile),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
 for _ in range(60):
  if running_server():webbrowser.open('http://127.0.0.1:8877/control/index.html');return
  time.sleep(1)
 raise RuntimeError('لم يبدأ البرنامج؛ سجل التشغيل محفوظ للدعم')

def login():
 profile=json.loads((APP_HOME/'runtime.json').read_text(encoding='utf-8'))
 subprocess.Popen([profile['codex'],'login'],env=environment(profile),creationflags=getattr(subprocess,'CREATE_NEW_CONSOLE',0))

def work():
 try:
  profilefile=APP_HOME/'runtime.json';profile=json.loads(profilefile.read_text(encoding='utf-8'))if profilefile.exists()else {}
  if not profile_current(profile):profile=provision()
  launch(profile);EVENTS.put(None)
 except Exception as error:EVENTS.put(('error',type(error).__name__+' — '+str(error)))

def main():
 import tkinter as tk
 from tkinter import messagebox
 window=tk.Tk();window.title('مونتاج — التجهيز والتشغيل');window.geometry('700x310')
 label=tk.Label(window,text='جاري التجهيز — أول تشغيل يحتاج اتصال إنترنت',wraplength=650,font=('Arial',15));label.pack(padx=20,pady=25)
 tk.Label(window,text='البيانات محفوظة على جهازك. أغلق هذه النافذة بعد فتح مونتاج؛ الخدمة تظل تعمل.',wraplength=640).pack()
 account=tk.Button(window,text='ربط حساب ChatGPT الخاص بالشركة',state='disabled',command=login);account.pack(pady=15)
 tk.Button(window,text='فتح مجلد السجلات والدعم',command=lambda:os.startfile(str(APP_HOME))).pack()
 def poll():
  try:
   while True:
    message=EVENTS.get_nowait()
    if message is None:
     label.config(text='تم فتح مونتاج. في أول استخدام اربط حساب الشركة من الزر التالي.');account.config(state='normal');return
    if isinstance(message,tuple):messagebox.showerror('تعذر إكمال التجهيز',message[1]+'\nملفات الدعم: '+str(APP_HOME));window.destroy();return
    label.config(text=message)
  except queue.Empty:pass
  window.after(200,poll)
 threading.Thread(target=work,daemon=True).start();window.after(200,poll);window.mainloop()
if __name__=='__main__':
 if len(sys.argv)==3 and sys.argv[1]=='--check-bundle':
  result=check_embedded_bundle();Path(sys.argv[2]).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');sys.exit(0 if result['ok']else 1)
 main()

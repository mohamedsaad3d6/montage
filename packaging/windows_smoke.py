"""Exercise the real local HTTP server on a temporary, isolated database."""
import json,os,socket,subprocess,sys,tempfile,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='montaj-acceptance-') as tmp:
 with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
 base=f'http://127.0.0.1:{port}'
 env={**os.environ,'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'}
 with (Path(tmp)/'server.log').open('wb') as log:
  process=subprocess.Popen([sys.executable,str(ROOT/'source/app-local/server.py'),'--port',str(port),'--data',str(Path(tmp)/'data')],env=env,stdout=log,stderr=log)
  try:
   for _ in range(100):
    if process.poll() is not None:raise RuntimeError('Local server failed to start:\n'+(Path(tmp)/'server.log').read_text(encoding='utf-8',errors='replace'))
    try:
     with urllib.request.urlopen(base+'/api/bootstrap',timeout=2) as response:boot=json.load(response)
     break
    except OSError:time.sleep(.1)
   else:raise RuntimeError('Local server timed out')
   assert 'token' in boot and 'runtime' in boot
   request=urllib.request.Request(base+'/api/projects',data=json.dumps({'name':'اختبار تسليم ويندوز'}).encode(),headers={'Content-Type':'application/json','Origin':base,'X-Montaj-Token':boot['token']})
   with urllib.request.urlopen(request) as response:project=json.load(response)
   assert project['id'] and project['active']
   for url in ['/control/index.html','/api/project?id='+project['id'],'/api/channels','/api/health','/api/service-links']:
    with urllib.request.urlopen(base+url) as response:assert response.status==200 and response.read()
   print('PASS: local startup, isolated Arabic project creation, control UI, project/channel/health/service APIs. No external accounts invoked.')
  finally:process.terminate();process.wait(timeout=15)

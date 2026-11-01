"""Content-addressed local ASR reuse. Analysis only; never cut/review evidence."""
import hashlib,json,os,uuid
from pathlib import Path

def key(identity):return hashlib.sha256(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def _atomic(path,data):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.part')
 try:
  with tmp.open('xb') as f:os.chmod(tmp,0o600);f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(tmp,path)
 finally:
  if tmp.exists():tmp.unlink()
def restore(root,identity,output):
 file=Path(root)/(key(identity)+'.json')
 try:
  item=json.loads(file.read_text());data=item['response'].encode()
  if item['identity']!=identity or hashlib.sha256(data).hexdigest()!=item['response_sha256']:return False
  transcript=json.loads(data)
  if not isinstance(transcript,dict) or not isinstance(transcript.get('transcription'),list):return False
 except (OSError,ValueError,KeyError,TypeError,AttributeError):return False
 _atomic(output,data);return True

def save(root,identity,output):
 data=Path(output).read_bytes();transcript=json.loads(data)
 if not isinstance(transcript,dict) or not isinstance(transcript.get('transcription'),list):raise ValueError('Invalid ASR response; not cached')
 root=Path(root);root.mkdir(parents=True,exist_ok=True);os.chmod(root,0o700)
 entry={'identity':identity,'response':data.decode(),'response_sha256':hashlib.sha256(data).hexdigest(),'scope':'transcription_only_not_cut_or_review_approval'}
 _atomic(root/(key(identity)+'.json'),json.dumps(entry,ensure_ascii=False).encode())

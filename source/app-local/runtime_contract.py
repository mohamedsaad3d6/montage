"""Runtime/source identity prevents mixed old-backend/new-frontend mutations."""
import hashlib,threading
from pathlib import Path
class Contract:
 def __init__(self,base):
  self.base=Path(base);self.lock=threading.Lock();self.stamp=None;self.digest=None;self.running=self.current()
 def paths(self):
  files=list(self.base.glob('*.py'))
  for folder in ('web/control','graphics','cards','transition'):
   for suffix in ('*.js','*.mjs','*.tsx','*.css','*.html','*.json'):files.extend((self.base/folder).glob(suffix))
  return sorted(set(files))
 def current(self):
  with self.lock:
   files=self.paths();stamp=tuple((str(p),p.stat().st_size,p.stat().st_mtime_ns)for p in files)
   if stamp!=self.stamp:
    h=hashlib.sha256()
    for path in files:h.update(str(path.relative_to(self.base)).encode());h.update(path.read_bytes())
    self.stamp=stamp;self.digest=h.hexdigest()
   return self.digest
 def describe(self):return {'protocol':2,'running_build':self.running,'restart_required':self.running!=self.current()}

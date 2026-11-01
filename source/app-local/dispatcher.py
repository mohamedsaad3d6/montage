"""One launcher per store; queued work stays in SQLite, not waiting child processes."""
import subprocess,sys,threading
import platform_lock as fcntl
from pathlib import Path

class Dispatcher:
 def __init__(self,store,base,popen=None):
  self.store=store;self.base=Path(base);self.popen=popen or subprocess.Popen
  self.guard=threading.Lock();self.thread=None
 def start(self,job):
  with self.store.connect() as c:
   row=c.execute('SELECT status FROM jobs WHERE id=?',(job,)).fetchone()
  if not row or row['status']!='queued':return
  with self.guard:
   if self.thread is None:
    self.thread=threading.Thread(target=self._drain,daemon=True);self.thread.start()
 def _drain(self):
  try:
   with (self.store.root/'dispatch.lock').open('a') as lock:
    fcntl.flock(lock,fcntl.LOCK_EX)
    while True:
     # Keep the empty-queue decision atomic with start(), avoiding a lost wake-up.
     with self.guard:
      with self.store.connect() as c:row=c.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created,id LIMIT 1").fetchone()
      if row is None:self.thread=None;return
     job=row['id'];error=None
     try:
      # Cancelled jobs are never launched. worker.execute also checks the state.
      with self.store.connect() as c:state=c.execute('SELECT status FROM jobs WHERE id=?',(job,)).fetchone()
      if state['status']!='queued':continue
      with (self.store.root/'worker.log').open('ab') as log:
       proc=self.popen([sys.executable,str(self.base/'worker.py'),'--data',str(self.store.root),'--job',job],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,cwd=self.base)
       code=proc.wait()
      error='انتهى العامل دون حفظ نتيجة؛ راجع سجل المهمة' if code==0 else 'توقف العامل قبل اكتمال المهمة (رمز '+str(code)+')'
     except (OSError,subprocess.SubprocessError) as exc:error='تعذر تشغيل العامل المحلي: '+type(exc).__name__
     if error:
      with self.store.connect() as c:c.execute("UPDATE jobs SET status='failed',error=? WHERE id=? AND status IN ('queued','running')",(error,job))
  finally:
   with self.guard:
    if self.thread is threading.current_thread():self.thread=None

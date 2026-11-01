"""Bounded local process groups: cancellation and timeout release the worker queue."""
import os,signal,subprocess,time
from media import Cancelled

def stop(proc):
 if proc.poll() is not None:return
 if os.name=='nt':
  # Only this owned worker and its descendants; never kill a process by name.
  subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
  proc.wait(timeout=5)
  return
 try:os.killpg(proc.pid,signal.SIGTERM)
 except ProcessLookupError:pass
 try:proc.wait(timeout=4)
 except subprocess.TimeoutExpired:
  try:os.killpg(proc.pid,signal.SIGKILL)
  except ProcessLookupError:pass
  proc.wait(timeout=4)

def wait(proc,cancel,timeout_seconds=300):
 deadline=time.monotonic()+timeout_seconds
 while proc.poll() is None:
  if cancel():stop(proc);raise Cancelled()
  if time.monotonic()>=deadline:
   stop(proc)
   raise TimeoutError('تجاوز توليد الموشن مهلة التشغيل؛ أُوقفت المهمة لتحرير الطابور. راجع سجل الرندر قبل إعادة المحاولة')
  time.sleep(.1)
 return proc.returncode

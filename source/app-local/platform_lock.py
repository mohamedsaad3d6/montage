"""Portable one-byte Windows / flock POSIX locks. Windows requires target testing."""
import os
LOCK_EX=2
LOCK_NB=4
LOCK_UN=8
def flock(file,operation):
 if os.name!='nt':
  import fcntl
  return fcntl.flock(file,operation)
 import msvcrt,time
 file.seek(0)
 if operation==LOCK_UN:
  return msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)
 if os.fstat(file.fileno()).st_size==0:
  file.write('0');file.flush()
 while True:
  file.seek(0)
  try:return msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
  except OSError as error:
   if operation&LOCK_NB:raise BlockingIOError()from error
   time.sleep(.1)

import sys,tempfile,unittest,zipfile,hashlib,importlib.util
from pathlib import Path
from unittest.mock import patch
p=Path(__file__).resolve().parents[1]/'windows_launcher.py';spec=importlib.util.spec_from_file_location('launcher',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Installer(unittest.TestCase):
 def test_wrong_hash_never_becomes_executable(self):
  import io
  with tempfile.TemporaryDirectory()as tmp,patch.object(m.urllib.request,'urlopen',return_value=io.BytesIO(b'wrong')):
   target=Path(tmp)/'program.exe'
   with self.assertRaises(ValueError):m.download('https://fixture',target,'0'*64)
   self.assertFalse(target.exists())
 def test_matching_cached_file_does_not_redownload(self):
  with tempfile.TemporaryDirectory()as tmp:
   p=Path(tmp)/'good';p.write_bytes(b'good')
   with patch.object(m.urllib.request,'urlopen',side_effect=AssertionError('unexpected network')):m.download('unused',p,hashlib.sha256(b'good').hexdigest())
 def test_zip_cannot_escape_install_folder(self):
  with tempfile.TemporaryDirectory()as tmp:
   root=Path(tmp);p=root/'bad.zip'
   with zipfile.ZipFile(p,'w')as z:z.writestr('../outside.exe',b'bad')
   with self.assertRaises(ValueError):m.unpack(p,root/'dest')
   self.assertFalse((root/'outside.exe').exists())
 def test_platform_lock_is_importable_without_windows_module_on_posix(self):
  sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'source/app-local'))
  import platform_lock
  with tempfile.TemporaryFile(mode='a+')as f:platform_lock.flock(f,platform_lock.LOCK_EX);platform_lock.flock(f,platform_lock.LOCK_UN)

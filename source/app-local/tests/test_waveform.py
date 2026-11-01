import sys,wave,tempfile,unittest,json,struct
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid,uid,dump
from media import file_hash
from waveform import peaks
class Waveform(unittest.TestCase):
 def test_real_samples_and_tamper_guard(self):
  with tempfile.TemporaryDirectory() as tmp:
   s=Store(Path(tmp)/'data',[tmp]);p=s.create('wave');folder=s.root/'jobs'/'test';folder.mkdir(parents=True);path=folder/'audio.wav'
   with wave.open(str(path),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(16000);f.writeframes(struct.pack('<h',16384)*16000)
   j=uid()
   with s.connect() as c:c.execute('INSERT INTO jobs(id,project,revision,kind,status,result,created) VALUES(?,?,?,?,?,?,?)',(j,p['id'],p['active'],'transcribe','completed',dump({'wave_file':str(path),'wave_sha256':file_hash(path)}),1))
   data=peaks(s,j);self.assertEqual(data['duration'],1);self.assertEqual(max(data['peaks']),.5);self.assertFalse(data['editorial_quality_proven']);path.write_bytes(b'changed')
   with self.assertRaises(Invalid):peaks(s,j)

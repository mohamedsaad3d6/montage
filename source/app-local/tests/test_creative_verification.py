import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import creative_verification as v

class AdapterEvidence(unittest.TestCase):
 def test_unrelated_ui_and_worker_edits_keep_proof_but_adapter_or_artifact_changes_invalidate(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(v,'COMPONENTS',{'music':(['adapter.py'],['generate_music'])}),patch.object(v,'EXTERNAL',{}):
   root=Path(tmp);(root/'adapter.py').write_text('def generate(): return 1')
   (root/'worker.py').write_text("if j['kind']=='generate_music':\n result=generate()\nelif j['kind']=='other':\n result=0\n")
   (root/'output.wav').write_bytes(b'evidence');original=v.component_hash(root,'music')
   proof={'schema':2,'checks':{'music':{'passed':True,'component_sha256':original,'artifacts':[{'path':str(root/'output.wav'),'sha256':v.file_hash(root/'output.wav')}]}}}
   (root/'creative-tool-verification.json').write_text(json.dumps(proof))
   self.assertIn('music',v.verified(root,root))
   (root/'web.js').write_text('new UI')
   (root/'worker.py').write_text((root/'worker.py').read_text().replace('result=0','result=100'))
   self.assertEqual(v.component_hash(root,'music'),original);self.assertIn('music',v.verified(root,root))
   (root/'output.wav').write_bytes(b'changed');self.assertFalse(v.verified(root,root))
   (root/'output.wav').write_bytes(b'evidence');(root/'adapter.py').write_text('def generate(): return 2')
   self.assertFalse(v.verified(root,root))
   (root/'adapter.py').write_text('def generate(): return 1')
   (root/'worker.py').write_text((root/'worker.py').read_text().replace('result=generate()','result=new_generate()'))
   self.assertFalse(v.verified(root,root))
 def test_legacy_and_missing_artifact_not_treated_as_proof(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);path=root/'creative-tool-verification.json'
   path.write_text('{"schema":1,"checks":{"music":{"passed":true}}}')
   self.assertFalse(v.verified(root,root))
   path.write_text('{"schema":2,"checks":{"music":{"passed":true,"artifacts":[]}}}')
   self.assertFalse(v.verified(root,root))

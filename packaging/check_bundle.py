"""Verify the public source manifest and installer inputs, without any external calls."""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def check():
 manifest=json.loads((ROOT/'source-files.json').read_text(encoding='utf-8'))
 actual={p.relative_to(ROOT/'source').as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'source').rglob('*') if p.is_file() and not any(x in p.parts for x in ('__pycache__','node_modules','.fixtures','.local-data')) and p.suffix not in ('.pyc','.pyo')}
 errors=[]
 if actual!=manifest:errors.append('Source inventory mismatch')
 for p in actual:
  if any(x in Path(p).parts for x in ('jobs','uploads','.config','.codex')) or Path(p).suffix in ('.sqlite','.sqlite3','.db','.mp4','.mov','.opus','.mp3','.wav') or Path(p).name.startswith('.env'):errors.append('Private or runtime file: '+p)
 for p in ['packaging/models.json','packaging/node.json','packaging/requirements-windows.txt','source/app-local/server.py','source/app-local/package-lock.json','source/library/our-transitions-01/src/transition-engine.ts','source/app-local/graphics/public/earth-nasa.jpg']:
  if not(ROOT/p).is_file():errors.append('Missing '+p)
 print(json.dumps({'source_files':len(actual),'errors':errors,'source_package_valid':not errors,'company_acceptance':'pending'},ensure_ascii=False,indent=2))
 return not errors
if __name__=='__main__':sys.exit(0 if check() else 1)

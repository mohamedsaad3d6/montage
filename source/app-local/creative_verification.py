"""Execution evidence belongs to an adapter, not unrelated UI/application edits."""
import ast,hashlib,json
from pathlib import Path
COMMON=['media.py','process_guard.py','voice.py','visual.py','color_grade.py','layers.py','audio_mix.py','render_stages.py']
GRAPHICS=['graphics/render.mjs','graphics/main.tsx','graphics/Geo3D.tsx','graphics/region.json','graphics/catalog.json','graphics/public/Cairo.ttf','graphics/public/earth-nasa.jpg','node_modules/@remotion/renderer/package.json','node_modules/@remotion/bundler/package.json','node_modules/three/package.json']
CARDS=['cards.py','cards/render.mjs','cards/main.tsx','graphics/public/Cairo.ttf','node_modules/@remotion/renderer/package.json','node_modules/@remotion/bundler/package.json']
TRANSITIONS=['transitions.py','transition/render.mjs','transition/main.tsx','node_modules/@remotion/renderer/package.json','node_modules/@remotion/bundler/package.json']
COMPONENTS={
 'motion':(COMMON+GRAPHICS,['generate_graphic','render']),
 'graphics':(COMMON+CARDS,['render']),
 'transitions':(COMMON+TRANSITIONS,['preview_transition','render']),
 'music':(COMMON+['music_adapter.py'],['generate_music','render']),
 'archives':(['archive.py','archive_import.py','process_guard.py','media.py'],['archive_search','archive_collect'])}
EXTERNAL={'music':['engine/monteer/music/code_bed.py'],'transitions':['library/our-transitions-01/catalog.json','library/our-transitions-01/src/transition-engine.ts'],'graphics':['experiments/saudi-semantic-repair-03/public/Cairo.ttf']}

def file_hash(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()

def component_hash(base,kind,root=None):
 base=Path(base);root=Path(root or base.parent);files,branches=COMPONENTS[kind];h=hashlib.sha256()
 for name in sorted(files):
  path=base/name
  if not path.is_file():raise ValueError('Missing dependency: '+name)
  h.update(name.encode());h.update(bytes.fromhex(file_hash(path)))
 tree=ast.parse((base/'worker.py').read_text());found={}
 for n in ast.walk(tree):
  if isinstance(n,ast.If):
   for kind_name in branches:
    if ast.unparse(n.test)=="j['kind'] == '"+kind_name+"'":found[kind_name]=ast.dump(ast.Module(body=n.body,type_ignores=[]),include_attributes=False)
 if set(found)!=set(branches):raise ValueError('Missing execution adapter')
 h.update(json.dumps(found,sort_keys=True).encode())
 for name in EXTERNAL.get(kind,[]):h.update(name.encode());h.update(bytes.fromhex(file_hash(root/name)))
 return h.hexdigest()

def verified(base,data_root,root=None):
 try:stored=json.loads((Path(data_root)/'creative-tool-verification.json').read_text())
 except (OSError,ValueError):return {}
 if stored.get('schema')!=2:return {}
 out={}
 for kind,evidence in stored.get('checks',{}).items():
  try:
   artifacts=evidence.get('artifacts',[])
   if kind not in COMPONENTS or evidence.get('passed')is not True or not artifacts:continue
   if evidence.get('component_sha256')!=component_hash(base,kind,root):continue
   if not all(file_hash(a['path'])==a['sha256'] for a in artifacts):continue
   out[kind]=evidence
  except (OSError,ValueError,KeyError,TypeError):continue
 return out

import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from creative_tools import describe
class CreativeTools(unittest.TestCase):
 def test_renderer_dependency_is_resolved_from_actual_cards_runtime(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);base=root/'app-local'
   (base/'cards/node_modules/@remotion/renderer').mkdir(parents=True)
   (base/'graphics').mkdir();(base/'graphics/catalog.json').write_text('[]')
   (root/'library/our-transitions-01').mkdir(parents=True)
   (root/'library/our-transitions-01/catalog.json').write_text('{"recipes":[]}')
   browser=root/'chrome';browser.touch()
   with patch('creative_tools.ROOT',root),patch('creative_tools.shutil.which',return_value='/node'),patch.dict('os.environ',{'MONTAJ_CHROME':str(browser)}):
    result=describe(root)
   tools={x['id']:x for x in result['tools']}
   self.assertTrue(all(tools[k]['available']for k in ('motion','graphics','transitions')))
   self.assertTrue(all(not tools[k]['execution_verified']for k in tools))
   self.assertFalse(result['automatic_episode'])

import sys,unittest,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Invalid
from profiles import save_profile,apply_profile,set_default,list_profiles
class Profiles(unittest.TestCase):
 def test_only_approved_feedback_becomes_reusable_default_without_changing_old_media(self):
  with tempfile.TemporaryDirectory() as td:
   s=Store(td,[td]);v=s.create('مصدر الأسلوب');active=v['active']
   with self.assertRaises(Invalid):save_profile(s,v['id'],'اختبار')
   s.feedback(v['id'],active,0,'cards','الكارت قصير');v=s.project(v['id']);v=s.propose_rule(v['id'],v['feedback'][0]['id'],'card_min_seconds',4)
   with self.assertRaises(Invalid):save_profile(s,v['id'],'اختبار')
   s.rule_status(v['id'],v['rules'][0]['id'],'approved');profile=save_profile(s,v['id'],'أسلوب القناة');set_default(s,profile['id'])
   new=s.create('حلقة جديدة');self.assertEqual(new['style_profile']['id'],profile['id']);self.assertEqual(new['style_profile']['rules']['card_min_seconds']['value'],4)
   original=s.project(v['id']);self.assertEqual(original['active'],active);self.assertIsNone(original['style_profile'])
   apply_profile(s,v['id'],profile['id']);self.assertEqual(s.project(v['id'])['active'],active);self.assertEqual(len(list_profiles(s)),1)
if __name__=='__main__':unittest.main()

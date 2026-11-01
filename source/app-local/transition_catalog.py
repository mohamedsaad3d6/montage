"""Bounded access to all parameter recipes, separately marked from tested representatives."""
import json
from media import ROOT

def query(family='',offset=0,limit=50):
 cat=json.loads((ROOT/'library/our-transitions-01/catalog.json').read_text())
 validation=json.loads((ROOT/'library/our-transitions-01/validation.json').read_text());recipes=cat['recipes']
 families=sorted(set(r['family'] for r in recipes))
 if family and family not in families:raise ValueError('عائلة انتقال غير موجودة')
 if type(offset)!=int or not 0<=offset<=len(recipes):raise ValueError('صفحة انتقالات غير صالحة')
 matches=[r for r in recipes if not family or r['family']==family]
 return {'families':families,'total':len(matches),'offset':offset,'next_offset':offset+limit if offset+limit<len(matches) else None,
         'choices':[{**r,'representative_tested':r['id'] in validation['rendered_ids']} for r in matches[offset:offset+limit]],
         'all_individually_verified':False}

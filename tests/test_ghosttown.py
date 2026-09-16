"""Original size-one Settler warning must remain a model choice, never Enter-only."""
from copy import deepcopy
from pathlib import Path
import unittest

from civ2.dialogs import classify_dialog


SOURCE='''@GHOSTTOWN
@title=Domestic Advisor
@width=320
%STRING0 is about to build %STRING1, but it is only a size 1 city.  Continue anyway?

Delay Settler production.
Build Settlers anyway (disbands city).
'''
STATE={'player':{'id':1},'evidence':{'save_sha256':'a'*64},
       'cities':[{'id':1,'owner':1,'name':'TEST Veii','x':11,'y':13,'size':1}]}
RULES={'units':[{'id':0,'name':'Settlers','role':5},{'id':2,'name':'Warriors','role':0}]}


def fixture():
    def row(text,x,y,w):return {'text':text,'center':[x,y],'bounds':[x-w//2,y-7,w,14],'confidence':1}
    rows=[row('Domestic Admsor',320,176,110),
          row('TEST Vei is about to build Settlers, but it is only a',310,202,300),
          row('size 1 city. Continue anyway!',275,222,220),
          row('• Delay Settler production.',280,247,196),
          row('• Build Settlers anyway (dishands city).',315,274,280),row('OK',320,305,24)]
    return {'width':640,'height':480,'sha256':'b'*64,'lines':rows,'text':'\n'.join(r['text'] for r in rows)}


class GhosttownTests(unittest.TestCase):
    def classify(self,o,state=None,rules=None,source=SOURCE):
        return classify_dialog(o,state=STATE if state is None else state,rules=RULES if rules is None else rules,game_text=source)

    def test_full_warning_preserves_both_raw_options_and_requires_model(self):
        result=self.classify(fixture())
        self.assertTrue(result['supported'],result);self.assertEqual(result['kind'],'worker_disband_choice')
        self.assertTrue(result['requires_model']);self.assertIsNone(result['mechanical_action'])
        self.assertEqual(result['resource_tag'],'GHOSTTOWN')
        self.assertEqual([r['text']for r in result['options']],['• Delay Settler production.','• Build Settlers anyway (dishands city).'])
        self.assertEqual(result['evidence']['worker_disband_warning']['city_name'],'TEST Veii')

    def test_missing_consequence_choice_body_source_or_city_is_not_a_dispatch(self):
        for mutation in ('missing_choice','missing_consequence','different_body','other_item','unknown_city','extra_option','low_confidence','missing_ok'):
            o=fixture()
            if mutation=='missing_choice':o['lines'].pop(3)
            elif mutation=='missing_consequence':o['lines'][4]['text']='• Build Settlers anyway.'
            elif mutation=='different_body':o['lines'][2]['text']='size 2 city. Continue anyway?'
            elif mutation=='other_item':o['lines'][1]['text']=o['lines'][1]['text'].replace('Settlers','Warriors')
            elif mutation=='unknown_city':o['lines'][1]['text']=o['lines'][1]['text'].replace('Vei','Unknown')
            elif mutation=='extra_option':o['lines'].insert(-1,{'text':'Sell the city','center':[300,290],'bounds':[250,283,100,14],'confidence':1})
            elif mutation=='low_confidence':o['lines'][4]['confidence']=.5
            else:o['lines'].pop()
            with self.subTest(mutation=mutation):self.assertFalse(self.classify(o)['supported'])
        self.assertFalse(self.classify(fixture(),source=SOURCE.replace('(disbands city)','(keeps city)'))['supported'])
        state=deepcopy(STATE);state['cities'][0]['owner']=2
        self.assertFalse(self.classify(fixture(),state=state)['supported'])

    def test_optional_original006_warning(self):
        from civ2.observe import recognize
        from civ2.run import game_text
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-006/screens/ui-0000768.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original warning unavailable')
        state=deepcopy(STATE);state['cities'][0]['name']='Veii'
        result=self.classify(recognize(p),state=state,rules=parse_rules(original_rules()),source=game_text())
        self.assertTrue(result['supported'],result);self.assertTrue(result['requires_model'])
        self.assertEqual(result['kind'],'worker_disband_choice')

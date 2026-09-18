from copy import deepcopy
from pathlib import Path
import unittest
from civ2.native_choices import SOURCES,classify_native_choice
from civ2.dialogs import _rows,classify_dialog
from tests.test_herald import prepared


def observation():
    rows=[prepared('The High Council: A.D. 1',240,14,160,18),
        prepared('The High Council of the TEST Romans is meeting in',196,38,310,16),
        prepared('TEST Rome. If you wish, you may take this',196,58,280,16),
        prepared('opportunity to consult your advisors and hear',196,78,302,16),
        prepared('their views on the state of your realm.',196,98,254,16),
        prepared('Consult High Council.',228,122,150,18),
        prepared('• No thanks, too busy.',206,148,168,18),prepared('OK',308,182,24,16)]
    return dict(width=640,height=480,sha256='a'*64,lines=rows)


class CouncilChoiceTests(unittest.TestCase):
    def test_all_original_alternatives_require_a_real_model_choice(self):
        o=observation();d=classify_native_choice(o,_rows(o),[SOURCES['COUNCILTIME']])
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual([r['text'] for r in d['options']],['Consult High Council.','• No thanks, too busy.'])

    def test_partial_or_altered_dialog_rejects(self):
        for mode in ('missing_option','body','source','extra_control','low','title','geometry'):
            o=observation();resources=[deepcopy(SOURCES['COUNCILTIME'])]
            if mode=='missing_option':o['lines'].pop(6)
            elif mode=='body':o['lines'][3]['text']='Pay 100 gold to consult your advisors.'
            elif mode=='source':resources[0]['options'][0]='Pay 100 gold.'
            elif mode=='extra_control':o['lines'].append(prepared('Cancel',400,184,35,16))
            elif mode=='low':o['lines'][3]['confidence']=.5
            elif mode=='title':o['lines'][0]['text']='TEST unknown council'
            elif mode=='geometry':o['lines'][5]['bounds'][0]=480;o['lines'][5]['center'][0]=555
            with self.subTest(mode=mode):self.assertIsNone(classify_native_choice(o,_rows(o),resources))

    def test_original_first_ad_council(self):
        from civ2.observe import recognize
        from civ2.run import game_text,labels_text
        p=Path(__file__).resolve().parents[1]/'runs/attempt-012/screens/ui-0001496.png'
        if not p.exists():self.skipTest('Private original council absent')
        o=recognize(p);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported']);self.assertTrue(d['requires_model']);self.assertEqual(d['resource_tag'],'COUNCILTIME')
        self.assertEqual(d['title'],'The Fligh Cooncl: A.D. 1')
        row=next(r for r in o['lines'] if r['text']==d['title'])
        self.assertEqual(row['provenance'][0]['text'],'The Figh Comcl A.D.1')
        self.assertEqual(len(d['options']),2);self.assertEqual([b['text'] for b in d['buttons']],['OK'])

class ADMapDateTests(unittest.TestCase):
    def test_native_ad_prefix_keeps_other_map_guards(self):
        from tests.test_dialogs import native_map,ROMAN_STATE
        for date in ('A.D. 1','AD 1750','1750 A.D.','25 B.C.','A.D.','A.D. XX','1 UNKNOWN'):
            o=native_map();next(r for r in o['lines'] if r['text']=='4000 B.C.')['text']=date
            d=classify_dialog(o,state=ROMAN_STATE)
            self.assertEqual(d['supported'],date in ('A.D. 1','AD 1750','1750 A.D.','25 B.C.'))
